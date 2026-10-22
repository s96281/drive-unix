"""Upstash E2EE Cloud Synchronization REST API router (/api/upstash)."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from application.upstash_sync_service import UpstashSyncService
from core.config import ConfigManager
from core.crypto import DecryptionError, PayloadCorruptedError
from infrastructure.upstash_client import (
    UpstashAuthError,
    UpstashConnectionError,
    UpstashError,
)
from web.dependencies import get_config_manager

router = APIRouter(prefix="/api/upstash", tags=["Upstash Sync"])


class UpstashConfigResponse(BaseModel):
    rest_url: str | None = None
    has_token: bool = False
    has_passphrase: bool = False
    sync_key: str = "drive-unix:sync:default"
    auto_sync_tokens: bool = True
    auto_push_tokens: bool = True
    renew_leeway_minutes: int = 30


class UpstashConfigUpdateRequest(BaseModel):
    rest_url: str = Field(..., description="Upstash REST URL (例如 https://...upstash.io)")
    rest_token: str | None = Field(None, description="Upstash REST Token (留空則保留原設定)")
    sync_key: str = Field("drive-unix:sync:default", description="同步金鑰識別名稱")
    passphrase: str | None = Field(None, description="E2EE 主密碼 (留空則保留原設定)")
    auto_sync_tokens: bool | None = Field(None, description="過期時是否自動查詢獲取雲端憑證")
    auto_push_tokens: bool | None = Field(None, description="換發後是否自動推送雲端憑證")
    renew_leeway_minutes: int | None = Field(None, description="巡檢換發緩衝分鐘數")


class UpstashRenewTokensRequest(BaseModel):
    leeway_minutes: int = Field(30, description="過期緩衝分鐘數")
    remote_filter: str | None = Field(None, description="僅針對特定節點換發")


class UpstashPushRequest(BaseModel):
    passphrase: str = Field(..., min_length=1, description="E2EE 加密主密碼")
    sync_key: str | None = None
    include_auth_cache: bool = False
    include_tasks: bool = True


class UpstashPullRequest(BaseModel):
    passphrase: str = Field(..., min_length=1, description="E2EE 解密主密碼")
    sync_key: str | None = None
    strategy: str = Field("merge", description="合併策略: merge 或 replace")
    overwrite: bool = Field(False, description="同名節點是否直接覆蓋")
    dry_run: bool = Field(False, description="是否僅預覽差異而不寫入")


@router.get("/config", response_model=UpstashConfigResponse)
def get_upstash_config(
    config_mgr: ConfigManager = Depends(get_config_manager),
) -> UpstashConfigResponse:
    """取得目前 Upstash 連線設定概況 (不洩漏 Token 與 Passphrase 原始內容)。"""
    url, token, key = config_mgr.get_upstash_config()
    cfg = config_mgr.config.upstash
    passphrase = config_mgr.get_upstash_passphrase()
    return UpstashConfigResponse(
        rest_url=url,
        has_token=bool(token),
        has_passphrase=bool(passphrase),
        sync_key=key,
        auto_sync_tokens=cfg.auto_sync_tokens if cfg else True,
        auto_push_tokens=cfg.auto_push_tokens if cfg else True,
        renew_leeway_minutes=cfg.renew_leeway_minutes if cfg else 30,
    )


@router.post("/config", response_model=UpstashConfigResponse)
def update_upstash_config(
    req: UpstashConfigUpdateRequest,
    config_mgr: ConfigManager = Depends(get_config_manager),
) -> UpstashConfigResponse:
    """更新 Upstash REST 連線設定 (Token 與 Passphrase 將安全加密寫入 SecretStore)。"""
    try:
        config_mgr.set_upstash_config(
            rest_url=req.rest_url.strip(),
            rest_token=req.rest_token.strip() if req.rest_token else None,
            sync_key=req.sync_key.strip() or "drive-unix:sync:default",
            passphrase=req.passphrase.strip() if req.passphrase else None,
            auto_sync_tokens=req.auto_sync_tokens,
            auto_push_tokens=req.auto_push_tokens,
            renew_leeway_minutes=req.renew_leeway_minutes,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"無法儲存 Upstash 設定: {exc}",
        ) from exc

    return get_upstash_config(config_mgr=config_mgr)


@router.post("/test")
def test_upstash_connection(
    config_mgr: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """測試與 Upstash REST 伺服器的連線與認證。"""
    service = UpstashSyncService(config_mgr)
    t0 = time.perf_counter()
    try:
        client = service.get_client()
        pong = client.ping()
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "status": "ok" if pong else "failed",
            "ping": pong,
            "latency_ms": round(latency_ms, 2),
            "url": client.rest_url,
        }
    except UpstashAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Upstash 認證失敗: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"連線至 Upstash 失敗: {exc}",
        ) from exc


@router.get("/status")
def get_upstash_status(
    sync_key: str | None = Query(None, description="自訂同步金鑰"),
    config_mgr: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """檢視 Upstash 雲端備份的中繼資料與節點數量。"""
    service = UpstashSyncService(config_mgr)
    try:
        return service.fetch_status(sync_key=sync_key)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"取得雲端同步狀態失敗: {exc}",
        ) from exc


@router.post("/push")
def push_to_upstash(
    req: UpstashPushRequest,
    config_mgr: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """將本機節點與機密加密上傳至 Upstash。"""
    service = UpstashSyncService(config_mgr)
    try:
        return service.push(
            req.passphrase,
            sync_key=req.sync_key,
            include_auth_cache=req.include_auth_cache,
            include_tasks=req.include_tasks,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"上傳同步失敗: {exc}",
        ) from exc


@router.post("/pull")
def pull_from_upstash(
    req: UpstashPullRequest,
    config_mgr: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """從 Upstash 下載、解密並合併至本機節點與 SecretStore。"""
    service = UpstashSyncService(config_mgr)
    try:
        return service.pull(
            req.passphrase,
            sync_key=req.sync_key,
            strategy=req.strategy,
            overwrite=req.overwrite,
            dry_run=req.dry_run,
        )
    except DecryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"解密失敗：密碼錯誤或資料受損 ({exc})",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"拉取同步失敗: {exc}",
        ) from exc


@router.delete("")
def delete_upstash_bundle(
    sync_key: str | None = Query(None, description="自訂同步金鑰"),
    config_mgr: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """從 Upstash 雲端清除備份資料。"""
    service = UpstashSyncService(config_mgr)
    try:
        deleted = service.delete_bundle(sync_key=sync_key)
        return {"status": "ok", "deleted": deleted}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"刪除雲端資料失敗: {exc}",
        ) from exc


@router.get("/tokens")
def list_upstash_tokens(
    config_mgr: ConfigManager = Depends(get_config_manager),
) -> list[dict[str, Any]]:
    """檢視所有 OAuth 節點在 Upstash 雲端中繼資料 (到期時間、裝置來源、鎖定狀態)。"""
    import json
    from auth.identity import build_identity_cache_key, get_canonical_auth_identity
    from application.upstash_token_service import UpstashTokenService

    service = UpstashTokenService(config_mgr)
    client = service.get_client()

    identity_to_remotes: dict[str, list[str]] = {}
    for r_name, remote in config_mgr.config.remotes.items():
        if remote.type in {"sharepoint", "onedrive_business", "onedrive", "google_drive", "googlephotos"}:
            ident = get_canonical_auth_identity(r_name, remote, config_mgr)
            identity_to_remotes.setdefault(ident, []).append(r_name)

    results: list[dict[str, Any]] = []
    for ident, remotes in identity_to_remotes.items():
        ident_key = build_identity_cache_key(ident)
        token_key = f"drive-unix:token:{ident_key}"
        lock_key = f"drive-unix:lock:{ident_key}"

        cloud_meta: dict[str, Any] = {}
        locked_by: str | None = None

        if client:
            try:
                raw_str = client.get(token_key)
                if raw_str:
                    payload = json.loads(raw_str)
                    cloud_meta = payload.get("metadata", {})
            except Exception:
                pass

            try:
                locked_by = client.get(lock_key)
            except Exception:
                pass

        results.append({
            "identity": ident,
            "identity_key": ident_key,
            "remotes": remotes,
            "expires_at": cloud_meta.get("expires_at"),
            "updated_at": cloud_meta.get("updated_at"),
            "device_id": cloud_meta.get("device_id"),
            "is_locked": bool(locked_by),
            "locked_by": locked_by,
        })

    return results


@router.delete("/tokens/{identity_key}")
def delete_upstash_token(
    identity_key: str,
    config_mgr: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """手動清除指定身分於 Upstash 之快取金鑰。"""
    from application.upstash_token_service import UpstashTokenService

    service = UpstashTokenService(config_mgr)
    client = service.get_client()
    if not client:
        raise HTTPException(status_code=400, detail="未設定 Upstash 連線。")

    token_key = f"drive-unix:token:{identity_key}"
    client.delete(token_key)
    return {"status": "ok", "deleted": token_key}


@router.delete("/locks/{identity_key}")
def release_upstash_lock(
    identity_key: str,
    config_mgr: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """強制解除指定身分於 Upstash 之分散式鎖定。"""
    from application.upstash_token_service import UpstashTokenService

    service = UpstashTokenService(config_mgr)
    client = service.get_client()
    if not client:
        raise HTTPException(status_code=400, detail="未設定 Upstash 連線。")

    lock_key = f"drive-unix:lock:{identity_key}"
    client.delete(lock_key)
    return {"status": "ok", "released": lock_key}


@router.post("/renew-tokens")
def renew_upstash_tokens(
    req: UpstashRenewTokensRequest = UpstashRenewTokensRequest(),
    config_mgr: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """[憑證換發中心] 巡檢所有或指定節點憑證，若即將過期則提前換發並回寫 Upstash。"""
    from application.upstash_token_service import UpstashTokenService

    service = UpstashTokenService(config_mgr)
    try:
        return service.renew_all_tokens(
            leeway_minutes=req.leeway_minutes,
            remote_filter=req.remote_filter,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"憑證巡檢換發失敗: {exc}",
        ) from exc
