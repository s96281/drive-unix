# auth/providers/google_drive.py
import os
import tempfile
from datetime import timezone
from typing import Optional, Dict, Any, cast
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from auth.base import AuthProvider, AuthContext
from auth.exceptions import AuthLoginError

class GoogleDriveAuthProvider(AuthProvider):
    provider_name = "google_drive"
    SCOPES = ['https://www.googleapis.com/auth/drive']

    def __init__(self, credentials_json: str, token_cache_path: str, metadata: Optional[Dict[str, Any]] = None):
        self.credentials_json = credentials_json
        self.token_cache_path = token_cache_path
        self.metadata = dict(metadata or {})
        
        if not os.path.exists(self.credentials_json):
            raise FileNotFoundError(f"找不到 Google OAuth 憑證檔案: {self.credentials_json}")

    def get_auth_context(self) -> AuthContext:
        # 直接呼叫 refresh 來處理讀取與更新邏輯
        return self.refresh()

    def refresh(self) -> AuthContext:
        creds = None
        
        # 1. 嘗試從快取檔案讀取憑證
        if os.path.exists(self.token_cache_path):
            creds = Credentials.from_authorized_user_file(self.token_cache_path, self.SCOPES)
            
        # 2. 如果憑證有效，直接封裝回傳
        if creds and creds.valid:
            return self._creds_to_auth_context(creds)
            
        # 3. 如果憑證過期，但我們有 refresh_token，則進行「無感刷新」
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                # 刷新失敗 (可能被使用者從後台撤銷授權)，退回重新登入
                creds = self._interactive_login()
        else:
            # 4. 完全沒有憑證，彈出瀏覽器要求登入
            creds = self._interactive_login()
            
        # 將最新憑證安全寫回實體檔案。refresh token / client secret
        # 只留在 Google OAuth 自己的 token cache，不再進入 AuthContext。
        self._save_token_cache(creds.to_json())
            
        return self._creds_to_auth_context(creds)

    def _interactive_login(self) -> Credentials:
        try:
            flow = InstalledAppFlow.from_client_secrets_file(self.credentials_json, self.SCOPES)
            # 關鍵修正：加入 prompt='consent'，強制 Google 每次都核發 refresh_token
            creds = flow.run_local_server(port=0, prompt='consent')
            if not isinstance(creds, Credentials):
                raise AuthLoginError("Google OAuth 回傳的 Credentials 型別無效。")
            return cast(Credentials, creds)
        except Exception as e:
            raise AuthLoginError(f"Google Drive 登入流程失敗: {e}")

    def _save_token_cache(self, content: str) -> None:
        cache_path = os.path.abspath(os.path.expanduser(self.token_cache_path))
        cache_dir = os.path.dirname(cache_path)
        os.makedirs(cache_dir, mode=0o700, exist_ok=True)
        try:
            os.chmod(cache_dir, 0o700)
        except OSError:
            pass

        fd, temp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(cache_path)}.",
            suffix=".tmp",
            dir=cache_dir,
            text=True,
        )
        try:
            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                pass
            with os.fdopen(fd, "w", encoding="utf-8") as token_file:
                token_file.write(content)
                token_file.flush()
                os.fsync(token_file.fileno())
            os.replace(temp_path, cache_path)
            try:
                os.chmod(cache_path, 0o600)
            except OSError:
                pass
        finally:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass

    def _creds_to_auth_context(self, creds: Credentials) -> AuthContext:
        # AuthContext 只攜帶目前 request 所需的 Access Token；
        # refresh token / client secret 留在 OAuth provider 的私有狀態。
        merged_metadata = {
            "provider": self.provider_name,
            "auth_type": "oauth2",
        }
        merged_metadata.update(self.metadata)

        safe_expires_at = None
        if creds.expiry:
            safe_expires_at = creds.expiry.replace(tzinfo=timezone.utc).timestamp()

        return AuthContext(
            headers={
                "Authorization": f"Bearer {creds.token}"
            },
            expires_at=safe_expires_at,
            metadata=merged_metadata
        )
