import os
import shutil
from datetime import datetime, timezone

from core.constants import DEFAULT_BUFFER_SIZE
from core.hashing import QuickXorHash
from storage.base import FileItem, FileList, ProgressCallback, StorageProvider, StorageStat
from core.paths import resolve_local_path


class LocalStorage(StorageProvider):
    def __init__(self, root_path: str):
        self.root_path = str(resolve_local_path(root_path, "/"))

    def _get_abs_path(self, remote_path: str) -> str:
        """將 POSIX 風格的遠端路徑安全地映射到本機絕對路徑。"""
        return str(resolve_local_path(self.root_path, remote_path))

    def list_dir(
        self,
        remote_path: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[FileItem]:
        if offset < 0:
            offset = 0
        if limit is not None and limit <= 0:
            return FileList([], total_count=0)

        target = self._get_abs_path(remote_path)
        if not os.path.exists(target):
            raise ValueError(f"路徑不存在: {target}")
        
        items: list[FileItem] = []
        target_end = (offset + limit) if limit is not None else None
        if os.path.isdir(target):
            clean_remote = remote_path.rstrip('/')
            entries = sorted(os.scandir(target), key=lambda e: (not e.is_dir(), e.name.lower()))
            total_count = len(entries)
            target_slice = entries[offset:target_end]
            for entry in target_slice:
                stat = entry.stat()
                items.append(FileItem(
                    name=entry.name,
                    path=f"{clean_remote}/{entry.name}",
                    is_dir=entry.is_dir(),
                    size=stat.st_size if not entry.is_dir() else 0,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                ))
            return FileList(items, total_count=total_count)
        else:
            if offset == 0:
                stat = os.stat(target)
                items.append(FileItem(
                    name=os.path.basename(target),
                    path=remote_path,
                    is_dir=False,
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                ))
            return FileList(items, total_count=1)

    def mkdir(self, remote_path: str, parents: bool = False) -> bool:
        target = self._get_abs_path(remote_path)
        if parents:
            os.makedirs(target, exist_ok=True)
        else:
            os.mkdir(target)
        return True

    def upload(self, local_path: str, remote_path: str, callback: ProgressCallback | None = None) -> bool:
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"找不到檔案: {local_path}")
            
        target = self._get_abs_path(remote_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(local_path, target)
        
        if callback:
            size = os.path.getsize(local_path)
            callback(size, size)
        return True

    def download(self, remote_path: str, local_path: str, recursive: bool = False, callback: ProgressCallback | None = None) -> bool:
        target = self._get_abs_path(remote_path)
        if not os.path.exists(target):
            raise FileNotFoundError(f"找不到檔案: {target}")
            
        item_name = os.path.basename(target)
        final_local_path = os.path.join(local_path, item_name) if os.path.isdir(local_path) else local_path

        if os.path.isdir(target):
            if not recursive:
                raise IsADirectoryError(f"{remote_path} 是一個資料夾")
            shutil.copytree(target, final_local_path, dirs_exist_ok=True)
        else:
            os.makedirs(os.path.dirname(os.path.abspath(final_local_path)), exist_ok=True)
            shutil.copy2(target, final_local_path)
            if callback:
                size = os.path.getsize(target)
                callback(size, size)
        return True

    def delete(self, remote_path: str, permanent: bool = False) -> bool:
        target = self._get_abs_path(remote_path)
        if not os.path.exists(target):
            return False
            
        if os.path.isdir(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
        return True

    def copy(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        src = self._get_abs_path(source_path)
        dst = self._get_abs_path(dest_path)
        
        if not os.path.exists(src):
            raise ValueError(f"來源不存在: {src}")
        if not overwrite and os.path.exists(dst):
            raise ValueError(f"目標已存在: {dst}")
            
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=overwrite)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        return True

    def move(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        src = self._get_abs_path(source_path)
        dst = self._get_abs_path(dest_path)
        
        if not os.path.exists(src):
            raise ValueError(f"來源不存在: {src}")
        if not overwrite and os.path.exists(dst):
            raise ValueError(f"目標已存在: {dst}")
            
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if overwrite and os.path.exists(dst):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            else:
                os.remove(dst)
        shutil.move(src, dst)
        return True

    def stat(self, remote_path: str) -> StorageStat:
        clean_path = remote_path.strip("/")
        
        if not clean_path:
            total, used, free = shutil.disk_usage(self.root_path)
            
            # 計算根目錄底下的項目數量
            filecount = 0
            try:
                filecount = sum(1 for _ in os.scandir(self.root_path))
            except (PermissionError, FileNotFoundError):
                pass
                
            return {
                "type": "remote",
                "name": f"Local Disk",
                "total": total,
                "used": used,
                "created": None,
                "modified": None,
                "filecount": filecount
            }
            
        target = self._get_abs_path(remote_path)
        if not os.path.exists(target):
            raise ValueError(f"路徑不存在: {target}")
            
        stat_info = os.stat(target)
        is_dir = os.path.isdir(target)
        
        # 若為資料夾，計算其包含的直接項目數量；若為檔案則預設為 0
        filecount = 0
        if is_dir:
            try:
                filecount = sum(1 for _ in os.scandir(target))
            except (PermissionError, FileNotFoundError):
                pass

        return {
            "type": "folder" if is_dir else "file",
            "name": os.path.basename(target),
            "size": stat_info.st_size if not is_dir else 0,
            "created": datetime.fromtimestamp(stat_info.st_ctime, tz=timezone.utc),
            "modified": datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc),
            "filecount": filecount
        }

    def get_share_link(self, remote_path: str) -> str:
        target = self._get_abs_path(remote_path)
        return f"file://{target}"

    def search(self, remote_path: str, query: str) -> list:
        target = self._get_abs_path(remote_path)
        if not os.path.exists(target):
            return []
            
        items = []
        query_lower = query.lower()
        for root, dirs, files in os.walk(target):
            for name in dirs + files:
                if query_lower in name.lower():
                    full_path = os.path.join(root, name)
                    rel_path = os.path.relpath(full_path, self.root_path)
                    remote_rel = "/" + rel_path.replace(os.sep, "/")
                    
                    is_dir = os.path.isdir(full_path)
                    stat_info = os.stat(full_path)
                    
                    items.append(FileItem(
                        name=name,
                        path=remote_rel,
                        is_dir=is_dir,
                        size=stat_info.st_size if not is_dir else 0,
                        modified_at=datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc)
                    ))
        return items

    def get_hash(self, remote_path: str, algo: str) -> str:
        import hashlib
        target = self._get_abs_path(remote_path)
        if os.path.isdir(target):
            raise ValueError("無法對資料夾計算雜湊值")
        
        algo_lower = algo.lower()
        
        # --- 新增: 支援 QuickXorHash (本地計算) ---
        if algo_lower in ("quickxorhash", "quickxor", "qxh"):
            h = QuickXorHash()
            with open(target, "rb") as f:
                for chunk in iter(lambda: f.read(DEFAULT_BUFFER_SIZE), b""):
                    h.update(chunk)
            return h.base64digest()

        if algo_lower == "md5":
            hashlib_hasher = hashlib.md5()
        elif algo_lower == "sha1":
            hashlib_hasher = hashlib.sha1()
        elif algo_lower == "sha256":
            hashlib_hasher = hashlib.sha256()
        else:
            raise ValueError(f"本機節點不支援此雜湊演算法: {algo}")

        with open(target, "rb") as f:
            for chunk in iter(lambda: f.read(DEFAULT_BUFFER_SIZE), b""):
                hashlib_hasher.update(chunk)
        return hashlib_hasher.hexdigest()