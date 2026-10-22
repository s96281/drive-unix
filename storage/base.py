"""Abstract storage provider contract shared by all backends."""

from __future__ import annotations

import logging
from datetime import datetime
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from enum import Enum
from types import TracebackType
from typing import Literal, TypedDict

from domain.models import FileItem

ProgressCallback = Callable[[int, int], None]

logger = logging.getLogger(__name__)


class DeleteCapability(str, Enum):
    """Deletion semantics exposed by a storage backend.

    The capability is deliberately explicit because ``delete(permanent=False)``
    does not imply recoverability for protocols such as FTP/SFTP/WebDAV or the
    local filesystem.
    """

    PERMANENT_ONLY = "permanent_only"
    TRASH_ONLY = "trash_only"
    TRASH_AND_PERMANENT = "trash_and_permanent"

    @property
    def supports_trash(self) -> bool:
        return self in {self.TRASH_ONLY, self.TRASH_AND_PERMANENT}

    @property
    def supports_permanent(self) -> bool:
        return self in {self.PERMANENT_ONLY, self.TRASH_AND_PERMANENT}


class StorageStat(TypedDict, total=False):
    """Normalized metadata returned by :meth:`StorageProvider.stat`."""

    type: Literal["file", "folder", "remote"]
    name: str
    size: int
    total: int
    used: int
    created: datetime | str | None
    modified: datetime | str | None
    filecount: int


class StorageProvider(ABC):
    """Common contract implemented by local and remote storage backends."""

    delete_capability: DeleteCapability = DeleteCapability.PERMANENT_ONLY

    @abstractmethod
    def list_dir(
        self,
        remote_path: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[FileItem]:
        """List the direct children of ``remote_path``.

        Args:
            remote_path: Target directory path.
            offset: Zero-based starting index for pagination (default 0).
            limit: Maximum number of items to return, or None for all items.
        """
        raise NotImplementedError

    @abstractmethod
    def upload(
        self,
        local_path: str,
        remote_path: str,
        callback: ProgressCallback | None = None,
    ) -> bool:
        """Upload one local file to ``remote_path``."""
        raise NotImplementedError

    @abstractmethod
    def get_share_link(self, remote_path: str) -> str:
        """Return a share/download link for ``remote_path``."""
        raise NotImplementedError

    def get_download_link(self, remote_path: str) -> str:
        """Return a direct download link when supported."""
        raise NotImplementedError("This provider does not support template file download.")

    def get_preview_link(self, remote_path: str) -> str:
        """Return a preview link when supported."""
        raise NotImplementedError("This provider does not support file preview.")

    def get_thumbnail_link(self, remote_path: str) -> str:
        """Return a thumbnail image link when supported."""
        raise NotImplementedError("This provider does not support thumbnail retrieval.")

    @abstractmethod
    def download(
        self,
        remote_path: str,
        local_path: str,
        recursive: bool = False,
        callback: ProgressCallback | None = None,
    ) -> bool:
        """Download one remote file or, when supported, a directory tree."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, remote_path: str, permanent: bool = False) -> bool:
        """Delete ``remote_path``; ``False`` means the target was not removed.

        Callers must inspect :attr:`delete_capability` before describing the
        operation as recoverable.  Some providers permanently delete even when
        ``permanent`` is false.
        """
        raise NotImplementedError

    def validate_delete_request(self, *, permanent: bool) -> None:
        """Reject deletion modes that the provider cannot honour."""

        if permanent and not self.delete_capability.supports_permanent:
            raise ValueError("此 Provider 不支援永久刪除；刪除操作只會移至回收桶。")

    @abstractmethod
    def copy(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        """Copy an item within the same provider."""
        raise NotImplementedError

    @abstractmethod
    def move(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        """Move or rename an item within the same provider."""
        raise NotImplementedError

    @abstractmethod
    def mkdir(self, remote_path: str, parents: bool = False) -> bool:
        """Create a directory, optionally including missing parents."""
        raise NotImplementedError

    @abstractmethod
    def stat(self, remote_path: str) -> StorageStat:
        """Return normalized metadata for one path."""
        raise NotImplementedError

    def search(self, remote_path: str, query: str) -> list[FileItem]:
        """Perform provider-native search when available."""
        raise NotImplementedError("This provider does not support remote search.")

    def close(self) -> None:
        """Release provider-side persistent resources, if any."""

    def __enter__(self) -> StorageProvider:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        """Release resources without masking an exception already in flight."""
        try:
            self.close()
        except Exception:
            if exc is None:
                raise
            logger.exception("Provider cleanup failed while handling another error: %r", self)
        return False

    @abstractmethod
    def get_hash(self, remote_path: str, algo: str) -> str:
        """Return a provider-side content hash for ``remote_path``."""
        raise NotImplementedError


@contextmanager
def managed_storage(provider: StorageProvider) -> Iterator[StorageProvider]:
    """Own a provider for one operation and release it deterministically.

    ``getattr`` keeps lightweight test doubles and third-party adapters usable
    during the StorageProvider typing migration.
    """

    close = getattr(provider, "close", None)
    try:
        yield provider
    except BaseException:
        if callable(close):
            try:
                close()
            except Exception:
                logger.exception(
                    "Provider cleanup failed while handling another error: %r", provider
                )
        raise
    else:
        if callable(close):
            close()
