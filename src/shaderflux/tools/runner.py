"""Safe subprocess execution for external shader tools.

This is the only module in the project that spawns processes. Rules:

* arguments are always a list, never a shell string;
* every run has a timeout and the whole process group is killed on expiry;
* captured output is capped so a runaway tool cannot exhaust memory;
* recorded command lines are redacted before they reach logs or reports.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from shaderflux.core.errors import (
    InvalidInputError,
    ToolFailedError,
    ToolMissingError,
    ToolTimeoutError,
)

DEFAULT_TIMEOUT_S = 60.0
DEFAULT_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_READ_CHUNK = 64 * 1024
_JOIN_GRACE_S = 5.0


@dataclass(frozen=True)
class ToolRun:
    """Result of one external process execution."""

    command: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes
    duration_s: float
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def stdout_text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")

    @property
    def stderr_text(self) -> str:
        return self.stderr.decode("utf-8", errors="replace")


class _Capture(threading.Thread):
    """Drain a pipe, keeping at most ``limit`` bytes and discarding the rest."""

    def __init__(self, stream: object, limit: int) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._limit = limit
        self.data = bytearray()
        self.truncated = False

    def run(self) -> None:
        read = self._stream.read1 if hasattr(self._stream, "read1") else self._stream.read  # type: ignore[attr-defined]
        while True:
            chunk = read(_READ_CHUNK)
            if not chunk:
                break
            room = self._limit - len(self.data)
            if room > 0:
                self.data += chunk[:room]
            if len(chunk) > room:
                self.truncated = True


def _feed_stdin(stream: object, data: bytes) -> None:
    try:
        stream.write(data)  # type: ignore[attr-defined]
    except (BrokenPipeError, OSError):
        pass  # the tool exited before reading everything; its exit code tells the story
    finally:
        with contextlib.suppress(OSError):
            stream.close()  # type: ignore[attr-defined]


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    try:
        if sys.platform == "win32":
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    except OSError:
        with contextlib.suppress(OSError):
            proc.kill()


def run_tool(
    args: Sequence[str | os.PathLike[str]],
    *,
    input: bytes | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> ToolRun:
    """Run an external program and capture its output.

    Raises:
        InvalidInputError: ``args`` is empty or contains a NUL byte.
        ToolMissingError: the executable does not exist.
        ToolTimeoutError: the process exceeded ``timeout`` seconds.
        ToolFailedError: the process could not be started for another reason.

    A non-zero exit code is **not** an error here: compilers report problems
    that way, and the caller decides what that means.
    """
    argv = [os.fspath(a) for a in args]
    if not argv:
        raise InvalidInputError("cannot run an empty command")
    if any("\0" in a for a in argv):
        raise InvalidInputError("command arguments must not contain NUL bytes")
    name = Path(argv[0]).name

    # New process group (Windows) / new session (POSIX) so a timeout can kill the whole tree.
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    started = time.monotonic()
    try:
        proc = subprocess.Popen(  # argument list, never a shell
            argv,
            stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            creationflags=creationflags,
            start_new_session=sys.platform != "win32",
        )
    except FileNotFoundError as exc:
        raise ToolMissingError(name) from exc
    except PermissionError as exc:
        raise ToolFailedError(name, f"cannot execute: {exc.strerror or exc}") from exc
    except OSError as exc:
        raise ToolFailedError(name, f"cannot start: {exc.strerror or exc}") from exc

    assert proc.stdout is not None
    assert proc.stderr is not None
    out_reader = _Capture(proc.stdout, max_output_bytes)
    err_reader = _Capture(proc.stderr, max_output_bytes)
    out_reader.start()
    err_reader.start()
    writer: threading.Thread | None = None
    if input is not None:
        assert proc.stdin is not None
        writer = threading.Thread(target=_feed_stdin, args=(proc.stdin, input), daemon=True)
        writer.start()

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        proc.wait()
        for thread in (out_reader, err_reader):
            thread.join(_JOIN_GRACE_S)
        raise ToolTimeoutError(name, timeout) from None

    for thread in (out_reader, err_reader):
        thread.join(_JOIN_GRACE_S)
    if writer is not None:
        writer.join(_JOIN_GRACE_S)

    return ToolRun(
        command=tuple(argv),
        returncode=proc.returncode,
        stdout=bytes(out_reader.data),
        stderr=bytes(err_reader.data),
        duration_s=time.monotonic() - started,
        truncated=out_reader.truncated or err_reader.truncated,
    )


@contextmanager
def workspace(*, keep: bool = False, prefix: str = "shaderflux-") -> Iterator[Path]:
    """Create a private temporary directory for one tool invocation.

    The directory is removed on exit unless ``keep`` is true (useful for
    debugging with ``--keep-temp``).
    """
    path = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield path
    finally:
        if not keep:
            shutil.rmtree(path, ignore_errors=True)


_SECRET_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[=:]\s*)\S+"),
)


def redact_text(text: str, *, home: str | None = None) -> str:
    """Remove secrets and the user's home directory from text kept in reports."""
    home = home if home is not None else str(Path.home())
    if home and home not in ("/", ""):
        text = text.replace(home, "~")
    text = _SECRET_PATTERNS[0].sub("[REDACTED]", text)
    return _SECRET_PATTERNS[1].sub(r"\1[REDACTED]", text)


def redact_command(command: Sequence[str], *, home: str | None = None) -> list[str]:
    """Redact every argument of a command line."""
    return [redact_text(part, home=home) for part in command]
