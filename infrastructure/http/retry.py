from __future__ import annotations

import random
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone


@dataclass(frozen=True)
class RetryPolicy:
    """Retry configuration for transient HTTP failures."""

    max_attempts: int = 4
    backoff_factor: float = 0.5
    max_delay: float = 8.0
    jitter: float = 0.1
    retryable_statuses: frozenset[int] = field(
        default_factory=lambda: frozenset({429, 500, 502, 503, 504})
    )
    retryable_methods: frozenset[str] = field(
        default_factory=lambda: frozenset({"GET", "HEAD", "OPTIONS", "DELETE"})
    )

    def should_retry(self, method: str, status_code: int | None = None) -> bool:
        return method.upper() in self.retryable_methods and (
            status_code is None or status_code in self.retryable_statuses
        )

    def delay_for(self, attempt: int, retry_after: str | None = None) -> float:
        """Return bounded exponential-backoff delay with optional Retry-After support."""
        retry_after_delay = _parse_retry_after(retry_after)
        if retry_after_delay is not None:
            return float(min(retry_after_delay, self.max_delay))

        exponential = self.backoff_factor * (2 ** max(attempt - 1, 0))
        jitter = random.uniform(0.0, self.jitter) if self.jitter else 0.0
        return float(min(exponential + jitter, self.max_delay))


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None

    try:
        return max(float(value), 0.0)
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max((retry_at - datetime.now(timezone.utc)).total_seconds(), 0.0)
    except (TypeError, ValueError, OverflowError):
        return None
