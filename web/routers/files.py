"""Virtual filesystem REST API router (/api/fs)."""

from __future__ import annotations

import concurrent.futures
import logging
import mimetypes
import os
import posixpath
import tempfile
import threading
import time
import uuid
from typing import Any, Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from core.config import ConfigManager
from domain.models import FileItem
from infrastructure.http import HttpStatusError
from storage.base import managed_storage
from web.cache import directory_cache
from web.dependencies import get_config_manager, resolve_storage
from web.events import broadcaster, task_event_manager
from web.transfer_jobs import run_transfer_job

router = APIRouter(prefix="/api/fs", tags=["Filesystem"])


class FileItemResponse(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int
    modified_at: str | None
    thumbnail_url: str | None = None


class ThumbnailResponse(BaseModel):
    remote: str
    path: str
    url: str
    thumbnail_url: str


class LinkResponse(BaseModel):
    remote: str
    path: str
    url: str


class ListDirResponse(BaseModel):
    remote: str
    path: str
    total_count: int
    items: list[FileItemResponse]


class MkdirRequest(BaseModel):
    path: str = Field(..., min_length=1, description="欲建立之資料夾路徑")
    parents: bool = Field(False, description="是否一併建立上層目錄")


class DeleteRequest(BaseModel):
    path: str = Field(..., min_length=1, description="欲刪除之路徑")
    permanent: bool = Field(False, description="是否永久刪除（若為 False 則移至回收桶）")


class RenameRequest(BaseModel):
    path: str = Field(..., min_length=1, description="欲重新命名之路徑")
    new_name: str = Field(..., min_length=1, pattern=r"^[^/\\]+$", description="新名稱（不可包含路徑分隔符號）")


class MoveCopyRequest(BaseModel):
    source: str = Field(..., min_length=1, description="來源路徑")
    destination: str = Field(..., min_length=1, description="目的路徑")
    overwrite: bool = Field(False, description="是否覆蓋已存在之目的項目")


class TransferRequest(BaseModel):
    sources: list[str] = Field(..., min_length=1, description="來源 URI 清單 (如 remote:/path)")
    dest_dir: str = Field(..., min_length=1, description="目的目錄 URI (如 remote:/target_dir)")
    mode: Literal["copy", "move"] = Field("copy", description="傳輸模式: copy 或 move")


logger = logging.getLogger(__name__)

_warmup_lock = threading.Lock()
_active_warmups: set[tuple[str, str]] = set()
_warmup_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="dir-cache-warmup"
)


def _background_warmup_directory(remote: str, path: str, config_manager: ConfigManager) -> None:
    """Fetch full directory in background and store in directory_cache, then notify frontend via SSE."""
    warmup_key = (remote, path)
    start_time = time.time()
    try:
        # Check if already cached
        if directory_cache.get(remote, path) is not None:
            return

        storage = resolve_storage(remote, config_manager)
        with managed_storage(storage) as provider:
            raw_items = provider.list_dir(path)

        # Skip storing if directory was invalidated while fetching
        if hasattr(directory_cache, "get_invalidation_time"):
            if directory_cache.get_invalidation_time(remote, path) > start_time:
                logger.debug("目錄在預熱期間被使失效，跳過寫入舊快取: %s:%s", remote, path)
                return

        directory_cache.put(remote, path, raw_items)
        logger.info("目錄快取背景預熱完成: %s:%s (共 %d 個項目)", remote, path, len(raw_items))

        # Broadcast SSE event to update frontend total counts & total pages
        broadcaster.publish("fs.cache_warmed", {
            "remote": remote,
            "path": path,
            "total_count": len(raw_items),
        })
    except Exception as exc:
        logger.warning("目錄快取背景預熱失敗 (%s:%s): %s", remote, path, exc)
    finally:
        with _warmup_lock:
            _active_warmups.discard(warmup_key)


def _schedule_background_warmup(remote: str, path: str, config_manager: ConfigManager) -> None:
    """Schedule background full-directory warmup if not already warming up or cached."""
    warmup_key = (remote, path)
    with _warmup_lock:
        if warmup_key in _active_warmups:
            return
        if directory_cache.get(remote, path) is not None:
            return
        _active_warmups.add(warmup_key)
        _warmup_executor.submit(_background_warmup_directory, remote, path, config_manager)


