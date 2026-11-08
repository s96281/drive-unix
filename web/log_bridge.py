"""Logging handler bridge directing Python log records to SSE broadcaster."""

from __future__ import annotations

import logging
import time
from typing import Any

from web.events import broadcaster

logger = logging.getLogger(__name__)


class SSELogHandler(logging.Handler):
    """Bridges logging output into the EventBroadcaster as 'log' SSE events."""

    def __init__(self, min_level: int = logging.INFO) -> None:
        super().__init__(level=min_level)
        self._last_bucket_reset = time.time()
        self._emitted_this_second = 0
        self._max_per_second = 30

    def emit(self, record: logging.LogRecord) -> None:
        # Ignore noisy web access logs or our own broadcaster emissions
        if record.name.startswith("uvicorn.access") or record.name.startswith("sse_starlette"):
            return

        now = time.time()
        if now - self._last_bucket_reset >= 1.0:
            self._last_bucket_reset = now
            self._emitted_this_second = 0

        if self._emitted_this_second >= self._max_per_second:
            return

        self._emitted_this_second += 1

        try:
            msg = self.format(record)
            payload: dict[str, Any] = {
                "level": record.levelname,
                "logger": record.name,
                "message": msg,
                "ts": record.created,
            }
            broadcaster.publish("log", payload)
        except Exception:
            self.handleError(record)


_global_handler: SSELogHandler | None = None


def setup_log_bridge(root_logger: logging.Logger | None = None, min_level: int = logging.INFO) -> SSELogHandler:
    """Attach the SSE handler to drive-unix application loggers."""
    global _global_handler
    if _global_handler is not None:
        _global_handler.setLevel(min_level)
        return _global_handler

    handler = SSELogHandler(min_level=min_level)
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)

    target_logger = root_logger or logging.getLogger("drive_unix")
    target_logger.addHandler(handler)

    # Also capture web app logs
    logging.getLogger("web").addHandler(handler)

    _global_handler = handler
    return handler
