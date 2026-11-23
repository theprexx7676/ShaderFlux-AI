"""SPIRV-Tools wrappers: ``spirv-val``, ``spirv-dis`` and ``spirv-opt``."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import Diagnostic, Severity
from shaderflux.tools.base import ToolResult, check_spirv_env, finish, locate, tool_info
from shaderflux.tools.runner import run_tool, workspace

_SPIRV_MAGIC = b"\x03\x02\x23\x07"  # 0x07230203, little endian
_SPIRV_MAGIC_BE = b"\x07\x23\x02\x03"
_VAL_HEAD = re.compile(r"^(?P<sev>error|warning|info): (?:line (?P<index>\d+): )?(?P<msg>.*)$")


def looks_like_spirv(data: bytes) -> bool:
    """Cheap check of the SPIR-V magic number (either byte order)."""
    return len(data) >= 4 and data[:4] in (_SPIRV_MAGIC, _SPIRV_MAGIC_BE)


def to_spirv_tools_env(environment: str | None) -> str | None:
    """Translate our environment names to SPIRV-Tools' spelling (``spirv1.5`` -> ``spv1.5``)."""
    env = check_spirv_env(environment)
    if env is None:
        return None
    return env.replace("spirv1", "spv1")


def parse_validator_diagnostics(text: str, *, tool: str = "spirv-val") -> list[Diagnostic]:
    """Parse ``spirv-val`` output.

    Messages look like ``error: line 2: <message>`` followed by the offending
    instruction on indented lines. The number is an *instruction index* in the
    binary, not a source line, so it is kept in the message.
    """
    found: list[Diagnostic] = []
    current: dict[str, str] | None = None
    context: list[str] = []

    def flush() -> None:
        nonlocal current, context
        if current is None:
            return
        message = current["msg"]
        if current.get("index"):
            message = f"(instruction {current['index']}) {message}"
        if context:
            message += "\n" + "\n".join(context)
        found.append(
            Diagnostic(
                severity={"error": Severity.ERROR, "warning": Severity.WARNING}.get(
                    current["sev"], Severity.NOTE
                ),
                message=message,
                tool=tool,
            )
        )
        current, context = None, []

    for raw in text.splitlines():
        match = _VAL_HEAD.match(raw)
        if match:
            flush()
            current = {k: v for k, v in match.groupdict().items() if v is not None}
        elif current is not None and raw.strip():
            context.append(raw.rstrip())
    flush()
    return found


class SpirvToolsBackend:
    """Validation, disassembly and optimisation of SPIR-V binaries."""

    name = "spirv-tools"

    def __init__(
        self,
        val_path: Path,
        *,
        val_version: str | None = None,
        dis_path: Path | None = None,
        opt_path: Path | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.val_path = val_path
        self.val_version = val_version
        self.dis_path = dis_path
        self.opt_path = opt_path
        self.timeout = timeout

    @classmethod
    def discover(
        cls,
        *,
        configured: Mapping[str, str] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> SpirvToolsBackend:
        val, version = locate("spirv-val", configured=configured, environ=environ)
        dis = _optional("spirv-dis", configured, environ)
        opt = _optional("spirv-opt", configured, environ)
        return cls(val, val_version=version, dis_path=dis, opt_path=opt)

    # -- validation -----------------------------------------------------

    def validate(self, spirv: bytes, *, environment: str | None = None) -> ToolResult:
        env = to_spirv_tools_env(environment)
        info = tool_info("spirv-val", self.val_path, self.val_version)
        with workspace() as work:
            module = work / "module.spv"
            module.write_bytes(spirv)
            args: list[str | Path] = [self.val_path]
            if env:
                args.extend(["--target-env", env])  # spirv-val wants a separate argument
            args.append(module)
            run = run_tool(args, timeout=self.timeout, cwd=work)
        diagnostics = parse_validator_diagnostics(run.stderr_text + "\n" + run.stdout_text)
        if not run.ok and not any(d.severity is Severity.ERROR for d in diagnostics):
            detail = (run.stderr_text or run.stdout_text).strip() or f"exit code {run.returncode}"
            diagnostics.append(
                Diagnostic(severity=Severity.ERROR, message=detail, tool="spirv-val")
            )
        return finish(run, info=info, ok=run.ok, output=None, diagnostics=diagnostics)

    # -- disassembly ----------------------------------------------------

    def disassemble(self, spirv: bytes) -> ToolResult:
        if self.dis_path is None:
            raise InvalidInputError("spirv-dis is not available")
        info = tool_info("spirv-dis", self.dis_path, None)
        with workspace() as work:
            module = work / "module.spv"
            module.write_bytes(spirv)
            run = run_tool([self.dis_path, "--no-color", module], timeout=self.timeout, cwd=work)
        diagnostics = parse_validator_diagnostics(run.stderr_text, tool="spirv-dis")
        return finish(
            run,
            info=info,
            ok=run.ok,
            output=run.stdout if run.ok else None,
            diagnostics=diagnostics,
        )

    # -- optimisation ---------------------------------------------------

    def optimize(
        self, spirv: bytes, *, level: str = "O", environment: str | None = None
    ) -> ToolResult:
        if self.opt_path is None:
            raise InvalidInputError("spirv-opt is not available")
        if level not in ("O", "Os"):
            raise InvalidInputError(f"unsupported optimisation level {level!r} (use O or Os)")
        env = to_spirv_tools_env(environment)
        info = tool_info("spirv-opt", self.opt_path, None)
        with workspace() as work:
            module = work / "in.spv"
            module.write_bytes(spirv)
            out = work / "out.spv"
            args: list[str | Path] = [self.opt_path, f"-{level}"]
            if env:
                args.append(f"--target-env={env}")
            args.extend([module, "-o", out])
            run = run_tool(args, timeout=self.timeout, cwd=work)
            produced = out.read_bytes() if run.ok and out.exists() else None
        diagnostics = parse_validator_diagnostics(run.stderr_text, tool="spirv-opt")
        return finish(
            run, info=info, ok=produced is not None, output=produced, diagnostics=diagnostics
        )


def _optional(
    key: str, configured: Mapping[str, str] | None, environ: Mapping[str, str] | None
) -> Path | None:
    from shaderflux.core.errors import ToolMissingError

    try:
        return locate(key, configured=configured, environ=environ)[0]
    except ToolMissingError:
        return None
