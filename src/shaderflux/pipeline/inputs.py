"""Reading shader files and working out what they are."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import ShaderLanguage, ShaderSource, ShaderStage

DEFAULT_MAX_BYTES = 5 * 1024 * 1024

_LANGUAGE_BY_EXTENSION: dict[str, ShaderLanguage] = {
    ".hlsl": ShaderLanguage.HLSL,
    ".hlsli": ShaderLanguage.HLSL,
    ".fx": ShaderLanguage.HLSL,
    ".glsl": ShaderLanguage.GLSL,
    ".vert": ShaderLanguage.GLSL,
    ".frag": ShaderLanguage.GLSL,
    ".comp": ShaderLanguage.GLSL,
    ".geom": ShaderLanguage.GLSL,
    ".tesc": ShaderLanguage.GLSL,
    ".tese": ShaderLanguage.GLSL,
    ".mesh": ShaderLanguage.GLSL,
    ".task": ShaderLanguage.GLSL,
    ".spv": ShaderLanguage.SPIRV,
}

_STAGE_BY_EXTENSION: dict[str, ShaderStage] = {
    ".vert": ShaderStage.VERTEX,
    ".frag": ShaderStage.FRAGMENT,
    ".comp": ShaderStage.COMPUTE,
    ".geom": ShaderStage.GEOMETRY,
    ".tesc": ShaderStage.TESS_CONTROL,
    ".tese": ShaderStage.TESS_EVALUATION,
    ".mesh": ShaderStage.MESH,
    ".task": ShaderStage.TASK,
}

# Name suffixes such as ``lighting.ps.hlsl`` or ``lighting_ps.hlsl``.
_STAGE_BY_SUFFIX: dict[str, ShaderStage] = {
    "vs": ShaderStage.VERTEX,
    "vert": ShaderStage.VERTEX,
    "vertex": ShaderStage.VERTEX,
    "ps": ShaderStage.FRAGMENT,
    "fs": ShaderStage.FRAGMENT,
    "frag": ShaderStage.FRAGMENT,
    "pixel": ShaderStage.FRAGMENT,
    "fragment": ShaderStage.FRAGMENT,
    "cs": ShaderStage.COMPUTE,
    "comp": ShaderStage.COMPUTE,
    "compute": ShaderStage.COMPUTE,
    "gs": ShaderStage.GEOMETRY,
    "geom": ShaderStage.GEOMETRY,
    "hs": ShaderStage.TESS_CONTROL,
    "ds": ShaderStage.TESS_EVALUATION,
    "ms": ShaderStage.MESH,
    "as": ShaderStage.TASK,
}

_STAGE_NAMES: dict[str, ShaderStage] = {
    "vertex": ShaderStage.VERTEX,
    "pixel": ShaderStage.FRAGMENT,
    "fragment": ShaderStage.FRAGMENT,
    "compute": ShaderStage.COMPUTE,
    "geometry": ShaderStage.GEOMETRY,
    "hull": ShaderStage.TESS_CONTROL,
    "domain": ShaderStage.TESS_EVALUATION,
    "tesscontrol": ShaderStage.TESS_CONTROL,
    "tesseval": ShaderStage.TESS_EVALUATION,
    "mesh": ShaderStage.MESH,
    "amplification": ShaderStage.TASK,
    "task": ShaderStage.TASK,
}

_GLSL_PRAGMA_STAGE = re.compile(r"#\s*pragma\s+shader_stage\s*\(\s*(\w+)\s*\)")
_HLSL_SHADER_ATTR = re.compile(r"\[\s*shader\s*\(\s*\"(\w+)\"\s*\)\s*\]")
_HLSL_ENTRY = re.compile(r"\b(\w+)\s*\([^;{)]{0,500}\)\s*:\s*SV_\w+")
_HLSL_NUMTHREADS = re.compile(
    r"\[\s*numthreads\s*\([^)]{0,100}\)\s*\]\s*(?:\[[^\]]{0,100}\]\s*){0,8}void\s+(\w+)"
)


def parse_stage_name(name: str) -> ShaderStage:
    """Parse a user-supplied stage name (``fragment``, ``pixel``, ``frag`` ...)."""
    key = name.strip().lower().replace("-", "").replace("_", "")
    if key in _STAGE_NAMES:
        return _STAGE_NAMES[key]
    if key in _STAGE_BY_SUFFIX:
        return _STAGE_BY_SUFFIX[key]
    raise InvalidInputError(
        f"unknown shader stage {name!r} "
        "(use vertex, fragment/pixel, compute, geometry, tess_control, tess_evaluation, mesh, task)"
    )


def parse_language_name(name: str) -> ShaderLanguage:
    key = name.strip().lower()
    aliases = {"spv": "spirv", "spir-v": "spirv", "metal": "msl"}
    try:
        return ShaderLanguage(aliases.get(key, key))
    except ValueError:
        raise InvalidInputError(
            f"unknown language {name!r} (use hlsl, glsl, spirv or msl)"
        ) from None


def detect_language(path: Path) -> ShaderLanguage | None:
    return _LANGUAGE_BY_EXTENSION.get(path.suffix.lower())


def detect_stage(path: Path | None, text: str, language: ShaderLanguage) -> ShaderStage | None:
    """Best-effort stage detection. Returns ``None`` when unsure; never guesses wildly."""
    if language is ShaderLanguage.GLSL:
        match = _GLSL_PRAGMA_STAGE.search(text)
        if match and match.group(1).lower() in _STAGE_NAMES:
            return _STAGE_NAMES[match.group(1).lower()]
    if language is ShaderLanguage.HLSL:
        match = _HLSL_SHADER_ATTR.search(text)
        if match and match.group(1).lower() in _STAGE_NAMES:
            return _STAGE_NAMES[match.group(1).lower()]
    if path is None:
        return None
    if path.suffix.lower() in _STAGE_BY_EXTENSION:
        return _STAGE_BY_EXTENSION[path.suffix.lower()]
    parts = re.split(r"[._-]", path.stem.lower())
    if len(parts) > 1 and parts[-1] in _STAGE_BY_SUFFIX:
        return _STAGE_BY_SUFFIX[parts[-1]]
    return None


def find_entry_candidates(text: str, language: ShaderLanguage) -> list[str]:
    """List plausible entry points. HLSL only; GLSL always uses ``main``."""
    if language is not ShaderLanguage.HLSL:
        return ["main"]
    found: list[str] = []
    for regex in (_HLSL_NUMTHREADS, _HLSL_ENTRY):
        for match in regex.finditer(text):
            if match.group(1) not in found:
                found.append(match.group(1))
    return found


def decode_text(data: bytes, *, name: str = "input") -> str:
    """Decode UTF-8 (with or without BOM). Rejects binary data."""
    if b"\0" in data:
        raise InvalidInputError(f"{name} looks like a binary file, not shader source")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidInputError(f"{name} is not valid UTF-8 text: {exc.reason}") from exc


def load_source(
    path: Path,
    *,
    language: ShaderLanguage | None = None,
    stage: ShaderStage | None = None,
    entry_point: str | None = None,
    defines: Mapping[str, str | None] | None = None,
    include_dirs: Sequence[Path] = (),
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> ShaderSource:
    """Read a shader file into a :class:`ShaderSource`."""
    path = Path(path)
    if not path.is_file():
        raise InvalidInputError(f"no such file: {path}")
    size = path.stat().st_size
    if size > max_bytes:
        raise InvalidInputError(
            f"{path} is {size} bytes, over the {max_bytes} byte limit (raise it with --max-size)"
        )
    data = path.read_bytes()

    language = language or detect_language(path)
    if language is None:
        raise InvalidInputError(f"cannot tell the language of {path.name}; pass --from")

    common = {
        "path": path,
        "language": language,
        "defines": dict(defines or {}),
        "include_dirs": list(include_dirs),
    }
    if language is ShaderLanguage.SPIRV:
        return ShaderSource(binary=data, stage=stage, entry_point=entry_point or "main", **common)

    text = decode_text(data, name=path.name)
    return ShaderSource(
        text=text,
        stage=stage or detect_stage(path, text, language),
        entry_point=entry_point or "main",
        **common,
    )
