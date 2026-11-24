"""On-disk cache of successful translations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import ValidationError

from shaderflux.core.models import TranslationResult

CACHE_VERSION = "1"


def make_key(parts: Iterable[str]) -> str:
    """Hash an ordered list of strings into a cache key."""
    digest = hashlib.sha256(CACHE_VERSION.encode())
    for part in parts:
        digest.update(b"\0")
        digest.update(part.encode("utf-8"))
    return digest.hexdigest()


class TranslationCache:
    """Stores successful :class:`TranslationResult` objects keyed by input hash.

    A broken or unreadable entry is treated as a miss, never as an error.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _paths(self, key: str) -> tuple[Path, Path]:
        return self.directory / f"{key}.json", self.directory / f"{key}.bin"

    def get(self, key: str) -> TranslationResult | None:
        meta, blob = self._paths(key)
        try:
            result = TranslationResult.model_validate(json.loads(meta.read_text("utf-8")))
            if blob.exists():
                result.output_bytes = blob.read_bytes()
        except (OSError, ValueError, ValidationError):
            return None
        if result.output_text is None and result.output_bytes is None:
            return None
        result.cached = True
        return result

    def put(self, key: str, result: TranslationResult) -> None:
        if not result.ok:
            return
        meta, blob = self._paths(key)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            if result.output_bytes is not None:
                blob.write_bytes(result.output_bytes)
            meta.write_text(result.model_dump_json(), encoding="utf-8")
        except OSError:
            return  # a cache that cannot be written must never break a translation