def _cleanup_temp_file(file_path: str) -> None:
    """Background task to remove temporary downloaded file."""
    try:
        if os.path.exists(file_path):
            os.unlink(file_path)
    except OSError:
        pass


@router.get("/{remote}/ls", response_model=ListDirResponse)
def list_directory(
    remote: str,
    path: str = Query("/", description="遠端目錄路徑"),
    offset: int = Query(0, ge=0, description="起始索引偏移量"),
    limit: int | None = Query(None, ge=1, description="回傳項目數量上限"),
    sort_by: str = Query("name", description="排序欄位: name, size, modified"),
    reverse: bool = Query(False, description="是否反向排序"),
    refresh: bool = Query(False, description="是否略過快取並強制重新讀取"),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> ListDirResponse:
    """列出指定節點與路徑下的檔案與資料夾清單（支援目錄快取與高效分頁載入）。"""
    if remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{remote}' 的遠端節點。")

    norm_path = path.strip() or "/"
    cached_items: list[FileItem] | None = None
    if not refresh:
        cached_items = directory_cache.get(remote, norm_path)

    # 排序處理：資料夾優先，其次依 sort_by
    def sort_key(item: FileItem) -> tuple[bool, Any]:
        if sort_by == "size":
            return (not item.is_dir, item.size)
        elif sort_by == "modified":
            ts = item.modified_at.timestamp() if item.modified_at else 0.0
            return (not item.is_dir, ts)
        else:
            return (not item.is_dir, item.name.lower())

    if cached_items is not None:
        sorted_items = sorted(cached_items, key=sort_key, reverse=reverse)
        total_count = len(sorted_items)
        target_end = (offset + limit) if limit is not None else None
        paged_items = sorted_items[offset:target_end]
        return ListDirResponse(
            remote=remote,
            path=norm_path,
            total_count=total_count,
            items=[
                FileItemResponse(
                    name=it.name,
                    path=it.path,
                    is_dir=it.is_dir,
                    size=it.size,
                    modified_at=it.modified_at.isoformat() if it.modified_at else None,
                    thumbnail_url=it.thumbnail_url,
                )
                for it in paged_items
            ],
        )

    try:
        storage = resolve_storage(remote, config_manager)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"初始化儲存驅動失敗: {exc}") from exc

    if limit is not None:
        # 具有分頁限制且快取未命中：以最小請求次數僅向 Provider 請求指定範圍項目，避免全量載入
        with managed_storage(storage) as provider:
            try:
                page_items = provider.list_dir(norm_path, offset=offset, limit=limit)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"讀取目錄失敗 ({norm_path}): {exc}") from exc

        total_count = getattr(page_items, "total_count", None)
        if total_count is None:
            if len(page_items) < limit:
                total_count = offset + len(page_items)
            else:
                total_count = offset + len(page_items) + 1

        # 若未命中快取，在背景非同步預熱完整目錄快取，實現後續翻頁、排序與精確總數 0 延遲
        _schedule_background_warmup(remote, norm_path, config_manager)

        return ListDirResponse(
            remote=remote,
            path=norm_path,
            total_count=total_count,
            items=[
                FileItemResponse(
                    name=it.name,
                    path=it.path,
                    is_dir=it.is_dir,
                    size=it.size,
                    modified_at=it.modified_at.isoformat() if it.modified_at else None,
                    thumbnail_url=it.thumbnail_url,
                )
                for it in page_items
            ],
        )

    # limit is None: 全量讀取並存入目錄快取
    with managed_storage(storage) as provider:
        try:
            raw_items = provider.list_dir(norm_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"讀取目錄失敗 ({norm_path}): {exc}") from exc

    directory_cache.put(remote, norm_path, raw_items)
    sorted_items = sorted(raw_items, key=sort_key, reverse=reverse)
    total_count = len(sorted_items)
    paged_items = sorted_items[offset:]

    return ListDirResponse(
        remote=remote,
        path=norm_path,
        total_count=total_count,
        items=[
            FileItemResponse(
                name=it.name,
                path=it.path,
                is_dir=it.is_dir,
                size=it.size,
                modified_at=it.modified_at.isoformat() if it.modified_at else None,
                thumbnail_url=it.thumbnail_url,
            )
            for it in paged_items
        ],
    )


