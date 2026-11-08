from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote, unquote, urlparse

import requests

from auth.base import AuthProvider
from infrastructure.http import HttpClient


MICROSOFT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0"
)


class Microsoft365Client:
    """Shared transport and REST helpers for SharePoint/OneDrive Business."""

    def __init__(
        self,
        *,
        auth_provider: AuthProvider,
        base_url: str,
        site: str = "",
    ):
        self.auth_provider = auth_provider
        self.base_url = base_url.rstrip("/")
        self.site = self._normalize_site(site)
        self.http = HttpClient(user_agent=MICROSOFT_USER_AGENT)
        self._drive_id_cache: dict[str, str] | None = None
        self._drive_path_cache: dict[str, str] | None = None

    def close(self) -> None:
        """Release HTTP sessions owned by this Microsoft 365 client."""
        self.http.close()

    @staticmethod
    def _json_object(response: requests.Response, *, context: str) -> dict[str, Any]:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError(f"{context} 回應格式無效：預期 JSON object。")
        return data

    @staticmethod
    def _normalize_site(site: str | None) -> str:
        clean = (site or "").strip("/")
        return f"/{clean}" if clean else ""

    def set_site(self, site: str | None) -> None:
        normalized = self._normalize_site(site)
        if normalized != self.site:
            self.site = normalized
            self._drive_id_cache = None
            self._drive_path_cache = None

    @property
    def drive_id_cache(self) -> dict[str, str] | None:
        return self._drive_id_cache

    @property
    def drive_path_cache(self) -> dict[str, str] | None:
        return self._drive_path_cache

    def get_headers(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        """Build request headers from the current authentication context."""
        auth_context = self.auth_provider.get_auth_context()
        headers: dict[str, str] = {
            "Accept": "application/json;odata=verbose",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0",
        }

        if auth_context.headers.get("Cookie"):
            headers["Cookie"] = auth_context.headers["Cookie"]

        if extra:
            headers.update(extra)

        return headers

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        return self.http.request(method, url, **kwargs)

    def init_drives_cache(self, *, resolve_site: Callable[[], None] | None = None) -> None:
        if self._drive_id_cache is not None and self._drive_path_cache is not None:
            return

        if resolve_site is not None:
            resolve_site()

        headers = self.get_headers({
            "Accept": "application/json;odata.metadata=minimal",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0",
            "Sec-Fetch-User": "?1",
        })

        api_url = f"{self.base_url}{self.site}/_api/v2.0/drives"
        response = self.http.get(api_url, headers=headers)
        self.http.raise_for_status(response, context="初始化 Microsoft 365 文件庫")

        payload = self._json_object(response, context="Microsoft 365 drives")
        drive_cache: dict[str, str] = {}
        path_cache: dict[str, str] = {}
        for drive in payload.get("value", []):
            if not isinstance(drive, dict):
                continue
            drive_id = drive.get("id")
            drive_name = drive.get("name")
            if not isinstance(drive_id, str) or not isinstance(drive_name, str):
                continue
            drive_cache[drive_name] = drive_id

            web_url = drive.get("webUrl")
            folder_url_name = ""
            server_relative_path = ""
            if web_url:
                parsed_path = urlparse(web_url).path
                server_relative_path = unquote(parsed_path).rstrip("/")
                folder_url_name = unquote(web_url.rstrip("/").split("/")[-1])
                drive_cache[folder_url_name] = drive_id

            if not server_relative_path:
                server_relative_path = f"{self.site}/{folder_url_name or drive_name}".rstrip("/")

            path_cache[drive_name] = server_relative_path
            if folder_url_name:
                path_cache[folder_url_name] = server_relative_path

            # Common aliases for default document library:
            is_default_doc_lib = (
                folder_url_name in ("Shared Documents", "Documents")
                or drive_name in ("Shared Documents", "Documents", "文件")
            )
            if is_default_doc_lib:
                for alias in ("Shared Documents", "Documents", "文件"):
                    drive_cache[alias] = drive_id
                    path_cache[alias] = server_relative_path

        self._drive_id_cache = drive_cache
        self._drive_path_cache = path_cache

    def get_server_relative_path(
        self,
        remote_path: str,
        *,
        resolve_site: Callable[[], None] | None = None,
        library_aliases: tuple[str, ...] = ("Shared Documents", "Documents", "文件"),
    ) -> str:
        """Resolve a logical remote path to a SharePoint server-relative URL path."""
        cleaned = remote_path.replace("\\", "/").strip("/")
        if not cleaned:
            return self.site or "/"

        # If already starts with self.site (e.g. /sites/drive/Shared Documents/foo)
        if self.site and (f"/{cleaned}" == self.site or f"/{cleaned}".startswith(f"{self.site}/")):
            return f"/{cleaned}"

        self.init_drives_cache(resolve_site=resolve_site)
        path_cache = self._drive_path_cache or {}

        parts = [p for p in cleaned.split("/") if p]
        first_part = parts[0]
        rest = parts[1:]

        base_path = path_cache.get(first_part)
        if not base_path:
            for alias in library_aliases:
                if first_part in library_aliases:
                    base_path = path_cache.get(alias)
                    if base_path:
                        break

        if base_path:
            if rest:
                return f"{base_path}/{'/'.join(rest)}"
            return base_path

        return f"{self.site}/{cleaned}"

    def get_v2_metadata(
        self,
        remote_path: str,
        *,
        resolve_site: Callable[[], None] | None = None,
        library_aliases: tuple[str, ...] = ("Shared Documents", "Documents", "文件"),
    ) -> tuple[dict[str, Any], str]:
        parts = [part for part in remote_path.replace("\\", "/").strip("/").split("/") if part]
        if not parts:
            raise ValueError("遠端路徑不可為空。")

        if resolve_site is not None:
            resolve_site()

        library_name = parts[0]
        file_relative_path = "/".join(parts[1:])
        self.init_drives_cache()

        assert self._drive_id_cache is not None
        drive_id = self._drive_id_cache.get(library_name)
        if not drive_id:
            for alias in library_aliases:
                drive_id = self._drive_id_cache.get(alias)
                if drive_id and library_name in library_aliases:
                    break

        if not drive_id:
            raise ValueError(f"找不到對應的文件庫 (Drive): {library_name}。")

        headers = self.get_headers({
            "Accept": "application/json;odata.metadata=minimal",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0",
            "Sec-Fetch-User": "?1",
        })

        if file_relative_path:
            encoded_file_path = quote(file_relative_path)
            item_api_url = (
                f"{self.base_url}/_api/v2.0/drives/"
                f"{drive_id}/root:/{encoded_file_path}"
            )
        else:
            item_api_url = (
                f"{self.base_url}/_api/v2.0/drives/{drive_id}/root"
            )

        response = self.http.get(item_api_url, headers=headers)
        if response.status_code == 404:
            raise ValueError(f"❌ 找不到指定的遠端路徑 ({remote_path})")

        self.http.raise_for_status(response, context="取得 Microsoft 365 metadata")
        return self._json_object(response, context="Microsoft 365 metadata"), item_api_url

    def get_request_digest(self) -> str:
        headers = self.get_headers()
        api_url = f"{self.base_url}{self.site}/_api/contextinfo"
        response = self.http.post(api_url, headers=headers, retry=False)
        self.http.raise_for_status(response, context="取得 SharePoint Request Digest")
        payload = self._json_object(response, context="SharePoint Request Digest")
        value = (
            payload
            .get("d", {})
            .get("GetContextWebInformation", {})
            .get("FormDigestValue", "")
        )
        if not isinstance(value, str):
            raise ValueError("SharePoint Request Digest 回應格式無效。")
        return value
