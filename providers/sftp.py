import os
import posixpath
import tempfile
import stat
from datetime import datetime, timezone
from contextlib import contextmanager
import threading

import paramiko

from storage.base import FileItem, ProgressCallback, StorageProvider, StorageStat
from core.paths import resolve_posix_path

class SFTPStorage(StorageProvider):
    def __init__(self, host: str, port: int, username: str,
                 password: str | None = None, key_filename: str | None = None, root_path: str = "/",
                 known_hosts: str | None = None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_filename = key_filename
        self.root_path = root_path
        self.known_hosts = known_hosts
        self._connections: dict[int, tuple[paramiko.SSHClient, paramiko.SFTPClient]] = {}
        self._connection_lock = threading.RLock()

    def _create_connection(self):
        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        if self.known_hosts:
            ssh.load_host_keys(os.path.expanduser(self.known_hosts))
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy())

        try:
            key_file = os.path.expanduser(self.key_filename) if self.key_filename else None
            ssh.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                key_filename=key_file,
                timeout=30,
                look_for_keys=True,
            )
            return ssh, ssh.open_sftp()
        except Exception as exc:
            try:
                ssh.close()
            except Exception:
                pass
            raise ValueError(f"SFTP 連線失敗: {exc}") from exc

    @contextmanager
    def _get_connection(self):
        """Reuse one SSH/SFTP connection per worker thread."""
        thread_id = threading.get_ident()
        with self._connection_lock:
            connection = self._connections.get(thread_id)
            if connection is None:
                connection = self._create_connection()
                self._connections[thread_id] = connection
            else:
                ssh, sftp = connection
                transport = ssh.get_transport()
                if transport is None or not transport.is_active():
                    try:
                        sftp.close()
                    except Exception:
                        pass
                    try:
                        ssh.close()
                    except Exception:
                        pass
                    connection = self._create_connection()
                    self._connections[thread_id] = connection

        yield connection

    def close(self) -> None:
        """Close all persistent worker-thread SSH/SFTP connections."""
        with self._connection_lock:
            connections = list(self._connections.values())
            self._connections.clear()

        for ssh, sftp in connections:
            try:
                sftp.close()
            except Exception:
                pass
            try:
                ssh.close()
            except Exception:
                pass

    def _get_abs_path(self, remote_path: str) -> str:
        """安全地轉換相對路徑為 SFTP 絕對路徑。"""
        return resolve_posix_path(self.root_path, remote_path)

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

        target_path = self._get_abs_path(remote_path)
        items = []
        target_end = (offset + limit) if limit is not None else None
        
        with self._get_connection() as (ssh, sftp):
            try:
                # 測試是否為資料夾
                try:
                    sftp.chdir(target_path)
                except IOError:
                    # 若無法進入，嘗試將其當作單一檔案獲取屬性
                    try:
                        attr = sftp.stat(target_path)
                        single = [FileItem(
                            name=posixpath.basename(target_path),
                            path=remote_path,
                            is_dir=False,
                            size=attr.st_size,
                            modified_at=datetime.fromtimestamp(attr.st_mtime, tz=timezone.utc)
                        )]
                        return single[offset:target_end]
                    except IOError:
                        raise ValueError(f"路徑不存在或無權限: {remote_path}")

                # 是資料夾，列出底下內容
                for attr in sftp.listdir_attr(target_path):
                    if attr.filename in ('.', '..'): continue
                    
                    is_dir = stat.S_ISDIR(attr.st_mode)
                    clean_remote = remote_path.rstrip('/')
                    item_path = f"{clean_remote}/{attr.filename}" if clean_remote else f"/{attr.filename}"
                    
                    items.append(FileItem(
                        name=attr.filename,
                        path=item_path.replace("//", "/"),
                        is_dir=is_dir,
                        size=attr.st_size if not is_dir else 0,
                        modified_at=datetime.fromtimestamp(attr.st_mtime, tz=timezone.utc)
                    ))
            except Exception as e:
                raise ValueError(f"取得目錄清單失敗: {e}")
                
        return items[offset:target_end]

    def mkdir(self, remote_path: str, parents: bool = False) -> bool:
        clean_path = remote_path.strip("/")
        if not clean_path:
            raise ValueError("資料夾路徑不可為空。")
            
        target_path = self._get_abs_path(remote_path)
        
        with self._get_connection() as (ssh, sftp):
            if not parents:
                try:
                    sftp.mkdir(target_path)
                    return True
                except IOError as e:
                    raise ValueError(f"建立資料夾失敗: {e} (提示: 若父目錄不存在，請加上 -p 參數)")
            
            # 遞迴建立中繼目錄
            parts = clean_path.split("/")
            current_path = self.root_path
            for part in parts:
                current_path = posixpath.join(current_path, part).replace("//", "/")
                try:
                    sftp.stat(current_path)
                except IOError:
                    try:
                        sftp.mkdir(current_path)
                    except IOError as e:
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
            
        with self._get_connection() as (ssh, sftp):
            try:
                sftp.stat(remote_folder)
            except IOError:
                raise ValueError(f"目標目錄不存在: {remote_folder}")
                
            # 將進度回傳交給傳入的 callback
            def internal_callback(transferred, total):
                if callback: callback(transferred, total)

            sftp.put(local_path, target_path, callback=internal_callback)
            
        return True

    def download(self, remote_path: str, local_path: str, recursive: bool = False, callback: ProgressCallback | None = None) -> bool:
        target_path = self._get_abs_path(remote_path)
        item_name = posixpath.basename(target_path)
        final_local_path = os.path.join(local_path, item_name) if os.path.isdir(local_path) else local_path
        
        with self._get_connection() as (ssh, sftp):
            try:
                attr = sftp.stat(target_path)
                is_dir = stat.S_ISDIR(attr.st_mode)
            except IOError:
                raise ValueError(f"遠端路徑不存在: {remote_path}")
                
            if is_dir:
                if not recursive:
                    raise IsADirectoryError(f"{remote_path} 是一個資料夾")
                os.makedirs(final_local_path, exist_ok=True)
                
                # 遞迴下載
                for child_attr in sftp.listdir_attr(target_path):
                    if child_attr.filename in ('.', '..'): continue
                    child_remote = posixpath.join(remote_path, child_attr.filename).replace("//", "/")
                    self.download(child_remote, final_local_path, recursive=True, callback=callback)
                return True
            else:
                os.makedirs(os.path.dirname(os.path.abspath(final_local_path)), exist_ok=True)
                
                def internal_callback(transferred, total):
                    if callback: callback(transferred, total)
                    
                sftp.get(target_path, final_local_path, callback=internal_callback)
                return True

    def delete(self, remote_path: str, permanent: bool = False) -> bool:
        target_path = self._get_abs_path(remote_path)
        with self._get_connection() as (ssh, sftp):
            try:
                attr = sftp.stat(target_path)
                if stat.S_ISDIR(attr.st_mode):
                    self._rmtree(sftp, target_path)
                else:
                    sftp.remove(target_path)
                return True
            except IOError:
                return False

    def _rmtree(self, sftp, path):
        """內部遞迴刪除 SFTP 目錄"""
        for attr in sftp.listdir_attr(path):
            if attr.filename in ('.', '..'): continue
            item_path = posixpath.join(path, attr.filename).replace("//", "/")
            if stat.S_ISDIR(attr.st_mode):
                self._rmtree(sftp, item_path)
            else:
                sftp.remove(item_path)
        sftp.rmdir(path)

    def copy(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        """
        SFTP 協定原生無伺服器端複製，此處進行橋接暫存處理。
        """
        stat_info = self.stat(source_path)
        if stat_info["type"] == "folder":
            raise ValueError("SFTP 節點不支援直接複製整個資料夾。請使用 CLI 自動跨節點橋接 (cp A B) 進行。")
            
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file_path = os.path.join(temp_dir, posixpath.basename(source_path))
            self.download(source_path, temp_file_path, recursive=False)
            self.upload(temp_file_path, dest_path)
        return True

    def move(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        src = self._get_abs_path(source_path)
        dst = self._get_abs_path(dest_path)
        
        with self._get_connection() as (ssh, sftp):
            if overwrite:
                try:
                    sftp.remove(dst)
                except IOError:
                    pass
            try:
                sftp.rename(src, dst)
            except IOError as e:
                raise ValueError(f"移動失敗: {e}")
        return True

    def stat(self, remote_path: str) -> StorageStat:
        clean_path = remote_path.strip("/")
        
        with self._get_connection() as (ssh, sftp):
            if not clean_path:
                # 查詢根節點容量 (透過 ssh 執行 df -kP)
                total, used = -1, -1
                try:
                    import shlex
                    stdin, stdout, stderr = ssh.exec_command(
                        f"df -kP {shlex.quote(self.root_path)}"
                    )
                    lines = stdout.readlines()
                    if len(lines) > 1:
                        parts = lines[1].split()
                        # blocks, used, available, capacity, mounted on (區塊為 1K)
                        total = int(parts[1]) * 1024
                        used = int(parts[2]) * 1024
                except Exception:
                    pass
                    
                return {
                    "type": "remote",
                    "name": f"SFTP: {self.host}",
                    "total": total,
                    "used": used,
                    "filecount": -1,
                    "created": None,
                    "modified": None
                }
                
            target_path = self._get_abs_path(remote_path)
            try:
                attr = sftp.stat(target_path)
                is_dir = stat.S_ISDIR(attr.st_mode)
                
                return {
                    "type": "folder" if is_dir else "file",
                    "name": posixpath.basename(target_path),
                    "size": attr.st_size if not is_dir else 0,
                    "created": None,
                    "modified": datetime.fromtimestamp(attr.st_mtime, tz=timezone.utc)
                }
            except IOError:
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
            
        return f"sftp://{auth_str}{self.host}:{self.port}{encoded_path}"

    def get_hash(self, remote_path: str, algo: str) -> str:
        """
        嘗試透過 SSH 直接在伺服器端執行 hash sum 驗證，節省下載時間。
        """
        target_path = self._get_abs_path(remote_path)
        algo_lower = algo.lower()
        
        cmd_map = {
            "md5": "md5sum",
            "sha1": "sha1sum",
            "sha256": "sha256sum"
        }
        
        if algo_lower not in cmd_map:
            raise ValueError(f"SFTP 伺服器不支援 {algo} 雜湊。")
            
        cmd = cmd_map[algo_lower]
        
        with self._get_connection() as (ssh, sftp):
            try:
                # 防呆: 不允許對資料夾做 Hash
                attr = sftp.stat(target_path)
                if stat.S_ISDIR(attr.st_mode):
                    raise ValueError("無法對資料夾計算雜湊值。")
            except IOError:
                raise ValueError(f"路徑不存在: {remote_path}")
                
            # 透過 SSH 通道執行指令
            import shlex

            stdin, stdout, stderr = ssh.exec_command(
                f"{cmd} {shlex.quote(target_path)}"
            )
            raw_output = stdout.read()
            if isinstance(raw_output, bytes):
                out = raw_output.decode("utf-8").strip()
            else:
                out = str(raw_output).strip()

            if not out or "command not found" in out.lower():
                raise ValueError(f"SFTP 伺服器端不支援 {cmd} 指令，或無權限執行。請加上 --download 參數強制本機驗證。")
                
            # output 格式通常為 "hash_value  /path/to/file"
            hash_value = out.split()[0]
            return hash_value