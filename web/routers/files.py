"""Virtual filesystem REST API router (/api/fs)."""

from __future__ import annotations

import mimetypes
import os
import posixpath
import tempfile
from typing import Any

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
    sort_by: str = Query("name", description="排序欄位: name, size, modified"),
    reverse: bool = Query(False, description="是否反向排序"),
    refresh: bool = Query(False, description="是否略過快取並強制重新讀取"),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> ListDirResponse:
    """列出指定節點與路徑下的檔案與資料夾清單（支援目錄快取）。"""
    if remote not in config_manager.config.remotes:
        raise HTTPException(status_code=404, detail=f"找不到名為 '{remote}' 的遠端節點。")

    norm_path = path.strip() or "/"
    raw_items: list[FileItem] | None = None
    if not refresh:
        raw_items = directory_cache.get(remote, norm_path)

    if raw_items is None:
        try:
            storage = resolve_storage(remote, config_manager)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"初始化儲存驅動失敗: {exc}") from exc

        with managed_storage(storage) as provider:
            try:
                raw_items = provider.list_dir(norm_path)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"讀取目錄失敗 ({norm_path}): {exc}") from exc

        directory_cache.put(remote, norm_path, raw_items)

    # 排序處理：資料夾優先，其次依 sort_by
    def sort_key(item: FileItem) -> tuple[bool, Any]:
        if sort_by == "size":
            return (not item.is_dir, item.size)
        elif sort_by == "modified":
            ts = item.modified_at.timestamp() if item.modified_at else 0.0
            return (not item.is_dir, ts)
        else:
            return (not item.is_dir, item.name.lower())

    sorted_items = sorted(raw_items, key=sort_key, reverse=reverse)

    items_resp = [
        FileItemResponse(
            name=it.name,
            path=it.path,
            is_dir=it.is_dir,
            size=it.size,
            modified_at=it.modified_at.isoformat() if it.modified_at else None,
            thumbnail_url=it.thumbnail_url,
        )
        for it in sorted_items
    ]

    return ListDirResponse(
        remote=remote,
        path=norm_path,
        total_count=len(items_resp),
        items=items_resp,
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


@router.get("/{remote}/raw")
def raw_file(
    remote: str,
    path: str = Query(..., description="要直接串流或預覽之遠端檔案路徑"),
    redirect: bool = Query(False, description="若 Provider 支援直鏈是否直接 307 重導向"),
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
