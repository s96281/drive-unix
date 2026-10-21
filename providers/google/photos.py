# providers/google/photos.py
from __future__ import annotations

import logging
import mimetypes
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, cast

import requests

from domain.models import FileItem
from storage.base import (
    DeleteCapability,
    ProgressCallback,
    StorageProvider,
    StorageStat,
)

logger = logging.getLogger(__name__)

SUPPORTED_MIME_PREFIXES = ("image/", "video/")
CHUNK_SIZE = 64 * 1024


class GooglePhotosClient:
    """Client for Google Photos Library REST API."""

    BASE_URL = "https://photoslibrary.googleapis.com/v1"
    UPLOAD_URL = "https://photoslibrary.googleapis.com/v1/uploads"

    def __init__(
        self,
        auth_provider: Any = None,
        session: requests.Session | None = None,
        token: str | None = None,
    ) -> None:
        self.auth_provider = auth_provider
        self.session = session or requests.Session()
        self._token = token

    def _get_headers(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.auth_provider:
            ctx = self.auth_provider.get_auth_context()
            headers.update(ctx.headers)
        elif self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        if extra:
            headers.update(extra)
        return headers

    @staticmethod
    def _check_response(resp: requests.Response) -> None:
        if resp.ok:
            return
        try:
            data = resp.json()
            error_info = data.get("error", {})
            if isinstance(error_info, dict) and "message" in error_info:
                msg = error_info["message"]
                raise requests.HTTPError(
                    f"{resp.status_code} Client Error: {resp.reason} for url: {resp.url}\nGoogle API 錯誤訊息: {msg}",
                    response=resp,
                )
        except (ValueError, TypeError):
            pass
        resp.raise_for_status()

    def list_albums(self) -> list[dict[str, Any]]:
        albums: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "pageSize": 50,
                "excludeNonAppCreatedData": True,
            }
            if page_token:
                params["pageToken"] = page_token

            resp = self.session.get(
                f"{self.BASE_URL}/albums",
                params=params,
                headers=self._get_headers(),
            )
            self._check_response(resp)
            data = resp.json()
            albums.extend(data.get("albums", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return albums

    def create_album(self, title: str) -> dict[str, Any]:
        resp = self.session.post(
            f"{self.BASE_URL}/albums",
            json={"album": {"title": title}},
            headers=self._get_headers({"Content-Type": "application/json"}),
        )
        self._check_response(resp)
        return cast(dict[str, Any], resp.json())

    def list_library_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"pageSize": 100}
            if page_token:
                params["pageToken"] = page_token

            resp = self.session.get(
                f"{self.BASE_URL}/mediaItems",
                params=params,
                headers=self._get_headers(),
            )
            self._check_response(resp)
            data = resp.json()
            items.extend(data.get("mediaItems", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return items

    def list_album_items(self, album_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            payload: dict[str, Any] = {
                "albumId": album_id,
                "pageSize": 100,
            }
            if page_token:
                payload["pageToken"] = page_token

            resp = self.session.post(
                f"{self.BASE_URL}/mediaItems:search",
                json=payload,
                headers=self._get_headers({"Content-Type": "application/json"}),
            )
            self._check_response(resp)
            data = resp.json()
            items.extend(data.get("mediaItems", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return items

    def upload_raw_bytes(
        self,
        local_path: str,
        callback: ProgressCallback | None = None,
    ) -> str:
        file_size = os.path.getsize(local_path)
        mime_type, _ = mimetypes.guess_type(local_path)
        mime_type = mime_type or "application/octet-stream"

        headers = self._get_headers({
            "Content-Type": "application/octet-stream",
            "X-Goog-Upload-Content-Type": mime_type,
            "X-Goog-Upload-Protocol": "raw",
        })

        def stream_generator():
            sent = 0
            with open(local_path, "rb") as handle:
                while True:
                    chunk = handle.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    sent += len(chunk)
                    if callback:
                        callback(sent, file_size)
                    yield chunk

        resp = self.session.post(
            self.UPLOAD_URL,
            data=stream_generator(),
            headers=headers,
        )
        self._check_response(resp)
        upload_token = resp.text.strip()
        if not upload_token:
            raise RuntimeError("Google Photos API 未回傳有效的 uploadToken。")
        return upload_token

    def create_media_item(
        self,
        upload_token: str,
        filename: str,
        album_id: str | None = None,
    ) -> bool:
        payload: dict[str, Any] = {
            "newMediaItems": [
                {
                    "description": filename,
                    "simpleMediaItem": {
                        "uploadToken": upload_token,
                        "fileName": filename,
                    },
                }
            ]
        }
        if album_id:
            payload["albumId"] = album_id

        resp = self.session.post(
            f"{self.BASE_URL}/mediaItems:batchCreate",
            json=payload,
            headers=self._get_headers({"Content-Type": "application/json"}),
        )
        self._check_response(resp)
        data = resp.json()
        results = data.get("newMediaItemResults", [])
        if results:
            status = results[0].get("status", {})
            code = status.get("code", 0)
            message = status.get("message", "")
            if code != 0 and message.lower() not in ("success", "ok", ""):
                raise RuntimeError(f"Google Photos 建立媒體項目失敗: {message}")
        return True

    def download_stream(
        self,
        download_url: str,
        local_path: str,
        callback: ProgressCallback | None = None,
    ) -> bool:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        with self.session.get(download_url, stream=True) as resp:
            self._check_response(resp)
            total_size = int(resp.headers.get("content-length", 0))
            downloaded = 0
            with open(local_path, "wb") as handle:
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if callback:
                            callback(downloaded, total_size)
        return True

    def remove_from_album(self, album_id: str, media_item_ids: list[str]) -> bool:
        resp = self.session.post(
            f"{self.BASE_URL}/albums/{album_id}:batchRemoveMediaItems",
            json={"mediaItemIds": list(media_item_ids)},
            headers=self._get_headers({"Content-Type": "application/json"}),
        )
        self._check_response(resp)
        return True


class GooglePhotosStorage(StorageProvider):
    delete_capability = DeleteCapability.PERMANENT_ONLY

    def __init__(
        self,
        client: Any = None,
        remote_name: str = "googlephotos",
        auth_provider: Any = None,
    ) -> None:
        if client is not None:
            self.client = client
        elif auth_provider is not None:
            self.client = GooglePhotosClient(auth_provider=auth_provider)
        else:
            self.client = GooglePhotosClient()
        self.remote_name = remote_name
        self._album_cache: dict[str, str] = {}  # title -> album_id

    def _normalize_path(self, path: str) -> str:
        cleaned = "/" + path.strip().replace("\\", "/").strip("/")
        return cleaned if cleaned != "" else "/"

    def _parse_time(self, time_val: str | None) -> datetime | None:
        if not time_val:
            return None
        try:
            return datetime.fromisoformat(time_val.replace("Z", "+00:00"))
        except Exception:
            return None

    def _resolve_album_id(self, album_title: str) -> str:
        if album_title in self._album_cache:
            return self._album_cache[album_title]
        albums = self.client.list_albums()
        self._album_cache = {a["title"]: a["id"] for a in albums if "title" in a and "id" in a}
        if album_title in self._album_cache:
            return self._album_cache[album_title]
        raise ValueError(f"找不到相簿: '{album_title}'")

    def _ensure_album_exists(self, album_title: str) -> str:
        try:
            return self._resolve_album_id(album_title)
        except ValueError:
            created = self.client.create_album(album_title)
            album_id = str(created["id"])
            self._album_cache[album_title] = album_id
            return album_id

    def _resolve_media_item(self, path: str) -> dict[str, Any]:
        norm_path = self._normalize_path(path)
        parts = norm_path.strip("/").split("/")
        if len(parts) > 2:
            raise ValueError("Google Photos 不支援多層巢狀目錄結構。")

        if len(parts) == 1:
            target_name = parts[0]
            items = self.client.list_library_items()
            for item in items:
                if item.get("filename") == target_name:
                    return cast(dict[str, Any], item)
            raise FileNotFoundError(f"找不到指定的媒體項目: {path}")

        album_title, target_name = parts[0], parts[1]
        if album_title == "_all":
            items = self.client.list_library_items()
        else:
            album_id = self._resolve_album_id(album_title)
            items = self.client.list_album_items(album_id)

        for item in items:
            if item.get("filename") == target_name:
                return cast(dict[str, Any], item)
        raise FileNotFoundError(f"找不到指定的媒體項目: {path}")

    def list_dir(self, path: str) -> list[FileItem]:
        norm_path = self._normalize_path(path)

        # 1. 根目錄：列出全部相簿 + 虛擬 _all 目錄
        if norm_path == "/":
            albums = self.client.list_albums()
            self._album_cache = {a["title"]: a["id"] for a in albums if "title" in a and "id" in a}
            items = [
                FileItem(name=a["title"], path=f"/{a['title']}", is_dir=True)
                for a in albums
                if "title" in a
            ]
            items.append(FileItem(name="_all", path="/_all", is_dir=True))
            return items

        # 2. 相簿或全量目錄
        parts = norm_path.strip("/").split("/")
        if len(parts) > 1:
            raise ValueError("Google Photos 不支援多層巢狀目錄結構。")

        target = parts[0]
        if target == "_all":
            media_items = self.client.list_library_items()
        else:
            album_id = self._resolve_album_id(target)
            media_items = self.client.list_album_items(album_id)

        return [
            FileItem(
                name=item["filename"],
                path=f"/{target}/{item['filename']}",
                is_dir=False,
                size=int(item.get("mediaMetadata", {}).get("width", 0)),
                modified_at=self._parse_time(item.get("mediaMetadata", {}).get("creationTime")),
                remote_hash=None,
                thumbnail_url=f"{item['baseUrl']}=w300-h300" if item.get("baseUrl") else None,
            )
            for item in media_items
            if "filename" in item
        ]

    def upload(
        self,
        local_path: str,
        remote_path: str,
        callback: ProgressCallback | None = None,
    ) -> bool:
        # 1. 前置 MIME 檢查，避免無效請求
        mime_type, _ = mimetypes.guess_type(local_path)
        if not mime_type or not any(mime_type.startswith(p) for p in SUPPORTED_MIME_PREFIXES):
            raise ValueError(f"不支援的媒體格式: {local_path} ({mime_type})")

        # 2. 第一階段：上傳 Raw Bytes 換取 uploadToken
        upload_token = self.client.upload_raw_bytes(local_path, callback=callback)

        # 3. 解析所屬相簿
        parts = self._normalize_path(remote_path).strip("/").split("/")
        if len(parts) > 2:
            raise ValueError("Google Photos 不支援多層巢狀目錄結構。")

        album_id = None
        filename = Path(local_path).name

        if len(parts) == 2:
            if parts[0] != "_all":
                album_id = self._ensure_album_exists(parts[0])
            filename = parts[1]
        elif len(parts) == 1 and parts[0]:
            if remote_path.endswith("/") and parts[0] != "_all":
                album_id = self._ensure_album_exists(parts[0])
            elif parts[0] != "_all":
                if parts[0] in self._album_cache:
                    album_id = self._album_cache[parts[0]]
                else:
                    filename = parts[0]

        # 4. 第二階段：呼叫 batchCreate 關聯實體
        return bool(self.client.create_media_item(upload_token, filename, album_id=album_id))

    def download(
        self,
        remote_path: str,
        local_path: str,
        recursive: bool = False,
        callback: ProgressCallback | None = None,
    ) -> bool:
        item = self._resolve_media_item(remote_path)
        # Google Photos 原始檔全尺寸下載後綴標籤
        download_url = f"{item['baseUrl']}=d"
        return bool(self.client.download_stream(download_url, local_path, callback=callback))

    def stat(self, path: str) -> StorageStat:
        norm_path = self._normalize_path(path)
        if norm_path == "/":
            return StorageStat(
                type="remote",
                name=f"Google Photos: {self.remote_name}",
                total=-1,
                used=-1,
                filecount=-1,
                created=None,
                modified=None,
            )

        if norm_path == "/_all" or norm_path.strip("/") in self._album_cache:
            return StorageStat(type="folder", size=0, name=norm_path.strip("/"))

        parts = norm_path.strip("/").split("/")
        if len(parts) == 1:
            try:
                self._resolve_album_id(parts[0])
                return StorageStat(type="folder", size=0, name=parts[0])
            except ValueError:
                pass

        item = self._resolve_media_item(norm_path)
        created_time = self._parse_time(item.get("mediaMetadata", {}).get("creationTime"))
        return StorageStat(
            type="file",
            name=item.get("filename", ""),
            size=0,
            modified=created_time,
            created=created_time,
        )

    def delete(self, path: str, permanent: bool = False) -> bool:
        norm_path = self._normalize_path(path)
        parts = norm_path.strip("/").split("/")
        if len(parts) != 2 or parts[0] == "_all":
            raise NotImplementedError(
                "Google Photos API 不支援自相簿庫全域刪除照片，僅能自特定相簿中移除。"
            )

        album_id = self._resolve_album_id(parts[0])
        item = self._resolve_media_item(path)
        return bool(self.client.remove_from_album(album_id, [item["id"]]))

    def mkdir(self, remote_path: str, parents: bool = False) -> bool:
        norm_path = self._normalize_path(remote_path)
        if norm_path in ("/", "/_all"):
            return True

        parts = norm_path.strip("/").split("/")
        if len(parts) > 1:
            raise ValueError("Google Photos 不支援多層巢狀目錄結構。")

        self._ensure_album_exists(parts[0])
        return True

    def copy(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        raise NotImplementedError("Google Photos 不支援同節點複製。")

    def move(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        raise NotImplementedError("Google Photos 不支援同節點移動。")

    def get_share_link(self, remote_path: str) -> str:
        norm_path = self._normalize_path(remote_path)
        if norm_path in ("/", "/_all"):
            return "https://photos.google.com"

        parts = norm_path.strip("/").split("/")
        if len(parts) == 1 and parts[0] != "_all":
            try:
                album_id = self._resolve_album_id(parts[0])
                albums = self.client.list_albums()
                for a in albums:
                    if a.get("id") == album_id and "productUrl" in a:
                        return str(a["productUrl"])
            except ValueError:
                pass

        item = self._resolve_media_item(remote_path)
        return str(item.get("productUrl", item.get("baseUrl", "https://photos.google.com")))

    def get_download_link(self, remote_path: str) -> str:
        item = self._resolve_media_item(remote_path)
        return f"{item['baseUrl']}=d"

    def get_preview_link(self, remote_path: str) -> str:
        item = self._resolve_media_item(remote_path)
        return str(item.get("productUrl", item.get("baseUrl", "")))

    def get_thumbnail_link(self, remote_path: str) -> str:
        item = self._resolve_media_item(remote_path)
        base_url = item.get("baseUrl")
        if not base_url:
            raise ValueError(f"Google Photos 未提供此項目之 baseUrl: {remote_path}")
        return f"{base_url}=w300-h300"

    def get_hash(self, remote_path: str, algo: str) -> str:
        raise NotImplementedError("Google Photos API does not support remote hash.")
