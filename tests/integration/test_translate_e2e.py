"""End-to-end translation with the real tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from shaderflux.core.models import ShaderLanguage, Target
from shaderflux.pipeline.translate import TranslateOptions, translate
from shaderflux.source.inputs import load_source
from shaderflux.tools.base import CrossOptions
from shaderflux.tools.registry import default_registry
from tests.conftest import require_tool

pytestmark = [pytest.mark.integration, pytest.mark.needs_tools]


def need_glsl_chain() -> None:
    require_tool("spirv-cross", "spirv-val", "glslangValidator")


def test_glsl_to_hlsl(corpus: Path) -> None:
    need_glsl_chain()
    result = translate(
        load_source(corpus / "glsl" / "textured.frag"),
        Target(language=ShaderLanguage.HLSL, version="50"),
        registry=default_registry(),
    )
    assert result.ok, result.diagnostics
    assert "cbuffer Params" in (result.output_text or "")
    names = [s.name for s in result.stages]
    assert names[:4] == ["includes", "compile glsl", "validate spirv", "convert to hlsl"]
    assert names[4] == "recompile generated hlsl"  # compiled with dxc if present, else skipped
    tooled = [s for s in result.stages if s.name not in ("includes", "recompile generated hlsl")]
    assert all(s.tool and s.tool.name for s in tooled)
    # spirv-cross builds without --version legitimately report no version
    assert all(s.tool.version for s in tooled if s.tool and s.tool.name != "spirv-cross")


def test_glsl_to_spirv_validates(corpus: Path) -> None:
    need_glsl_chain()
    result = translate(
        load_source(corpus / "glsl" / "passthrough.vert"),
        Target(language=ShaderLanguage.SPIRV),
        registry=default_registry(),
    )
    assert result.ok, result.diagnostics
    assert result.output_bytes is not None
    assert result.output_bytes[:4] in (b"\x03\x02\x23\x07", b"\x07\x23\x02\x03")


def test_glsl_roundtrip_recompiles(corpus: Path) -> None:
    need_glsl_chain()
    registry = default_registry()
    options = TranslateOptions(roundtrip=True, cross=CrossOptions(vulkan_semantics=True))
    first = translate(
        load_source(corpus / "glsl" / "textured.frag"),
        Target(language=ShaderLanguage.GLSL, version="450"),
        registry=registry,
        options=options,
    )
    assert first.ok, first.diagnostics
    assert first.output_text is not None
    again = translate(
        load_source(corpus / "glsl" / "textured.frag").model_copy(
            update={"text": first.output_text, "path": None}
        ),
        Target(language=ShaderLanguage.SPIRV),
        registry=registry,
    )
    assert again.ok, again.diagnostics


def test_compile_error_is_reported_with_location(corpus: Path) -> None:
    need_glsl_chain()
    result = translate(
        load_source(corpus / "glsl" / "broken.frag"),
        Target(language=ShaderLanguage.HLSL),
        registry=default_registry(),
    )
    assert not result.ok
    assert result.output_text is None
    located = [d for d in result.diagnostics if d.line == 3]
    assert located
    assert "undefined_thing" in located[0].message
    assert result.stages[-1].name == "compile glsl"


def test_include_resolution_with_real_compiler(tmp_path: Path) -> None:
    need_glsl_chain()
    (tmp_path / "common.glsl").write_text("vec4 tint() { return vec4(0.5); }\n")
    shader = tmp_path / "main.frag"
    shader.write_text(
        "#version 450\n#extension GL_GOOGLE_include_directive : require\n"
        '#include "common.glsl"\n'
        "layout(location = 0) out vec4 color;\nvoid main() { color = tint(); }\n"
    )
    result = translate(
        load_source(shader),
        Target(language=ShaderLanguage.GLSL, version="450"),
        registry=default_registry(),
        options=TranslateOptions(roundtrip=True, cross=CrossOptions(vulkan_semantics=True)),
    )
    assert result.ok, result.diagnostics
    assert next(s for s in result.stages if s.name == "includes").ok


def test_cache_with_real_tools(corpus: Path, tmp_path: Path) -> None:
    from shaderflux.pipeline.cache import TranslationCache

    need_glsl_chain()
    options = TranslateOptions(cache=TranslationCache(tmp_path / "cache"))
    args = (load_source(corpus / "glsl" / "textured.frag"), Target(language=ShaderLanguage.HLSL))
    first = translate(*args, registry=default_registry(), options=options)
    second = translate(*args, registry=default_registry(), options=options)
    assert first.ok
    assert second.cached
    assert second.output_text == first.output_text


def test_repair_loop_with_real_compiler_and_scripted_model(corpus: Path) -> None:
    """The model is scripted; the compiler, validator and converter are real."""
    import json

    from shaderflux.llm.provider import FakeProvider
    from shaderflux.llm.repair import repair_and_translate

    need_glsl_chain()
    fix = json.dumps(
        {
            "summary": "use a literal instead of the undeclared name",
            "edits": [
                {
                    "file": "broken.frag",
                    "start_line": 3,
                    "end_line": 3,
                    "expected": "void main() { color = vec4(undefined_thing); }",
                    "replacement": "void main() { color = vec4(1.0); }",
                    "reason": "undefined_thing is not declared anywhere",
                }
            ],
            "confidence": "high",
        }
    )
    provider = FakeProvider([fix])
    outcome = repair_and_translate(
        load_source(corpus / "glsl" / "broken.frag"),
        Target(language=ShaderLanguage.HLSL),
        registry=default_registry(),
        provider=provider,
    )
    assert outcome.ok, outcome.stop_reason
    assert outcome.translation.output_text
    assert "vec4(1.0)" in outcome.source.text
    assert "undefined_thing" not in outcome.source.text
    assert "undefined_thing" in (corpus / "glsl" / "broken.frag").read_text()  # input untouched
    sent = provider.requests[0].user
    assert "broken.frag:3: error" in sent  # the real glslc/glslang diagnostic reached the prompt


def test_generated_glsl_that_is_not_vulkan_glsl_is_caught(corpus: Path) -> None:
    """Real finding: without --vulkan this shader's GLSL output is not valid Vulkan GLSL."""
    need_glsl_chain()
    shader = load_source(corpus / "glsl" / "rich.frag")
    target = Target(language=ShaderLanguage.GLSL, version="450")
    plain = translate(
        shader, target, registry=default_registry(), options=TranslateOptions(roundtrip=True)
    )
    assert not plain.ok
    assert plain.output_text
    assert plain.stages[-1].name == "recompile generated glsl"
    assert any("--vulkan" in d.message for d in plain.diagnostics)

    vulkan = translate(
        shader,
        target,
        registry=default_registry(),
        options=TranslateOptions(roundtrip=True, cross=CrossOptions(vulkan_semantics=True)),
    )
    assert vulkan.ok, vulkan.diagnostics


