"""``shaderflux fix`` as a library and as a command. No tools, no network, no key needed."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from shaderflux.analysis.limits import MAX_LINE_CHARS
from shaderflux.analysis.reflection import Reflection, Resource, ResourceKind
from shaderflux.cli.app import app
from shaderflux.core.errors import InvalidInputError, ToolFailedError
from shaderflux.core.models import (
    Diagnostic,
    Severity,
    ShaderLanguage,
    ShaderSource,
    ShaderStage,
    Target,
)
from shaderflux.tools.base import ToolResult
from shaderflux.tools.registry import BackendRegistry
from shaderflux.workflows.fix_file import FixRequest, VerifyStatus, run_fix
from tests.fakes import result

pytestmark = pytest.mark.unit

runner = CliRunner()


@pytest.fixture
def shader(tmp_path: Path, corpus: Path) -> Path:
    target = tmp_path / "collision.hlsl"
    shutil.copy(corpus / "hlsl" / "collision.hlsl", target)
    return target


def test_default_is_a_dry_run_that_changes_nothing(shader: Path) -> None:
    before = shader.read_bytes()
    outcome = run_fix(FixRequest(shader))
    assert outcome.changed
    assert outcome.complete
    assert "+[[vk::binding(1, 0)]] Texture2D albedo" in outcome.diff
    assert outcome.written_to is None
    assert shader.read_bytes() == before


def test_write_changes_the_file_in_place(shader: Path) -> None:
    outcome = run_fix(FixRequest(shader, write=True))
    assert outcome.written_to == shader
    assert "[[vk::binding(" in shader.read_text()
    assert run_fix(FixRequest(shader)).plan.edits == []  # idempotent


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no POSIX permission bits")
def test_write_in_place_keeps_the_file_mode(shader: Path) -> None:
    shader.chmod(0o640)
    run_fix(FixRequest(shader, write=True))
    assert shader.stat().st_mode & 0o777 == 0o640


def test_out_writes_a_copy_and_leaves_the_original(shader: Path, tmp_path: Path) -> None:
    before = shader.read_bytes()
    copy = tmp_path / "fixed.hlsl"
    run_fix(FixRequest(shader, out=copy))
    assert shader.read_bytes() == before
    assert "[[vk::binding(" in copy.read_text()


def test_out_refuses_to_overwrite_without_force(shader: Path, tmp_path: Path) -> None:
    copy = tmp_path / "fixed.hlsl"
    copy.write_text("keep me")
    with pytest.raises(InvalidInputError, match="already exists"):
        run_fix(FixRequest(shader, out=copy))
    assert copy.read_text() == "keep me"
    run_fix(FixRequest(shader, out=copy, force=True))
    assert "[[vk::binding(" in copy.read_text()


def test_bad_options_fail_before_anything_is_written(shader: Path, tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError, match="either"):
        run_fix(FixRequest(shader, write=True, out=tmp_path / "x.hlsl"))
    with pytest.raises(InvalidInputError, match="cannot fix MAT009"):
        run_fix(FixRequest(shader, rules=["MAT009"]))
    with pytest.raises(InvalidInputError, match="directory"):
        run_fix(FixRequest(shader, out=tmp_path))
    with pytest.raises(InvalidInputError, match="no such file"):
        run_fix(FixRequest(tmp_path / "missing.hlsl"))


def test_glsl_input_is_refused(tmp_path: Path) -> None:
    glsl = tmp_path / "a.frag"
    glsl.write_text("void main() {}\n")
    with pytest.raises(InvalidInputError, match="only HLSL"):
        run_fix(FixRequest(glsl))


def test_bom_and_crlf_survive_a_write(tmp_path: Path) -> None:
    path = tmp_path / "a.hlsl"
    path.write_bytes(
        b"\xef\xbb\xbfcbuffer C : register(b0) { row_major float4x4 m; };\r\n"
        b"Texture2D t : register(t0);\r\n"
    )
    run_fix(FixRequest(path, write=True))
    data = path.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")
    assert data.count(b"\r\n") == 2
    assert data.count(b"\n") == 2


def test_binding_fixes_are_withheld_when_the_shader_includes_other_files(tmp_path: Path) -> None:
    (tmp_path / "common.hlsli").write_text("cbuffer C : register(b0) { row_major float4x4 m; };\n")
    main = tmp_path / "main.hlsl"
    main.write_text('#include "common.hlsli"\nTexture2D t : register(t0);\nfloat4x4 loose;\n')
    outcome = run_fix(FixRequest(main))
    assert not outcome.plan.rules & {"BND001"}
    assert any("includes other files" in note for note in outcome.notes)


def test_clean_file_has_nothing_to_fix(tmp_path: Path, corpus: Path) -> None:
    path = tmp_path / "clean.hlsl"
    shutil.copy(corpus / "lint" / "pbr_clean.hlsl", path)
    outcome = run_fix(FixRequest(path))
    assert not outcome.changed
    assert outcome.diff == ""


def test_oversized_input_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "wide.hlsl"
    path.write_text("a" * (MAX_LINE_CHARS + 1) + "\n")
    with pytest.raises(InvalidInputError, match="too big"):
        run_fix(FixRequest(path))


# ----------------------------------------------------------------------------- command


def test_cli_dry_run_prints_a_diff_and_exits_zero(shader: Path) -> None:
    result = runner.invoke(app, ["fix", str(shader)])
    assert result.exit_code == 0
    assert "+[[vk::binding(1, 0)]] Texture2D" in result.stdout
    assert "nothing was changed" in result.output


def test_cli_check_exits_one_when_fixes_are_pending(shader: Path) -> None:
    assert runner.invoke(app, ["fix", "--check", str(shader)]).exit_code == 1
    runner.invoke(app, ["fix", "--write", str(shader)])
    assert runner.invoke(app, ["fix", "--check", str(shader)]).exit_code == 0


def test_cli_check_cannot_be_combined_with_write(shader: Path) -> None:
    assert runner.invoke(app, ["fix", "--check", "--write", str(shader)]).exit_code == 2


def test_cli_only_selects_a_rule(shader: Path) -> None:
    result = runner.invoke(app, ["fix", "--only", "mat002", str(shader)])
    assert result.exit_code == 0
    assert "BND001" not in result.output


def test_cli_bad_input_exits_two(tmp_path: Path) -> None:
    assert runner.invoke(app, ["fix", str(tmp_path / "nope.hlsl")]).exit_code == 2


# ----------------------------------------------------------------------------- --verify


class _FakeHlsl:
    """Stands in for DXC: fails on ``BROKEN`` or, when told to, on the attribute we insert."""

    name = "fake-dxc"
    languages = frozenset({ShaderLanguage.HLSL})

    def __init__(self, *, reject_attribute: bool = False, always_fail: bool = False) -> None:
        self.reject_attribute = reject_attribute
        self.always_fail = always_fail

    def compile(self, source: ShaderSource, *, target: Target) -> ToolResult:
        bad = self.always_fail or (self.reject_attribute and "[[vk::binding" in source.text)
        if bad:
            error = Diagnostic(severity=Severity.ERROR, message="boom", tool="fake", line=1)
            return result("fake-dxc", ok=False, errors=(error,))
        return result("fake-dxc", output=b"\x03\x02\x23\x07")


def _reflection(*slots: tuple[str, int, int]) -> Reflection:
    return Reflection(
        resources=[
            Resource(kind=ResourceKind.SAMPLED_IMAGE, name=n, type="t", set=s, binding=b)
            for n, s, b in slots
        ]
    )


def _registry(compiler: _FakeHlsl) -> BackendRegistry:
    reg = BackendRegistry()
    reg.register_compiler(compiler)  # type: ignore[arg-type]
    return reg


def _fragment(tmp_path: Path, corpus: Path) -> Path:
    path = tmp_path / "collision_ps.hlsl"
    shutil.copy(corpus / "hlsl" / "collision.hlsl", path)
    return path


def test_verify_ok_when_it_compiles_and_every_binding_is_distinct(
    tmp_path: Path, corpus: Path
) -> None:
    outcome = run_fix(
        FixRequest(_fragment(tmp_path, corpus), verify=True),
        registry=_registry(_FakeHlsl()),
        reflector=lambda _spirv: _reflection(("a", 0, 0), ("b", 0, 1)),
    )
    assert outcome.verification is not None
    assert outcome.verification.status is VerifyStatus.OK
    assert "fake-dxc" in (outcome.verification.tool or "")


def test_verify_reports_bindings_that_are_still_shared(tmp_path: Path, corpus: Path) -> None:
    outcome = run_fix(
        FixRequest(_fragment(tmp_path, corpus), verify=True),
        registry=_registry(_FakeHlsl()),
        reflector=lambda _spirv: _reflection(("a", 0, 0), ("b", 0, 0)),
    )
    assert outcome.verification is not None
    assert outcome.verification.status is VerifyStatus.COLLISIONS
    assert "set 0 binding 0: a, b" in outcome.verification.detail


def test_verify_without_a_compiler_says_nothing_was_checked(tmp_path: Path, corpus: Path) -> None:
    outcome = run_fix(
        FixRequest(_fragment(tmp_path, corpus), verify=True),
        registry=BackendRegistry(),
        reflector=None,
    )
    assert outcome.verification is not None
    assert outcome.verification.status is VerifyStatus.NOT_RUN


def test_verify_needs_a_stage(tmp_path: Path, corpus: Path) -> None:
    unnamed = tmp_path / "shader.hlsl"  # no stage in the name, none given
    shutil.copy(corpus / "hlsl" / "collision.hlsl", unnamed)
    outcome = run_fix(
        FixRequest(unnamed, verify=True), registry=_registry(_FakeHlsl()), reflector=None
    )
    assert outcome.verification is not None
    assert outcome.verification.status is VerifyStatus.NOT_RUN
    assert "stage" in outcome.verification.detail
    given = run_fix(
        FixRequest(unnamed, verify=True, stage=ShaderStage.FRAGMENT),
        registry=_registry(_FakeHlsl()),
        reflector=lambda _spirv: _reflection(("a", 0, 0)),
    )
    assert given.verification is not None
    assert given.verification.status is VerifyStatus.OK


def test_a_fix_that_breaks_compilation_is_not_written(tmp_path: Path, corpus: Path) -> None:
    path = _fragment(tmp_path, corpus)
    before = path.read_bytes()
    outcome = run_fix(
        FixRequest(path, write=True, verify=True),
        registry=_registry(_FakeHlsl(reject_attribute=True)),
        reflector=None,
    )
    assert outcome.verification is not None
    assert outcome.verification.status is VerifyStatus.REGRESSED
    assert outcome.written_to is None
    assert path.read_bytes() == before
    assert any("not written" in note for note in outcome.notes)


def test_a_shader_that_never_compiled_is_reported_as_such(tmp_path: Path, corpus: Path) -> None:
    outcome = run_fix(
        FixRequest(_fragment(tmp_path, corpus), verify=True),
        registry=_registry(_FakeHlsl(always_fail=True)),
        reflector=None,
    )
    assert outcome.verification is not None
    assert outcome.verification.status is VerifyStatus.STILL_BROKEN


def test_cli_verify_without_a_compiler_exits_two_and_says_not_verified(
    tmp_path: Path, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "shaderflux.workflows.fix_file.default_registry", lambda **_kw: BackendRegistry()
    )
    result = runner.invoke(app, ["fix", "--verify", str(_fragment(tmp_path, corpus))])
    assert result.exit_code == 2
    assert "not verified" in result.output


def test_cli_stage_without_verify_is_an_error(shader: Path) -> None:
    assert runner.invoke(app, ["fix", "--stage", "fragment", str(shader)]).exit_code == 2


def test_a_failed_reflection_keeps_the_fact_that_it_compiled(tmp_path: Path, corpus: Path) -> None:
    def broken(_spirv: bytes) -> Reflection:
        raise ToolFailedError("spirv-cross", "reflection failed: nope")

    outcome = run_fix(
        FixRequest(_fragment(tmp_path, corpus), verify=True),
        registry=_registry(_FakeHlsl()),
        reflector=broken,
    )
    assert outcome.verification is not None
    assert outcome.verification.status is VerifyStatus.OK
    assert "bindings not checked" in outcome.verification.detail


# ----------------------------------------------------------------------------- several files


def _tree(tmp_path: Path, corpus: Path) -> Path:
    (tmp_path / "shaders" / "sub").mkdir(parents=True)
    shutil.copy(corpus / "hlsl" / "collision.hlsl", tmp_path / "shaders" / "a.hlsl")
    shutil.copy(corpus / "lint" / "pbr_clean.hlsl", tmp_path / "shaders" / "sub" / "b.hlsl")
    return tmp_path


def test_cli_check_walks_a_glob_and_fails_if_any_file_needs_fixing(
    tmp_path: Path, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(_tree(tmp_path, corpus))
    result = runner.invoke(app, ["fix", "--check", "shaders/**/*.hlsl"])
    assert result.exit_code == 1
    assert "a.hlsl" in result.output
    assert "b.hlsl" in result.output  # every file is reported, not just the first


def test_cli_write_fixes_every_file_and_then_check_passes(
    tmp_path: Path, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(_tree(tmp_path, corpus))
    assert runner.invoke(app, ["fix", "--write", "shaders/**/*.hlsl"]).exit_code == 0
    assert "[[vk::binding(" in (tmp_path / "shaders" / "a.hlsl").read_text()
    assert runner.invoke(app, ["fix", "--check", "shaders/**/*.hlsl"]).exit_code == 0


def test_cli_out_needs_a_single_input(
    tmp_path: Path, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(_tree(tmp_path, corpus))
    result = runner.invoke(app, ["fix", "--out", "x.hlsl", "shaders/**/*.hlsl"])
    assert result.exit_code == 2
    assert not (tmp_path / "x.hlsl").exists()


def test_cli_one_unreadable_file_does_not_stop_the_others(
    tmp_path: Path, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(_tree(tmp_path, corpus))
    (tmp_path / "shaders" / "binary.hlsl").write_bytes(b"\x00\x01\x02")
    result = runner.invoke(app, ["fix", "--check", "shaders/**/*.hlsl"])
    assert result.exit_code == 2  # the worst outcome wins
    assert "a.hlsl" in result.output
    assert "binary file" in result.output


# ----------------------------------------------------------------------------- review findings


def test_an_unwritable_destination_is_a_clean_error_not_a_traceback(
    shader: Path, tmp_path: Path
) -> None:
    blocker = tmp_path / "plain_file"
    blocker.write_text("x")
    with pytest.raises(InvalidInputError, match="cannot write"):
        run_fix(FixRequest(shader, out=blocker / "x.hlsl"))
    result = runner.invoke(app, ["fix", "--out", str(blocker / "x.hlsl"), str(shader)])
    assert result.exit_code == 2
    assert "Traceback" not in result.output


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_write_follows_a_symlink_instead_of_replacing_it(tmp_path: Path, corpus: Path) -> None:
    real = tmp_path / "real.hlsl"
    shutil.copy(corpus / "hlsl" / "collision.hlsl", real)
    link = tmp_path / "link.hlsl"
    link.symlink_to(real.name)
    run_fix(FixRequest(link, write=True))
    assert link.is_symlink()
    assert "[[vk::binding(" in real.read_text()


def test_a_directory_as_input_is_named_as_such(tmp_path: Path) -> None:
    (tmp_path / "shaders.hlsl").mkdir()
    with pytest.raises(InvalidInputError, match="is a directory"):
        run_fix(FixRequest(tmp_path / "shaders.hlsl"))
