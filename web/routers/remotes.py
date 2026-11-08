"""Remote storage node management REST API router."""

from __future__ import annotations

import time
import uuid
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from core.config import (
    AlistRemote,
    ConfigManager,
    FTPRemote,
    GoogleDriveRemote,
    GooglePhotosRemote,
    LocalRemote,
    OneDriveBusinessRemote,
    OneDriveRemote,
    PikPakRemote,
    RemoteConfig,
    SFTPRemote,
    SharePointRemote,
    WebDAVRemote,
)
from storage.base import DeleteCapability, managed_storage
from storage.registry import DEFAULT_PROVIDER_REGISTRY
from web.dependencies import get_config_manager, resolve_storage
from web.events import broadcaster
from web.storage_pool import storage_pool

router = APIRouter(prefix="/api/remotes", tags=["Remotes"])

_remotes_health: dict[str, dict[str, Any]] = {}
_quota_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class RemoteSummary(BaseModel):
    name: str
    type: str
    is_default: bool
    details: dict[str, Any]
    health: dict[str, Any] | None = None


class QuotaResponse(BaseModel):
    supported: bool
    name: str
    total: int = 0
    used: int = 0
    free: int = 0
    filecount: int = -1


class RemoteListResponse(BaseModel):
    default_remote: str | None
    supported_types: list[str]
    remotes: list[RemoteSummary]


class RemoteCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="節點識別名稱")
    type: str = Field(..., description="儲存節點類型 (如 local, ftp, sftp...)")
    is_default: bool = False
    password: str | None = Field(None, description="純文字密碼（將立即加密存入 SecretRepository）")
    client_secret: str | None = Field(None, description="純文字 OAuth Client Secret")
    params: dict[str, Any] = Field(default_factory=dict, description="Provider 特定參數")


class RemoteUpdateRequest(BaseModel):
    new_name: str | None = None
    is_default: bool | None = None
    password: str | None = None
    client_secret: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class TestRemoteRequest(BaseModel):
    write: bool = Field(False, description="是否執行暫存資料夾寫入與刪除測試")


class TestRemoteResponse(BaseModel):
    status: str
    name: str
    read_ok: bool
    write_tested: bool
    write_ok: bool
    delete_capability: str | None = None
    latency_ms: float
    error: str | None = None


def _build_remote_instance(
    name: str,
    remote_type: str,
    params: dict[str, Any],
    password_ref: str | None,
    client_secret_ref: str | None,
) -> RemoteConfig:
    data = dict(params)
    data["type"] = remote_type.strip().lower()

    if password_ref:
        data["password_ref"] = password_ref
    if client_secret_ref:
        data["client_secret_ref"] = client_secret_ref

    type_to_model: dict[str, type[BaseModel]] = {
        "sharepoint": SharePointRemote,
        "onedrive": OneDriveRemote,
        "onedrive_business": OneDriveBusinessRemote,
        "alist": AlistRemote,
        "google_drive": GoogleDriveRemote,
        "googlephotos": GooglePhotosRemote,
        "local": LocalRemote,
        "ftp": FTPRemote,
        "webdav": WebDAVRemote,
        "sftp": SFTPRemote,
        "pikpak": PikPakRemote,
    }

    model_cls = type_to_model.get(data["type"])
    if not model_cls:
        supported = ", ".join(sorted(type_to_model))
        raise ValueError(f"不支援的 Remote 類型: '{data['type']}'。支援類型: {supported}")

    return cast(RemoteConfig, model_cls.model_validate(data))


@router.get("", response_model=RemoteListResponse)
def list_remotes(
    config_manager: ConfigManager = Depends(get_config_manager),
) -> RemoteListResponse:
    """列出所有已設定的 Remote 節點（零認證洩漏）。"""
    app_config = config_manager.config
    remotes_list: list[RemoteSummary] = []

    for name, remote_cfg in app_config.remotes.items():
        # model_dump exclude none
        details = remote_cfg.model_dump(exclude_none=True)
        remotes_list.append(
            RemoteSummary(
                name=name,
                type=remote_cfg.type,
                is_default=(app_config.default_remote == name),
                details=details,
                health=_remotes_health.get(name),
            )
        )

    return RemoteListResponse(
        default_remote=app_config.default_remote,
        supported_types=list(DEFAULT_PROVIDER_REGISTRY.supported_types()),
        remotes=remotes_list,
    )


