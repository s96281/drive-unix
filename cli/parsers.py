"""CLI input parsing helpers."""

from __future__ import annotations

import re
from datetime import datetime


_SIZE_RE = re.compile(r"^([\d.]+)\s*([KMGT]?B?)$", re.IGNORECASE)
_SIZE_MULTIPLIERS = {
    "": 1,
    "K": 1024,
    "M": 1024**2,
    "G": 1024**3,
    "T": 1024**4,
}


def parse_size_to_bytes(size_str: str) -> int:
    """Convert values such as ``10MB`` or ``1.5GB`` to bytes."""
    if not size_str:
        return 0

    match = _SIZE_RE.fullmatch(size_str.strip())
    if not match:
        raise ValueError(
            f"無法解析大小格式: {size_str} (支援範例: 10MB, 1.5GB)"
        )

    value_str, unit = match.groups()
    unit = unit.upper().replace("B", "")
    return int(float(value_str) * _SIZE_MULTIPLIERS[unit])


def parse_date_to_aware_datetime(date_str: str) -> datetime:
    """Parse a date or ISO-8601 timestamp into an aware datetime."""
    if not date_str:
        return None

    try:
        return datetime.strptime(date_str, "%Y-%m-%d").astimezone()
    except ValueError:
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"無法解析日期格式: {date_str} (請使用 YYYY-MM-DD)"
            ) from exc
