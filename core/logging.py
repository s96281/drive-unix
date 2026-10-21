"""Application logging helpers."""

from __future__ import annotations

import logging
import os

LOGGER_NAME = "drive_unix"


def configure_logging(level: str | None = None) -> None:
    """Configure application logging once without changing library root logging."""
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return

    configured_level = level or os.getenv("DRIVE_UNIX_LOG_LEVEL") or "WARNING"
    resolved_level = getattr(logging, configured_level.upper(), logging.WARNING)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    logger.setLevel(resolved_level)
    logger.addHandler(handler)
    logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the application namespace."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
