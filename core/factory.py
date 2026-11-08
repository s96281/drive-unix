
from core.config import ConfigManager
from storage.base import StorageProvider
from storage.registry import DEFAULT_PROVIDER_REGISTRY


def parse_remote_path(raw_path: str, default_remote: str | None = None) -> tuple[str, str]:
    """Split ``remote:path`` into its remote name and provider-relative path."""
    if ":" in raw_path:
        remote_name, path = raw_path.split(":", 1)
        return remote_name, path

    if not default_remote:
        raise ValueError(
            "未指定遠端節點名稱 (Remote)，且配置檔中無預設節點。"
            "格式應為 remote_name:path"
        )

    return default_remote, raw_path


def get_storage_provider(
    remote_name: str,
    config_manager: ConfigManager,
) -> StorageProvider:
    """Create a storage provider through the central registry."""
    return DEFAULT_PROVIDER_REGISTRY.create(remote_name, config_manager)
