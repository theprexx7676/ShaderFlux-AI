#!/usr/bin/env python3
"""Print facts about a real ``dxc`` so the documentation can rest on evidence.

Not a test: it asserts nothing, it records what DXC actually does. CI runs it (the
``dxc-tests`` job) and its output is read when updating ``docs/matrix-conventions.md`` and
``docs/pain-points.md``. Needs ``dxc`` and ``spirv-cross`` on PATH.

    python scripts/dxc_experiments.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "corpus" / "hlsl"


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=120)


def compile_spirv(work: Path, source: str, profile: str, flags: list[str]) -> Path | str:
    """Return the SPIR-V path, or the error text."""
    out = work / "out.spv"
    out.unlink(missing_ok=True)
    command = ["dxc", "-spirv", "-T", profile, "-E", "main", *flags, "-Fo", out.name, source]
    result = run(command, work)
    if result.returncode != 0 or not out.exists():
        return (result.stderr or result.stdout).strip()[:600]
    return out


def reflect(work: Path, spirv: Path) -> dict:
    result = run(["spirv-cross", spirv.name, "--reflect"], work)
    return json.loads(result.stdout) if result.returncode == 0 else {"error": result.stderr[:300]}


def section(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def resources(reflection: dict) -> dict[str, tuple[int, int]]:
    found = {}
    for key in ("ubos", "ssbos", "separate_images", "separate_samplers", "textures", "images"):
        for item in reflection.get(key, []):
            found[f"{key}:{item['name']}"] = (item.get("set", 0), item.get("binding"))
    return found


def main() -> int:
    if not shutil.which("dxc") or not shutil.which("spirv-cross"):
        print("needs dxc and spirv-cross on PATH")
        return 2
    work = Path(tempfile.mkdtemp(prefix="dxc-exp-"))

    section("dxc --version")
    version = run(["dxc", "--version"], work)
    print(repr(version.stdout.strip()), repr(version.stderr.strip()))
    section("dxc -help (binding options)")
    helptext = run(["dxc", "-help"], work).stdout + run(["dxc", "--help"], work).stdout
    for line in helptext.splitlines():
        if "fvk" in line or "-Zpr" in line or "-Zpc" in line or "spirv" in line.lower():
            print(line.rstrip())

    # 1. Binding mapping: default versus the flags `shaderflux lint` proposes
    section("binding mapping of tests/corpus/hlsl/collision.hlsl")
    shutil.copy(CORPUS / "collision.hlsl", work / "collision.hlsl")
    default = compile_spirv(work, "collision.hlsl", "ps_6_0", [])
    if isinstance(default, str):
        print("default mapping FAILED to compile:", default)
    else:
        print("default :", json.dumps(resources(reflect(work, default)), sort_keys=True))
    sys.path.insert(0, str(ROOT / "src"))
    from shaderflux.analysis.bindings import parse_hlsl_bindings, propose_policy

    plan = propose_policy(parse_hlsl_bindings((CORPUS / "collision.hlsl").read_text()))
    flags = plan.policy.to_args() if plan.policy else []
    print("flags proposed by shaderflux:", flags)
    fixed = compile_spirv(work, "collision.hlsl", "ps_6_0", flags)
    if isinstance(fixed, str):
        print("proposed flags FAILED to compile:", fixed)
    else:
        print("fixed   :", json.dumps(resources(reflect(work, fixed)), sort_keys=True))

    # 2. Matrix layout of members with and without qualifiers, and the -Zpr / -Zpc flags
    section("matrix layout in a constant buffer (reflection of each member)")
    matrix_hlsl = """\
cbuffer U : register(b0)
{
    float4x4 plain;
    row_major float4x4 rowm;
    column_major float4x4 colm;
    float2x3 rect;
};
float4 main(float4 p : POSITION) : SV_Position
{
    return mul(p, plain) + mul(p, rowm) + mul(p, colm) + float4(mul(p.xy, rect), 0);
}
"""
    (work / "matrix.hlsl").write_text(matrix_hlsl)
    for label, extra in (("default", []), ("-Zpr", ["-Zpr"]), ("-Zpc", ["-Zpc"])):
        spirv = compile_spirv(work, "matrix.hlsl", "vs_6_0", extra)
        if isinstance(spirv, str):
            print(f"[{label}] FAILED: {spirv}")
            continue
        reflection = reflect(work, spirv)
        for block in reflection.get("types", {}).values():
            if block.get("name", "").endswith("U"):
                rows = [
                    {k: m.get(k) for k in ("name", "type", "offset", "matrix_stride", "row_major")}
                    for m in block["members"]
                ]
                print(f"[{label}]", json.dumps(rows))

    # 3. Is the HLSL that SPIRV-Cross generates accepted by DXC, as SPIR-V and as DXIL?
    section("re-check of SPIRV-Cross HLSL output with DXC (SPIR-V vs DXIL)")
    from shaderflux.core.models import ShaderLanguage, ShaderStage, Target
    from shaderflux.pipeline.translate import TranslateOptions, translate
    from shaderflux.source.inputs import load_source
    from shaderflux.tools.registry import default_registry

    for name in ("textured.frag", "passthrough.vert", "rich.frag"):
        shader = ROOT / "tests" / "corpus" / "glsl" / name
        result = translate(
            load_source(shader),
            Target(language=ShaderLanguage.HLSL, version="50"),
            registry=default_registry(),
            options=TranslateOptions(recheck=False),
        )
        if not result.ok or result.output_text is None:
            print(f"{name}: translation failed: {[d.format() for d in result.diagnostics][:2]}")
            continue
        (work / "gen.hlsl").write_text(result.output_text)
        stage = ShaderStage.VERTEX if name.endswith(".vert") else ShaderStage.FRAGMENT
        profile = "vs_6_0" if stage is ShaderStage.VERTEX else "ps_6_0"
        as_spirv = compile_spirv(work, "gen.hlsl", profile, [])
        dxil = run(["dxc", "-T", profile, "-E", "main", "-Fo", "gen.dxil", "gen.hlsl"], work)
        spirv_text = "ok" if not isinstance(as_spirv, str) else "FAILED: " + as_spirv[:200]
        dxil_text = "ok" if dxil.returncode == 0 else "FAILED: " + dxil.stderr[:200]
        print(f"{name}: as SPIR-V -> {spirv_text} | as DXIL -> {dxil_text}")
    print("\ndone")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
