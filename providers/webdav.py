import os
import posixpath
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, unquote, urlparse

import requests
from infrastructure.http import HttpClient

from storage.base import FileItem, ProgressCallback, StorageProvider, StorageStat

class WebDAVStorage(StorageProvider):
    def __init__(self, base_url: str, username: str, password: str = ""):
        self.base_url = base_url.rstrip("/")
        self.auth = (username, password) if username else None
        self.session = HttpClient(auth=self.auth)

    def close(self) -> None:
        self.session.close()

    def _get_url(self, remote_path: str) -> str:
        """安全地將相對路徑轉為 WebDAV 完整的 URL"""
        clean_path = remote_path.strip("/")
        if not clean_path:
            return self.base_url + "/"
        
        # 正確跳脫路徑中的特殊字元 (例如空白)
        parts = clean_path.split("/")
        quoted_path = "/".join(quote(p) for p in parts)
        return f"{self.base_url}/{quoted_path}"

    def _find_elem(self, node, name: str):
        """輔助方法：忽略 XML Namespace (通常是 DAV:) 以相容各大伺服器"""
        if node is None:
            return None
        res = node.find(f'.//{{DAV:}}{name}')
        if res is not None:
            return res
        for child in node.iter():
            if child.tag.endswith(f"}}{name}") or child.tag == name:
                return child
        return None

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

        url = self._get_url(remote_path)
        target_end = (offset + limit) if limit is not None else None
        # WebDAV 查詢目錄需要設定 Depth: 1 (只看第一層子項目)
        headers = {"Depth": "1"}
        
        response = self.session.request("PROPFIND", url, headers=headers)
        if response.status_code == 404:
            raise ValueError(f"路徑不存在: {remote_path}")
        self.session.raise_for_status(response)

        # 解析回傳的 XML
        root = ET.fromstring(response.content)
        responses = root.findall('.//{DAV:}response')
        if not responses:
            responses = [e for e in root.iter() if e.tag.endswith('}response') or e.tag == 'response']

        if not responses:
            return []

        # 第一個回應通常是查詢目標本身 (目錄自己或檔案)，需要區分處理
        first_resp = responses[0]
        first_is_dir = False
        resourcetype = self._find_elem(first_resp, 'resourcetype')
        if resourcetype is not None and self._find_elem(resourcetype, 'collection') is not None:
            first_is_dir = True

        if first_is_dir:
            # 如果是目錄，我們只看它的子項目 (略過自己，從索引 1 開始)
            responses_to_process = responses[1:]
        else:
            # 如果使用者是對單一檔案執行 ls，則直接回傳自己
            responses_to_process = responses

        items = []
        for resp in responses_to_process:
            href_elem = self._find_elem(resp, 'href')
            if href_elem is None or not href_elem.text:
                continue
                
            href = unquote(href_elem.text.strip())
            name = posixpath.basename(href.rstrip("/"))
            if not name:
                continue

            propstat = self._find_elem(resp, 'propstat')
            prop = self._find_elem(propstat, 'prop') if propstat is not None else None
            if prop is None:
                continue

            # 判斷是否為資料夾 (collection)
            is_dir = False
            resourcetype = self._find_elem(prop, 'resourcetype')
            if resourcetype is not None and self._find_elem(resourcetype, 'collection') is not None:
                is_dir = True

            # 取得大小
            size = 0
            if not is_dir:
                getcontentlength = self._find_elem(prop, 'getcontentlength')
                if getcontentlength is not None and getcontentlength.text:
                    size = int(getcontentlength.text)

            # 取得修改時間
            modified_at = None
            getlastmodified = self._find_elem(prop, 'getlastmodified')
            if getlastmodified is not None and getlastmodified.text:
                try:
                    modified_at = parsedate_to_datetime(getlastmodified.text)
                except Exception:
                    pass

            clean_remote = remote_path.rstrip('/')
            item_path = f"{clean_remote}/{name}" if clean_remote else f"/{name}"

            items.append(FileItem(
                name=name,
                path=item_path.replace("//", "/"),
                is_dir=is_dir,
                size=size,
                modified_at=modified_at
            ))

        return items[offset:target_end]

    def mkdir(self, remote_path: str, parents: bool = False) -> bool:
        clean_path = remote_path.strip("/")
        if not clean_path:
            raise ValueError("資料夾路徑不可為空。")

        if not parents:
            url = self._get_url(clean_path)
            # WebDAV 建立目錄使用 MKCOL
            response = self.session.request("MKCOL", url)
            if response.status_code in (403, 404, 405, 409):
                raise ValueError(f"建立資料夾失敗 ({response.status_code}): 可能是父目錄不存在，或已存在。若要自動建立父目錄，請加上 -p 參數。")
            self.session.raise_for_status(response)
            return True

        # 遞迴建立目錄 (-p 機制)
        parts = clean_path.split("/")
        current_path = ""
        for part in parts:
            current_path = posixpath.join(current_path, part).replace("//", "/")
            url = self._get_url(current_path)
            
            # 先使用 PROPFIND Depth:0 測試目錄是否已存在，減少報錯機率
            check = self.session.request("PROPFIND", url, headers={"Depth": "0"})
            if check.status_code == 404:
                resp = self.session.request("MKCOL", url)
                # 405 = Method Not Allowed (通常代表已被其他並發建立)
                if resp.status_code not in (200, 201, 204, 207, 405): 
                    raise ValueError(f"建立中繼資料夾 '{part}' 失敗: {resp.status_code} - {resp.text}")
                    
        return True

    def upload(self, local_path: str, remote_path: str, callback: ProgressCallback | None = None) -> bool:
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"找不到本機檔案: {local_path}")
            
        url = self._get_url(remote_path)
        # 防呆：如果使用者只提供目錄，自動幫他加上本機檔名
        if remote_path.endswith("/"):
            url = self._get_url(posixpath.join(remote_path, os.path.basename(local_path)))
            
        file_size = os.path.getsize(local_path)
        
        with open(local_path, "rb") as f:
            # 建立一個產生器封裝，在 requests 送出 PUT 時實現精準進度條回呼
            def read_in_chunks():
                uploaded = 0
                while True:
                    data = f.read(8192)
                    if not data:
                        break
                    uploaded += len(data)
                    if callback: callback(uploaded, file_size)
                    yield data
                    
            response = self.session.request("PUT", url, data=read_in_chunks())
            self.session.raise_for_status(response)
            
        return True

    def download(self, remote_path: str, local_path: str, recursive: bool = False, callback: ProgressCallback | None = None) -> bool:
        url = self._get_url(remote_path)
        
        # 下載前先判斷是檔案還是資料夾 (PROPFIND Depth: 0)
        headers = {"Depth": "0"}
        response = self.session.request("PROPFIND", url, headers=headers)
        if response.status_code == 404:
            raise ValueError(f"遠端路徑不存在: {remote_path}")
        self.session.raise_for_status(response)
        
        root = ET.fromstring(response.content)
        resp = root.find('.//{DAV:}response') or root[0]
        resourcetype = self._find_elem(resp, 'resourcetype')
        is_dir = resourcetype is not None and self._find_elem(resourcetype, 'collection') is not None
        
        item_name = posixpath.basename(urlparse(url).path.rstrip('/'))
        final_local_path = os.path.join(local_path, item_name) if os.path.isdir(local_path) else local_path

        if is_dir:
            if not recursive:
                raise IsADirectoryError(f"{remote_path} 是一個資料夾")
            os.makedirs(final_local_path, exist_ok=True)
            children = self.list_dir(remote_path)
            for child in children:
                self.download(child.path, final_local_path, recursive=True, callback=callback)
            return True
        else:
            os.makedirs(os.path.dirname(os.path.abspath(final_local_path)), exist_ok=True)
            
            # 使用串流模式 (stream=True) 來接收檔案
            with self.session.request("GET", url, stream=True) as r:
                self.session.raise_for_status(r)
                total_size = int(r.headers.get('content-length', 0))
                downloaded = 0
                
                with open(final_local_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if callback: callback(downloaded, total_size)
            return True

    def delete(self, remote_path: str, permanent: bool = False) -> bool:
        url = self._get_url(remote_path)
        # WebDAV 伺服器端會自動遞迴刪除資料夾，十分高效
        response = self.session.request("DELETE", url)
        if response.status_code == 404:
            return False
        self.session.raise_for_status(response)
        return True

    def copy(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        """
        利用 WebDAV 原生 COPY 指令進行伺服器端極速複製 (免頻寬消耗)。
        """
        src_url = self._get_url(source_path)
        dst_url = self._get_url(dest_path)
        headers = {
            "Destination": dst_url,
            "Overwrite": "T" if overwrite else "F"
        }
        response = self.session.request("COPY", src_url, headers=headers)
        if response.status_code in (412, 403, 409):
            raise ValueError(f"複製失敗 ({response.status_code}): 可能目標已存在或有衝突。")
        self.session.raise_for_status(response)
        return True

    def move(self, source_path: str, dest_path: str, overwrite: bool = False) -> bool:
        """
        利用 WebDAV 原生 MOVE 指令進行伺服器端極速移動與改名。
        """
        src_url = self._get_url(source_path)
        dst_url = self._get_url(dest_path)
        headers = {
            "Destination": dst_url,
            "Overwrite": "T" if overwrite else "F"
        }
        response = self.session.request("MOVE", src_url, headers=headers)
        if response.status_code in (412, 403, 409):
            raise ValueError(f"移動失敗 ({response.status_code}): 可能目標已存在或有衝突。")
        self.session.raise_for_status(response)
        return True

    def stat(self, remote_path: str) -> StorageStat:
        url = self._get_url(remote_path)
        headers = {"Depth": "0"}
        
        response = self.session.request("PROPFIND", url, headers=headers)
        if response.status_code == 404:
            raise ValueError(f"路徑不存在或無權限: {remote_path}")
        self.session.raise_for_status(response)

        root = ET.fromstring(response.content)
        responses = root.findall('.//{DAV:}response')
        resp = responses[0] if responses else root[0]
            
        is_dir = False
        propstat = self._find_elem(resp, 'propstat')
        prop = self._find_elem(propstat, 'prop') if propstat is not None else None
        
        if prop is not None:
            resourcetype = self._find_elem(prop, 'resourcetype')
            if resourcetype is not None and self._find_elem(resourcetype, 'collection') is not None:
                is_dir = True

            size = 0
            getcontentlength = self._find_elem(prop, 'getcontentlength')
            if getcontentlength is not None and getcontentlength.text:
                size = int(getcontentlength.text)

            modified_at = None
            getlastmodified = self._find_elem(prop, 'getlastmodified')
            if getlastmodified is not None and getlastmodified.text:
                try:
                    modified_at = parsedate_to_datetime(getlastmodified.text)
                except Exception:
                    pass

            if not remote_path.strip("/"):
                # 若為根目錄，我們嘗試解析現代 WebDAV (如 Nextcloud) 的容量屬性 (RFC 4331)
                quota_avail = self._find_elem(prop, 'quota-available-bytes')
                quota_used = self._find_elem(prop, 'quota-used-bytes')
                
                total, used = -1, -1
                
                if quota_avail is not None and quota_avail.text and quota_used is not None and quota_used.text:
                    avail = int(quota_avail.text)
                    used = int(quota_used.text)
                    total = avail + used
                    
                return {
                    "type": "remote",
                    "name": f"WebDAV: {urlparse(self.base_url).netloc}",
                    "total": total,
                    "used": used,
                    "filecount": -1,
                    "created": None,
                    "modified": modified_at
                }
                
        return {
            "type": "folder" if is_dir else "file",
            "name": posixpath.basename(remote_path.strip("/")),
            "size": size,
            "created": None,
            "modified": modified_at
        }

    def get_share_link(self, remote_path: str) -> str:
        """
        將認證資訊夾帶於 URL 中，回傳可供其他工具直接下載的連結。
        """
        parsed = urlparse(self._get_url(remote_path))
        if self.auth:
            user, pwd = self.auth
            auth_str = f"{quote(user)}"
            if pwd:
                auth_str += f":{quote(pwd)}"
            return f"{parsed.scheme}://{auth_str}@{parsed.netloc}{parsed.path}?{parsed.query}".rstrip("?")
        return parsed.geturl()

    def get_download_link(self, remote_path: str) -> str:
        return self.get_share_link(remote_path)

    def get_hash(self, remote_path: str, algo: str) -> str:
        """
        嘗試從伺服器取得雜湊值 (支援 Nextcloud <oc:checksums> 與通用 ETag)
        """
        url = self._get_url(remote_path)
        response = self.session.request("PROPFIND", url, headers={"Depth": "0"})
        self.session.raise_for_status(response)
        
        etag = response.headers.get("ETag")
        root = ET.fromstring(response.content)
        
        found_hash = None
        # 尋找任何包含 checksum 的節點 (例如 Nextcloud 的 <oc:checksums>)
        for child in root.iter():
            if "checksum" in child.tag.lower() and child.text:
                text = child.text.strip()
                if ":" in text:
                    alg, val = text.split(":", 1)
                    if alg.lower() == algo.lower():
                        found_hash = val
                        break
                        
        if found_hash:
            return found_hash
            
        # 若無明確提供，但使用者指定 md5 且有 ETag，我們嘗試將 ETag 視為 md5 回傳
        if etag and algo.lower() == "md5":
            clean_etag = etag.strip('"').split('-')[0]
            if len(clean_etag) == 32:
                return clean_etag
                
        raise ValueError(f"伺服器並未提供 {algo} 的雜湊值，請加上 --download 參數強制本機驗證。")