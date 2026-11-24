"""``shaderflux fix`` as a library and as a command. No tools, no network, no key needed."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from shaderflux.analysis.limits import MAX_LINE_CHARS
from shaderflux.cli.app import app
from shaderflux.core.errors import InvalidInputError
from shaderflux.workflows.fix_file import FixRequest, run_fix

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