@router.get("/{remote}/stat", response_model=dict[str, Any])
def get_stat(
    remote: str,
    path: str = Query(..., description="檔案或資料夾路徑"),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """取得單一檔案或資料夾的元資料狀態。"""
    if remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{remote}' 的遠端節點。")

    storage = resolve_storage(remote, config_manager)
    with managed_storage(storage) as provider:
        try:
            stat_info = provider.stat(path)
            return dict(stat_info)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"無法取得路徑資訊: {exc}") from exc


@router.post("/{remote}/mkdir", status_code=status.HTTP_201_CREATED)
def make_directory(
    remote: str,
    req: MkdirRequest,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """於指定節點建立目錄。"""
    if remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{remote}' 的遠端節點。")

    storage = resolve_storage(remote, config_manager)
    with managed_storage(storage) as provider:
        try:
            ok = provider.mkdir(req.path, parents=req.parents)
            if not ok:
                raise RuntimeError("Provider 建立目錄回傳 False。")
            directory_cache.invalidate(remote, req.path)
            return {"status": "created", "remote": remote, "path": req.path}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"建立目錄失敗: {exc}") from exc


@router.post("/{remote}/delete", status_code=status.HTTP_200_OK)
def delete_item(
    remote: str,
    req: DeleteRequest,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """刪除指定節點上的檔案或資料夾。"""
    if remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{remote}' 的遠端節點。")

    storage = resolve_storage(remote, config_manager)
    with managed_storage(storage) as provider:
        try:
            provider.validate_delete_request(permanent=req.permanent)
            ok = provider.delete(req.path, permanent=req.permanent)
            if not ok:
                raise RuntimeError("Provider 刪除項目回傳 False。")
            directory_cache.invalidate(remote, req.path)
            return {
                "status": "deleted",
                "remote": remote,
                "path": req.path,
                "permanent": req.permanent,
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"刪除失敗: {exc}") from exc


@router.get("/{remote}/download")
def download_file(
    remote: str,
    path: str = Query(..., description="要下載之遠端檔案路徑"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> FileResponse:
    """下載遠端檔案至瀏覽器（安全分流與背景清理）。"""
    if remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{remote}' 的遠端節點。")

    filename = posixpath.basename(path.rstrip("/"))
    if not filename:
        raise HTTPException(status_code=400, detail="無效的檔案路徑。")

    media_type, _ = mimetypes.guess_type(filename)
    if not media_type:
        media_type = "application/octet-stream"

    storage = resolve_storage(remote, config_manager)
    with managed_storage(storage) as provider:
        # 若為本機磁碟，直接返回原始路徑
        if hasattr(provider, "_get_abs_path"):
            try:
                abs_path = provider._get_abs_path(path)
                if os.path.isfile(abs_path):
                    return FileResponse(
                        path=abs_path,
                        filename=filename,
                        media_type=media_type,
                        content_disposition_type="attachment",
                    )
            except Exception:
                pass

        # 建立暫存檔並下載
        temp_fd, temp_file_path = tempfile.mkstemp(prefix="drive_download_")
        os.close(temp_fd)

        try:
            ok = provider.download(path, temp_file_path, recursive=False)
            if not ok:
                _cleanup_temp_file(temp_file_path)
                raise RuntimeError("Provider 下載回傳 False。")
        except Exception as exc:
            _cleanup_temp_file(temp_file_path)
            raise HTTPException(status_code=500, detail=f"下載檔案失敗: {exc}") from exc

    background_tasks.add_task(_cleanup_temp_file, temp_file_path)
    return FileResponse(
        path=temp_file_path,
        filename=filename,
        media_type=media_type,
        content_disposition_type="attachment",
        background=background_tasks,
    )


class ReadResponse(BaseModel):
    remote: str
    path: str
    content: str
    size: int
    truncated: bool
    is_binary: bool = False
    encoding: str = "utf-8"


def _decode_preview_bytes(data: bytes) -> tuple[str, str]:
    """Decode preview bytes, trying BOM / common encodings. Returns (text, encoding)."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), "utf-8"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace"), "utf-16"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError as exc:
        # 可能只是被截斷在多位元組字元中間
        if exc.start >= len(data) - 4:
            return data[: exc.start].decode("utf-8", errors="replace"), "utf-8"
    for enc in ("big5", "gb18030"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8"


@router.get("/{remote}/read", response_model=ReadResponse)
def read_file_text(
    remote: str,
    path: str = Query(..., description="要預覽之遠端文字檔路徑"),
    max_bytes: int = Query(102400, ge=1, le=5 * 1024 * 1024, description="最多讀取位元組數"),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> ReadResponse:
    """讀取檔案開頭內容作為文字預覽（自動偵測編碼與二進位檔）。"""
    if remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{remote}' 的遠端節點。")

    filename = posixpath.basename(path.rstrip("/"))
    if not filename:
        raise HTTPException(status_code=400, detail="無效的檔案路徑。")

    storage = resolve_storage(remote, config_manager)
    temp_file_path: str | None = None
    try:
        with managed_storage(storage) as provider:
            abs_path: str | None = None
            if hasattr(provider, "_get_abs_path"):
                try:
                    candidate = provider._get_abs_path(path)
                    if os.path.isfile(candidate):
                        abs_path = candidate
                except Exception:
                    abs_path = None

            if abs_path is None:
                temp_fd, temp_file_path = tempfile.mkstemp(prefix="drive_read_")
                os.close(temp_fd)
                try:
                    ok = provider.download(path, temp_file_path, recursive=False)
                    if not ok:
                        raise RuntimeError("Provider 下載回傳 False。")
                except Exception as exc:
                    raise HTTPException(status_code=500, detail=f"讀取檔案失敗: {exc}") from exc
                abs_path = temp_file_path

            total_size = os.path.getsize(abs_path)
            with open(abs_path, "rb") as fh:
                data = fh.read(max_bytes)
    finally:
        if temp_file_path:
            _cleanup_temp_file(temp_file_path)

    if b"\x00" in data and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return ReadResponse(
            remote=remote, path=path, content="", size=total_size,
            truncated=False, is_binary=True,
        )

    text, encoding = _decode_preview_bytes(data)
    return ReadResponse(
        remote=remote,
        path=path,
        content=text,
        size=total_size,
        truncated=total_size > len(data),
        encoding=encoding,
    )


@router.get("/{remote}/raw")
def raw_file(
    remote: str,
    path: str = Query(..., description="要直接串流或預覽之遠端檔案路徑"),
    redirect: bool = Query(True, description="若 Provider 支援直鏈是否直接 307 重導向（預設 True 避免後端重複下載）"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> Any:
    """直接串流預覽遠端檔案（支援音訊/視訊/PDF等行內預覽與 Range 請求）。"""
    if remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{remote}' 的遠端節點。")

    filename = posixpath.basename(path.rstrip("/"))
    if not filename:
        raise HTTPException(status_code=400, detail="無效的檔案路徑。")

    media_type, _ = mimetypes.guess_type(filename)
    if not media_type:
        media_type = "application/octet-stream"

    storage = resolve_storage(remote, config_manager)
    with managed_storage(storage) as provider:
        # 1. 若允許 redirect，嘗試取得雲端直鏈重定向
        if redirect:
            try:
                link_url = provider.get_download_link(path)
                if link_url:
                    return RedirectResponse(url=link_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
            except Exception:
                pass

        # 2. 若為本機存儲，以 FileResponse 提供高效 Range 串流
        if hasattr(provider, "_get_abs_path"):
            try:
                abs_path = provider._get_abs_path(path)
                if os.path.isfile(abs_path):
                    return FileResponse(
                        path=abs_path,
                        filename=filename,
                        media_type=media_type,
                        content_disposition_type="inline",
                    )
            except Exception:
                pass

        # 3. 其它存儲透過暫存檔案提供行內串流
        temp_fd, temp_file_path = tempfile.mkstemp(prefix="drive_raw_")
        os.close(temp_fd)

        try:
            ok = provider.download(path, temp_file_path, recursive=False)
            if not ok:
                _cleanup_temp_file(temp_file_path)
                raise RuntimeError("Provider 下載回傳 False。")
        except Exception as exc:
            _cleanup_temp_file(temp_file_path)
            raise HTTPException(status_code=500, detail=f"串流檔案失敗: {exc}") from exc

    background_tasks.add_task(_cleanup_temp_file, temp_file_path)
    return FileResponse(
        path=temp_file_path,
        filename=filename,
        media_type=media_type,
        content_disposition_type="inline",
        background=background_tasks,
    )


@router.get("/{remote}/link", response_model=LinkResponse)
@router.get("/{remote}/download-link", response_model=LinkResponse)
def get_direct_link(
    remote: str,
    path: str = Query(..., description="要獲取直接下載連結之遠端檔案路徑"),
    redirect: bool = Query(False, description="是否直接重新導向至下載網址"),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> Any:
    """針對支援產生直接下載連結之 Provider 獲取直鏈。"""
    if remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{remote}' 的遠端節點。")

    storage = resolve_storage(remote, config_manager)
    with managed_storage(storage) as provider:
        link_url = None
        try:
            link_url = provider.get_download_link(path)
        except (NotImplementedError, AttributeError):
            try:
                link_url = provider.get_share_link(path)
            except (NotImplementedError, AttributeError, ValueError) as exc:
                raise HTTPException(status_code=501, detail=f"此 Provider 不支援獲取直接下載連結: {exc}") from exc
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=f"無法取得直接下載連結: {exc}") from exc
        except HttpStatusError as exc:
            if exc.status_code in (400, 404):
                raise HTTPException(status_code=404, detail=f"無法取得直接下載連結: {exc}") from exc
            raise HTTPException(status_code=502, detail=f"遠端服務回應錯誤: {exc}") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"取得直接下載連結失敗: {exc}") from exc

    if not link_url:
        raise HTTPException(status_code=404, detail="未取得有效的直接下載連結。")

    if redirect:
        return RedirectResponse(url=link_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    return LinkResponse(remote=remote, path=path, url=link_url)


@router.get("/{remote}/thumbnail", response_model=ThumbnailResponse)
@router.get("/{remote}/thumbnail-link", response_model=ThumbnailResponse)
def get_thumbnail(
    remote: str,
    path: str = Query(..., description="要獲取縮圖之遠端檔案路徑"),
    redirect: bool = Query(False, description="是否直接重新導向至縮圖網址"),
    refresh: bool = Query(False, description="是否強制重新獲取縮圖 (略過快取)"),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> Any:
    """針對支援縮圖之 Provider 獲取指定檔案的縮圖網址（支援快取）。"""
    if remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{remote}' 的遠端節點。")

    if not refresh:
        cached_thumb = directory_cache.get_thumbnail(remote, path)
        if cached_thumb:
            if redirect:
                return RedirectResponse(url=cached_thumb, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
            return ThumbnailResponse(
                remote=remote,
                path=path,
                url=cached_thumb,
                thumbnail_url=cached_thumb,
            )

    storage = resolve_storage(remote, config_manager)
    with managed_storage(storage) as provider:
        try:
            thumb_url = provider.get_thumbnail_link(path)
            if not thumb_url:
                raise ValueError("未取得有效的縮圖網址。")
        except NotImplementedError as exc:
            raise HTTPException(status_code=501, detail=f"此 Provider 不支援獲取縮圖: {exc}") from exc
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=f"無法取得縮圖: {exc}") from exc
        except HttpStatusError as exc:
            if exc.status_code in (400, 404):
                raise HTTPException(status_code=404, detail=f"無法取得縮圖: {exc}") from exc
            raise HTTPException(status_code=502, detail=f"遠端服務回應錯誤: {exc}") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"取得縮圖失敗: {exc}") from exc

    directory_cache.put_thumbnail(remote, path, thumb_url)

    if redirect:
        return RedirectResponse(url=thumb_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    return ThumbnailResponse(
        remote=remote,
        path=path,
        url=thumb_url,
        thumbnail_url=thumb_url,
    )


@router.post("/{remote}/upload", status_code=status.HTTP_201_CREATED)
def upload_file(
    remote: str,
    target_dir: str = Form("/", description="目的地目錄"),
    file: UploadFile = File(..., description="上傳之檔案物件"),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """接收瀏覽器上傳之檔案並儲存至遠端節點（串流暫存，防記憶體暴增）。"""
    if remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{remote}' 的遠端節點。")

    original_filename = file.filename or "uploaded_file"
    remote_path = f"{target_dir.rstrip('/')}/{original_filename}".replace("//", "/")

    temp_fd, temp_file_path = tempfile.mkstemp(prefix="drive_upload_")
    total_bytes = 0

    try:
        # 分塊寫入暫存檔
        with os.fdopen(temp_fd, "wb") as f_out:
            while chunk := file.file.read(64 * 1024):
                f_out.write(chunk)
                total_bytes += len(chunk)

        storage = resolve_storage(remote, config_manager)
        with managed_storage(storage) as provider:
            ok = provider.upload(temp_file_path, remote_path)
            if not ok:
                raise RuntimeError("Provider 上傳回傳 False。")

        directory_cache.invalidate(remote, remote_path)
        return {
            "status": "uploaded",
            "remote": remote,
            "path": remote_path,
            "size": total_bytes,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"檔案上傳失敗: {exc}") from exc
    finally:
        _cleanup_temp_file(temp_file_path)
        file.file.close()


@router.post("/transfer", status_code=status.HTTP_202_ACCEPTED)
def transfer_files(
    req: TransferRequest,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """跨儲存節點批次傳輸 (複製或移動)。回傳 task_id 以供 SSE 即時監控。"""
    task_id = str(uuid.uuid4())
    task_event_manager.register_task(
        task_id,
        kind="transfer",
        title=f"傳輸 ({req.mode}): {len(req.sources)} 個項目 -> {req.dest_dir}",
        source_uri=req.sources[0] if len(req.sources) == 1 else f"{len(req.sources)} 個來源",
        dest_uri=req.dest_dir,
        request_payload=req.model_dump(),
    )
    t = threading.Thread(
        target=run_transfer_job,
        args=(task_id, req.sources, req.dest_dir, req.mode, config_manager),
        daemon=True,
    )
    t.start()
    return {"status": "started", "task_id": task_id}


@router.post("/{remote}/rename", status_code=status.HTTP_200_OK)
def rename_item(
    remote: str,
    req: RenameRequest,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """於同節點內重新命名檔案或資料夾。"""
    if remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{remote}' 的遠端節點。")

    parent_dir = posixpath.dirname(req.path.rstrip("/"))
    dest_path = posixpath.join(parent_dir, req.new_name).replace("//", "/")

    storage = resolve_storage(remote, config_manager)
    with managed_storage(storage) as provider:
        try:
            ok = provider.move(req.path, dest_path, overwrite=False)
            if not ok:
                raise RuntimeError("Provider 重新命名回傳 False。")
            directory_cache.invalidate(remote, req.path)
            directory_cache.invalidate(remote, dest_path)
            directory_cache.invalidate(remote, parent_dir or "/")
            broadcaster.publish("system", {"topic": "files", "action": "rename", "remote": remote})
            return {"status": "renamed", "remote": remote, "old_path": req.path, "new_path": dest_path}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"重新命名失敗: {exc}") from exc


@router.post("/{remote}/move", status_code=status.HTTP_200_OK)
def move_item(
    remote: str,
    req: MoveCopyRequest,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """於同節點內移動檔案或資料夾。"""
    if remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{remote}' 的遠端節點。")

    storage = resolve_storage(remote, config_manager)
    with managed_storage(storage) as provider:
        try:
            ok = provider.move(req.source, req.destination, overwrite=req.overwrite)
            if not ok:
                raise RuntimeError("Provider 移動項目回傳 False。")
            directory_cache.invalidate(remote, req.source)
            directory_cache.invalidate(remote, req.destination)
            broadcaster.publish("system", {"topic": "files", "action": "move", "remote": remote})
            return {"status": "moved", "remote": remote, "source": req.source, "destination": req.destination}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"移動項目失敗: {exc}") from exc


@router.post("/{remote}/copy", status_code=status.HTTP_200_OK)
def copy_item(
    remote: str,
    req: MoveCopyRequest,
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """於同節點內複製檔案或資料夾。"""
    if remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{remote}' 的遠端節點。")

    storage = resolve_storage(remote, config_manager)
    with managed_storage(storage) as provider:
        try:
            ok = provider.copy(req.source, req.destination, overwrite=req.overwrite)
            if not ok:
                raise RuntimeError("Provider 複製項目回傳 False。")
            directory_cache.invalidate(remote, req.destination)
            broadcaster.publish("system", {"topic": "files", "action": "copy", "remote": remote})
            return {"status": "copied", "remote": remote, "source": req.source, "destination": req.destination}
        except NotImplementedError as exc:
            raise HTTPException(status_code=501, detail=f"此儲存節點不支援直接複製: {exc}") from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"複製項目失敗: {exc}") from exc
