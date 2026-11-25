"""Repair-loop tests: a scripted fake model against fake compilers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shaderflux.core.errors import LlmError
from shaderflux.core.models import (
    Diagnostic,
    Severity,
    ShaderLanguage,
    ShaderSource,
    ShaderStage,
    Target,
)
from shaderflux.llm.provider import FakeProvider, LlmResponse
from shaderflux.llm.repair import (
    Outcome,
    RepairOptions,
    describe,
    prepare_repair_prompt,
    repair_and_translate,
)
from tests.fakes import FakeCompiler, FakeCross, registry

pytestmark = pytest.mark.unit

BAD = "void main() {\n    float x = undefined_thing;\n}\n"
GOOD = "void main() {\n    float x = 1.0;\n}\n"
TARGET = Target(language=ShaderLanguage.HLSL, version="50")


def source(text: str = BAD, path: Path | None = None) -> ShaderSource:
    return ShaderSource(
        text=text, language=ShaderLanguage.GLSL, stage=ShaderStage.FRAGMENT, path=path
    )


def proposal(
    start: int,
    end: int,
    expected: str,
    replacement: str,
    *,
    file: str = "shader",
    confidence: str = "high",
) -> str:
    return json.dumps(
        {
            "summary": "replace the undefined name",
            "edits": [
                {
                    "file": file, "start_line": start, "end_line": end,
                    "expected": expected, "replacement": replacement, "reason": "r",
                }
            ],
            "confidence": confidence,
        }
    )  # fmt: skip


FIX = proposal(2, 2, "    float x = undefined_thing;", "    float x = 1.0;")


def test_fixed_on_first_attempt() -> None:
    provider = FakeProvider([FIX])
    outcome = repair_and_translate(source(), TARGET, registry=registry(), provider=provider)
    assert outcome.ok
    assert outcome.translation.ok
    assert outcome.source.text == GOOD
    assert outcome.original_text == BAD
    assert outcome.changed
    assert [a.outcome for a in outcome.attempts] == [Outcome.FIXED]
    assert "-    float x = undefined_thing;" in outcome.diff
    assert "+    float x = 1.0;" in outcome.diff
    assert outcome.usage.calls == 1
    assert outcome.prompt_version == "system@1+repair_compile_error@1"


def test_prompt_sent_to_the_model_has_the_source_and_the_error() -> None:
    provider = FakeProvider([FIX])
    repair_and_translate(source(), TARGET, registry=registry(), provider=provider)
    (request,) = provider.requests
    assert "    2|     float x = undefined_thing;" in request.user
    assert "shader:2: error: 'undefined_thing' : undeclared identifier" in request.user
    assert request.effort == "high"
    assert request.schema["required"] == ["summary", "edits", "confidence"]


def test_nothing_to_repair_makes_no_model_call() -> None:
    provider = FakeProvider([])
    outcome = repair_and_translate(source(GOOD), TARGET, registry=registry(), provider=provider)
    assert outcome.ok
    assert not outcome.changed
    assert provider.requests == []
    assert outcome.stop_reason == "no repair needed"


def test_stale_patch_is_rejected_then_next_attempt_succeeds() -> None:
    stale = proposal(2, 2, "    float x = something_else;", "    float x = 1.0;")
    outcome = repair_and_translate(
        source(), TARGET, registry=registry(), provider=FakeProvider([stale, FIX])
    )
    assert outcome.ok
    assert [a.outcome for a in outcome.attempts] == [Outcome.REJECTED, Outcome.FIXED]
    assert "do not match" in outcome.attempts[0].message


def test_invalid_json_counts_as_an_attempt() -> None:
    outcome = repair_and_translate(
        source(), TARGET, registry=registry(), provider=FakeProvider(["not json", FIX])
    )
    assert outcome.ok
    assert outcome.attempts[0].outcome is Outcome.REJECTED
    assert "not valid JSON" in outcome.attempts[0].message


def test_gives_up_at_the_attempt_cap_and_leaves_the_source_alone() -> None:
    provider = FakeProvider(["not json"] * 5)
    outcome = repair_and_translate(
        source(),
        TARGET,
        registry=registry(),
        provider=provider,
        options=RepairOptions(max_attempts=3),
    )
    assert not outcome.ok
    assert len(provider.requests) == 3
    assert outcome.stop_reason == "gave up after 3 attempt(s)"
    assert outcome.source.text == BAD
    assert not outcome.changed


def test_a_patch_that_adds_errors_is_discarded() -> None:
    worse = proposal(
        2,
        2,
        "    float x = undefined_thing;",
        "    float x = undefined_thing;\n    float y = undefined_thing;",
    )
    compiler = FakeCompiler()
    outcome = repair_and_translate(
        source(), TARGET, registry=registry(compiler), provider=FakeProvider([worse, FIX])
    )
    assert outcome.ok
    assert [a.outcome for a in outcome.attempts] == [Outcome.WORSE, Outcome.FIXED]
    assert (outcome.attempts[0].errors_before, outcome.attempts[0].errors_after) == (1, 2)
    assert outcome.source.text == GOOD  # the worse text never became the baseline


def test_model_that_gives_up_stops_the_loop() -> None:
    giving_up = json.dumps(
        {"summary": "I cannot tell what this should be", "edits": [], "confidence": "low"}
    )
    provider = FakeProvider([giving_up, FIX])
    outcome = repair_and_translate(source(), TARGET, registry=registry(), provider=provider)
    assert not outcome.ok
    assert outcome.attempts[0].outcome is Outcome.NO_CHANGE
    assert "could not propose a fix" in outcome.stop_reason
    assert len(provider.requests) == 1


def test_model_failure_stops_cleanly() -> None:
    outcome = repair_and_translate(
        source(), TARGET, registry=registry(), provider=FakeProvider([LlmError("rate limited")])
    )
    assert not outcome.ok
    assert outcome.attempts[0].outcome is Outcome.LLM_ERROR
    assert "rate limited" in outcome.stop_reason


def test_token_budget_stops_the_loop() -> None:
    expensive = LlmResponse(text="not json", input_tokens=900, output_tokens=200)
    provider = FakeProvider([expensive, expensive, FIX])
    outcome = repair_and_translate(
        source(),
        TARGET,
        registry=registry(),
        provider=provider,
        options=RepairOptions(max_total_tokens=1000),
    )
    assert not outcome.ok
    assert len(provider.requests) == 1
    assert "token budget" in outcome.stop_reason
    assert outcome.usage.total_tokens == 1100


def test_same_errors_coming_back_is_no_progress() -> None:
    sidestep = proposal(2, 2, "    float x = undefined_thing;", "    float y = undefined_thing;")
    provider = FakeProvider([sidestep, FIX])
    outcome = repair_and_translate(source(), TARGET, registry=registry(), provider=provider)
    assert not outcome.ok
    assert outcome.attempts[0].outcome is Outcome.IMPROVED
    assert outcome.stop_reason == "no progress: the same errors came back"
    assert len(provider.requests) == 1


def test_only_compile_errors_are_repaired() -> None:
    provider = FakeProvider([FIX])
    outcome = repair_and_translate(
        source(GOOD), TARGET, registry=registry(cross=FakeCross(fail=True)), provider=provider
    )
    assert not outcome.ok
    assert provider.requests == []
    assert "not a compile error" in outcome.stop_reason


def test_edits_to_other_files_are_rejected() -> None:
    wrong_file = proposal(1, 1, "x", "y", file="/etc/passwd")
    outcome = repair_and_translate(
        source(),
        TARGET,
        registry=registry(),
        provider=FakeProvider([wrong_file]),
        options=RepairOptions(max_attempts=1),
    )
    assert outcome.attempts[0].outcome is Outcome.REJECTED
    assert "not provided" in outcome.attempts[0].message


def test_includes_are_read_only_context_and_nothing_else_is_sent(tmp_path: Path) -> None:
    (tmp_path / "common.glsl").write_text("float shared_value;\n")
    (tmp_path / "secrets.txt").write_text("TOP-SECRET-TOKEN-12345\n")
    main = tmp_path / "main.frag"
    main.write_text('#include "common.glsl"\nvoid main() {\n    float x = undefined_thing;\n}\n')
    src = source(main.read_text(), path=main)
    edit_include = proposal(1, 1, "float shared_value;", "float other;", file="common.glsl")
    provider = FakeProvider(
        [
            edit_include,
            proposal(
                3, 3, "    float x = undefined_thing;", "    float x = 1.0;", file="main.frag"
            ),
        ]
    )
    outcome = repair_and_translate(src, TARGET, registry=registry(), provider=provider)
    assert outcome.ok
    assert outcome.attempts[0].outcome is Outcome.REJECTED
    assert "read-only" in outcome.attempts[0].message
    assert outcome.files_sent == ["main.frag", "common.glsl"]
    everything = " ".join(r.system + r.user for r in provider.requests)
    assert "shared_value" in everything
    assert "TOP-SECRET-TOKEN" not in everything
    assert str(tmp_path) not in everything  # no absolute paths leak
    assert main.read_text().count("undefined_thing") == 1  # the file on disk is never touched


def test_prepare_prompt_for_dry_run_sends_nothing() -> None:
    errors = [Diagnostic(severity=Severity.ERROR, message="bad", file="shader", line=2, tool="t")]
    prompt = prepare_repair_prompt(source(), TARGET, errors, tool="fake")
    assert "undefined_thing" in prompt.user
    assert prompt.files_sent == ["shader"]


def test_describe_summarises_attempts_and_tokens() -> None:
    outcome = repair_and_translate(
        source(), TARGET, registry=registry(), provider=FakeProvider(["bad", FIX])
    )
    text = describe(outcome)
    assert "repair: fixed (fixed)" in text
    assert "attempt 1: rejected" in text
    assert "attempt 2: fixed" in text
    assert "tokens: 200 in / 100 out over 2 call(s)" in text
