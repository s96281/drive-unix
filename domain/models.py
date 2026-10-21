"""Core domain models shared by storage and application layers."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class FileItem(BaseModel):
    """Normalized representation of a remote/local file-system item."""

    name: str
    path: str
    is_dir: bool
    size: int = 0
    modified_at: datetime | None = None
    remote_hash: str | None = None
    thumbnail_url: str | None = None
