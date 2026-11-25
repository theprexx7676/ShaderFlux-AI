"""Logging helpers. Every run gets an id so log lines and reports can be matched."""

from __future__ import annotations

import logging
import uuid

LOGGER_NAME = "shaderflux"


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def get_logger(run_id: str | None = None) -> logging.LoggerAdapter[logging.Logger]:
    return logging.LoggerAdapter(logging.getLogger(LOGGER_NAME), {"run_id": run_id or "-"})


def setup_logging(*, verbose: bool = False, quiet: bool = False) -> None:
    """Configure the ``shaderflux`` logger for command-line use."""
    level = logging.DEBUG if verbose else logging.ERROR if quiet else logging.WARNING
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s [%(run_id)s] %(message)s"))
        logger.addHandler(handler)
