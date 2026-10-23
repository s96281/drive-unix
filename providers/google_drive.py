# providers/google_drive.py
import os
import posixpath
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2.credentials import Credentials

from storage.base import DeleteCapability, FileItem, ProgressCallback, StorageProvider, StorageStat
from auth.base import AuthProvider

class GoogleDriveStorage(StorageProvider):
    delete_capability = DeleteCapability.TRASH_AND_PERMANENT
    def __init__(self, auth_provider: AuthProvider, root_folder_id: str = "root"):
        self.auth_provider = auth_provider
        self.root_folder_id = root_folder_id
        
    def _get_service(self):
        """從 AuthContext 萃取憑證並建立 Google API Service 實例"""
        ctx = self.auth_provider.get_auth_context()
        token = ctx.headers.get("Authorization", "").replace("Bearer ", "")
        
        if not token:
            raise ValueError("Google Drive 認證內容缺少 Access Token。")

        # OAuth refresh / client secret 由 AuthProvider 自己管理；
        # Storage 層只接收當次 API request 所需的 access token。
        creds = Credentials(token=token)
        return build('drive', 'v3', credentials=creds, cache_discovery=False)

    def _get_id_from_path(self, remote_path: str) -> tuple[str, bool]:
        """
        將 POSIX 路徑轉換為 Google Drive 檔案/資料夾的 ID
        回傳: (item_id, is_folder)
        """
        clean_path = remote_path.strip("/")
        if not clean_path:
            return self.root_folder_id, True
            
        parts = clean_path.split("/")
        current_id = self.root_folder_id
        is_folder = True
        
        service = self._get_service()
        
        for part in parts:
            # 防護：跳脫單引號，避免類似 WORKING'!! 的報錯
            safe_part = part.replace("'", "\\'")
            
            query = f"'{current_id}' in parents and name='{safe_part}' and trashed=false"
            results = service.files().list(q=query, fields="files(id, mimeType)").execute()
            items = results.get('files', [])
            
            if not items:
                raise ValueError(f"遠端路徑不存在: {remote_path} (找不到 '{part}')")
            
            # 💡 關鍵修正：Google Drive 允許同名檔案與資料夾共存
            # 當遇到同名項目時，我們「優先」尋找資料夾
            target_item = None
            for item in items:
                if item['mimeType'] == 'application/vnd.google-apps.folder':
                    target_item = item
                    break
            
            # 如果全部的同名項目都不是資料夾，那我們才妥協拿第一個 (代表使用者路徑的最後一層確實是指定一個檔案)
            if not target_item:
                target_item = items[0]
                
            current_id = target_item['id']
            is_folder = (target_item['mimeType'] == 'application/vnd.google-apps.folder')
            
        return current_id, is_folder
    
    def _get_path_from_id(self, item_id: str) -> str:
        """
        將 Google Drive ID 轉換回完整的 POSIX 絕對路徑。
        透過向上追蹤 parents 屬性直到抵達 root_folder_id。
        """
        if item_id == self.root_folder_id:
            return "/"
            
        service = self._get_service()
        path_parts = []
        curr_id: str | None = item_id
        
        # 向上遍歷父節點
        while curr_id and curr_id != self.root_folder_id:
            try:
                # 請求名稱與父目錄列表
                f = service.files().get(
                    fileId=curr_id, 
                    fields="name, parents",
                    supportsAllDrives=True
                ).execute()
                
                path_parts.append(f.get('name'))
                parents = f.get('parents')
                
                # 取第一個父目錄繼續向上找 (Google Drive 支援多父目錄，但 CLI 通常取其一)
                curr_id = parents[0] if parents else None
            except Exception:
                # 遇到權限不足或路徑中斷時停止
                break
                
        # 將零件反轉並組合成路徑字串
        return "/" + "/".join(reversed(path_parts))
    
    def list_dir(
        self,
        remote_path: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[FileItem]:
        if offset < 0:
            offset = 0
        if limit is not None and limit <= 0:
            return []

        service = self._get_service()
        folder_id, is_folder = self._get_id_from_path(remote_path)
        
        if not is_folder:
            raise ValueError(f"[{remote_path}] 是一個檔案，無法列出目錄內容。")
            
        query = f"'{folder_id}' in parents and trashed=false"
        result_items: list[FileItem] = []
        page_token = None
        fetched_total = 0
        max_page_size = 1000
        target_end = (offset + limit) if limit is not None else None
        
        while True:
            if target_end is not None:
                remaining_needed = target_end - fetched_total
                if remaining_needed <= 0:
                    break
                current_window = min(remaining_needed, max_page_size)
            else:
                current_window = max_page_size

            results = service.files().list(
                q=query, 
                fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, thumbnailLink)",
                pageToken=page_token,
                pageSize=current_window
            ).execute()
            
            raw_files = results.get('files', [])
            if not raw_files:
                break

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
                    is_dir = (f['mimeType'] == 'application/vnd.google-apps.folder')
                    mod_time = datetime.fromisoformat(f['modifiedTime'].replace('Z', '+00:00')) if 'modifiedTime' in f else None
                    
                    clean_remote = remote_path.rstrip('/')
                    item_path = f"{clean_remote}/{f['name']}"
                    
                    result_items.append(FileItem(
                        name=f['name'],
                        path=item_path,
                        is_dir=is_dir,
                        size=int(f.get('size', 0)) if not is_dir else 0,
                        modified_at=mod_time,
                        thumbnail_url=f.get('thumbnailLink') if not is_dir else None,
                    ))
                
            if target_end is not None and fetched_total >= target_end:
                break

            page_token = results.get('nextPageToken')
            if not page_token:
                break
                
        return result_items

    def mkdir(self, remote_path: str, parents: bool = False) -> bool:
        service = self._get_service()
        clean_path = remote_path.strip("/")
        if not clean_path:
            raise ValueError("資料夾路徑不可為空。")
            
        parts = clean_path.split("/")
        current_id = self.root_folder_id
        
        for i, part in enumerate(parts):
            escaped = part.replace('"', '\\"')
            query = f"'{current_id}' in parents and name='{escaped}' and trashed=false"
            results = service.files().list(q=query, fields="files(id, mimeType)").execute()
            items = results.get('files', [])
            
            if items:
                current_id = items[0]['id']
            else:
                if not parents and i < len(parts) - 1:
                    raise ValueError(f"父目錄不存在且未啟用遞迴建立: {part}")
                
                file_metadata = {
                    'name': part,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [current_id]
                }
                folder = service.files().create(body=file_metadata, fields='id').execute()
                current_id = folder.get('id')
                
        return True

    def upload(self, local_path: str, remote_path: str, callback: ProgressCallback | None = None) -> bool:
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"找不到本機檔案: {local_path}")

        file_size = os.path.getsize(local_path)
        remote_folder, file_name = posixpath.split(remote_path)
        if not file_name:
            file_name = os.path.basename(local_path)
            
        # 找出父目錄 ID
        try:
            folder_id, is_folder = self._get_id_from_path(remote_folder)
            if not is_folder: raise ValueError("目標不是一個資料夾")
        except ValueError:
            # 若父目錄不存在，則拋錯
            raise ValueError(f"目標目錄不存在: {remote_folder}")
            
        service = self._get_service()
        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }
        
        # 啟用斷點續傳 (Resumable Upload) 支援超大檔
        media = MediaFileUpload(local_path, resumable=True)
        request = service.files().create(body=file_metadata, media_body=media, fields='id')
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if callback:
                callback(int(status.progress() * file_size), file_size)
        return True

    def download(self, remote_path: str, local_path: str, recursive: bool = False, callback: ProgressCallback | None = None) -> bool:
        file_id, is_folder = self._get_id_from_path(remote_path)
        service = self._get_service()
        
        item_name = posixpath.basename(remote_path)
        final_local_path = os.path.join(local_path, item_name) if os.path.isdir(local_path) else local_path
        
        if is_folder:
            if not recursive:
                raise IsADirectoryError(f"{remote_path} 是一個資料夾")
                
            os.makedirs(final_local_path, exist_ok=True)
            children = self.list_dir(remote_path)
            for child in children:
                self.download(child.path, final_local_path, recursive=True, callback=callback)
            return True
        else:
            request = service.files().get_media(fileId=file_id)
            os.makedirs(os.path.dirname(os.path.abspath(final_local_path)), exist_ok=True)
            
            with open(final_local_path, 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024 * 10)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
                    if callback:
                        callback(int(status.progress() * status.total_size), status.total_size)
            return True

    def delete(self, remote_path: str, permanent: bool = False) -> bool:
        try:
            file_id, _ = self._get_id_from_path(remote_path)
        except ValueError:
            return False
            
        service = self._get_service()
        if permanent:
            service.files().delete(fileId=file_id).execute()
        else:
            service.files().update(fileId=file_id, body={'trashed': True}).execute()
        return True

    def copy(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        src_id, is_folder = self._get_id_from_path(source_path)
        if is_folder:
            raise ValueError("Google Drive API 原生不支援直接複製資料夾。")
            
        dest_parent, dest_name = posixpath.split(dest_path)
        dest_parent_id, _ = self._get_id_from_path(dest_parent)
        
        service = self._get_service()
        file_metadata = {
            'name': dest_name,
            'parents': [dest_parent_id]
        }
        service.files().copy(fileId=src_id, body=file_metadata).execute()
        return True

    def move(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        src_id, _ = self._get_id_from_path(source_path)
        dest_parent, dest_name = posixpath.split(dest_path)
        dest_parent_id, _ = self._get_id_from_path(dest_parent)
        
        service = self._get_service()
        # 取得原檔案的父目錄
        file_data = service.files().get(fileId=src_id, fields='parents').execute()
        previous_parents = ",".join(file_data.get('parents', []))
        
        # 呼叫 API 更新位置與名稱
        service.files().update(
            fileId=src_id,
            addParents=dest_parent_id,
            removeParents=previous_parents,
            body={'name': dest_name},
            fields='id, parents'
        ).execute()
        return True

    def stat(self, remote_path: str) -> StorageStat:
        if not remote_path.strip("/"):
            service = self._get_service()
            about = service.about().get(fields="storageQuota, user").execute()
            quota = about.get('storageQuota', {})
            return {
                "type": "remote",
                "name": about.get('user', {}).get('displayName', 'Google Drive'),
                "total": int(quota.get('limit', 0)),
                "used": int(quota.get('usage', 0)),
                "filecount": quota.get("fileCount", -1),
                "created": None,
                "modified": None
            }
            
        file_id, is_folder = self._get_id_from_path(remote_path)
        service = self._get_service()
        f = service.files().get(fileId=file_id, fields="name, size, createdTime, modifiedTime").execute()
        
        return {
            "type": "folder" if is_folder else "file",
            "name": f.get('name'),
            "size": int(f.get('size', 0)),
            "created": datetime.fromisoformat(f['createdTime'].replace('Z', '+00:00')) if 'createdTime' in f else None,
            "modified": datetime.fromisoformat(f['modifiedTime'].replace('Z', '+00:00')) if 'modifiedTime' in f else None
        }

    def get_share_link(self, remote_path: str) -> str:
        file_id, _ = self._get_id_from_path(remote_path)
        service = self._get_service()
        
        # 建立任何人皆可讀取的權限
        service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
        f = service.files().get(fileId=file_id, fields='webViewLink').execute()
        link = f.get('webViewLink')
        if not isinstance(link, str) or not link:
            raise ValueError("Google Drive 未回傳 webViewLink。")
        return link

    def get_download_link(self, remote_path: str) -> str:
        file_id, is_folder = self._get_id_from_path(remote_path)
        if is_folder:
            raise ValueError("無法為資料夾產生下載連結。")
        service = self._get_service()
        # 建立公開讀取權限並取得直接下載網址 webContentLink
        try:
            service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
        except Exception:
            pass
        f = service.files().get(fileId=file_id, fields='webContentLink').execute()
        link = f.get('webContentLink')
        if not isinstance(link, str) or not link:
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        return link

    def get_thumbnail_link(self, remote_path: str) -> str:
        file_id, is_folder = self._get_id_from_path(remote_path)
        if is_folder:
            raise ValueError("無法為資料夾產生縮圖。")

        service = self._get_service()
        f = service.files().get(fileId=file_id, fields="thumbnailLink").execute()
        link = f.get("thumbnailLink")
        if not isinstance(link, str) or not link:
            raise ValueError(f"Google Drive 未提供此檔案之縮圖網址: {remote_path}")
        return link

    def get_hash(self, remote_path: str, algo: str) -> str:
        if algo.lower() != "md5":
            raise ValueError(f"Google Drive 原生僅支援 md5 雜湊演算 (你輸入了 {algo})。")
            
        file_id, is_folder = self._get_id_from_path(remote_path)
        if is_folder:
            raise ValueError("無法對資料夾計算雜湊值。")
            
        service = self._get_service()
        f = service.files().get(fileId=file_id, fields='md5Checksum').execute()
        checksum = f.get('md5Checksum')
        if not isinstance(checksum, str) or not checksum:
            raise ValueError("Google Drive 未回傳 md5Checksum。")
        return checksum
    
    def search(self, remote_path: str, query: str) -> list[FileItem]:
        """
        使用原生 API 進行全域搜尋，並回傳包含完整絕對路徑的結果。
        """
        service = self._get_service()
        safe_query = query.replace("'", "\\'")
        q = f"name contains '{safe_query}' and trashed = false"
        
        items = []
        page_token = None
        
        try:
            while True:
                results = service.files().list(
                    q=q,
                    fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
                    pageToken=page_token,
                    pageSize=50 # 建議縮小分頁，因為每筆結果都需額外請求路徑
                ).execute()
                
                for f in results.get('files', []):
                    is_dir = (f['mimeType'] == 'application/vnd.google-apps.folder')
                    
                    # --- 關鍵修正：取得真實路徑 ---
                    full_path = self._get_path_from_id(f['id'])
                    
                    mod_time = None
                    if 'modifiedTime' in f:
                        mod_time = datetime.fromisoformat(f['modifiedTime'].replace('Z', '+00:00'))
                    
                    items.append(FileItem(
                        name=f['name'],
                        path=full_path,
                        is_dir=is_dir,
                        size=int(f.get('size', 0)) if not is_dir else 0,
                        modified_at=mod_time
                    ))
                    
                page_token = results.get('nextPageToken')
                if not page_token:
                    break
                    
            return items
        except Exception as e:
            raise ValueError(f"Google Drive 原生搜尋失敗: {e}")