def test_report_for_a_real_run_and_a_failed_run(corpus: Path, tmp_path: Path) -> None:
    import json

    from typer.testing import CliRunner

    from shaderflux.cli.app import app

    need_glsl_chain()
    runner = CliRunner()
    ok_path, bad_path = tmp_path / "ok.json", tmp_path / "bad.md"
    ok = runner.invoke(
        app,
        [
            "translate",
            str(corpus / "glsl" / "textured.frag"),
            "--to",
            "hlsl",
            "--report",
            str(ok_path),
        ],
    )
    assert ok.exit_code == 0, ok.output
    data = json.loads(ok_path.read_text())
    assert data["ok"] is True
    assert data["input"]["file"] == "textured.frag"
    assert data["porting_risks"] == []
    assert data["verdict"]["level"] >= 2
    assert any("not compiled again" in n or "recompiled" in n or "compiled again" in n
               for n in data["verdict"]["checked"] + data["verdict"]["not_checked"])  # fmt: skip

    bad = runner.invoke(
        app,
        [
            "translate",
            str(corpus / "glsl" / "broken.frag"),
            "--to",
            "hlsl",
            "--report",
            str(bad_path),
        ],
    )
    assert bad.exit_code == 1
    markdown = bad_path.read_text()  # a report is written even when the translation fails
    assert "**Result:** failed" in markdown
    assert "undefined_thing" in markdown
