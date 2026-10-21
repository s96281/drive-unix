import os
import posixpath
import tempfile
from ftplib import FTP, FTP_TLS, error_perm
from datetime import datetime, timezone
from contextlib import contextmanager
import threading

from storage.base import FileItem, ProgressCallback, StorageProvider, StorageStat
from core.paths import resolve_posix_path

class FTPStorage(StorageProvider):
    def __init__(self, host: str, port: int = 21, username: str = "anonymous", 
                 password: str = "", tls: bool = False, passive: bool = True, root_path: str = "/"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password or ""
        self.tls = tls
        self.passive = passive
        self.root_path = root_path
        self._connections: dict[int, FTP] = {}
        self._connection_lock = threading.RLock()

    def _create_connection(self) -> FTP:
        try:
            if self.tls:
                ftp_tls = FTP_TLS()
                ftp_tls.connect(self.host, self.port, timeout=30)
                ftp_tls.login(self.username, self.password)
                ftp_tls.prot_p()
                ftp: FTP = ftp_tls
            else:
                ftp = FTP()
                ftp.connect(self.host, self.port, timeout=30)
                ftp.login(self.username, self.password)

            ftp.set_pasv(self.passive)
            ftp.encoding = "utf-8"
            return ftp
        except Exception as exc:
            raise ValueError(f"FTP 連線失敗: {exc}") from exc

    @contextmanager
    def _get_connection(self):
        """Reuse one FTP connection per worker thread."""
        thread_id = threading.get_ident()
        with self._connection_lock:
            ftp = self._connections.get(thread_id)
            if ftp is None:
                ftp = self._create_connection()
                self._connections[thread_id] = ftp
            else:
                try:
                    ftp.voidcmd("NOOP")
                except Exception:
                    try:
                        ftp.close()
                    except Exception:
                        pass
                    ftp = self._create_connection()
                    self._connections[thread_id] = ftp

        yield ftp

    def close(self) -> None:
        """Close all persistent worker-thread FTP connections."""
        with self._connection_lock:
            connections = list(self._connections.values())
            self._connections.clear()

        for ftp in connections:
            try:
                ftp.quit()
            except Exception:
                try:
                    ftp.close()
                except Exception:
                    pass

    def _get_abs_path(self, remote_path: str) -> str:
        return resolve_posix_path(self.root_path, remote_path)

    def list_dir(self, remote_path: str) -> list[FileItem]:
        target_path = self._get_abs_path(remote_path)
        items = []
        
        with self._get_connection() as ftp:
            # 檢查是否為資料夾，若否則退回單一檔案模式
            try:
                ftp.cwd(target_path)
            except error_perm:
                try:
                    stat_info = self.stat(remote_path)
                    modified = stat_info.get("modified")
                    return [FileItem(
                        name=stat_info["name"],
                        path=remote_path,
                        is_dir=False,
                        size=stat_info["size"],
                        modified_at=modified if isinstance(modified, datetime) else None,
                    )]
                except Exception:
                    raise ValueError(f"路徑不存在或無權限: {remote_path}")

            ftp.cwd("/") # 切回根目錄以確保絕對路徑運作正常
            try:
                # 現代 FTP 伺服器支援 MLSD，提供高精度時間與精準判定
                entries = list(ftp.mlsd(target_path))
                for name, facts in entries:
                    if name in ('.', '..'):
                        continue
                        
                    is_dir = facts.get('type') in ('dir', 'pdir', 'cdir')
                    size = int(facts.get('size', 0)) if not is_dir else 0
                    
                    mod_time: datetime | None = None
                    if 'modify' in facts:
                        try:
                            # 時間格式: YYYYMMDDHHMMSS
                            mod_time = datetime.strptime(facts['modify'], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                        except ValueError:
                            pass
                            
                    clean_remote = remote_path.rstrip('/')
                    item_path = f"{clean_remote}/{name}" if clean_remote else f"/{name}"
                    
                    items.append(FileItem(
                        name=name,
                        path=item_path.replace("//", "/"),
                        is_dir=is_dir,
                        size=size,
                        modified_at=mod_time
                    ))
            except error_perm as e:
                raise ValueError(f"取得目錄清單失敗 (請確認 FTP 伺服器是否支援 MLSD 擴充指令): {e}")
                
        return items

    def mkdir(self, remote_path: str, parents: bool = False) -> bool:
        clean_path = remote_path.strip("/")
        if not clean_path:
            raise ValueError("資料夾路徑不可為空。")
            
        target_path = self._get_abs_path(remote_path)
        
        with self._get_connection() as ftp:
            if not parents:
                try:
                    ftp.mkd(target_path)
                    return True
                except Exception as e:
                    raise ValueError(f"建立資料夾失敗: {e} (提示: 若父目錄不存在，請加上 -p 參數)")
            
            parts = clean_path.split("/")
            current_path = self.root_path
            for part in parts:
                current_path = posixpath.join(current_path, part).replace("//", "/")
                try:
                    ftp.cwd(current_path)
                except error_perm:
                    try:
                        ftp.mkd(current_path)
                    except error_perm as e:
                        raise ValueError(f"建立中繼資料夾 '{part}' 失敗: {e}")
                        
        return True

    def upload(self, local_path: str, remote_path: str, callback: ProgressCallback | None = None) -> bool:
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"找不到本機檔案: {local_path}")
            
        target_path = self._get_abs_path(remote_path)
        remote_folder, file_name = posixpath.split(target_path)
        
        if not file_name:
            file_name = os.path.basename(local_path)
            target_path = posixpath.join(remote_folder, file_name).replace("//", "/")
            
        with self._get_connection() as ftp:
            try:
                ftp.cwd(remote_folder)
            except error_perm:
                raise ValueError(f"目標目錄不存在: {remote_folder}")
                
            file_size = os.path.getsize(local_path)
            uploaded = 0
            
            with open(local_path, "rb") as f:
                def internal_callback(data):
                    nonlocal uploaded
                    uploaded += len(data)
                    if callback: callback(uploaded, file_size)

                ftp.storbinary(f'STOR {target_path}', f, blocksize=8192, callback=internal_callback)
                
        return True

    def download(self, remote_path: str, local_path: str, recursive: bool = False, callback: ProgressCallback | None = None) -> bool:
        target_path = self._get_abs_path(remote_path)
        item_name = posixpath.basename(target_path)
        final_local_path = os.path.join(local_path, item_name) if os.path.isdir(local_path) else local_path
        
        with self._get_connection() as ftp:
            try:
                ftp.cwd(target_path)
                is_dir = True
            except error_perm:
                is_dir = False
                
            if is_dir:
                if not recursive:
                    raise IsADirectoryError(f"{remote_path} 是一個資料夾")
                os.makedirs(final_local_path, exist_ok=True)
                
                try:
                    entries = list(ftp.mlsd(target_path))
                except error_perm as e:
                    raise ValueError(f"取得目錄清單失敗: {e}")
                    
                for name, facts in entries:
                    if name in ('.', '..'): continue
                    child_remote = posixpath.join(remote_path, name).replace("//", "/")
                    self.download(child_remote, final_local_path, recursive=True, callback=callback)
                return True
            else:
                os.makedirs(os.path.dirname(os.path.abspath(final_local_path)), exist_ok=True)
                
                try:
                    ftp.sendcmd("TYPE I")
                    file_size = ftp.size(target_path)
                except Exception:
                    file_size = 0
                
                downloaded = 0
                
                with open(final_local_path, "wb") as f:
                    def internal_callback(data):
                        nonlocal downloaded
                        f.write(data)
                        downloaded += len(data)
                        if callback: callback(downloaded, file_size)
                        
                    ftp.retrbinary(f"RETR {target_path}", internal_callback, blocksize=8192)
                
                return True

    def delete(self, remote_path: str, permanent: bool = False) -> bool:
        target_path = self._get_abs_path(remote_path)
        
        with self._get_connection() as ftp:
            try:
                ftp.delete(target_path)
                return True
            except error_perm:
                pass
                
            # 若不是檔案，嘗試透過遞迴工具將其視為資料夾刪除
            try:
                self._rmtree(ftp, target_path)
                return True
            except Exception:
                return False

    def _rmtree(self, ftp, path):
        for name, facts in ftp.mlsd(path):
            if name in ('.', '..'):
                continue
            item_path = posixpath.join(path, name).replace("//", "/")
            if facts.get('type') in ('dir', 'pdir', 'cdir'):
                self._rmtree(ftp, item_path)
            else:
                ftp.delete(item_path)
        ftp.rmd(path)

    def copy(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        # FTP 不支援原生的伺服器端複製功能，這裡建立橋接自動將其退回到客戶端暫存複製
        stat_info = self.stat(source_path)
        if stat_info["type"] == "folder":
            raise ValueError("FTP 節點內不支援直接複製整個資料夾。請使用 CLI 自動跨節點橋接 (cp A B) 進行。")
            
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file_path = os.path.join(temp_dir, posixpath.basename(source_path))
            self.download(source_path, temp_file_path, recursive=False)
            self.upload(temp_file_path, dest_path)
        return True

    def move(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        src = self._get_abs_path(source_path)
        dst = self._get_abs_path(dest_path)
        
        with self._get_connection() as ftp:
            if overwrite:
                try:
                    ftp.delete(dst)
                except error_perm:
                    pass
            try:
                ftp.rename(src, dst)
            except Exception as e:
                raise ValueError(f"移動失敗: {e}")
        return True

    def stat(self, remote_path: str) -> StorageStat:
        clean_path = remote_path.strip("/")
        if not clean_path:
            return {
                "type": "remote",
                "name": f"FTP: {self.host}",
                "total": -1, # FTP 無法直接取得總空間
                "used": -1,
                "filecount": -1,
                "created": None,
                "modified": None
            }
            
        target_path = self._get_abs_path(remote_path)
        parent_dir, filename = posixpath.split(target_path)
        if not parent_dir:
            parent_dir = "/"
            
        with self._get_connection() as ftp:
            try:
                entries = list(ftp.mlsd(parent_dir))
                for name, facts in entries:
                    if name == filename:
                        is_dir = facts.get('type') in ('dir', 'pdir', 'cdir')
                        size = int(facts.get('size', 0)) if not is_dir else 0
                        mod_time: datetime | None = None
                        if 'modify' in facts:
                            try:
                                mod_time = datetime.strptime(facts['modify'], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                            except ValueError:
                                pass
                                
                        return {
                            "type": "folder" if is_dir else "file",
                            "name": name,
                            "size": size,
                            "created": None,
                            "modified": mod_time
                        }
            except error_perm:
                pass
                
            raise ValueError(f"無法取得狀態，目標不存在或無權限: {remote_path}")

    def get_share_link(self, remote_path: str) -> str:
        import urllib.parse
        target_path = self._get_abs_path(remote_path)
        encoded_path = urllib.parse.quote(target_path)
        
        user = urllib.parse.quote(self.username) if self.username else ""
        pwd = urllib.parse.quote(self.password) if self.password else ""
        
        auth_str = ""
        if user:
            auth_str = user
            if pwd:
                auth_str += f":{pwd}"
            auth_str += "@"
            
        return f"ftp://{auth_str}{self.host}:{self.port}{encoded_path}"

    def get_download_link(self, remote_path: str) -> str:
        return self.get_share_link(remote_path)

    def get_hash(self, remote_path: str, algo: str) -> str:
        raise ValueError(f"FTP 協定未標準化雜湊取得方式，請加上 --download 參數強制本機驗證。")