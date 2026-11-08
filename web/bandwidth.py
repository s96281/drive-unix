"""Thread-safe bandwidth rate limiter using token bucket algorithm."""

from __future__ import annotations

import threading
import time


class BandwidthLimiter:
    """Thread-safe token bucket rate limiter for global bandwidth throttling."""

    def __init__(self, limit_kbps: int = 0) -> None:
        self._lock = threading.Lock()
        self._limit_kbps = limit_kbps
        self._tokens: float = float(limit_kbps * 1024) if limit_kbps > 0 else 0.0
        self._capacity: float = float(limit_kbps * 1024) if limit_kbps > 0 else 0.0
        self._last_check: float = time.time()

    def set_limit_kbps(self, limit_kbps: int) -> None:
        """Update bandwidth limit in Kilobits per second (0 to disable)."""
        with self._lock:
            self._limit_kbps = max(0, limit_kbps)
            capacity = float(self._limit_kbps * 1024)
            self._capacity = capacity
            self._tokens = min(self._tokens, capacity)

    @property
    def limit_kbps(self) -> int:
        with self._lock:
            return self._limit_kbps

    def consume(self, num_bytes: int) -> None:
        """Reserve byte transfer quota. If rate limit is exceeded, sleep outside the lock."""
        if num_bytes <= 0:
            return

        sleep_duration = 0.0
        with self._lock:
            if self._limit_kbps <= 0:
                return

            now = time.time()
            elapsed = now - self._last_check
            self._last_check = now

            # Replenish tokens (bytes per second = limit_kbps * 1024 / 8)
            rate_bps = (self._limit_kbps * 1024) / 8.0
            self._tokens = min(self._capacity, self._tokens + elapsed * rate_bps)

            if self._tokens >= num_bytes:
                self._tokens -= num_bytes
            else:
                deficit = num_bytes - self._tokens
                self._tokens = 0.0
                sleep_duration = deficit / rate_bps if rate_bps > 0 else 0.0

        if sleep_duration > 0:
            time.sleep(sleep_duration)


bandwidth_limiter = BandwidthLimiter()
