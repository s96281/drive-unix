"""Dependency injection providers for the Web layer."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from core.config import ConfigManager
from core.factory import get_storage_provider, parse_remote_path
from storage.base import StorageProvider, managed_storage


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


def resolve_storage(
    remote_name: str,
    config: ConfigManager | None = None,
) -> StorageProvider:
    """Instantiate a storage provider for a remote node."""
    cfg = config or get_config_manager()
    return get_storage_provider(remote_name, cfg)


@contextmanager
def get_managed_storage(
    remote_name: str,
    config: ConfigManager | None = None,
) -> Iterator[StorageProvider]:
    """Context manager acquiring and deterministically releasing a StorageProvider."""
    storage = resolve_storage(remote_name, config)
    with managed_storage(storage) as provider:
        yield provider


def parse_uri(uri: str, default_remote: str | None = None) -> tuple[str, str]:
    """Parse remote:path notation."""
    return parse_remote_path(uri, default_remote)
