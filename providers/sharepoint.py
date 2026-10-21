# providers/sharepoint.py
import os
import posixpath
import uuid
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import quote
from datetime import datetime, timezone

from storage.base import DeleteCapability, FileItem, ProgressCallback, StorageProvider, StorageStat
from auth.base import AuthProvider
from providers.microsoft365.client import Microsoft365Client
from core.logging import get_logger
from infrastructure.http import HttpStatusError


logger = get_logger("providers.sharepoint")

class SharePointStorage(StorageProvider):
    delete_capability = DeleteCapability.TRASH_AND_PERMANENT
    def __init__(self, auth_provider: AuthProvider, base_url: str, site: str):
        self.auth_provider = auth_provider
        self.base_url = base_url.rstrip("/")
        self.site = "/" + site.strip("/") if site else ""
        self.client = Microsoft365Client(
            auth_provider=auth_provider,
            base_url=self.base_url,
            site=self.site,
        )
        self.session = self.client.http
        self._drive_id_cache: dict[str, str] = {}

    def close(self) -> None:
        self.client.close()

    def _get_headers(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        """Return authentication-aware headers from the shared Microsoft client."""
        return self.client.get_headers(extra=extra)

    def _init_drives_cache(self) -> None:
        self.client.init_drives_cache()
        cache = self.client.drive_id_cache
        if cache is None:
            raise RuntimeError("SharePoint drive cache 初始化失敗。")
        self._drive_id_cache = cache

    def _get_v2_metadata(self, remote_path: str) -> tuple[dict[str, Any], str]:
        return self.client.get_v2_metadata(
            remote_path,
            library_aliases=("Shared Documents", "Documents"),
        )

    def _get_request_digest(self) -> str:
        return self.client.get_request_digest()

    def list_dir(self, remote_path: str) -> list[FileItem]:
        """
        列出指定目錄下的所有檔案與資料夾。
        使用 v2 API 解決超過 5000 個項目的 List View Threshold (LVT) 問題，
        並支援大資料夾的自動分頁載入與 5xx 伺服器錯誤指數退避重試機制。
        """
        from datetime import datetime
        import time  # 確保引入 time 以支援重試延遲
        
        # ==========================================
        # 💡 新增：攔截根目錄請求，自動列出所有文件庫 (Drives)
        # ==========================================
        clean_path = remote_path.strip("/")
        if not clean_path:
            logger.info("正在自動獲取 SharePoint 文件庫清單")
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
                    modified_dt = None
                    if time_str:
                        modified_dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                    from urllib.parse import unquote
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

        # ==========================================
        # 處理進入文件庫後的查詢
        # ==========================================

        # 1. 取得目標資料夾的 metadata 與 API URL
        try:
            metadata, item_api_url = self._get_v2_metadata(remote_path)
        except ValueError as e:
            raise ValueError(f"讀取路徑失敗: {e}")

        # 如果使用者輸入的是單一檔案路徑 (Fallback 機制)
        if "folder" not in metadata:
            time_str = metadata.get("fileSystemInfo", {}).get("lastModifiedDateTime")
            modified_dt = None
            if time_str:
                modified_dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                
            return [FileItem(
                name=metadata.get("name", "Unknown"),
                path=remote_path,
                is_dir=False,
                size=metadata.get("size", 0),
                modified_at=modified_dt
            )]

        # 2. 準備 v2 專屬 Headers
        headers = self._get_headers()
        headers.update({
            "Accept": "application/json;odata.metadata=minimal",
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0"),
            "Sec-Fetch-User": "?1"
        })

        # 3. 組合分頁請求網址 (設定每次拿 200 筆，避免超時)
        if item_api_url.endswith("/root"):
            children_url = f"{item_api_url}/children?$top=200"
        else:
            children_url = f"{item_api_url}:/children?$top=1000"

        items = []

        # HttpClient 已統一處理 429/5xx 與 transient network retry。
        while children_url:
            response = self.session.get(children_url, headers=headers)
            self.session.raise_for_status(response, context="讀取 SharePoint 資料夾內容")
            data = response.json()

            # 5. 解析這頁的項目
            for item in data.get('value', []):
                is_dir = "folder" in item
                
                time_str = item.get("fileSystemInfo", {}).get("lastModifiedDateTime")
                modified_dt = None
                if time_str:
                    modified_dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))

                clean_remote = remote_path.rstrip('/')
                item_path = f"{clean_remote}/{item['name']}"

                items.append(FileItem(
                    name=item.get("name", "Unknown"),
                    path=item_path,
                    is_dir=is_dir,
                    size=item.get("size", 0) if not is_dir else 0,
                    modified_at=modified_dt
                ))
            
            # 即時更新進度條 (確保加入 flush=True，讓畫面正確渲染)
            logger.debug("SharePoint 已載入 %d 筆項目", len(items))
            
            # 取得下一頁的連結，如果沒有了就代表全數載入完畢
            children_url = data.get('@odata.nextLink')

        # 清除動態進度條
        logger.debug("SharePoint 清單載入完成，共 %d 筆", len(items))
        return items

    def list_dir_old(self, remote_path: str) -> list[FileItem]:
        """
        列出指定目錄下的所有檔案與資料夾。
        若指定的路徑是一個檔案，則回傳僅包含該檔案的清單。
        """
        headers = self._get_headers()
        clean_path = "/" + remote_path.strip("/") if remote_path else ""
        server_relative_url = f"{self.site}{clean_path}"
        encoded_url = quote(server_relative_url.replace("'", "''"))
        
        # 定義時間解析工具
        def parse_sp_time(time_str: str):
            if not time_str:
                return None
            try:
                clean_str = time_str.replace("Z", "+00:00")
                return datetime.fromisoformat(clean_str)
            except ValueError:
                return None

        # 1. 先嘗試當作「資料夾」來讀取
        folder_api_url = f"{self.base_url}{self.site}/_api/web/GetFolderByServerRelativeUrl('{encoded_url}')?$expand=Files,Folders"
        
        try:
            response = self.session.get(folder_api_url, headers=headers)
            self.session.raise_for_status(response) 
            
            data = response.json()
            items = []
            
            # 解析資料夾 (Folders)
            folders = data.get('d', {}).get('Folders', {}).get('results', [])
            for folder in folders:
                items.append(FileItem(
                    name=folder.get('Name', 'Unknown'),
                    path=folder.get('ServerRelativeUrl', ''),
                    is_dir=True,
                    size=0,
                    modified_at=parse_sp_time(folder.get('TimeLastModified'))
                ))
                
            # 解析檔案 (Files)
            files = data.get('d', {}).get('Files', {}).get('results', [])
            for file in files:
                items.append(FileItem(
                    name=file.get('Name', 'Unknown'),
                    path=file.get('ServerRelativeUrl', ''),
                    is_dir=False,
                    size=int(file.get('Length', 0)),
                    modified_at=parse_sp_time(file.get('TimeLastModified'))
                ))
                
            return items
            
        except HttpStatusError as e:
            # 2. 如果回傳 404，代表可能不是資料夾，我們降級嘗試當作「單一檔案」來讀取
            if e.http_response.status_code == 404:
                file_api_url = f"{self.base_url}{self.site}/_api/web/GetFileByServerRelativeUrl('{encoded_url}')"
                try:
                    file_response = self.session.get(file_api_url, headers=headers)
                    self.session.raise_for_status(file_response)
                    
                    # 成功取得單一檔案資訊
                    file_data = file_response.json().get('d', {})
                    return [FileItem(
                        name=file_data.get('Name', 'Unknown'),
                        path=file_data.get('ServerRelativeUrl', ''),
                        is_dir=False,
                        size=int(file_data.get('Length', 0)),
                        modified_at=parse_sp_time(file_data.get('TimeLastModified'))
                    )]
                except HttpStatusError as file_err:
                    # 如果當作檔案查也 404，或者發生其他錯誤，就拋出異常
                    raise ValueError(f"遠端路徑不存在或無權限: {remote_path}") from file_err
            
            # 如果不是 404 (例如 401 未授權, 500 伺服器錯誤)，則直接拋出原錯誤
            logger.error("SharePoint API 請求失敗，狀態碼: %s", e.http_response.status_code)
            logger.error("SharePoint API 回應: %s", e.http_response.text)
            raise

    def mkdir(self, remote_path: str, parents: bool = False) -> bool:
        """
        在 SharePoint 上建立新資料夾。支援遞迴建立 (-p)。
        """
        import posixpath
        from urllib.parse import quote
        
        cleaned_path = remote_path.strip("/")
        if not cleaned_path:
            raise ValueError("資料夾路徑不可為空。")
            
        digest_value = self._get_request_digest()
        headers = self._get_headers()
        headers["X-RequestDigest"] = digest_value
        
        if not parents:
            # === 單層建立邏輯 (預設) ===
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
                error_msg = e.http_response.text
                raise ValueError(f"建立資料夾失敗: {e.http_response.status_code} - {error_msg}\n(提示: 若父目錄不存在，請加上 -p 參數)") from e
                
        else:
            # === 遞迴建立邏輯 (類似 mkdir -p) ===
            parts = cleaned_path.split("/")
            if len(parts) < 2:
                 return True # 只有根文件庫名稱 (例如 Shared Documents) 則略過
                 
            current_parent = parts[0]
            
            # 從第二層開始，一層一層向下建立
            for folder_name in parts[1:]:
                clean_parent = "/" + current_parent
                server_relative_parent = f"{self.site}{clean_parent}"
                
                encoded_parent = quote(server_relative_parent.replace("'", "''"))
                encoded_folder = quote(folder_name.replace("'", "''"))
                
                url = f"{self.base_url}{self.site}/_api/web/GetFolderByServerRelativeUrl('{encoded_parent}')/folders/add(url='{encoded_folder}')"
                
                try:
                    response = self.session.post(url, headers=headers)
                    self.session.raise_for_status(response)
                except HttpStatusError as e:
                    error_msg = e.http_response.text
                    raise ValueError(f"建立中繼資料夾 '{folder_name}' 失敗: {e.http_response.status_code} - {error_msg}") from e
                    
                # 建立成功後，將當前資料夾變成下一層的父目錄
                current_parent = f"{current_parent}/{folder_name}"
                
            return True

    def search(self, remote_path: str, query: str) -> list:
        """
        使用 Graph API 進行伺服器端極速搜尋。支援自動分頁。
        """
        from urllib.parse import quote, unquote
        from datetime import datetime
        
        # --- (前面取得 API URL 與 Headers 的邏輯保持不變) ---
        try:
            _, item_api_url = self._get_v2_metadata(remote_path)
        except ValueError as e:
            raise ValueError(f"無法存取搜尋起點: {e}")

        headers = self._get_headers()
        headers.update({
            "Accept": "application/json;odata.metadata=minimal",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0",
            "Sec-Fetch-User": "?1"
        })

        encoded_query = quote(query.replace("'", "''"))
        
        if item_api_url.endswith("/root"):
            search_url = f"{item_api_url}/search(q='{encoded_query}')"
        else:
            search_url = f"{item_api_url}:/search(q='{encoded_query}')"

        items = []
        
        # 💡 從使用者的輸入路徑中，提取出當前的文件庫名稱 (例如 Shared Documents)
        parts = [p for p in remote_path.strip("/").split("/") if p]
        library_name = parts[0] if parts else ""

        try:
            while search_url:
                response = self.session.get(search_url, headers=headers)
                self.session.raise_for_status(response)
                data = response.json()

                for item in data.get('value', []):
                    is_dir = "folder" in item
                    
                    time_str = item.get("fileSystemInfo", {}).get("lastModifiedDateTime")
                    modified_dt = None
                    if time_str:
                        modified_dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))

                    # ==========================================
                    # 🛡️ 啟動三段式路徑解析防禦機制
                    # ==========================================
                    parent_path = ""
                    
                    # [防禦一] 標準情況：微軟乖乖給了 path
                    if 'parentReference' in item and 'path' in item['parentReference']:
                        raw_path = item['parentReference']['path']
                        if "root:" in raw_path:
                            parent_path = unquote(raw_path.split("root:")[-1])
                        elif "/root/" in raw_path:
                            parent_path = "/" + unquote(raw_path.split("/root/")[-1])

                    # [防禦二] webUrl 反推：適用於 webUrl 包含真實路徑的情況
                    if not parent_path and 'webUrl' in item and 'DispForm.aspx' not in item['webUrl']:
                        decoded_weburl = unquote(item['webUrl'])
                        search_target = f"/{library_name}/"
                        if search_target in decoded_weburl:
                            relative_to_lib = decoded_weburl.split(search_target, 1)[-1]
                            clean_relative = relative_to_lib.split("?")[0]
                            if clean_relative.endswith(item['name']):
                                extracted_path = clean_relative[:-len(item['name'])].strip("/")
                            else:
                                if "/" in clean_relative:
                                    extracted_path = clean_relative.rsplit("/", 1)[0].strip("/")
                                else:
                                    extracted_path = ""
                            if extracted_path:
                                parent_path = "/" + extracted_path

                    # [防禦三] 真・終極反查：當 webUrl 是 DispForm.aspx 時，直接用 ID 去查父資料夾！
                    if not parent_path and 'parentReference' in item:
                        pref = item['parentReference']
                        if 'driveId' in pref and 'id' in pref:
                            try:
                                # 利用 driveId 和 parentId 發起二次請求
                                parent_api_url = f"{self.base_url}/_api/v2.0/drives/{pref['driveId']}/items/{pref['id']}"
                                parent_resp = self.session.get(parent_api_url, headers=headers)
                                if parent_resp.status_code == 200:
                                    parent_data = parent_resp.json()
                                    # 拿到父資料夾的 path (例如 /drive/root:/相片) 和 name (街拍)
                                    p_raw_path = parent_data.get('parentReference', {}).get('path', '')
                                    p_name = parent_data.get('name', '')
                                    
                                    temp_path = ""
                                    if "root:" in p_raw_path:
                                        temp_path = unquote(p_raw_path.split("root:")[-1])
                                        
                                    # 組合起來就是完整的父目錄路徑！
                                    parent_path = f"{temp_path}/{p_name}".replace("//", "/")
                            except Exception:
                                # 如果連反查都失敗，就只能妥協保留空路徑
                                pass

                    # 確保路徑格式乾淨
                    if parent_path == "/":
                        parent_path = ""
                    elif parent_path and not parent_path.startswith("/"):
                        parent_path = "/" + parent_path
                    # ==========================================

                    # 💡 將提取出的 library_name 補在最前面，並結合剛剛解析出的 parent_path
                    item_full_path = f"/{library_name}{parent_path}/{item['name']}".replace("//", "/")

                    items.append(FileItem(
                        name=item.get("name", "Unknown"),
                        path=item_full_path,
                        is_dir=is_dir,
                        size=item.get("size", 0) if not is_dir else 0,
                        modified_at=modified_dt
                    ))

                search_url = data.get('@odata.nextLink')

            return items

        except HttpStatusError as e:
            error_msg = e.http_response.text
            raise ValueError(f"伺服器端搜尋失敗: {e.http_response.status_code} - {error_msg}")

    def upload(self, local_path: str, remote_path: str, callback: ProgressCallback | None = None) -> bool:
        """
        將本機檔案上傳至雲端指定路徑。支援 >250MB 大檔分片上傳。
        """
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"本機檔案不存在: {local_path}")
            
        file_size = os.path.getsize(local_path)
        
        # 1. 解析遠端目標資料夾與檔名
        # 例如 remote_path="/Shared Documents/docs/report.pdf" 
        # -> folder="/Shared Documents/docs", filename="report.pdf"
        remote_folder, file_name = posixpath.split(remote_path)
        
        # 如果使用者沒有指定檔名 (例如路徑以 / 結尾)，則使用本機檔名
        if not file_name:
            file_name = os.path.basename(local_path)
            
        clean_folder = "/" + remote_folder.strip("/") if remote_folder else ""
        server_relative_folder = f"{self.site}{clean_folder}"
        
        encoded_folder_url = quote(server_relative_folder.replace("'", "''"))
        encoded_filename = quote(file_name.replace("'", "''"))
        
        # 2. 準備 POST 請求必備的 Headers
        digest_value = self._get_request_digest()
        headers = self._get_headers()
        headers["X-RequestDigest"] = digest_value

        LARGE_FILE_THRESHOLD = 250 * 1024 * 1024  # 250MB 閾值
        
        if not callback:
            logger.info("開始上傳 %s (%.2f MB)", file_name, file_size / 1024 / 1024)
        
        try:
            # --- 策略 A: Simple Upload (< 250MB) ---
            if file_size <= LARGE_FILE_THRESHOLD:
                url = f"{self.base_url}{self.site}/_api/web/GetFolderByServerRelativeUrl('{encoded_folder_url}')/Files/Add(url='{encoded_filename}', overwrite=true)"
                # 小檔上傳需要標示二進位主體
                headers["binaryStringRequestBody"] = "true" 
                
                with open(local_path, 'rb') as f:
                    response = self.session.post(url, headers=headers, data=f, timeout=(10, 120))
                    self.session.raise_for_status(response)
                
                if callback:
                    callback(file_size, file_size)
                else:
                    logger.info("SharePoint 上傳完成: %s", file_name)
                
            # --- 策略 B: Chunked Upload (> 250MB) ---
            else:
                if not callback:
                    logger.info("檔案超過 250MB，啟動分片上傳: %s", file_name)
                    
                # B1. 建立空檔案佔位 (Placeholder)
                create_url = f"{self.base_url}{self.site}/_api/web/GetFolderByServerRelativeUrl('{encoded_folder_url}')/Files/Add(url='{encoded_filename}', overwrite=true)"
                response = self.session.post(create_url, headers=headers, data=b'', timeout=(10, 60))
                self.session.raise_for_status(response, context="建立 SharePoint 上傳佔位檔")

                # B2. 準備分片參數
                upload_id = str(uuid.uuid4())
                encoded_full_path = quote(f"{server_relative_folder}/{file_name}".replace("'", "''"))
                file_endpoint = f"{self.base_url}{self.site}/_api/web/GetFileByServerRelativeUrl('{encoded_full_path}')"
                
                chunk_size = 50 * 1024 * 1024  # 50MB 分片
                offset = 0
                
                # B3. 開始分片迴圈
                with open(local_path, 'rb') as f:
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        
                        is_first_chunk = (offset == 0)
                        is_last_chunk = (offset + len(chunk) >= file_size)
                        
                        if is_first_chunk:
                            chunk_url = f"{file_endpoint}/StartUpload(uploadId=guid'{upload_id}')"
                        elif is_last_chunk:
                            chunk_url = f"{file_endpoint}/FinishUpload(uploadId=guid'{upload_id}', fileOffset={offset})"
                        else:
                            chunk_url = f"{file_endpoint}/ContinueUpload(uploadId=guid'{upload_id}', fileOffset={offset})"

                        # 發送分片
                        response = self.session.post(chunk_url, headers=headers, data=chunk, timeout=(10, 60), retry=True)
                        self.session.raise_for_status(response, context="上傳 SharePoint 分片")
                        offset += len(chunk)
                        
                        if callback:
                            callback(offset, file_size)
                        else:
                            logger.debug("SharePoint 上傳進度 %.1f%% (%d/%d bytes)", min(offset / file_size * 100, 100), offset, file_size)
                        
                if not callback:
                    logger.info("SharePoint 分片上傳完成: %s", file_name)
            return True
            
        except HttpStatusError as e:
            if not callback:
                if e.http_response.status_code == 404:
                    logger.error("上傳失敗: 目標資料夾不存在 (%s)", server_relative_folder)
                elif e.http_response.status_code == 423:
                    logger.error("上傳失敗: 檔案被鎖定 (Locked)")
                else:
                    logger.error("SharePoint API 錯誤: %s - %s", e.http_response.status_code, e.http_response.text)
            raise ValueError(f"上傳過程發生錯誤: {e}") from e

    def get_share_link(self, remote_path: str) -> str:
        """
        取得檔案的臨時免登入下載連結 (TempAuth)
        """
        # 一行搞定複雜的底層邏輯！
        metadata, _ = self._get_v2_metadata(remote_path)
        
        download_url = metadata.get('@content.downloadUrl')
        if not download_url:
            raise ValueError("無法取得檔案下載連結，該路徑可能是一個資料夾或無權限。")
            
        if not isinstance(download_url, str):
            raise ValueError("SharePoint download link 回應格式無效。")
        return download_url

    def get_download_link(self, remote_path: str) -> str:
        """取得檔案的臨時免登入下載連結 (TempAuth)。"""
        metadata, _ = self._get_v2_metadata(remote_path)
        download_url = metadata.get('@content.downloadUrl')
        if not download_url:
            raise ValueError("無法取得檔案下載連結，該路徑可能是一個資料夾或無權限。")
        if not isinstance(download_url, str):
            raise ValueError("SharePoint download link 回應格式無效。")
        return download_url

    def get_thumbnail_link(self, remote_path: str) -> str:
        """取得檔案縮圖連結。"""
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
                        return thumb[size_key]["url"]
        except HttpStatusError as e:
            if e.http_response.status_code in (400, 404):
                raise ValueError(f"此檔案無可用縮圖: {remote_path}") from e
            raise
        raise ValueError(f"SharePoint 未提供此檔案之縮圖: {remote_path}")
    
    def download(self, remote_path: str, local_path: str, recursive: bool = False, callback: ProgressCallback | None = None) -> bool:
        """
        從雲端下載檔案或資料夾到本機指定路徑。
        支援遞迴下載資料夾並維持原始結構。
        """
        parts = [p for p in remote_path.strip("/").split("/") if p]
        if not parts:
            raise ValueError("遠端路徑不可為空。")
            
        file_relative_path = "/".join(parts[1:])
            
        headers = self._get_headers()

        headers.update({
            "Accept": "application/json;odata.metadata=minimal",
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0"),
            "Sec-Fetch-User": "?1"
        })

        metadata, item_api_url = self._get_v2_metadata(remote_path)

        item_name = metadata.get('name', 'downloaded_item')

        # 3. 智慧判斷本機路徑
        # 如果給定的 local_path 是一個已存在的「資料夾」，則將檔案或資料夾放進該目錄內
        if os.path.isdir(local_path):
            final_local_path = os.path.join(local_path, item_name)
        else:
            final_local_path = local_path

        # 4. 判斷是資料夾還是檔案
        if "folder" in metadata:
            if not recursive:
                # 拋出標準例外，讓上層 (CLI) 攔截並詢問使用者
                raise IsADirectoryError(f"{remote_path} 是一個資料夾")

            # === 遞迴下載資料夾邏輯 ===
            os.makedirs(final_local_path, exist_ok=True)

            # 取得資料夾內容 (處理 API 可能的分頁)
            children_url = f"{item_api_url}:/children" if file_relative_path else f"{item_api_url}/children"
            
            while children_url:
                resp = self.session.get(children_url, headers=headers)
                self.session.raise_for_status(resp)
                children_data = resp.json()

                for child in children_data.get('value', []):
                    child_remote = f"{remote_path}/{child['name']}".replace("//", "/")
                    # 遞迴呼叫：因為 final_local_path 現在肯定是一個資料夾
                    # 所以下層物件會自動被放在 final_local_path 裡面，完美保持結構！
                    self.download(child_remote, final_local_path, recursive=True, callback=callback)

                # 檢查是否有下一頁
                children_url = children_data.get('@odata.nextLink')

            return True

        elif "file" in metadata:
            # === 單一檔案下載邏輯 ===
            download_url = metadata.get('@content.downloadUrl')
            if not download_url:
                raise ValueError(f"無法取得檔案下載連結: {item_name}")
                
            # 從 metadata 預先取得檔案大小 (Fallback)
            expected_size = metadata.get('size', 0)
                
            if not callback:
                logger.info("開始下載: %s", item_name)
            
            # 確保上層目錄存在 (防呆)
            os.makedirs(os.path.dirname(os.path.abspath(final_local_path)), exist_ok=True)
            
            with self.session.get(download_url, stream=True) as r:
                self.session.raise_for_status(r)
                
                # 嘗試從 Header 取得最準確的檔案大小，若無則使用 metadata 的大小
                total_size = int(r.headers.get('content-length', expected_size))
                downloaded_size = 0
                
                with open(final_local_path, 'wb') as f:
                    # 串流寫入 (每次 8KB)
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk: # 確保有資料
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            
                            # 優先呼叫 callback 更新 UI 進度
                            if callback:
                                callback(downloaded_size, total_size)
                            else:
                                # 印出進度條 (\r 會讓游標回到行首，覆寫同一行文字)
                                if total_size > 0:
                                    percent = min((downloaded_size / total_size) * 100, 100)
                                    logger.debug("SharePoint 下載進度 %.1f%% (%d/%d bytes)", percent, downloaded_size, total_size)
                                else:
                                    logger.debug("SharePoint 已下載 %d bytes", downloaded_size)
                                
            if not callback:
                logger.info("SharePoint 下載完成: %s", item_name)
            return True
            
        else:
            raise ValueError(f"未知的項目類型: {item_name}")

    def delete(self, remote_path: str, permanent: bool = False) -> bool:
        """
        刪除雲端上的檔案或資料夾。支援移至回收桶或永久刪除。
        """
        # 1. 判斷是檔案還是資料夾 (重複利用我們寫好的 v2 API 解析工具)
        try:
            metadata, _ = self._get_v2_metadata(remote_path)
            is_folder = "folder" in metadata
        except ValueError as e:
            if "找不到" in str(e) or "404" in str(e):
                return False  # 目標已經不存在，視為刪除成功
            raise

        # 2. 取得 Request Digest (修改操作必備)
        digest_value = self._get_request_digest()
        headers = self._get_headers()
        headers["X-RequestDigest"] = digest_value

        # 3. 組合 v1 路徑
        clean_path = "/" + remote_path.strip("/") if remote_path else ""
        server_relative_path = f"{self.site}{clean_path}"
        encoded_path = quote(server_relative_path.replace("'", "''"))

        # 根據類型決定端點
        if is_folder:
            endpoint = f"GetFolderByServerRelativeUrl('{encoded_path}')"
        else:
            endpoint = f"GetFileByServerRelativeUrl('{encoded_path}')"

        # 4. 根據是否永久刪除決定請求方式
        if permanent:
            # 永久刪除: 附加 X-HTTP-Method: DELETE
            url = f"{self.base_url}{self.site}/_api/web/{endpoint}"
            headers["X-HTTP-Method"] = "DELETE"
        else:
            # 移至回收桶: 呼叫 recycle 方法
            url = f"{self.base_url}{self.site}/_api/web/{endpoint}/recycle"

        try:
            response = self.session.post(url, headers=headers)
            self.session.raise_for_status(response)
            return True
        except HttpStatusError as e:
            if e.http_response.status_code == 404:
                return False
            raise ValueError(f"刪除失敗: {e.http_response.status_code} - {e.http_response.text}") from e
        
    def copy(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        """
        (同節點) 在雲端伺服器上直接複製檔案或資料夾。
        """
        # 1. 判斷來源是檔案還是資料夾
        try:
            metadata, _ = self._get_v2_metadata(source_path)
            is_folder = "folder" in metadata
        except ValueError as e:
            raise ValueError(f"複製失敗，來源不存在: {e}")

        # 2. 取得 Request Digest
        digest_value = self._get_request_digest()
        headers = self._get_headers()
        headers["X-RequestDigest"] = digest_value

        # 3. 組合伺服器相對路徑 (ServerRelativeUrl)
        clean_src = "/" + source_path.strip("/")
        clean_dest = "/" + dest_path.strip("/")
        
        server_relative_src = f"{self.site}{clean_src}"
        server_relative_dest = f"{self.site}{clean_dest}"

        encoded_src = quote(server_relative_src.replace("'", "''"))
        encoded_dest = quote(server_relative_dest.replace("'", "''"))

        # 4. 根據類型決定呼叫的端點
        overwrite_str = "true" if overwrite else "false"
        if is_folder:
            # 資料夾的 CopyTo 不支援 bOverWrite 參數
            endpoint = f"GetFolderByServerRelativeUrl('{encoded_src}')/CopyTo(strNewUrl='{encoded_dest}')"
        else:
            endpoint = f"GetFileByServerRelativeUrl('{encoded_src}')/CopyTo(strNewUrl='{encoded_dest}', bOverWrite={overwrite_str})"

        url = f"{self.base_url}{self.site}/_api/web/{endpoint}"

        # 5. 執行 POST 請求
        try:
            response = self.session.post(url, headers=headers)
            self.session.raise_for_status(response)
            return True
        except HttpStatusError as e:
            error_msg = e.http_response.text
            if "-2130575257" in error_msg:
                raise ValueError(f"複製失敗: 目標路徑可能已存在 ({dest_path})")
            raise ValueError(f"API 請求失敗: {e.http_response.status_code} - {error_msg}")
        
    def move(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        """
        (同節點) 在雲端伺服器上直接移動/重新命名檔案或資料夾。
        """
        # 1. 判斷來源是檔案還是資料夾
        try:
            metadata, _ = self._get_v2_metadata(source_path)
            is_folder = "folder" in metadata
        except ValueError as e:
            raise ValueError(f"移動失敗，來源不存在: {e}")

        # 2. 取得 Request Digest
        digest_value = self._get_request_digest()
        headers = self._get_headers()
        headers["X-RequestDigest"] = digest_value

        # 3. 組合伺服器相對路徑
        clean_src = "/" + source_path.strip("/")
        clean_dest = "/" + dest_path.strip("/")
        
        server_relative_src = f"{self.site}{clean_src}"
        server_relative_dest = f"{self.site}{clean_dest}"

        encoded_src = quote(server_relative_src.replace("'", "''"))
        encoded_dest = quote(server_relative_dest.replace("'", "''"))

        # 4. 根據類型決定 MoveTo 端點
        # SharePoint MoveTo 對檔案支援 flags=1 (覆寫)，資料夾不支援
        flags = 1 if overwrite else 0
        if is_folder:
            endpoint = f"GetFolderByServerRelativeUrl('{encoded_src}')/MoveTo(newUrl='{encoded_dest}')"
        else:
            endpoint = f"GetFileByServerRelativeUrl('{encoded_src}')/MoveTo(newUrl='{encoded_dest}', flags={flags})"

        url = f"{self.base_url}{self.site}/_api/web/{endpoint}"

        # 5. 執行 POST 請求
        try:
            response = self.session.post(url, headers=headers)
            self.session.raise_for_status(response)
            return True
        except HttpStatusError as e:
            error_msg = e.http_response.text
            if "-2130575257" in error_msg:
                raise ValueError(f"移動失敗: 目標路徑可能已存在 ({dest_path})")
            raise ValueError(f"API 請求失敗: {e.http_response.status_code} - {error_msg}")
    
    def stat(self, remote_path: str) -> StorageStat:
        """
        取得遠端節點或特定檔案/資料夾的詳細資訊。
        """
        clean_path = remote_path.strip("/")
        
        # 1. 節點/容量層級 (當路徑為空，代表查詢整個 Remote 節點)
        if not clean_path:
            self._init_drives_cache()
            
            # 優先取得預設文件庫的 ID
            drive_id = self._drive_id_cache.get("Shared Documents") or self._drive_id_cache.get("Documents")
            if not drive_id and self._drive_id_cache:
                # 若找不到預設的，就隨便抓一個可用的來查容量
                drive_id = list(self._drive_id_cache.values())[0]
                
            if not drive_id:
                raise ValueError("找不到可用的文件庫來查詢容量。")
                
            headers = self._get_headers()
            headers.update({
                "Accept": "application/json;odata.metadata=minimal",
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0"),
                "Sec-Fetch-User": "?1"
            })
            
            api_url = f"{self.base_url}/_api/v2.0/drives/{drive_id}"
            
            try:
                response = self.session.get(api_url, headers=headers)
                self.session.raise_for_status(response)
                data = response.json()

                quota = data.get("quota", {})
                
                return {
                    "type": "remote",
                    "name": data.get("name", "Unknown Drive"),
                    "total": quota.get("total", 0),
                    "used": quota.get("used", 0),
                    "filecount": quota.get("fileCount", 0),
                    "created": data.get("createdDateTime"),
                    "modified": data.get("lastModifiedDateTime"),
                }
            except HttpStatusError as e:
                raise ValueError(f"無法取得節點容量資訊: {e.http_response.status_code}") from e

        # 2. 檔案/資料夾層級 (重用已建立好的工具)
        try:
            metadata, _ = self._get_v2_metadata(remote_path)
        except ValueError as e:
            raise ValueError(f"無法取得狀態，目標不存在或無權限: {e}")

        item_type: Literal["folder", "file"] = "folder" if "folder" in metadata else "file"
        fs_info = metadata.get("fileSystemInfo", {})
        
        return {
            "type": item_type,
            "name": metadata.get("name", "Unknown"),
            "size": metadata.get("size", 0),
            # 優先使用 fileSystemInfo 裡面的時間 (因為有時建立時間與上傳時間不同)
            "created": fs_info.get("createdDateTime") or metadata.get("createdDateTime"),
            "modified": fs_info.get("lastModifiedDateTime") or metadata.get("lastModifiedDateTime")
        }
    
    def get_hash(self, remote_path: str, algo: str) -> str:
        """
        從 Graph API 中提取檔案的 Hash 值。
        """
        try:
            metadata, _ = self._get_v2_metadata(remote_path)
        except ValueError as e:
            raise ValueError(f"無法存取檔案: {e}")

        if "folder" in metadata:
            raise ValueError("無法對資料夾計算雜湊值。")

        hashes = metadata.get("file", {}).get("hashes", {})
        
        # Graph API 提供的 key 通常是: quickXorHash, sha1Hash, sha256Hash
        algo_lower = algo.lower()
        hash_map = {
            "quickxorhash": hashes.get("quickXorHash"),
            "sha1": hashes.get("sha1Hash"),
            "sha256": hashes.get("sha256Hash"),
            "md5": hashes.get("md5Hash")  # SharePoint 不一定有，但保留擴充性
        }
        
        target_hash = hash_map.get(algo_lower)
        
        if not target_hash:
            # 整理出該檔案目前伺服器有提供的演算法
            available = [k for k, v in hash_map.items() if v is not None]
            avail_str = ', '.join(available) if available else '無'
            raise ValueError(f"遠端伺服器未提供 '{algo}' 的雜湊值。(目前該檔案可用: {avail_str})")
            
        if not isinstance(target_hash, str):
            raise ValueError(f"遠端 '{algo}' 雜湊值格式無效。")
        return target_hash