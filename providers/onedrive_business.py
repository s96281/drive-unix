# providers/onedrive_business.py
import os
import posixpath
import uuid
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import quote, unquote, urlparse
from datetime import datetime

from storage.base import DeleteCapability, FileItem, ProgressCallback, StorageProvider, StorageStat
from auth.base import AuthProvider
from providers.microsoft365.client import Microsoft365Client
from core.logging import get_logger
from infrastructure.http import HttpStatusError


logger = get_logger("providers.onedrive_business")

class OneDriveBusinessStorage(StorageProvider):
    delete_capability = DeleteCapability.TRASH_AND_PERMANENT
    def __init__(self, auth_provider: AuthProvider, base_url: str, site: str = ""):
        self.auth_provider = auth_provider
        self.base_url = base_url.rstrip("/")
        self.raw_site = site or ""
        self.site = ""
        self.client = Microsoft365Client(
            auth_provider=auth_provider,
            base_url=self.base_url,
        )
        self.session = self.client.http
        self._site_resolved = False
        self._drive_id_cache: dict[str, str] = {}

    def close(self) -> None:
        self.client.close()

    def _get_headers(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        return self.client.get_headers(extra=extra)

    def _ensure_site_resolved(self):
        """自動解析 OneDrive 個人網站位址"""
        if self._site_resolved:
            return
            
        clean_site = self.raw_site.strip("/")
        if not clean_site or clean_site.lower() == "my":
            logger.info("正在自動解析 OneDrive 個人網站位址")
            headers = self._get_headers()
            try:
                # 存取 /my 會自動 302 導向到使用者的 /personal/ 網址
                res = self.session.get(f"{self.base_url}/my", headers=headers, allow_redirects=True)
                self.session.raise_for_status(res)
                
                parsed = urlparse(res.url)
                parts = [p for p in parsed.path.split('/') if p]
                
                # 取出 /personal/user_email_com
                if len(parts) >= 2 and parts[0].lower() == "personal":
                    self.site = f"/{parts[0]}/{parts[1]}"
                    self.client.set_site(self.site)
                    logger.info("成功解析 OneDrive 個人網站: %s", self.site)
                else:
                    self.site = ""
                    self.client.set_site("")
            except Exception as e:
                logger.warning("解析 OneDrive /my 失敗，維持原設定嘗試: %s", e)
                self.site = ""
        else:
            self.site = "/" + clean_site
            self.client.set_site(self.site)
            
        self._site_resolved = True
    
    def _init_drives_cache(self) -> None:
        self._ensure_site_resolved()
        self.client.init_drives_cache()
        cache = self.client.drive_id_cache
        if cache is None:
            raise RuntimeError("OneDrive Business drive cache 初始化失敗。")
        self._drive_id_cache = cache

    def _get_v2_metadata(self, remote_path: str) -> tuple[dict[str, Any], str]:
        return self.client.get_v2_metadata(
            remote_path,
            resolve_site=self._ensure_site_resolved,
            library_aliases=("Shared Documents", "Documents"),
        )

    def _get_request_digest(self) -> str:
        self._ensure_site_resolved()
        return self.client.get_request_digest()

    def list_dir(self, remote_path: str) -> list[FileItem]:
        clean_path = remote_path.strip("/")
        if not clean_path:
            logger.info("正在獲取 OneDrive Business 文件庫清單")
            self._ensure_site_resolved()
            headers = self._get_headers()
            headers.update({
                "Accept": "application/json;odata.metadata=minimal",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Sec-Fetch-User": "?1"  
            })
            api_url = f"{self.base_url}{self.site}/_api/v2.0/drives"
            
            try:
                response = self.session.get(api_url, headers=headers)
                self.session.raise_for_status(response)
                
                items = []
                for drive in response.json().get('value', []):
                    time_str = drive.get("lastModifiedDateTime")
                    modified_dt = datetime.fromisoformat(time_str.replace("Z", "+00:00")) if time_str else None
                    raw_name = drive.get('webUrl', '').split('/')[-1]
                    items.append(FileItem(
                        name=unquote(raw_name),
                        path=f"/{drive['name']}",
                        is_dir=True,
                        size=0,
                        modified_at=modified_dt
                    ))
                return items
            except Exception as e:
                raise ValueError(f"無法自動獲取文件庫清單: {e}")

        try:
            metadata, item_api_url = self._get_v2_metadata(remote_path)
        except ValueError as e:
            raise ValueError(f"讀取路徑失敗: {e}")

        if "folder" not in metadata:
            time_str = metadata.get("fileSystemInfo", {}).get("lastModifiedDateTime")
            modified_dt = datetime.fromisoformat(time_str.replace("Z", "+00:00")) if time_str else None
            return [FileItem(
                name=metadata.get("name", "Unknown"),
                path=remote_path,
                is_dir=False,
                size=metadata.get("size", 0),
                modified_at=modified_dt
            )]

        headers = self._get_headers()
        headers.update({
            "Accept": "application/json;odata.metadata=minimal",
            "User-Agent": "Mozilla/5.0",
            "Sec-Fetch-User": "?1"
        })

        if item_api_url.endswith("/root"):
            children_url = f"{item_api_url}/children?$top=200"
        else:
            children_url = f"{item_api_url}:/children?$top=1000"

        items = []

        while children_url:
            response = self.session.get(children_url, headers=headers)
            self.session.raise_for_status(response, context="讀取 OneDrive Business 資料夾內容")
            data = response.json()

            for item in data.get('value', []):
                is_dir = "folder" in item
                time_str = item.get("fileSystemInfo", {}).get("lastModifiedDateTime")
                modified_dt = datetime.fromisoformat(time_str.replace("Z", "+00:00")) if time_str else None
                clean_remote = remote_path.rstrip('/')
                item_path = f"{clean_remote}/{item['name']}"

                items.append(FileItem(
                    name=item.get("name", "Unknown"), path=item_path, is_dir=is_dir,
                    size=item.get("size", 0) if not is_dir else 0, modified_at=modified_dt
                ))
            
            logger.debug("OneDrive Business 已載入 %d 筆項目", len(items))
            children_url = data.get('@odata.nextLink')

        logger.debug("OneDrive Business 清單載入完成，共 %d 筆", len(items))
        return items

    def mkdir(self, remote_path: str, parents: bool = False) -> bool:
        cleaned_path = remote_path.strip("/")
        if not cleaned_path:
            raise ValueError("資料夾路徑不可為空。")
            
        self._ensure_site_resolved()
        digest_value = self._get_request_digest()
        headers = self._get_headers()
        headers["X-RequestDigest"] = digest_value
        
        if not parents:
            parent_path, folder_name = posixpath.split(cleaned_path)
            clean_parent = "/" + parent_path if parent_path else ""
            server_relative_parent = f"{self.site}{clean_parent}"
            
            encoded_parent = quote(server_relative_parent.replace("'", "''"))
            encoded_folder = quote(folder_name.replace("'", "''"))
            url = f"{self.base_url}{self.site}/_api/web/GetFolderByServerRelativeUrl('{encoded_parent}')/folders/add(url='{encoded_folder}')"
            
            try:
                response = self.session.post(url, headers=headers)
                self.session.raise_for_status(response)
                return True
            except HttpStatusError as e:
                raise ValueError(f"建立資料夾失敗: {e.http_response.status_code} - {e.http_response.text}\n(提示: 若父目錄不存在，請加上 -p 參數)") from e
        else:
            parts = cleaned_path.split("/")
            if len(parts) < 2: return True
            current_parent = parts[0]
            
            for folder_name in parts[1:]:
                clean_parent = "/" + current_parent
                server_relative_parent = f"{self.site}{clean_parent}"
                encoded_parent = quote(server_relative_parent.replace("'", "''"))
                encoded_folder = quote(folder_name.replace("'", "''"))
                url = f"{self.base_url}{self.site}/_api/web/GetFolderByServerRelativeUrl('{encoded_parent}')/folders/add(url='{encoded_folder}')"
                
                try:
                    response = self.session.post(url, headers=headers)
                    self.session.raise_for_status(response)
                except HttpStatusError:
                    pass
                current_parent = f"{current_parent}/{folder_name}"
            return True

    def search(self, remote_path: str, query: str) -> list:
        try:
            _, item_api_url = self._get_v2_metadata(remote_path)
        except ValueError as e:
            raise ValueError(f"無法存取搜尋起點: {e}")

        headers = self._get_headers()
        headers.update({
            "Accept": "application/json;odata.metadata=minimal",
            "User-Agent": "Mozilla/5.0",
            "Sec-Fetch-User": "?1"
        })

        encoded_query = quote(query.replace("'", "''"))
        search_url = f"{item_api_url}/search(q='{encoded_query}')" if item_api_url.endswith("/root") else f"{item_api_url}:/search(q='{encoded_query}')"

        items = []
        parts = [p for p in remote_path.strip("/").split("/") if p]
        library_name = parts[0] if parts else ""

        try:
            while search_url:
                response = self.session.get(search_url, headers=headers)
                self.session.raise_for_status(response, context="OneDrive Business 搜尋")
                data = response.json()

                for item in data.get('value', []):
                    is_dir = "folder" in item
                    time_str = item.get("fileSystemInfo", {}).get("lastModifiedDateTime")
                    modified_dt = datetime.fromisoformat(time_str.replace("Z", "+00:00")) if time_str else None

                    parent_path = ""
                    if 'parentReference' in item and 'path' in item['parentReference']:
                        raw_path = item['parentReference']['path']
                        if "root:" in raw_path:
                            parent_path = unquote(raw_path.split("root:")[-1])
                        elif "/root/" in raw_path:
                            parent_path = "/" + unquote(raw_path.split("/root/")[-1])

                    if not parent_path and 'webUrl' in item and 'DispForm.aspx' not in item['webUrl']:
                        decoded_weburl = unquote(item['webUrl'])
                        search_target = f"/{library_name}/"
                        if search_target in decoded_weburl:
                            relative_to_lib = decoded_weburl.split(search_target, 1)[-1]
                            clean_relative = relative_to_lib.split("?")[0]
                            if clean_relative.endswith(item['name']):
                                extracted_path = clean_relative[:-len(item['name'])].strip("/")
                            else:
                                extracted_path = clean_relative.rsplit("/", 1)[0].strip("/") if "/" in clean_relative else ""
                            if extracted_path: parent_path = "/" + extracted_path

                    if parent_path == "/": parent_path = ""
                    elif parent_path and not parent_path.startswith("/"): parent_path = "/" + parent_path

                    item_full_path = f"/{library_name}{parent_path}/{item['name']}".replace("//", "/")
                    items.append(FileItem(
                        name=item.get("name", "Unknown"), path=item_full_path, is_dir=is_dir,
                        size=item.get("size", 0) if not is_dir else 0, modified_at=modified_dt
                    ))
                search_url = data.get('@odata.nextLink')
            return items
        except HttpStatusError as e:
            raise ValueError(f"伺服器端搜尋失敗: {e.http_response.status_code} - {e.http_response.text}")

    def upload(self, local_path: str, remote_path: str, callback: ProgressCallback | None = None) -> bool:
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"本機檔案不存在: {local_path}")
            
        file_size = os.path.getsize(local_path)
        remote_folder, file_name = posixpath.split(remote_path)
        if not file_name: file_name = os.path.basename(local_path)
            
        self._ensure_site_resolved()
        clean_folder = "/" + remote_folder.strip("/") if remote_folder else ""
        server_relative_folder = f"{self.site}{clean_folder}"
        encoded_folder_url = quote(server_relative_folder.replace("'", "''"))
        encoded_filename = quote(file_name.replace("'", "''"))
        
        digest_value = self._get_request_digest()
        headers = self._get_headers()
        headers["X-RequestDigest"] = digest_value

        LARGE_FILE_THRESHOLD = 250 * 1024 * 1024  
        if not callback:
            logger.info("開始上傳 %s (%.2f MB)", file_name, file_size / 1024 / 1024)
        
        try:
            if file_size <= LARGE_FILE_THRESHOLD:
                url = f"{self.base_url}{self.site}/_api/web/GetFolderByServerRelativeUrl('{encoded_folder_url}')/Files/Add(url='{encoded_filename}', overwrite=true)"
                headers["binaryStringRequestBody"] = "true" 
                with open(local_path, 'rb') as f:
                    response = self.session.post(url, headers=headers, data=f)
                    self.session.raise_for_status(response)
                if callback: callback(file_size, file_size)
                else:
                    logger.info("OneDrive Business 上傳完成: %s", file_name)
            else:
                if not callback:
                    logger.info("檔案超過 250MB，啟動分片上傳: %s", file_name)
                create_url = f"{self.base_url}{self.site}/_api/web/GetFolderByServerRelativeUrl('{encoded_folder_url}')/Files/Add(url='{encoded_filename}', overwrite=true)"
                response = self.session.post(create_url, headers=headers, data=b'')
                self.session.raise_for_status(response)

                upload_id = str(uuid.uuid4())
                encoded_full_path = quote(f"{server_relative_folder}/{file_name}".replace("'", "''"))
                file_endpoint = f"{self.base_url}{self.site}/_api/web/GetFileByServerRelativeUrl('{encoded_full_path}')"
                
                chunk_size = 50 * 1024 * 1024  
                offset = 0
                
                with open(local_path, 'rb') as f:
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk: break
                        
                        is_first_chunk = (offset == 0)
                        is_last_chunk = (offset + len(chunk) >= file_size)
                        
                        if is_first_chunk: chunk_url = f"{file_endpoint}/StartUpload(uploadId=guid'{upload_id}')"
                        elif is_last_chunk: chunk_url = f"{file_endpoint}/FinishUpload(uploadId=guid'{upload_id}', fileOffset={offset})"
                        else: chunk_url = f"{file_endpoint}/ContinueUpload(uploadId=guid'{upload_id}', fileOffset={offset})"

                        response = self.session.post(
                            chunk_url,
                            headers=headers,
                            data=chunk,
                            retry=True,
                        )
                        self.session.raise_for_status(response, context="上傳 OneDrive Business 分片")
                                
                        offset += len(chunk)
                        if callback: callback(offset, file_size)
                        else:
                            logger.debug("OneDrive Business 上傳進度 %.1f%% (%d/%d bytes)", min(offset / file_size * 100, 100), offset, file_size)
                if not callback:
                    logger.info("OneDrive Business 分片上傳完成: %s", file_name)
                
            return True
        except HttpStatusError as e:
            if not callback:
                if e.http_response.status_code == 404:
                    logger.error("上傳失敗: 目標資料夾不存在")
                elif e.http_response.status_code == 423:
                    logger.error("上傳失敗: 檔案被鎖定 (Locked)")
                else:
                    logger.error("OneDrive Business API 錯誤: %s - %s", e.http_response.status_code, e.http_response.text)
            raise ValueError(f"上傳過程發生錯誤: {e}") from e

    def get_share_link(self, remote_path: str) -> str:
        metadata, _ = self._get_v2_metadata(remote_path)
        download_url = metadata.get('@content.downloadUrl')
        if not download_url:
            raise ValueError("無法取得檔案下載連結，該路徑可能是一個資料夾或無權限。")
        if not isinstance(download_url, str):
            raise ValueError("OneDrive Business download link 回應格式無效。")
        return download_url

    def get_download_link(self, remote_path: str) -> str:
        return self.get_share_link(remote_path)
    
    def download(self, remote_path: str, local_path: str, recursive: bool = False, callback: ProgressCallback | None = None) -> bool:
        parts = [p for p in remote_path.strip("/").split("/") if p]
        if not parts: raise ValueError("遠端路徑不可為空。")
            
        file_relative_path = "/".join(parts[1:])
        headers = self._get_headers()
        headers.update({
            "Accept": "application/json;odata.metadata=minimal",
            "User-Agent": "Mozilla/5.0",
            "Sec-Fetch-User": "?1"
        })

        metadata, item_api_url = self._get_v2_metadata(remote_path)
        item_name = metadata.get('name', 'downloaded_item')
        final_local_path = os.path.join(local_path, item_name) if os.path.isdir(local_path) else local_path

        if "folder" in metadata:
            if not recursive: raise IsADirectoryError(f"{remote_path} 是一個資料夾")
            os.makedirs(final_local_path, exist_ok=True)
            children_url = f"{item_api_url}:/children" if file_relative_path else f"{item_api_url}/children"
            
            while children_url:
                resp = self.session.get(children_url, headers=headers)
                self.session.raise_for_status(resp)
                children_data = resp.json()
                for child in children_data.get('value', []):
                    child_remote = f"{remote_path}/{child['name']}".replace("//", "/")
                    self.download(child_remote, final_local_path, recursive=True, callback=callback)
                children_url = children_data.get('@odata.nextLink')
            return True

        elif "file" in metadata:
            download_url = metadata.get('@content.downloadUrl')
            if not download_url: raise ValueError(f"無法取得檔案下載連結: {item_name}")
                
            expected_size = metadata.get('size', 0)
            if not callback:
                logger.info("開始下載: %s", item_name)
            os.makedirs(os.path.dirname(os.path.abspath(final_local_path)), exist_ok=True)
            
            with self.session.get(download_url, stream=True) as r:
                self.session.raise_for_status(r)
                total_size = int(r.headers.get('content-length', expected_size))
                downloaded_size = 0
                with open(final_local_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk: 
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            if callback: callback(downloaded_size, total_size)
                            else:
                                if total_size > 0:
                                    percent = min((downloaded_size / total_size) * 100, 100)
                                    logger.debug("OneDrive Business 下載進度 %.1f%% (%d/%d bytes)", percent, downloaded_size, total_size)
                                else:
                                    logger.debug("OneDrive Business 已下載 %d bytes", downloaded_size)
                                
            if not callback:
                logger.info("OneDrive Business 下載完成: %s", item_name)
            return True
        else:
            raise ValueError(f"未知的項目類型: {item_name}")

    def delete(self, remote_path: str, permanent: bool = False) -> bool:
        try:
            metadata, _ = self._get_v2_metadata(remote_path)
            is_folder = "folder" in metadata
        except ValueError as e:
            if "找不到" in str(e) or "404" in str(e): return False  
            raise

        self._ensure_site_resolved()
        digest_value = self._get_request_digest()
        headers = self._get_headers()
        headers["X-RequestDigest"] = digest_value

        clean_path = "/" + remote_path.strip("/") if remote_path else ""
        server_relative_path = f"{self.site}{clean_path}"
        encoded_path = quote(server_relative_path.replace("'", "''"))
        endpoint = f"GetFolderByServerRelativeUrl('{encoded_path}')" if is_folder else f"GetFileByServerRelativeUrl('{encoded_path}')"

        if permanent:
            url = f"{self.base_url}{self.site}/_api/web/{endpoint}"
            headers["X-HTTP-Method"] = "DELETE"
        else:
            url = f"{self.base_url}{self.site}/_api/web/{endpoint}/recycle"

        try:
            response = self.session.post(url, headers=headers)
            self.session.raise_for_status(response)
            return True
        except HttpStatusError as e:
            if e.http_response.status_code == 404: return False
            raise ValueError(f"刪除失敗: {e.http_response.status_code} - {e.http_response.text}") from e
        
    def copy(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        try:
            metadata, _ = self._get_v2_metadata(source_path)
            is_folder = "folder" in metadata
        except ValueError as e: raise ValueError(f"複製失敗，來源不存在: {e}")

        self._ensure_site_resolved()
        digest_value = self._get_request_digest()
        headers = self._get_headers()
        headers["X-RequestDigest"] = digest_value

        clean_src = "/" + source_path.strip("/")
        clean_dest = "/" + dest_path.strip("/")
        server_relative_src = f"{self.site}{clean_src}"
        server_relative_dest = f"{self.site}{clean_dest}"

        encoded_src = quote(server_relative_src.replace("'", "''"))
        encoded_dest = quote(server_relative_dest.replace("'", "''"))
        overwrite_str = "true" if overwrite else "false"
        endpoint = f"GetFolderByServerRelativeUrl('{encoded_src}')/CopyTo(strNewUrl='{encoded_dest}')" if is_folder else f"GetFileByServerRelativeUrl('{encoded_src}')/CopyTo(strNewUrl='{encoded_dest}', bOverWrite={overwrite_str})"

        url = f"{self.base_url}{self.site}/_api/web/{endpoint}"
        try:
            response = self.session.post(url, headers=headers)
            self.session.raise_for_status(response)
            return True
        except HttpStatusError as e:
            if "-2130575257" in e.http_response.text: raise ValueError(f"複製失敗: 目標路徑可能已存在 ({dest_path})")
            raise ValueError(f"API 請求失敗: {e.http_response.status_code} - {e.http_response.text}")
        
    def move(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        try:
            metadata, _ = self._get_v2_metadata(source_path)
            is_folder = "folder" in metadata
        except ValueError as e: raise ValueError(f"移動失敗，來源不存在: {e}")

        self._ensure_site_resolved()
        digest_value = self._get_request_digest()
        headers = self._get_headers()
        headers["X-RequestDigest"] = digest_value

        clean_src = "/" + source_path.strip("/")
        clean_dest = "/" + dest_path.strip("/")
        server_relative_src = f"{self.site}{clean_src}"
        server_relative_dest = f"{self.site}{clean_dest}"

        encoded_src = quote(server_relative_src.replace("'", "''"))
        encoded_dest = quote(server_relative_dest.replace("'", "''"))
        flags = 1 if overwrite else 0
        endpoint = f"GetFolderByServerRelativeUrl('{encoded_src}')/MoveTo(newUrl='{encoded_dest}')" if is_folder else f"GetFileByServerRelativeUrl('{encoded_src}')/MoveTo(newUrl='{encoded_dest}', flags={flags})"

        url = f"{self.base_url}{self.site}/_api/web/{endpoint}"
        try:
            response = self.session.post(url, headers=headers)
            self.session.raise_for_status(response)
            return True
        except HttpStatusError as e:
            if "-2130575257" in e.http_response.text: raise ValueError(f"移動失敗: 目標路徑可能已存在 ({dest_path})")
            raise ValueError(f"API 請求失敗: {e.http_response.status_code} - {e.http_response.text}")
    
    def stat(self, remote_path: str) -> StorageStat:
        clean_path = remote_path.strip("/")
        if not clean_path:
            self._init_drives_cache()
            drive_id = self._drive_id_cache.get("Documents") or self._drive_id_cache.get("Shared Documents")
            if not drive_id and self._drive_id_cache: drive_id = list(self._drive_id_cache.values())[0]
            if not drive_id: raise ValueError("找不到可用的文件庫來查詢容量。")
                
            self._ensure_site_resolved()
            headers = self._get_headers()
            headers.update({"Accept": "application/json;odata.metadata=minimal", "User-Agent": "Mozilla/5.0", "Sec-Fetch-User": "?1"})
            api_url = f"{self.base_url}/_api/v2.0/drives/{drive_id}"
            
            try:
                response = self.session.get(api_url, headers=headers)
                self.session.raise_for_status(response)
                data = response.json()
                quota = data.get("quota", {})
                return {
                    "type": "remote", "name": data.get("name", "Unknown Drive"), "total": quota.get("total", 0),
                    "used": quota.get("used", 0), "filecount": quota.get("fileCount", 0),
                    "created": data.get("createdDateTime"), "modified": data.get("lastModifiedDateTime"),
                }
            except HttpStatusError as e:
                raise ValueError(f"無法取得節點容量資訊: {e.http_response.status_code}") from e

        try:
            metadata, _ = self._get_v2_metadata(remote_path)
        except ValueError as e: raise ValueError(f"無法取得狀態，目標不存在或無權限: {e}")

        item_type: Literal["folder", "file"] = "folder" if "folder" in metadata else "file"
        fs_info = metadata.get("fileSystemInfo", {})
        return {
            "type": item_type, "name": metadata.get("name", "Unknown"), "size": metadata.get("size", 0),
            "created": fs_info.get("createdDateTime") or metadata.get("createdDateTime"),
            "modified": fs_info.get("lastModifiedDateTime") or metadata.get("lastModifiedDateTime")
        }

    def get_thumbnail_link(self, remote_path: str) -> str:
        metadata, item_api_url = self._get_v2_metadata(remote_path)
        if "folder" in metadata:
            raise ValueError("無法為資料夾產生縮圖。")
        headers = self._get_headers({"Accept": "application/json;odata.metadata=minimal"})
        try:
            resp = self.session.get(f"{item_api_url}:/thumbnails", headers=headers)
            if resp.status_code in (400, 404):
                raise ValueError(f"此檔案無可用縮圖: {remote_path}")
            self.session.raise_for_status(resp)
            data = resp.json()
            values = data.get("value", [])
            if values and isinstance(values, list):
                thumb = values[0]
                for size_key in ("medium", "large", "small"):
                    if (
                        size_key in thumb
                        and isinstance(thumb[size_key], dict)
                        and "url" in thumb[size_key]
                    ):
                        return str(thumb[size_key]["url"])
        except HttpStatusError as e:
            if e.http_response.status_code in (400, 404):
                raise ValueError(f"此檔案無可用縮圖: {remote_path}") from e
            raise
        raise ValueError(f"Microsoft 365 未提供此檔案之縮圖: {remote_path}")
    
    def get_hash(self, remote_path: str, algo: str) -> str:
        try:
            metadata, _ = self._get_v2_metadata(remote_path)
        except ValueError as e: raise ValueError(f"無法存取檔案: {e}")
        if "folder" in metadata: raise ValueError("無法對資料夾計算雜湊值。")

        hashes = metadata.get("file", {}).get("hashes", {})
        algo_lower = algo.lower()
        hash_map = {"quickxorhash": hashes.get("quickXorHash"), "sha1": hashes.get("sha1Hash"), "sha256": hashes.get("sha256Hash"), "md5": hashes.get("md5Hash")}
        
        target_hash = hash_map.get(algo_lower)
        if not target_hash:
            available = [k for k, v in hash_map.items() if v is not None]
            raise ValueError(f"遠端伺服器未提供 '{algo}' 的雜湊值。(目前該檔案可用: {', '.join(available) if available else '無'})")
        if not isinstance(target_hash, str):
            raise ValueError(f"遠端 '{algo}' 雜湊值格式無效。")
        return target_hash