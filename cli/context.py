"""Shared runtime context for CLI commands."""

from __future__ import annotations

from dataclasses import dataclass

from core.config import ConfigManager
from core.factory import get_storage_provider, parse_remote_path
from storage.base import StorageProvider


@dataclass(slots=True)
class CLIContext:
    """Runtime dependencies shared by CLI commands."""

    config: ConfigManager

    @classmethod
    def create(cls) -> "CLIContext":
        return cls(config=ConfigManager())

    @property
    def default_remote(self) -> str | None:
        return self.config.config.default_remote

    def resolve_remote_path(self, value: str) -> tuple[str, str]:
        return parse_remote_path(value, self.default_remote)

    def storage(self, remote_name: str) -> StorageProvider:
        return get_storage_provider(remote_name, self.config)

    def storage_for(self, value: str) -> tuple[str, str, StorageProvider]:
        remote_name, remote_path = self.resolve_remote_path(value)
        return remote_name, remote_path, self.storage(remote_name)
