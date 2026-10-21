"""Thread-safe rate limiting primitives used by concurrent operations."""

from __future__ import annotations

import threading
import time


class RateLimiter:
    """Reserve operation permits at least ``min_interval`` seconds apart.

    The limiter reserves the next available time while holding the lock and
    sleeps outside the lock, so worker threads do not block one another while
    waiting. The reservation schedule is deterministic; the exact instant a
    caller executes after ``acquire()`` returns still depends on OS scheduling.
    """

    def __init__(self, min_interval: float = 0.0):
        if min_interval < 0:
            raise ValueError("min_interval 不可小於 0")
        self.min_interval = float(min_interval)
        self._lock = threading.Lock()
        self._next_allowed_at = 0.0

    def acquire(self) -> None:
        if self.min_interval <= 0:
            return

        with self._lock:
            now = time.monotonic()
            scheduled_at = max(now, self._next_allowed_at)
            self._next_allowed_at = scheduled_at + self.min_interval

        delay = scheduled_at - now
        if delay > 0:
            time.sleep(delay)

    def reset(self) -> None:
        with self._lock:
            self._next_allowed_at = 0.0
