"""The translate workflow used as a library: no command line, fake tools, scripted model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import ShaderLanguage
from shaderflux.llm.provider import FakeProvider
from shaderflux.workflows.translate_file import (
    TranslateRequest,
    check_request,
    run_translate,
)
from tests.fakes import FakeCompiler, FakeCross, registry

pytestmark = pytest.mark.unit

BAD = "void main() {\n    float x = undefined_thing;\n}\n"
GOOD = "void main() {\n    float x = 1.0;\n}\n"
FIX = json.dumps(
    {
        "summary": "use a literal",
        "edits": [
            {
                "file": "a.frag",
                "start_line": 2,
                "end_line": 2,
                "expected": "    float x = undefined_thing;",
                "replacement": "    float x = 1.0;",
                "reason": "undeclared",
            }
        ],
        "confidence": "high",
    }
)


def request(tmp_path: Path, text: str = GOOD, **overrides: object) -> TranslateRequest:
    shader = tmp_path / "a.frag"
    shader.write_text(text)
    values: dict[str, object] = {
        "input_file": shader,
        "target_language": ShaderLanguage.HLSL,
    }
    values.update(overrides)
    return TranslateRequest(**values)  # type: ignore[arg-type]


def test_plain_translation_writes_the_output_and_a_report(tmp_path: Path) -> None:
    out, report = tmp_path / "out.hlsl", tmp_path / "report.md"
    outcome = run_translate(request(tmp_path, out=out, report=report), registry=registry())
    assert outcome.result.ok
    assert outcome.repair is None
    assert out.read_text() == "// hlsl\n"
    assert outcome.report_path == report
    assert "**Result:** success" in report.read_text()
    assert outcome.result.output_path == out


def test_failed_translation_writes_no_output_but_still_a_report(tmp_path: Path) -> None:
    out, report = tmp_path / "out.hlsl", tmp_path / "report.json"
    outcome = run_translate(request(tmp_path, BAD, out=out, report=report), registry=registry())
    assert not outcome.result.ok
    assert not out.exists()
    assert json.loads(report.read_text())["ok"] is False


def test_repair_fixes_and_saves_the_corrected_source(tmp_path: Path) -> None:
    fixed = tmp_path / "fixed.frag"
    provider = FakeProvider([FIX])
    outcome = run_translate(
        request(tmp_path, BAD, repair=True, write_fixed=fixed),
        registry=registry(),
        provider=provider,
    )
    assert outcome.result.ok
    assert outcome.repair is not None
    assert outcome.repair.changed
    assert fixed.read_text() == GOOD
    assert outcome.fixed_path == fixed
    assert (tmp_path / "a.frag").read_text() == BAD  # the original is never touched
    assert not outcome.model_call_failed


def test_repair_that_fails_to_reach_the_model_is_flagged(tmp_path: Path) -> None:
    from shaderflux.core.errors import LlmError

    outcome = run_translate(
        request(tmp_path, BAD, repair=True),
        registry=registry(),
        provider=FakeProvider([LlmError("rate limited")]),
    )
    assert not outcome.result.ok
    assert outcome.model_call_failed


def test_repair_makes_no_model_call_when_nothing_is_broken(tmp_path: Path) -> None:
    provider = FakeProvider([FIX])
    outcome = run_translate(
        request(tmp_path, GOOD, repair=True), registry=registry(), provider=provider
    )
    assert outcome.result.ok
    assert provider.requests == []


def test_dry_run_reports_the_prompt_and_sends_nothing(tmp_path: Path) -> None:
    provider = FakeProvider([FIX])
    outcome = run_translate(
        request(tmp_path, BAD, repair=True, dry_run=True),
        registry=registry(),
        provider=provider,
    )
    assert provider.requests == []
    assert outcome.dry_run is not None
    assert "undefined_thing" in outcome.dry_run.request.user
    assert outcome.dry_run.files_sent == ["a.frag"]
    assert not outcome.nothing_to_repair


def test_dry_run_on_a_working_shader_says_there_is_nothing_to_repair(tmp_path: Path) -> None:
    outcome = run_translate(request(tmp_path, GOOD, repair=True, dry_run=True), registry=registry())
    assert outcome.nothing_to_repair
    assert outcome.dry_run is None


def test_the_cache_is_used_when_a_directory_is_given(tmp_path: Path) -> None:
    compiler = FakeCompiler()
    reg = registry(compiler)
    cache = tmp_path / "cache"
    first = run_translate(request(tmp_path, cache_dir=cache), registry=reg)
    second = run_translate(request(tmp_path, cache_dir=cache), registry=reg)
    assert not first.result.cached
    assert second.result.cached
    assert second.result.output_text == first.result.output_text


def test_a_failing_converter_fails_the_workflow(tmp_path: Path) -> None:
    outcome = run_translate(request(tmp_path), registry=registry(cross=FakeCross(fail=True)))
    assert not outcome.result.ok


# ---- check_request: nothing may be spent before the paths are known to be usable ----------


def test_existing_outputs_are_refused_unless_forced(tmp_path: Path) -> None:
    out = tmp_path / "out.hlsl"
    out.write_text("precious")
    for field in ("out", "write_fixed"):
        with pytest.raises(InvalidInputError, match="already exists"):
            check_request(request(tmp_path, repair=True, **{field: out}))
    check_request(request(tmp_path, repair=True, out=out, force=True))
    assert out.read_text() == "precious"


def test_directories_are_refused_as_outputs(tmp_path: Path) -> None:
    for field in ("out", "report"):
        with pytest.raises(InvalidInputError, match="is a directory"):
            check_request(request(tmp_path, **{field: tmp_path}))


def test_repair_only_options_need_repair(tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError, match="dry_run"):
        check_request(request(tmp_path, dry_run=True))
    with pytest.raises(InvalidInputError, match="write_fixed"):
        check_request(request(tmp_path, write_fixed=tmp_path / "x.frag"))


def test_a_bad_request_never_reaches_the_model(tmp_path: Path) -> None:
    existing = tmp_path / "exists.hlsl"
    existing.write_text("x")
    provider = FakeProvider([FIX])
    with pytest.raises(InvalidInputError):
        run_translate(
            request(tmp_path, BAD, repair=True, out=existing),
            registry=registry(),
            provider=provider,
        )
    assert provider.requests == []


def test_dry_run_shows_nothing_when_the_failure_is_a_missing_tool(tmp_path: Path) -> None:
    """A missing compiler is not a shader error: a real --repair sends nothing, so --dry-run
    must not claim that it would send a prompt."""
    from shaderflux.tools.registry import BackendRegistry

    source = tmp_path / "a.frag"
    source.write_text(GOOD)
    provider = FakeProvider([])
    request = TranslateRequest(
        input_file=source, target_language=ShaderLanguage.HLSL, repair=True, dry_run=True
    )
    dry = run_translate(request, registry=BackendRegistry(), provider=provider)
    assert dry.dry_run is None
    assert dry.not_repairable is not None
    assert "not a compile error" in dry.not_repairable

    real = run_translate(
        TranslateRequest(input_file=source, target_language=ShaderLanguage.HLSL, repair=True),
        registry=BackendRegistry(),
        provider=provider,
    )
    assert provider.requests == []  # the real run agrees: nothing is sent
    assert real.repair is not None
    assert real.repair.stop_reason == dry.not_repairable
