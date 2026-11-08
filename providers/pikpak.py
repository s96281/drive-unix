from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import requests

from core.hashing import calculate_local_hash
from domain.models import FileItem
from infrastructure.http import HttpClient
from storage.base import (
    DeleteCapability,
    ProgressCallback,
    StorageProvider,
    StorageStat,
)


class _ProgressStream:
    """Stream wrapper that reports transfer progress during PUT uploads."""

    def __init__(
        self,
        stream: Any,
        total_size: int,
        callback: ProgressCallback | None,
    ) -> None:
        self._stream = stream
        self._total_size = total_size
        self._callback = callback
        self._transferred = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(size)
        if chunk:
            self._transferred += len(chunk)
            if self._callback:
                self._callback(self._transferred, self._total_size)
        return cast(bytes, chunk)

    def seek(self, offset: int, whence: int = 0) -> int:
        return int(self._stream.seek(offset, whence))

    def tell(self) -> int:
        return int(self._stream.tell())

    def __len__(self) -> int:
        return self._total_size


class PikPakStorage(StorageProvider):
    delete_capability = DeleteCapability.TRASH_AND_PERMANENT
    API_BASE = "https://api-drive.mypikpak.com/drive/v1"

    def __init__(self, auth_provider: Any, root_folder_id: str = "") -> None:
        self.auth = auth_provider
        self.root_id = root_folder_id
        self.http = HttpClient()
        self._path_cache: dict[str, str] = {"/": self.root_id, "": self.root_id}
        self._cache_lock = threading.Lock()

    def _auth_headers(self) -> dict[str, str]:
        return cast(dict[str, str], self.auth.get_auth_context().headers)

    @staticmethod
    def _normalize_path(path: str) -> str:
        p = path.replace("\\", "/").strip()
        if not p or p == "/":
            return "/"
        return "/" + p.strip("/")

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        headers = kwargs.pop("headers", None)
        if headers is None:
            request_headers = self._auth_headers()
        else:
            request_headers = dict(headers)

        fn = getattr(self.http, method.lower())
        resp = fn(url, headers=request_headers, **kwargs)

        if resp.status_code == 401:
            self.auth.refresh()
            request_headers.update(self._auth_headers())
            resp = fn(url, headers=request_headers, **kwargs)

        return cast(requests.Response, resp)

    def _resolve_path(self, path: str) -> str:
        """遞迴或逐層比對取得該路徑的 file_id。"""
        norm_path = self._normalize_path(path)
        with self._cache_lock:
            if norm_path in self._path_cache:
                return self._path_cache[norm_path]

        parts = [p for p in norm_path.strip("/").split("/") if p]
        curr_id = self.root_id
        accumulated = ""
        for part in parts:
            accumulated += f"/{part}"
            with self._cache_lock:
                if accumulated in self._path_cache:
                    curr_id = self._path_cache[accumulated]
                    continue

            parent_dir = str(Path(accumulated).parent).replace("\\", "/")
            if parent_dir == ".":
                parent_dir = "/"
            items = self.list_dir(parent_dir)
            matched = next((item for item in items if item.name == part), None)
            if not matched:
                raise FileNotFoundError(f"找不到遠端路徑: {accumulated}")
            with self._cache_lock:
                curr_id = self._path_cache[accumulated]

        return curr_id

    def list_dir(
        self,
        path: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[FileItem]:
        if offset < 0:
            offset = 0
        if limit is not None and limit <= 0:
            return []

        folder_id = self._resolve_path(path)
        result_items: list[FileItem] = []
        page_token: str | None = None
        norm_dir = self._normalize_path(path)
        fetched_total = 0
        max_limit = 100
        target_end = (offset + limit) if limit is not None else None

        while True:
            if target_end is not None:
                remaining_needed = target_end - fetched_total
                if remaining_needed <= 0:
                    break
                current_limit = min(remaining_needed, max_limit)
            else:
                current_limit = max_limit

            params: dict[str, Any] = {"parent_id": folder_id, "limit": current_limit}
            if page_token:
                params["page_token"] = page_token

            resp = self._request("GET", f"{self.API_BASE}/files", params=params)
            self.http.raise_for_status(resp, context="PikPak 列舉目錄")
            data = resp.json()

            raw_files = [f for f in data.get("files", []) if not f.get("trashed")]
            for f in raw_files:
                name = f["name"]
                item_path = f"{norm_dir.rstrip('/')}/{name}" if norm_dir != "/" else f"/{name}"
                with self._cache_lock:
                    self._path_cache[item_path] = f["id"]

            page_start = fetched_total
            page_end = page_start + len(raw_files)
            fetched_total = page_end

            if target_end is not None:
                slice_start = max(0, offset - page_start)
                slice_end = min(len(raw_files), target_end - page_start)
            else:
                slice_start = max(0, offset - page_start)
                slice_end = len(raw_files)

            if slice_start < slice_end:
                for f in raw_files[slice_start:slice_end]:
                    name = f["name"]
                    item_path = f"{norm_dir.rstrip('/')}/{name}" if norm_dir != "/" else f"/{name}"
                    is_dir = f.get("kind") == "drive#folder"
                    mtime_str = f.get("modified_time")
                    mtime = (
                        datetime.fromisoformat(mtime_str.replace("Z", "+00:00"))
                        if mtime_str
                        else None
                    )
                    thumb_url = f.get("thumbnail_link") or f.get("thumbnail_url") or f.get("icon_link")
                    result_items.append(
                        FileItem(
                            name=name,
                            path=item_path,
                            is_dir=is_dir,
                            size=int(f.get("size", 0)),
                            modified_at=mtime,
                            remote_hash=f.get("md5_checksum"),
                            thumbnail_url=thumb_url if not is_dir else None,
                        )
                    )

            if target_end is not None and fetched_total >= target_end:
                break

            page_token = data.get("next_page_token")
            if not page_token:
                break

        return result_items

    def upload(
        self,
        local_path: str,
        remote_path: str,
        callback: ProgressCallback | None = None,
    ) -> bool:
        norm_remote = self._normalize_path(remote_path)
        parent_dir = str(Path(norm_remote).parent).replace("\\", "/")
        if parent_dir == ".":
            parent_dir = "/"
        parent_id = self._resolve_path(parent_dir)
        file_path = Path(local_path)
        file_size = file_path.stat().st_size
        file_name = file_path.name
        file_md5 = calculate_local_hash(local_path, "md5")

        # 1. 向 API 宣告檔案並嘗試秒傳
        body = {
            "kind": "drive#file",
            "parent_id": parent_id,
            "name": file_name,
            "size": str(file_size),
            "hash": file_md5,
        }
        res = self._request("POST", f"{self.API_BASE}/files", json=body)
        self.http.raise_for_status(res, context="PikPak 建立檔案")
        meta = res.json()

        # 2. 秒傳命中判定
        if (
            meta.get("upload_type") == "UPLOAD_TYPE_RESUME"
            or meta.get("phase") == "PHASE_TYPE_COMPLETE"
        ):
            if callback:
                callback(file_size, file_size)
            file_meta = meta.get("file", meta)
            if "id" in file_meta:
                with self._cache_lock:
                    self._path_cache[norm_remote] = file_meta["id"]
            return True

        # 3. 實體二進位資料串流上傳至 Presigned URL
        upload_url = meta.get("upload_url", "")
        with open(local_path, "rb") as stream:
            stream_data = (
                _ProgressStream(stream, file_size, callback)
                if callback
                else stream
            )
            put_res = requests.put(upload_url, data=stream_data)
            put_res.raise_for_status()

        file_meta = meta.get("file", meta)
        if "id" in file_meta:
            with self._cache_lock:
                self._path_cache[norm_remote] = file_meta["id"]
        return True

    def download(
        self,
        remote_path: str,
        local_path: str,
        recursive: bool = False,
        callback: ProgressCallback | None = None,
    ) -> bool:
        norm_remote = self._normalize_path(remote_path)
        file_id = self._resolve_path(norm_remote)
        res = self._request("GET", f"{self.API_BASE}/files/{file_id}")
        self.http.raise_for_status(res, context="PikPak 取得項目狀態")
        data = res.json()

        if data.get("kind") == "drive#folder":
            if not recursive:
                raise IsADirectoryError(f"{remote_path} 是一個資料夾")
            Path(local_path).mkdir(parents=True, exist_ok=True)
            for child in self.list_dir(norm_remote):
                child_local = os.path.join(local_path, child.name)
                self.download(
                    child.path,
                    child_local,
                    recursive=True,
                    callback=callback,
                )
            return True

        item_name = data.get("name", Path(norm_remote).name)
        final_local_path = (
            os.path.join(local_path, item_name)
            if os.path.isdir(local_path)
            else local_path
        )
        download_url = data.get("web_content_link") or data.get("download_url")
        if not download_url:
            raise ValueError("無法取得 PikPak 下載連結。")
        return self.http.download_stream(
            download_url, final_local_path, callback=callback
        )

    def stat(self, path: str) -> StorageStat:
        norm_path = self._normalize_path(path)
        if norm_path in ("/", ""):
            return StorageStat(type="folder", size=0)

        file_id = self._resolve_path(norm_path)
        res = self._request("GET", f"{self.API_BASE}/files/{file_id}")
        self.http.raise_for_status(res, context="PikPak 取得項目狀態")
        data = res.json()

        is_folder = data.get("kind") == "drive#folder"
        mtime_str = data.get("modified_time")
        mtime = (
            datetime.fromisoformat(mtime_str.replace("Z", "+00:00"))
            if mtime_str
            else None
        )
        return StorageStat(
            type="folder" if is_folder else "file",
            name=data.get("name", Path(norm_path).name),
            size=int(data.get("size", 0)),
            modified=mtime,
        )

    def delete(self, path: str, permanent: bool = False) -> bool:
        norm_path = self._normalize_path(path)
        try:
            file_id = self._resolve_path(norm_path)
        except FileNotFoundError:
            return False

        if permanent:
            res = self._request("DELETE", f"{self.API_BASE}/files/{file_id}")
        else:
            res = self._request(
                "POST",
                f"{self.API_BASE}/files/trash",
                json={"ids": [file_id]},
            )
        self.http.raise_for_status(res, context="PikPak 刪除檔案")
        self._invalidate_path_cache(norm_path)
        return True

    def mkdir(self, remote_path: str, parents: bool = False) -> bool:
        norm_path = self._normalize_path(remote_path)
        if norm_path in ("/", ""):
            return True

        parts = [p for p in norm_path.strip("/").split("/") if p]
        if parents:
            accum = ""
            parent_id = self.root_id
            for part in parts:
                accum += f"/{part}"
                try:
                    parent_id = self._resolve_path(accum)
                except FileNotFoundError:
                    body = {
                        "kind": "drive#folder",
                        "parent_id": parent_id,
                        "name": part,
                    }
                    res = self._request("POST", f"{self.API_BASE}/files", json=body)
                    self.http.raise_for_status(res, context="PikPak 建立資料夾")
                    meta = res.json()
                    parent_id = meta.get("file", meta).get("id", meta.get("id"))
                    with self._cache_lock:
                        self._path_cache[accum] = parent_id
            return True
        else:
            parent_dir = str(Path(norm_path).parent).replace("\\", "/")
            if parent_dir == ".":
                parent_dir = "/"
            parent_id = self._resolve_path(parent_dir)
            name = Path(norm_path).name
            body = {
                "kind": "drive#folder",
                "parent_id": parent_id,
                "name": name,
            }
            res = self._request("POST", f"{self.API_BASE}/files", json=body)
            self.http.raise_for_status(res, context="PikPak 建立資料夾")
            meta = res.json()
            folder_id = meta.get("file", meta).get("id", meta.get("id"))
            with self._cache_lock:
                self._path_cache[norm_path] = folder_id
            return True

    def get_hash(self, remote_path: str, algo: str) -> str:
        if algo.lower() != "md5":
            raise ValueError(f"PikPak 原生僅支援 md5 雜湊演算 (你輸入了 {algo})。")

        norm_path = self._normalize_path(remote_path)
        file_id = self._resolve_path(norm_path)
        res = self._request("GET", f"{self.API_BASE}/files/{file_id}")
        self.http.raise_for_status(res, context="PikPak 取得檔案狀態")
        data = res.json()

        if data.get("kind") == "drive#folder":
            raise ValueError("無法對資料夾計算雜湊值。")

        checksum = data.get("md5_checksum")
        if not checksum:
            raise ValueError("PikPak 未回傳 md5_checksum。")
        return str(checksum)

    def get_share_link(self, remote_path: str) -> str:
        norm_path = self._normalize_path(remote_path)
        file_id = self._resolve_path(norm_path)
        res = self._request("GET", f"{self.API_BASE}/files/{file_id}")
        self.http.raise_for_status(res, context="PikPak 取得檔案狀態")
        data = res.json()
        link = data.get("web_content_link") or data.get("download_url")
        if not link:
            raise ValueError("無法取得 PikPak 分享連結。")
        return str(link)

    def get_download_link(self, remote_path: str) -> str:
        return self.get_share_link(remote_path)

    def get_thumbnail_link(self, remote_path: str) -> str:
        norm_path = self._normalize_path(remote_path)
        file_id = self._resolve_path(norm_path)
        res = self._request("GET", f"{self.API_BASE}/files/{file_id}")
        self.http.raise_for_status(res, context="PikPak 取得檔案狀態")
        data = res.json()
        if data.get("kind") == "drive#folder":
            raise ValueError("無法為資料夾產生縮圖。")
        link = data.get("thumbnail_link") or data.get("thumbnail_url") or data.get("icon_link")
        if not link:
            raise ValueError(f"PikPak 未提供此檔案之縮圖: {remote_path}")
        return str(link)

    def copy(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        src_id = self._resolve_path(source_path)
        dest_parent = str(Path(self._normalize_path(dest_path)).parent).replace("\\", "/")
        if dest_parent == ".":
            dest_parent = "/"
        dest_parent_id = self._resolve_path(dest_parent)
        res = self._request(
            "POST",
            f"{self.API_BASE}/files/copy",
            json={"ids": [src_id], "to": {"parent_id": dest_parent_id}},
        )
        self.http.raise_for_status(res, context="PikPak 複製檔案")
        self._invalidate_path_cache(dest_parent)
        return True

    def move(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        src_id = self._resolve_path(source_path)
        dest_parent = str(Path(self._normalize_path(dest_path)).parent).replace("\\", "/")
        if dest_parent == ".":
            dest_parent = "/"
        dest_parent_id = self._resolve_path(dest_parent)
        dest_name = Path(dest_path).name

        res = self._request(
            "POST",
            f"{self.API_BASE}/files/move",
            json={"ids": [src_id], "to": {"parent_id": dest_parent_id}},
        )
        self.http.raise_for_status(res, context="PikPak 移動檔案")

        patch_res = self._request(
            "PATCH",
            f"{self.API_BASE}/files/{src_id}",
            json={"name": dest_name},
        )
        self.http.raise_for_status(patch_res, context="PikPak 重新命名檔案")

        self._invalidate_path_cache(source_path)
        self._invalidate_path_cache(dest_path)
        return True

    def _invalidate_path_cache(self, path: str) -> None:
        norm = self._normalize_path(path)
        prefix = f"{norm.rstrip('/')}/"
        with self._cache_lock:
            keys_to_remove = [
                k for k in self._path_cache
                if k == norm or k.startswith(prefix)
            ]
            for k in keys_to_remove:
                self._path_cache.pop(k, None)

    def close(self) -> None:
        self.http.close()
