"""Configuration loading.

Precedence, highest first: command-line overrides, environment variables,
project file (``shaderflux.toml`` found by walking up from the working
directory), user file, built-in defaults.

The API key is deliberately **not** a setting. It is only ever read from the
``ANTHROPIC_API_KEY`` environment variable by the LLM layer.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import platformdirs
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shaderflux.core.errors import InvalidInputError

PROJECT_FILE = "shaderflux.toml"
_FORBIDDEN_KEYS = {"api_key", "anthropic_api_key", "apikey"}

# Environment variable -> dotted setting path.
ENV_MAP: dict[str, str] = {
    "SHADERFLUX_ENVIRONMENT": "default_environment",
    "SHADERFLUX_CACHE_DIR": "cache_dir",
    "SHADERFLUX_REPORT_DIR": "report_dir",
    "SHADERFLUX_TIMEOUT": "tool_timeout_s",
    "SHADERFLUX_LLM": "llm.enabled",
    "SHADERFLUX_MODEL": "llm.model",
    "SHADERFLUX_MAX_ATTEMPTS": "llm.max_attempts",
}


class LlmSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    model: str | None = None
    max_attempts: int = Field(default=3, ge=1, le=10)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: dict[str, str] = Field(default_factory=dict)
    include_dirs: list[Path] = Field(default_factory=list)
    default_environment: str = "vulkan1.2"
    tool_timeout_s: float = Field(default=60.0, gt=0)
    cache_dir: Path | None = None
    report_dir: Path | None = None
    llm: LlmSettings = Field(default_factory=LlmSettings)


class LoadedSettings(BaseModel):
    """Effective settings and where each value came from."""

    settings: Settings
    sources: dict[str, str]
    files: list[str]


def find_project_file(start: Path) -> Path | None:
    """Walk up from ``start`` looking for ``shaderflux.toml``."""
    current = start.resolve()
    for directory in (current, *current.parents):
        candidate = directory / PROJECT_FILE
        if candidate.is_file():
            return candidate
    return None


def user_config_path() -> Path:
    return Path(platformdirs.user_config_dir("shaderflux")) / "config.toml"


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise InvalidInputError(f"{path}: invalid TOML: {exc}") from exc
    except OSError as exc:
        raise InvalidInputError(f"cannot read {path}: {exc.strerror or exc}") from exc
    _reject_secrets(data, path)
    return data


def _reject_secrets(data: Mapping[str, Any], path: Path, prefix: str = "") -> None:
    for key, value in data.items():
        if key.lower() in _FORBIDDEN_KEYS:
            raise InvalidInputError(
                f"{path}: '{prefix}{key}' must not be stored in a config file; "
                "set the ANTHROPIC_API_KEY environment variable instead"
            )
        if isinstance(value, Mapping):
            _reject_secrets(value, path, f"{prefix}{key}.")


def flatten_settings(data: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested tables. Tables under ``tools`` stay as one value."""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, Mapping) and path != "tools":
            flat.update(flatten_settings(value, path + "."))
        else:
            flat[path] = value
    return flat


def _unflatten(flat: Mapping[str, Any]) -> dict[str, Any]:
    nested: dict[str, Any] = {}
    for dotted, value in flat.items():
        parts = dotted.split(".")
        node = nested
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return nested


def _parse_env_value(path: str, raw: str) -> Any:
    if path == "llm.enabled":
        lowered = raw.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off", ""}:
            return False
        raise InvalidInputError(f"SHADERFLUX_LLM must be true or false, got {raw!r}")
    return raw


def load_settings(
    *,
    cwd: Path | None = None,
    environ: Mapping[str, str] | None = None,
    user_file: Path | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
) -> LoadedSettings:
    """Load and merge all configuration layers."""
    environ = os.environ if environ is None else environ
    cwd = cwd or Path.cwd()

    layers: list[tuple[str, dict[str, Any]]] = []
    files: list[str] = []

    user_path = user_file if user_file is not None else user_config_path()
    if user_path.is_file():
        layers.append((f"user file ({user_path})", flatten_settings(_read_toml(user_path))))
        files.append(str(user_path))
    project_path = find_project_file(cwd)
    if project_path is not None:
        layers.append(
            (f"project file ({project_path})", flatten_settings(_read_toml(project_path)))
        )
        files.append(str(project_path))

    env_layer = {
        path: _parse_env_value(path, environ[name])
        for name, path in ENV_MAP.items()
        if name in environ
    }
    if env_layer:
        layers.append(("environment", env_layer))
    if cli_overrides:
        layers.append(("command line", {k: v for k, v in cli_overrides.items() if v is not None}))

    merged: dict[str, Any] = {}
    origin: dict[str, str] = {}
    for name, layer in layers:
        for key, value in layer.items():
            merged[key] = value
            origin[key] = name

    try:
        settings = Settings.model_validate(_unflatten(merged))
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise InvalidInputError(f"invalid configuration: {details}") from exc

    sources: dict[str, str] = {}
    for key in flatten_settings(settings.model_dump(mode="json")):
        sources[key] = origin.get(key, "default")
    for key, name in origin.items():
        sources.setdefault(key, name)
    return LoadedSettings(settings=settings, sources=sources, files=files)
