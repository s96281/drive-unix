"""Connection pooling and provider instance caching for Web browsing."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from core.config import ConfigManager, RemoteConfig
from core.factory import get_storage_provider
from domain.models import FileItem
from storage.base import (
    DeleteCapability,
    ProgressCallback,
    StorageProvider,
    StorageStat,
)

logger = logging.getLogger(__name__)

# Errors that indicate broken sockets or severed transports that cannot be reused
FATAL_CONNECTION_ERRORS: tuple[type[BaseException], ...] = (
    ConnectionResetError,
    ConnectionAbortedError,
    ConnectionRefusedError,
    BrokenPipeError,
    EOFError,
    TimeoutError,
)

# Optional Paramiko SSHException if installed
try:
    import paramiko
    FATAL_CONNECTION_ERRORS = FATAL_CONNECTION_ERRORS + (paramiko.SSHException,)
except ImportError:
    pass


def compute_remote_config_hash(remote_config: RemoteConfig) -> str:
    """Generate a deterministic signature of remote configuration fields.

    If any connection parameter (host, port, user, root_path, secret reference, etc.)
    changes, the hash changes, triggering an automatic pool recreation.
    """
    raw_dict = remote_config.model_dump(mode="json")
    # Normalize dictionary into sorted json string
    serialized = json.dumps(raw_dict, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


class PooledStorageProxy(StorageProvider):
    """Transparent proxy delegating calls to a cached StorageProvider while preventing premature closure.

    When Web endpoints use ``with managed_storage(storage) as provider:``,
    the context manager's ``__exit__`` calls ``provider.close()``.
    This proxy intercepts ``close()``, keeping the underlying transport
    (SSH transport, FTP control socket, or HTTP Keep-Alive session) alive in the pool.
    """

    def __init__(
        self,
        pool: WebStoragePool,
        remote_name: str,
        target: StorageProvider,
    ) -> None:
        self._pool = pool
        self._remote_name = remote_name
        self._target = target

    @property
    def target(self) -> StorageProvider:
        """Return the underlying real StorageProvider."""
        return self._target

    @property
    def delete_capability(self) -> DeleteCapability:
        return getattr(self._target, "delete_capability", DeleteCapability.PERMANENT_ONLY)

    def close(self) -> None:
        """Release back to pool instead of tearing down the physical connection."""
        self._pool.release(self._remote_name)

    def _handle_call(self, func_name: str, *args: Any, **kwargs: Any) -> Any:
        fn = getattr(self._target, func_name)
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            # Check if this is a fatal transport disconnect
            if isinstance(exc, FATAL_CONNECTION_ERRORS):
                logger.warning(
                    "Fatal connection error on remote '%s' during %s(): %s. Evicting from pool.",
                    self._remote_name,
                    func_name,
                    exc,
                )
                self._pool.evict(self._remote_name)
            raise

    # StorageProvider contract methods
    def list_dir(
        self,
        remote_path: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[FileItem]:
        return self._handle_call("list_dir", remote_path, offset=offset, limit=limit)

    def upload(
        self,
        local_path: str,
        remote_path: str,
        callback: ProgressCallback | None = None,
    ) -> bool:
        return self._handle_call("upload", local_path, remote_path, callback=callback)

    def download(
        self,
        remote_path: str,
        local_path: str,
        callback: ProgressCallback | None = None,
        recursive: bool = True,
    ) -> bool:
        return self._handle_call(
            "download",
            remote_path,
            local_path,
            callback=callback,
            recursive=recursive,
        )

    def delete(self, remote_path: str, permanent: bool = False) -> bool:
        return self._handle_call("delete", remote_path, permanent=permanent)

    def move(self, src: str, dst: str, overwrite: bool = False) -> bool:
        return self._handle_call("move", src, dst, overwrite=overwrite)

    def copy(self, src: str, dst: str, overwrite: bool = False) -> bool:
        return self._handle_call("copy", src, dst, overwrite=overwrite)

    def mkdir(self, remote_path: str, parents: bool = False) -> bool:
        return self._handle_call("mkdir", remote_path, parents=parents)

    def stat(self, remote_path: str) -> StorageStat:
        return self._handle_call("stat", remote_path)

    def get_hash(self, remote_path: str, algo: str) -> str:
        return self._handle_call("get_hash", remote_path, algo=algo)

    def get_share_link(self, remote_path: str) -> str:
        return self._handle_call("get_share_link", remote_path)

    def get_download_link(self, remote_path: str) -> str:
        return self._handle_call("get_download_link", remote_path)

    def get_thumbnail_link(self, remote_path: str) -> str | None:
        return self._handle_call("get_thumbnail_link", remote_path)

    def search(self, remote_path: str, query: str) -> list[FileItem]:
        return self._handle_call("search", remote_path, query)

    def validate_delete_request(self, permanent: bool) -> None:
        return self._handle_call("validate_delete_request", permanent=permanent)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)

    def __repr__(self) -> str:
        return f"<PooledStorageProxy remote={self._remote_name!r} target={self._target!r}>"


@dataclass
class PooledEntry:
    remote_name: str
    provider: StorageProvider
    config_hash: str
    created_at: float
    last_accessed_at: float
    access_count: int = 1
    in_use_count: int = 1
    lock: threading.Lock | None = None

    def touch(self) -> None:
        self.last_accessed_at = time.time()
        self.access_count += 1
        self.in_use_count += 1

    def release(self) -> None:
        self.last_accessed_at = time.time()
        if self.in_use_count > 0:
            self.in_use_count -= 1

    def is_expired(self, idle_timeout: float, now: float | None = None) -> bool:
        curr = now if now is not None else time.time()
        # Only evict if not currently actively handling a request
        return (self.in_use_count == 0) and ((curr - self.last_accessed_at) > idle_timeout)


class WebStoragePool:
    """Thread-safe connection pool manager for Web API sessions."""

    def __init__(
        self,
        idle_timeout_seconds: float = 300.0,
        max_cached_remotes: int = 32,
        enabled: bool = True,
    ) -> None:
        self.idle_timeout_seconds = idle_timeout_seconds
        self.max_cached_remotes = max_cached_remotes
        self.enabled = enabled

        self._pool: dict[str, PooledEntry] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def acquire(self, remote_name: str, config_manager: ConfigManager) -> StorageProvider:
        """Acquire a StorageProvider for `remote_name`, reusing pooled instance if valid."""
        if not self.enabled:
            return get_storage_provider(remote_name, config_manager)

        remote_config = config_manager.get_remote(remote_name)
        current_hash = compute_remote_config_hash(remote_config)
        now = time.time()

        old_entry_to_close: StorageProvider | None = None

        with self._lock:
            # Housekeeping: prune any idle connections when acquiring
            self._cleanup_idle_locked(now)

            entry = self._pool.get(remote_name)
            if entry is not None:
                # Check if remote configuration was mutated
                if entry.config_hash == current_hash:
                    entry.touch()
                    self._hits += 1
                    return PooledStorageProxy(self, remote_name, entry.provider)
                else:
                    logger.info(
                        "Remote '%s' config changed; invalidating pooled provider instance.",
                        remote_name,
                    )
                    old_entry_to_close = entry.provider
                    del self._pool[remote_name]

            self._misses += 1

        # Safely close old provider if config changed
        if old_entry_to_close is not None:
            self._safe_close_provider(old_entry_to_close)

        # Create new provider instance outside global pool lock to avoid blocking other remotes
        new_provider = get_storage_provider(remote_name, config_manager)

        with self._lock:
            # If another thread created an entry in the meantime, check again
            existing = self._pool.get(remote_name)
            if existing is not None and existing.config_hash == current_hash:
                # Prefer existing and discard new instance
                self._safe_close_provider(new_provider)
                existing.touch()
                return PooledStorageProxy(self, remote_name, existing.provider)

            # Evict LRU if maximum cached remotes reached
            if len(self._pool) >= self.max_cached_remotes:
                self._evict_lru_locked()

            new_entry = PooledEntry(
                remote_name=remote_name,
                provider=new_provider,
                config_hash=current_hash,
                created_at=now,
                last_accessed_at=now,
                access_count=1,
                in_use_count=1,
                lock=threading.Lock(),
            )
            self._pool[remote_name] = new_entry
            return PooledStorageProxy(self, remote_name, new_provider)

    def release(self, remote_name: str) -> None:
        """Notify pool that a request using `remote_name` has completed."""
        with self._lock:
            entry = self._pool.get(remote_name)
            if entry is not None:
                entry.release()

    def evict(self, remote_name: str) -> bool:
        """Evict and close the cached provider for `remote_name`."""
        provider_to_close: StorageProvider | None = None
        with self._lock:
            entry = self._pool.pop(remote_name, None)
            if entry is not None:
                provider_to_close = entry.provider

        if provider_to_close is not None:
            self._safe_close_provider(provider_to_close)
            return True
        return False

    def clear(self) -> None:
        """Close and discard all pooled providers."""
        with self._lock:
            entries = list(self._pool.values())
            self._pool.clear()

        for entry in entries:
            self._safe_close_provider(entry.provider)

    def cleanup_idle(self, max_idle_seconds: float | None = None) -> int:
        """Evict all connections that have been idle longer than timeout."""
        timeout = max_idle_seconds if max_idle_seconds is not None else self.idle_timeout_seconds
        now = time.time()
        to_close: list[StorageProvider] = []

        with self._lock:
            evicted_keys = [
                name
                for name, entry in self._pool.items()
                if entry.is_expired(timeout, now)
            ]
            for key in evicted_keys:
                entry = self._pool.pop(key)
                to_close.append(entry.provider)

        for provider in to_close:
            self._safe_close_provider(provider)

        if evicted_keys:
            logger.info("Evicted %d idle provider connection(s): %s", len(evicted_keys), evicted_keys)
        return len(evicted_keys)

    def stats(self) -> dict[str, Any]:
        """Return operational statistics of the connection pool."""
        now = time.time()
        with self._lock:
            active_entries = [
                {
                    "remote": name,
                    "idle_seconds": round(now - entry.last_accessed_at, 1),
                    "age_seconds": round(now - entry.created_at, 1),
                    "access_count": entry.access_count,
                    "in_use_count": entry.in_use_count,
                    "provider_class": entry.provider.__class__.__name__,
                }
                for name, entry in self._pool.items()
            ]
            return {
                "enabled": self.enabled,
                "idle_timeout_seconds": self.idle_timeout_seconds,
                "max_cached_remotes": self.max_cached_remotes,
                "cached_remotes_count": len(self._pool),
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio": round(self._hits / (self._hits + self._misses), 3)
                if (self._hits + self._misses) > 0
                else 0.0,
                "remotes": active_entries,
            }

    def _cleanup_idle_locked(self, now: float) -> None:
        """Internal helper to prune idle entries while holding self._lock."""
        expired = [
            name
            for name, entry in self._pool.items()
            if entry.is_expired(self.idle_timeout_seconds, now)
        ]
        for name in expired:
            entry = self._pool.pop(name)
            self._safe_close_provider(entry.provider)

    def _evict_lru_locked(self) -> None:
        """Evict the least recently used entry that is not in use."""
        candidates = [
            (name, entry)
            for name, entry in self._pool.items()
            if entry.in_use_count == 0
        ]
        if not candidates:
            candidates = list(self._pool.items())

        if candidates:
            # Sort by last_accessed_at ascending (oldest first)
            candidates.sort(key=lambda pair: pair[1].last_accessed_at)
            lru_name, lru_entry = candidates[0]
            del self._pool[lru_name]
            self._safe_close_provider(lru_entry.provider)

    @staticmethod
    def _safe_close_provider(provider: StorageProvider) -> None:
        close = getattr(provider, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:
                logger.warning("Error while closing pooled provider %r: %s", provider, exc)


# Global singleton instance for Web layer
storage_pool = WebStoragePool()
