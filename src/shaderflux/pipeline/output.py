"""Writing translation results to disk."""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from pathlib import Path

from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import TranslationResult


def write_output(result: TranslationResult, path: Path, *, force: bool = False) -> Path:
    """Write the result to ``path`` atomically.

    Refuses to overwrite an existing file unless ``force`` is true. The data is
    written to a temporary file in the same directory and then renamed, so a
    crash never leaves a half-written shader behind.
    """
    path = Path(path)
    if not result.ok:
        raise InvalidInputError("refusing to write the output of a failed translation")
    if result.output_bytes is not None:
        data = result.output_bytes
    elif result.output_text is not None:
        data = result.output_text.encode("utf-8")
    else:
        raise InvalidInputError("the translation produced no output")
    if path.exists() and not force:
        raise InvalidInputError(f"{path} already exists (use --force to overwrite)")
    write_bytes_atomic(path, data)
    return path


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` through a temporary file in the same directory.

    A symbolic link is followed (the file it points to is replaced, the link stays), and an
    existing file keeps its permission bits. Overwrite policy is the caller's job. Problems
    with the destination (no such directory, no permission, ...) become ``InvalidInputError``.
    """
    if path.is_symlink():
        path = path.resolve()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    except OSError as exc:
        raise InvalidInputError(f"cannot write {path}: {exc.strerror or exc}") from exc
    try:
        with os.fdopen(handle, "wb") as tmp:
            tmp.write(data)
        if path.exists():
            shutil.copymode(path, tmp_name)
        os.replace(tmp_name, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise InvalidInputError(f"cannot write {path}: {exc.strerror or exc}") from exc
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