@router.post("", response_model=RemoteSummary, status_code=status.HTTP_201_CREATED)
def create_remote(
    req: RemoteCreateRequest,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> RemoteSummary:
    """新增遠端節點。若提供純文字密碼，即刻存入 SecretRepository，組態僅保留參照。"""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="節點名稱不可為空。")

    if name in config_manager.config.remotes:
        raise HTTPException(
            status_code=409,
            detail=f"遠端節點 '{name}' 已經存在，請使用其他名稱或先刪除既有節點。",
        )

    password_ref = None
    if req.password:
        password_ref = config_manager.store_remote_secret(name, "password", req.password)

    client_secret_ref = None
    if req.client_secret:
        client_secret_ref = config_manager.store_remote_secret(
            name, "client-secret", req.client_secret
        )

    try:
        remote_obj = _build_remote_instance(
            name=name,
            remote_type=req.type,
            params=req.params,
            password_ref=password_ref,
            client_secret_ref=client_secret_ref,
        )
    except Exception as exc:
        # 清理剛建立的 secret
        if password_ref:
            config_manager.secret_store.delete(password_ref)
        if client_secret_ref:
            config_manager.secret_store.delete(client_secret_ref)
        raise HTTPException(
            status_code=400,
            detail=f"節點設定驗證失敗: {exc}",
        ) from exc

    config_manager.add_remote(name, remote_obj)
    if req.is_default or not config_manager.config.default_remote:
        config_manager.config.default_remote = name
        config_manager.save()

    broadcaster.publish("system", {"topic": "remotes", "action": "created", "name": name})

    return RemoteSummary(
        name=name,
        type=remote_obj.type,
        is_default=(config_manager.config.default_remote == name),
        details=remote_obj.model_dump(exclude_none=True),
    )


