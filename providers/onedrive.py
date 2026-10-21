import os
import posixpath
import time
from urllib.parse import quote
from collections.abc import Mapping
from datetime import datetime

from infrastructure.http import HttpClient, HttpStatusError
from storage.base import DeleteCapability, FileItem, ProgressCallback, StorageProvider, StorageStat
from auth.base import AuthProvider

class OneDriveStorage(StorageProvider):
    delete_capability = DeleteCapability.TRASH_ONLY
    def __init__(self, auth_provider: AuthProvider):
        self.auth_provider = auth_provider
        self.session = HttpClient()
        self.base_url = "https://graph.microsoft.com/v1.0/me/drive"

    def close(self) -> None:
        self.session.close()

    def _get_headers(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        ctx = self.auth_provider.get_auth_context()
        headers = {"Content-Type": "application/json"}
        authorization = ctx.headers.get("Authorization")
        if authorization:
            headers["Authorization"] = authorization
        if extra:
            headers.update(extra)
        return headers

    def _get_item_url(self, remote_path: str, suffix: str = "") -> str:
        """安全組裝 Graph API 的 Item 存取網址"""
        clean_path = remote_path.strip("/")
        if not clean_path:
            root_suffix = suffix.lstrip(":") if suffix.startswith(":/") else suffix
            return f"{self.base_url}/root{root_suffix}"

        encoded_path = quote(clean_path)
        if not suffix:
            return f"{self.base_url}/root:/{encoded_path}"

        if suffix.startswith("?"):
            return f"{self.base_url}/root:/{encoded_path}{suffix}"

        if suffix.startswith(":"):
            return f"{self.base_url}/root:/{encoded_path}{suffix}"

        sub_action = suffix.lstrip("/")
        return f"{self.base_url}/root:/{encoded_path}:/{sub_action}"

    def _get_item_id(self, remote_path: str) -> str:
        """查詢檔案或資料夾的唯一 ID (供 Copy / Move 使用)"""
        url = self._get_item_url(remote_path, suffix="?$select=id")
        resp = self.session.get(url, headers=self._get_headers())
        self.session.raise_for_status(resp)
        item_id = resp.json().get("id")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError(f"OneDrive item ID 回應格式無效: {remote_path}")
        return item_id

    def list_dir(self, remote_path: str) -> list[FileItem]:
        # $top=999 最大化單次請求量，降低翻頁次數
        url = self._get_item_url(remote_path, suffix=":/children?$top=999")
            
        headers = self._get_headers()
        items = []
        
        try:
            while url:
                resp = self.session.get(url, headers=headers)
                self.session.raise_for_status(resp)
                data = resp.json()
                
                for item in data.get("value", []):
                    is_dir = "folder" in item
                    mod_time_str = item.get("fileSystemInfo", {}).get("lastModifiedDateTime")
                    mod_time = datetime.fromisoformat(mod_time_str.replace("Z", "+00:00")) if mod_time_str else None
                    
                    clean_remote = remote_path.rstrip('/')
                    item_path = f"{clean_remote}/{item['name']}"
                    
                    thumb_url = None
                    thumbs = item.get("thumbnails", [])
                    if thumbs and isinstance(thumbs, list):
                        t_item = thumbs[0]
                        for sk in ("medium", "large", "small"):
                            if sk in t_item and isinstance(t_item[sk], dict) and "url" in t_item[sk]:
                                thumb_url = t_item[sk]["url"]
                                break

                    items.append(FileItem(
                        name=item['name'],
                        path=item_path.replace("//", "/"),
                        is_dir=is_dir,
                        size=item.get("size", 0) if not is_dir else 0,
                        modified_at=mod_time,
                        thumbnail_url=thumb_url if not is_dir else None,
                    ))
                url = data.get("@odata.nextLink")
            return items
        except HttpStatusError as e:
            if e.http_response.status_code == 404:
                # 可能是單一檔案，降級查詢
                stat_info = self.stat(remote_path)
                if stat_info["type"] == "file":
                    modified = stat_info.get("modified")
                    return [FileItem(
                        name=stat_info["name"], path=remote_path, is_dir=False,
                        size=stat_info["size"],
                        modified_at=modified if isinstance(modified, datetime) else None,
                    )]
            error_text = e.http_response.text
            if "Tenant does not have a SPO license" in error_text:
                error_text += (
                    " (診斷：微軟回報租用戶無 SharePoint Online (SPO) 授權。"
                    "若使用的是個人微軟帳號，請將 Remote 設定的 tenant 設為 'common' 或 'consumers'，切勿指定特定組織租用戶 ID)"
                )
            raise ValueError(f"讀取目錄失敗: {e.http_response.status_code} - {error_text}")

    def mkdir(self, remote_path: str, parents: bool = False) -> bool:
        clean_path = remote_path.strip("/")
        if not clean_path:
            raise ValueError("資料夾路徑不可為空。")
            
        parts = clean_path.split("/")
        headers = self._get_headers()
        
        current_path = ""
        for i, part in enumerate(parts):
            if current_path:
                url = self._get_item_url(current_path, suffix=":/children")
            else:
                url = f"{self.base_url}/root/children"
                
            payload = {
                "name": part,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "fail"
            }
            
            resp = self.session.post(url, headers=headers, json=payload)
            if resp.status_code == 409:
                # 已存在
                if not parents and i == len(parts) - 1:
                    raise ValueError(f"建立失敗: 目標資料夾已存在 '{part}'")
            elif resp.status_code not in (200, 201):
                if not parents and i < len(parts) - 1:
                    raise ValueError(f"父目錄不存在，請加上 -p 參數。")
                self.session.raise_for_status(resp)
                
            current_path = posixpath.join(current_path, part)
            
        return True

    def upload(self, local_path: str, remote_path: str, callback: ProgressCallback | None = None) -> bool:
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"找不到本機檔案: {local_path}")
            
        file_size = os.path.getsize(local_path)
        remote_folder, file_name = posixpath.split(remote_path)
        if not file_name:
            file_name = os.path.basename(local_path)
            
        target_path = posixpath.join(remote_folder, file_name).replace("//", "/")
        headers = self._get_headers()
        
        try:
            if file_size <= 4 * 1024 * 1024:
                # 簡單上傳 (< 4MB)
                url = self._get_item_url(target_path, suffix=":/content")
                with open(local_path, "rb") as f:
                    resp = self.session.put(url, headers=headers, data=f)
                    self.session.raise_for_status(resp)
                if callback: callback(file_size, file_size)
            else:
                # 分片斷點續傳 (> 4MB)
                session_url = self._get_item_url(target_path, suffix=":/createUploadSession")
                payload = {"item": {"@microsoft.graph.conflictBehavior": "replace"}}
                resp = self.session.post(session_url, headers=headers, json=payload)
                self.session.raise_for_status(resp)
                upload_url = resp.json()["uploadUrl"]
                
                # 分片大小必須為 320 KB 的倍數，我們使用 ~3.2 MB
                chunk_size = 327680 * 10 
                offset = 0
                
                with open(local_path, "rb") as f:
                    while offset < file_size:
                        chunk = f.read(chunk_size)
                        if not chunk: break
                        
                        chunk_len = len(chunk)
                        chunk_headers = {
                            "Content-Length": str(chunk_len),
                            "Content-Range": f"bytes {offset}-{offset + chunk_len - 1}/{file_size}"
                        }
                        
                        put_resp = self.session.put(upload_url, headers=chunk_headers, data=chunk, retry=False)
                        self.session.raise_for_status(put_resp)
                        
                        offset += chunk_len
                        if callback: callback(offset, file_size)
                        
            return True
        except HttpStatusError as e:
            raise ValueError(f"上傳失敗: {e.http_response.status_code} - {e.http_response.text}")

    def download(self, remote_path: str, local_path: str, recursive: bool = False, callback: ProgressCallback | None = None) -> bool:
        url = self._get_item_url(remote_path)
        resp = self.session.get(url, headers=self._get_headers())
        self.session.raise_for_status(resp)
        metadata = resp.json()
        
        item_name = metadata.get("name", "downloaded_item")
        final_local_path = os.path.join(local_path, item_name) if os.path.isdir(local_path) else local_path
        
        if "folder" in metadata:
            if not recursive:
                raise IsADirectoryError(f"{remote_path} 是一個資料夾")
            os.makedirs(final_local_path, exist_ok=True)
            for child in self.list_dir(remote_path):
                self.download(child.path, final_local_path, recursive=True, callback=callback)
            return True
        else:
            download_url = metadata.get("@microsoft.graph.downloadUrl")
            if not download_url:
                raise ValueError("無法取得下載網址")
                
            total_size = metadata.get("size", 0)
            downloaded = 0
            
            os.makedirs(os.path.dirname(os.path.abspath(final_local_path)), exist_ok=True)
            
            with self.session.get(download_url, stream=True) as r:
                self.session.raise_for_status(r)
                with open(final_local_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if callback: callback(downloaded, total_size)
            return True

    def delete(self, remote_path: str, permanent: bool = False) -> bool:
        self.validate_delete_request(permanent=permanent)
        url = self._get_item_url(remote_path)
        resp = self.session.delete(url, headers=self._get_headers())
        if resp.status_code == 404:
            return False
        self.session.raise_for_status(resp)
        return True

    def copy(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        dest_parent, dest_name = posixpath.split(dest_path)
        dest_parent_id = self._get_item_id(dest_parent)
        
        url = self._get_item_url(source_path, suffix=":/copy")
        payload = {
            "parentReference": {"id": dest_parent_id},
            "name": dest_name
        }
        
        resp = self.session.post(url, headers=self._get_headers(), json=payload)
        self.session.raise_for_status(resp)
        
        # Graph API 的 Copy 是非同步的，需要 polling 監聽進度
        monitor_url = resp.headers.get("Location")
        if monitor_url:
            while True:
                status_resp = self.session.get(monitor_url)
                self.session.raise_for_status(status_resp)
                status = status_resp.json().get("status")
                if status in ("completed", "failed"):
                    if status == "failed":
                        raise ValueError(f"伺服器非同步複製失敗: {status_resp.text}")
                    break
                time.sleep(1)
        return True

    def move(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        dest_parent, dest_name = posixpath.split(dest_path)
        dest_parent_id = self._get_item_id(dest_parent)
        
        url = self._get_item_url(source_path)
        payload = {
            "parentReference": {"id": dest_parent_id},
            "name": dest_name,
            "@microsoft.graph.conflictBehavior": "replace" if overwrite else "fail"
        }
        
        resp = self.session.patch(url, headers=self._get_headers(), json=payload)
        self.session.raise_for_status(resp)
        return True

    def stat(self, remote_path: str) -> StorageStat:
        if not remote_path.strip("/"):
            resp = self.session.get(self.base_url, headers=self._get_headers())
            self.session.raise_for_status(resp)
            data = resp.json()
            quota = data.get("quota", {})
            return {
                "type": "remote",
                "name": data.get("owner", {}).get("user", {}).get("displayName", "OneDrive"),
                "total": quota.get("total", 0),
                "used": quota.get("used", 0),
                "filecount": -1,
                "created": None,
                "modified": None
            }
            
        url = self._get_item_url(remote_path)
        resp = self.session.get(url, headers=self._get_headers())
        if resp.status_code == 404:
            raise ValueError(f"目標不存在: {remote_path}")
        self.session.raise_for_status(resp)
        
        data = resp.json()
        is_folder = "folder" in data
        mod_str = data.get("fileSystemInfo", {}).get("lastModifiedDateTime")
        
        return {
            "type": "folder" if is_folder else "file",
            "name": data.get("name"),
            "size": data.get("size", 0),
            "created": None,
            "modified": datetime.fromisoformat(mod_str.replace("Z", "+00:00")) if mod_str else None
        }

    def get_share_link(self, remote_path: str) -> str:
        url = self._get_item_url(remote_path, suffix=":/createLink")
        payload = {"type": "view", "scope": "anonymous"}
        resp = self.session.post(url, headers=self._get_headers(), json=payload)
        self.session.raise_for_status(resp)
        link = resp.json().get("link", {}).get("webUrl", "")
        if not isinstance(link, str):
            raise ValueError("OneDrive share link 回應格式無效。")
        return link

    def get_download_link(self, remote_path: str) -> str:
        url = self._get_item_url(remote_path)
        resp = self.session.get(url, headers=self._get_headers())
        self.session.raise_for_status(resp)
        link = resp.json().get("@microsoft.graph.downloadUrl", "")
        if not isinstance(link, str):
            raise ValueError("OneDrive download link 回應格式無效。")
        return link

    def get_thumbnail_link(self, remote_path: str) -> str:
        clean_path = remote_path.strip("/")
        if not clean_path:
            raise ValueError("無法為根目錄產生縮圖。")

        url = self._get_item_url(remote_path, suffix=":/thumbnails")
        try:
            resp = self.session.get(url, headers=self._get_headers())
            if resp.status_code in (400, 404):
                raise ValueError(f"OneDrive 目標不存在或無縮圖: {remote_path}")
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
                        return thumb[size_key]["url"]
        except HttpStatusError as e:
            if e.http_response.status_code in (400, 404):
                raise ValueError(f"OneDrive 目標不存在或無縮圖: {remote_path}") from e
            raise
        raise ValueError(f"OneDrive 未提供此檔案之縮圖: {remote_path}")

    def get_hash(self, remote_path: str, algo: str) -> str:
        url = self._get_item_url(remote_path)
        resp = self.session.get(url, headers=self._get_headers())
        self.session.raise_for_status(resp)
        
        data = resp.json()
        if "folder" in data:
            raise ValueError("無法對資料夾計算雜湊值。")
            
        hashes = data.get("file", {}).get("hashes", {})
        algo_lower = algo.lower()
        
        hash_map = {
            "quickxorhash": hashes.get("quickXorHash"),
            "sha1": hashes.get("sha1Hash"),
            "sha256": hashes.get("sha256Hash")
        }
        
        target = hash_map.get(algo_lower)
        if not target:
            av = [k for k, v in hash_map.items() if v]
            raise ValueError(f"OneDrive 未提供 '{algo}' 的雜湊值。(目前該檔案可用: {', '.join(av) if av else '無'})")
        if not isinstance(target, str):
            raise ValueError(f"OneDrive '{algo}' 雜湊值格式無效。")
        return target

    def search(self, remote_path: str, query: str) -> list:
        # OneDrive 搜尋 API: /me/drive/root/search(q='...')
        encoded_query = quote(query.replace("'", "''"))
        url = f"{self.base_url}/root/search(q='{encoded_query}')?$top=200"
        
        headers = self._get_headers()
        items = []
        
        try:
            while url:
                resp = self.session.get(url, headers=headers)
                self.session.raise_for_status(resp)
                data = resp.json()
                
                for item in data.get("value", []):
                    is_dir = "folder" in item
                    mod_str = item.get("fileSystemInfo", {}).get("lastModifiedDateTime")
                    mod_time = datetime.fromisoformat(mod_str.replace("Z", "+00:00")) if mod_str else None
                    
                    # 取得完整的絕對路徑
                    parent_path = item.get("parentReference", {}).get("path", "")
                    if "root:" in parent_path:
                        from urllib.parse import unquote
                        parent_path = unquote(parent_path.split("root:")[-1])
                        
                    full_path = posixpath.join(parent_path, item["name"]).replace("//", "/")
                    
                    items.append(FileItem(
                        name=item['name'], path=full_path, is_dir=is_dir,
                        size=item.get("size", 0) if not is_dir else 0, modified_at=mod_time
                    ))
                url = data.get("@odata.nextLink")
            return items
        except HttpStatusError as e:
            raise ValueError(f"伺服器端搜尋失敗: {e.http_response.status_code} - {e.http_response.text}")