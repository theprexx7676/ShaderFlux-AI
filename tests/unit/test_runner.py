"""Tests for the subprocess runner, using the Python interpreter as a fake tool."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from shaderflux.core.errors import (
    InvalidInputError,
    ToolMissingError,
    ToolTimeoutError,
)
from shaderflux.tools.runner import (
    clean_environment,
    redact_command,
    redact_text,
    run_tool,
    workspace,
)

pytestmark = pytest.mark.unit


def py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_success_captures_stdout_and_stderr() -> None:
    run = run_tool(py("import sys; print('out'); print('err', file=sys.stderr)"))
    assert run.ok
    assert run.stdout_text.strip() == "out"
    assert run.stderr_text.strip() == "err"
    assert run.duration_s >= 0
    assert not run.truncated


def test_nonzero_exit_is_not_an_exception() -> None:
    run = run_tool(py("import sys; sys.exit(3)"))
    assert run.returncode == 3
    assert not run.ok


def test_stdin_is_passed_through() -> None:
    run = run_tool(py("import sys; sys.stdout.write(sys.stdin.read().upper())"), input=b"abc")
    assert run.stdout == b"ABC"


def test_large_stdin_and_stdout_do_not_deadlock() -> None:
    payload = b"x" * (2 * 1024 * 1024)
    run = run_tool(
        py("import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"),
        input=payload,
        max_output_bytes=4 * 1024 * 1024,
        timeout=30,
    )
    assert len(run.stdout) == len(payload)
    assert not run.truncated


def test_output_is_capped_and_flagged() -> None:
    run = run_tool(
        py("import sys; sys.stdout.write('a' * 5_000_000)"),
        max_output_bytes=1000,
        timeout=30,
    )
    assert run.ok
    assert len(run.stdout) == 1000
    assert run.truncated


def test_missing_binary_raises_tool_missing() -> None:
    with pytest.raises(ToolMissingError) as info:
        run_tool(["definitely-not-a-real-shader-tool-xyz"])
    assert info.value.tool == "definitely-not-a-real-shader-tool-xyz"


def test_timeout_kills_the_process() -> None:
    started = time.monotonic()
    with pytest.raises(ToolTimeoutError):
        run_tool(py("import time; time.sleep(30)"), timeout=0.5)
    assert time.monotonic() - started < 10


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX specific here")
def test_timeout_kills_grandchildren(tmp_path: Path) -> None:
    marker = tmp_path / "grandchild-survived"
    code = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', "
        f"\"import time, pathlib; time.sleep(2); pathlib.Path(r'{marker}').write_text('x')\"])\n"
        "time.sleep(30)\n"
    )
    with pytest.raises(ToolTimeoutError):
        run_tool(py(code), timeout=0.5)
    time.sleep(3)
    assert not marker.exists()


def test_empty_command_rejected() -> None:
    with pytest.raises(InvalidInputError):
        run_tool([])


def test_nul_in_argument_rejected() -> None:
    with pytest.raises(InvalidInputError):
        run_tool(["echo", "bad\0arg"])


def test_arguments_are_not_interpreted_by_a_shell() -> None:
    run = run_tool([*py("import sys; print(sys.argv[1])"), "$(echo injected); echo more"])
    assert run.stdout_text.strip() == "$(echo injected); echo more"


def test_workspace_is_removed(tmp_path: Path) -> None:
    with workspace() as path:
        assert path.is_dir()
        (path / "file.txt").write_text("x")
    assert not path.exists()


def test_workspace_can_be_kept() -> None:
    with workspace(keep=True) as path:
        pass
    try:
        assert path.exists()
    finally:
        path.rmdir()


def test_redact_text_replaces_home_and_secrets() -> None:
    text = "/home/alice/shaders/a.hlsl key=sk-ant-abc123_DEF api_key=hunter2 token: s3cr3t"
    redacted = redact_text(text, home="/home/alice")
    assert "alice" not in redacted
    assert redacted.startswith("~/shaders/a.hlsl")
    assert "sk-ant-abc123_DEF" not in redacted
    assert "hunter2" not in redacted
    assert "s3cr3t" not in redacted


def test_redact_command_handles_each_argument() -> None:
    assert redact_command(["dxc", "/home/bob/x.hlsl"], home="/home/bob") == ["dxc", "~/x.hlsl"]


def test_children_do_not_inherit_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_should_not_leak")
    monkeypatch.setenv("MY_DB_PASSWORD", "hunter2")
    monkeypatch.setenv("HARMLESS_SETTING", "visible")
    run = run_tool(
        py(
            "import os; print(sorted(k for k in os.environ if k in "
            "('ANTHROPIC_API_KEY','GITHUB_TOKEN','MY_DB_PASSWORD','HARMLESS_SETTING','PATH')))"
        )
    )
    assert "HARMLESS_SETTING" in run.stdout_text
    assert "ANTHROPIC_API_KEY" not in run.stdout_text
    assert "GITHUB_TOKEN" not in run.stdout_text
    assert "MY_DB_PASSWORD" not in run.stdout_text


def test_clean_environment_keeps_ordinary_variables() -> None:
    cleaned = clean_environment(
        {"PATH": "/bin", "HOME": "/h", "AWS_SECRET_ACCESS_KEY": "x", "api_key": "y"}
    )
    assert cleaned == {"PATH": "/bin", "HOME": "/h"}


def test_an_explicit_environment_is_used_as_given() -> None:
    run = run_tool(py("import os; print(os.environ.get('CUSTOM'))"), env={"CUSTOM": "yes"})
    assert run.stdout_text.strip() == "yes"
