"""Fake tool backends shared by tests that must not depend on real compilers."""

from __future__ import annotations

from shaderflux.core.models import (
    Diagnostic,
    Severity,
    ShaderLanguage,
    ShaderSource,
    Target,
    ToolInfo,
)
from shaderflux.tools.base import CrossOptions, ToolResult
from shaderflux.tools.registry import BackendRegistry

SPIRV_BYTES = b"\x03\x02\x23\x07"


def result(
    name: str, *, ok: bool = True, output: bytes | None = None, errors: tuple[Diagnostic, ...] = ()
) -> ToolResult:
    return ToolResult(
        ok=ok, output=output, diagnostics=errors, tool=ToolInfo(name=name, version="1"),
        command=(name,), duration_s=0.0,
    )  # fmt: skip


class FakeCompiler:
    """Fails once per occurrence of ``undefined_thing`` in the source."""

    name = "fake-compiler"
    version = "1"
    languages = frozenset({ShaderLanguage.GLSL})

    def __init__(self) -> None:
        self.compiled: list[str] = []

    def compile(self, source: ShaderSource, *, target: Target) -> ToolResult:
        self.compiled.append(source.text)
        errors = tuple(
            Diagnostic(
                severity=Severity.ERROR,
                message="'undefined_thing' : undeclared identifier",
                file="shader",
                line=i,
                tool="fake",
            )
            for i, line in enumerate(source.text.split("\n"), 1)
            if "undefined_thing" in line
        )
        if errors:
            return result("fake-compiler", ok=False, errors=errors)
        return result("fake-compiler", output=b"\x03\x02\x23\x07")


class FakeCross:
    name = "fake-cross"
    version = "1"
    targets = frozenset({ShaderLanguage.HLSL})

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def convert(
        self, spirv: bytes, target: Target, options: CrossOptions | None = None
    ) -> ToolResult:
        if self.fail:
            err = Diagnostic(severity=Severity.ERROR, message="cross failed", tool="x")
            return result("fake-cross", ok=False, errors=(err,))
        return result("fake-cross", output=b"// hlsl\n")


def registry(
    compiler: FakeCompiler | None = None, cross: FakeCross | None = None
) -> BackendRegistry:
    reg = BackendRegistry()
    reg.register_compiler(compiler or FakeCompiler())
    reg.register_cross_compiler(cross or FakeCross())
    return reg
