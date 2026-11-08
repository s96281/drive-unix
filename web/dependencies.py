"""Dependency injection providers for the Web layer."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from core.config import ConfigManager
from core.factory import get_storage_provider, parse_remote_path
from storage.base import StorageProvider, managed_storage
from web.storage_pool import WebStoragePool, storage_pool


_default_config_manager: ConfigManager | None = None


def get_config_manager() -> ConfigManager:
    """Return the runtime ConfigManager instance."""
    global _default_config_manager
    if _default_config_manager is None:
        _default_config_manager = ConfigManager()
    return _default_config_manager


def set_config_manager(manager: ConfigManager | None) -> None:
    """Explicitly override global ConfigManager for tests or custom environments."""
    global _default_config_manager
    _default_config_manager = manager


def get_storage_pool() -> WebStoragePool:
    """Return the global WebStoragePool instance."""
    return storage_pool


def resolve_storage(
    remote_name: str,
    config: ConfigManager | None = None,
    *,
    use_pool: bool = True,
) -> StorageProvider:
    """Resolve a StorageProvider for a remote node.

    When `use_pool=True` (default in Web layer), returns a pooled provider instance
    wrapped in a PooledStorageProxy to enable connection reuse across web browsing requests.
    """
    cfg = config or get_config_manager()
    if use_pool and storage_pool.enabled:
        return storage_pool.acquire(remote_name, cfg)
    return get_storage_provider(remote_name, cfg)


@contextmanager
def get_managed_storage(
    remote_name: str,
    config: ConfigManager | None = None,
    *,
    use_pool: bool = True,
) -> Iterator[StorageProvider]:
    """Context manager acquiring and deterministically releasing a StorageProvider."""
    storage = resolve_storage(remote_name, config, use_pool=use_pool)
    with managed_storage(storage) as provider:
        yield provider


def parse_uri(uri: str, default_remote: str | None = None) -> tuple[str, str]:
    """Parse remote:path notation."""
    return parse_remote_path(uri, default_remote)
