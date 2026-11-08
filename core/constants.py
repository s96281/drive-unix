"""Application-wide constants.

Keep values that affect behaviour in one place so domain/application code does not
spread magic numbers and provider-specific defaults throughout the project.
"""

from __future__ import annotations

from datetime import timedelta, timezone

DEFAULT_WORKERS = 4
DEFAULT_SCAN_WORKERS = 4
DEFAULT_SCAN_THROTTLE_SECONDS = 0.3
DEFAULT_BUFFER_SIZE = 64 * 1024
MAX_SCHEDULER_LOOKBACK = timedelta(days=7)
LOCAL_TIMEZONE = timezone(timedelta(hours=8))

MICROSOFT_PROVIDER_TYPES = frozenset({
    "onedrive",
    "onedrive_business",
    "sharepoint",
})

OFFICE_EXTENSIONS = frozenset({
    ".doc", ".docx", ".docm",
    ".xls", ".xlsx", ".xlsm",
    ".ppt", ".pptx", ".pptm",
})

__all__ = [
    "DEFAULT_BUFFER_SIZE",
    "DEFAULT_SCAN_THROTTLE_SECONDS",
    "DEFAULT_SCAN_WORKERS",
    "DEFAULT_WORKERS",
    "LOCAL_TIMEZONE",
    "MAX_SCHEDULER_LOOKBACK",
    "MICROSOFT_PROVIDER_TYPES",
    "OFFICE_EXTENSIONS",
]
