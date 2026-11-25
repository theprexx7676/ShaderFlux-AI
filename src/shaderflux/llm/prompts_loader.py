"""Loading prompt templates and filling their placeholders."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources

from shaderflux.core.errors import ShaderFluxError

_VERSION = re.compile(r"<!--\s*version:\s*(\w+)\s*-->")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    body: str

    def render(self, **values: str) -> str:
        """Replace ``{{name}}`` placeholders. Unknown or missing names are errors."""
        used = set(re.findall(r"\{\{(\w+)\}\}", self.body))
        if used != set(values):
            raise ShaderFluxError(
                f"prompt {self.name}: placeholders {sorted(used)} do not match {sorted(values)}"
            )
        text = self.body
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        return text


def load_prompt(name: str) -> Prompt:
    raw = resources.files("shaderflux.llm").joinpath(f"prompts/{name}.md").read_text("utf-8")
    match = _VERSION.search(raw)
    if match is None:
        raise ShaderFluxError(f"prompt {name} has no version header")
    return Prompt(name=name, version=match.group(1), body=_VERSION.sub("", raw, count=1).strip())


def prompt_version(*names: str) -> str:
    """A string like ``system@1+repair_compile_error@1`` recorded in reports."""
    return "+".join(f"{p.name}@{p.version}" for p in (load_prompt(n) for n in names))