@router.get("/{name}", response_model=RemoteSummary)
def get_remote(
    name: str,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> RemoteSummary:
    """取得單一遠端節點設定。"""
    try:
        remote_cfg = config_manager.get_remote(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return RemoteSummary(
        name=name,
        type=remote_cfg.type,
        is_default=(config_manager.config.default_remote == name),
        details=remote_cfg.model_dump(exclude_none=True),
    )


@router.put("/{name}", response_model=RemoteSummary)
def update_remote(
    name: str,
    req: RemoteUpdateRequest,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> RemoteSummary:
    """更新遠端節點設定或重新命名。"""
    if name not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{name}' 的遠端節點。")

    target_name = name
    if req.new_name and req.new_name != name:
        new_name = req.new_name.strip()
        try:
            config_manager.rename_remote(name, new_name)
            target_name = new_name
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if req.password:
        ref = config_manager.store_remote_secret(target_name, "password", req.password)
        req.params["password_ref"] = ref

    if req.client_secret:
        ref = config_manager.store_remote_secret(
            target_name, "client-secret", req.client_secret
        )
        req.params["client_secret_ref"] = ref

    if req.params:
        try:
            config_manager.edit_remote(target_name, **req.params)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if req.is_default is True:
        config_manager.config.default_remote = target_name
        config_manager.save()
    elif req.is_default is False and config_manager.config.default_remote == target_name:
        config_manager.config.default_remote = None
        config_manager.save()

    updated = config_manager.get_remote(target_name)
    storage_pool.evict(name)
    if target_name != name:
        storage_pool.evict(target_name)
    broadcaster.publish("system", {"topic": "remotes", "action": "updated", "name": target_name})
    return RemoteSummary(
        name=target_name,
        type=updated.type,
        is_default=(config_manager.config.default_remote == target_name),
        details=updated.model_dump(exclude_none=True),
    )


@router.delete("/{name}", status_code=status.HTTP_200_OK)
def delete_remote(
    name: str,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """刪除節點並自動清除關聯之 Secret。"""
    if name not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{name}' 的遠端節點。")

    config_manager.remove_remote(name)
    if config_manager.config.default_remote == name:
        config_manager.config.default_remote = None
        config_manager.save()

    storage_pool.evict(name)
    _remotes_health.pop(name, None)
    _quota_cache.pop(name, None)
    broadcaster.publish("system", {"topic": "remotes", "action": "deleted", "name": name})

    return {"status": "deleted", "name": name}


@router.post("/{name}/disconnect", status_code=status.HTTP_200_OK)
def disconnect_remote(name: str) -> dict[str, Any]:
    """手動中斷指定節點在連線池中的長效連線。"""
    evicted = storage_pool.evict(name)
    return {"status": "disconnected" if evicted else "not_connected", "name": name}


@router.post("/{name}/test", response_model=TestRemoteResponse)
def test_remote(
    name: str,
    req: TestRemoteRequest = TestRemoteRequest(write=False),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> TestRemoteResponse:
    """測試節點連線與讀取權限，可選擇性驗證寫入與刪除能力。"""
    if name not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{name}' 的遠端節點。")

    start_time = time.perf_counter()
    try:
        storage = resolve_storage(name, config_manager, use_pool=False)
    except Exception as exc:
        elapsed = (time.perf_counter() - start_time) * 1000
        res = TestRemoteResponse(
            status="failed",
            name=name,
            read_ok=False,
            write_tested=req.write,
            write_ok=False,
            latency_ms=round(elapsed, 2),
            error=f"無法初始化儲存驅動: {exc}",
        )
        _remotes_health[name] = {
            "status": res.status,
            "latency_ms": res.latency_ms,
            "read_ok": res.read_ok,
            "write_ok": res.write_ok,
            "checked_at": time.time(),
            "error": res.error,
        }
        return res

    with managed_storage(storage) as provider:
        try:
            # 1. 讀取測試
            provider.list_dir("/")
            read_ok = True
        except Exception as exc:
            elapsed = (time.perf_counter() - start_time) * 1000
            res = TestRemoteResponse(
                status="failed",
                name=name,
                read_ok=False,
                write_tested=req.write,
                write_ok=False,
                latency_ms=round(elapsed, 2),
                error=f"讀取根目錄失敗: {exc}",
            )
            _remotes_health[name] = {
                "status": res.status,
                "latency_ms": res.latency_ms,
                "read_ok": res.read_ok,
                "write_ok": res.write_ok,
                "checked_at": time.time(),
                "error": res.error,
            }
            return res

        # 2. 寫入測試 (選用)
        write_ok = False
        cap_val = (
            provider.delete_capability.value
            if hasattr(provider, "delete_capability")
            else DeleteCapability.PERMANENT_ONLY.value
        )

        if req.write:
            test_path = f"/.drive-unix-write-test-{uuid.uuid4().hex[:8]}"
            try:
                if not provider.mkdir(test_path, parents=False):
                    raise RuntimeError("Provider 建立測試資料夾回傳 False。")
                if not provider.delete(test_path, permanent=False):
                    raise RuntimeError("Provider 清理測試資料夾回傳 False。")
                write_ok = True
            except Exception as exc:
                elapsed = (time.perf_counter() - start_time) * 1000
                res = TestRemoteResponse(
                    status="failed",
                    name=name,
                    read_ok=True,
                    write_tested=True,
                    write_ok=False,
                    delete_capability=cap_val,
                    latency_ms=round(elapsed, 2),
                    error=f"寫入或清理測試失敗: {exc}",
                )
                _remotes_health[name] = {
                    "status": res.status,
                    "latency_ms": res.latency_ms,
                    "read_ok": res.read_ok,
                    "write_ok": res.write_ok,
                    "checked_at": time.time(),
                    "error": res.error,
                }
                return res

        elapsed = (time.perf_counter() - start_time) * 1000
        res = TestRemoteResponse(
            status="success",
            name=name,
            read_ok=read_ok,
            write_tested=req.write,
            write_ok=write_ok if req.write else False,
            delete_capability=cap_val,
            latency_ms=round(elapsed, 2),
            error=None,
        )
        _remotes_health[name] = {
            "status": res.status,
            "latency_ms": res.latency_ms,
            "read_ok": res.read_ok,
            "write_ok": res.write_ok,
            "checked_at": time.time(),
            "error": res.error,
        }
        return res


@router.get("/{name}/quota", response_model=QuotaResponse)
def get_remote_quota(
    name: str,
    refresh: bool = Query(False, description="是否強制重新整理快取"),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> QuotaResponse:
    """查詢雲端節點之儲存空間配額與使用量 (快取 5 分鐘)。"""
    if name not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{name}' 的遠端節點。")

    now = time.time()
    if not refresh and name in _quota_cache:
        ts, cached = _quota_cache[name]
        if now - ts < 300:
            return QuotaResponse(**cached)

    try:
        storage = resolve_storage(name, config_manager)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"初始化儲存驅動失敗: {exc}") from exc

    with managed_storage(storage) as provider:
        try:
            stat_info = provider.stat("/")
            total = int(stat_info.get("total", 0))
            used = int(stat_info.get("used", 0))
            filecount = int(stat_info.get("filecount", -1))
            supported = total > 0 or used > 0
            free = max(0, total - used) if total > 0 else 0
            res = {
                "supported": supported,
                "name": name,
                "total": total,
                "used": used,
                "free": free,
                "filecount": filecount,
            }
            _quota_cache[name] = (now, res)
            return QuotaResponse(**res)
        except Exception:
            res = {
                "supported": False,
                "name": name,
                "total": 0,
                "used": 0,
                "free": 0,
                "filecount": -1,
            }
            return QuotaResponse(**res)
