"""Backward-compatible import facade for the StorageProvider interface.

New code should import from ``storage.base``.
"""

from storage.base import FileItem, StorageProvider

__all__ = ["FileItem", "StorageProvider"]
