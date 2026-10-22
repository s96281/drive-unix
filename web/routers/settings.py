"""Web configuration and directory cache management API router (/api/settings)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from web.cache import directory_cache
from web.events import broadcaster
from web.settings import WebSettings, web_settings_manager

router = APIRouter(prefix="/api/settings", tags=["Settings"])


class SettingsResponse(BaseModel):
    settings: WebSettings
    cache_stats: dict[str, Any]


class UpdateSettingsRequest(BaseModel):
    cache: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None
    security: dict[str, Any] | None = None
    transfer: dict[str, Any] | None = None
    extra_options: dict[str, Any] | None = None


@router.get("", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    """取得完整網頁設定與目錄快取即時統計數據。"""
    return SettingsResponse(
        settings=web_settings_manager.settings,
        cache_stats=directory_cache.get_stats(),
    )


@router.put("", response_model=SettingsResponse)
def update_settings(req: UpdateSettingsRequest) -> SettingsResponse:
    """更新網頁組態與快取參數（即時生效並持久化儲存）。"""
    update_data = req.model_dump(exclude_none=True)
    updated_settings = web_settings_manager.update(update_data)
    broadcaster.publish("system", {"topic": "settings", "action": "updated"})
    return SettingsResponse(
        settings=updated_settings,
        cache_stats=directory_cache.get_stats(),
    )


@router.get("/cache/stats", response_model=dict[str, Any])
def get_cache_stats() -> dict[str, Any]:
    """取得目錄快取即時指標（命中率、項目數、快取節點）。"""
    return directory_cache.get_stats()


@router.post("/cache/clear", status_code=status.HTTP_200_OK)
def clear_cache(
    remote: str | None = Query(None, description="指定要清除快取的節點名稱；若未指定則清空所有快取"),
) -> dict[str, Any]:
    """手動清空目錄快取。"""
    if remote:
        count = directory_cache.invalidate(remote)
        message = f"已清除節點 '{remote}' 之快取 ({count} 項目)。"
    else:
        count = directory_cache.clear()
        message = f"已清空所有目錄快取 ({count} 項目)。"

    return {
        "status": "cleared",
        "cleared_entries": count,
        "message": message,
        "stats": directory_cache.get_stats(),
    }


def _get_screenshot_dir() -> Path:
    env_dir = os.getenv("SHAREPOINT_SCREENSHOT_DIR") or os.getenv("DRIVE_UNIX_DEBUG_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".config" / "drive-unix" / "debug"


@router.get("/debug/screenshots", response_model=list[dict[str, Any]])
def list_debug_screenshots() -> list[dict[str, Any]]:
    """取得 headless 瀏覽器登入失敗截圖列表 (包含每秒連環歷程與單張截圖)。"""
    sdir = _get_screenshot_dir()
    if not sdir.exists():
        return []

    results = []
    for f in sorted(sdir.rglob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = f.stat()
        rel_path = f.relative_to(sdir).as_posix()
        results.append({
            "filename": f.name,
            "path": rel_path,
            "size_bytes": st.st_size,
            "created_at": st.st_mtime,
            "url": f"/api/settings/debug/screenshots/{rel_path}",
        })
    return results


@router.get("/debug/screenshots/{file_path:path}")
def get_debug_screenshot(file_path: str):
    """檢視或下載指定的登入排查截圖 (支援歷程子目錄)。"""
    normalized = Path(file_path)
    if ".." in normalized.parts or not file_path.endswith(".png"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="無效的檔案路徑")

    full_path = (_get_screenshot_dir() / normalized).resolve()
    base_resolved = _get_screenshot_dir().resolve()

    if not str(full_path).startswith(str(base_resolved)) or not full_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="截圖檔案不存在")

    return FileResponse(path=full_path, media_type="image/png", filename=full_path.name)


@router.get("/debug/mfa-status", response_model=dict[str, Any])
def get_mfa_status() -> dict[str, Any]:
    """取得當前是否有進行中的 Microsoft Authenticator 數字比對挑戰。"""
    status_file = _get_screenshot_dir() / "mfa_challenge.json"
    if status_file.is_file():
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            if time.time() - data.get("updated_at", 0) < 120:
                return data
        except Exception:
            pass
    return {"active": False, "number": None}
