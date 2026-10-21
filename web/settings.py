"""Persistent and extensible configuration manager for web interface settings."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from core.config import DEFAULT_CONFIG_DIR
from web.cache import directory_cache

logger = logging.getLogger(__name__)


class CacheSettings(BaseModel):
    enabled: bool = True
    ttl_seconds: int = Field(default=300, ge=0, le=86400, description="快取留存秒數 (0 代表不快取)")
    max_entries: int = Field(default=1000, ge=10, le=50000, description="最大快取目錄數量")
    persist_to_disk: bool = Field(default=True, description="持久化快取至磁碟，避免應用程式重啟喪失快取")
    cache_dir: str | None = Field(default=None, description="自訂快取儲存目錄路徑 (留空使用預設組態目錄)")


class UISettings(BaseModel):
    site_title: str = "drive-unix"
    default_view_mode: str = Field(default="dual", description="'dual' (雙欄同步) 或 'unified' (AList 聚合)")
    default_display_layout: str = Field(default="list", description="'list' (列表) 或 'grid' (網格)")
    enable_preview: bool = True


class SecuritySettings(BaseModel):
    max_upload_size_mb: int = Field(default=2048, ge=1, le=102400)
    allow_guest_download: bool = True


class WebSettings(BaseModel):
    cache: CacheSettings = Field(default_factory=CacheSettings)
    ui: UISettings = Field(default_factory=UISettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    # Extensibility container for future features (e.g. plugins, custom CSS, WebDAV mounts)
    extra_options: dict[str, Any] = Field(default_factory=dict)


class WebSettingsManager:
    """Manages persistent web settings stored in web_settings.json."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
        self.settings_file = self.config_dir / "web_settings.json"
        self.settings: WebSettings = self.load()
        self._apply_cache_settings()

    def load(self) -> WebSettings:
        if not self.settings_file.exists():
            return WebSettings()
        try:
            content = self.settings_file.read_text(encoding="utf-8")
            data = json.loads(content)
            return WebSettings.model_validate(data)
        except Exception as exc:
            logger.warning("無法讀取網頁設定檔 %s，使用預設值: %s", self.settings_file, exc)
            return WebSettings()

    def save(self) -> None:
        try:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            data = self.settings.model_dump()
            self.settings_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            self._apply_cache_settings()
        except Exception as exc:
            logger.error("無法寫入網頁設定檔 %s: %s", self.settings_file, exc)
            raise RuntimeError(f"無法儲存網頁設定: {exc}") from exc

    def update(self, new_data: dict[str, Any]) -> WebSettings:
        current_dict = self.settings.model_dump()
        for section, values in new_data.items():
            if isinstance(values, dict) and section in current_dict:
                current_dict[section].update(values)
            else:
                current_dict[section] = values

        self.settings = WebSettings.model_validate(current_dict)
        self.save()
        return self.settings

    def _apply_cache_settings(self) -> None:
        """Apply cache configurations to the active directory_cache singleton."""
        directory_cache.enabled = self.settings.cache.enabled
        directory_cache.default_ttl = self.settings.cache.ttl_seconds
        directory_cache.max_entries = self.settings.cache.max_entries
        target_dir = Path(self.settings.cache.cache_dir) if self.settings.cache.cache_dir else self.config_dir
        directory_cache.set_db_path(target_dir / "cache.db", persist_to_disk=self.settings.cache.persist_to_disk)


# Global web settings manager instance
web_settings_manager = WebSettingsManager()
