# auth/providers/google_photos.py
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import timezone
from typing import Any, Mapping, cast

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from auth.base import AuthContext, AuthProvider
from auth.exceptions import AuthLoginError

logger = logging.getLogger(__name__)


class GooglePhotosAuthProvider(AuthProvider):
    provider_name = "googlephotos"
    SCOPES = [
        "https://www.googleapis.com/auth/photoslibrary.appendonly",
        "https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata",
        "https://www.googleapis.com/auth/photoslibrary.edit.appcreateddata",
    ]

    def __init__(
        self,
        credentials_json: str,
        token_cache_path: str,
        metadata: Mapping[str, Any] | None = None,
        scopes: list[str] | None = None,
    ) -> None:
        self.credentials_json = credentials_json
        self.token_cache_path = token_cache_path
        self.metadata = dict(metadata or {})
        if scopes:
            self.SCOPES = list(scopes)

        if not os.path.exists(self.credentials_json):
            raise FileNotFoundError(f"找不到 Google OAuth 憑證檔案: {self.credentials_json}")

    def get_auth_context(self) -> AuthContext:
        return self.refresh()

    def refresh(self) -> AuthContext:
        creds = None

        if os.path.exists(self.token_cache_path):
            try:
                with open(self.token_cache_path, "r", encoding="utf-8") as f:
                    token_data = json.load(f)
                cached_scopes = set(token_data.get("scopes") or [])
                if not set(self.SCOPES).issubset(cached_scopes):
                    logger.info("Google Photos Token 快取 Scope 與要求不符，將重新授權。")
                    creds = None
                else:
                    creds = Credentials.from_authorized_user_file(self.token_cache_path, self.SCOPES)
            except Exception:
                creds = None

        if creds and creds.valid:
            return self._creds_to_auth_context(creds)

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = self._interactive_login()
        else:
            creds = self._interactive_login()

        self._save_token_cache(creds.to_json())
        return self._creds_to_auth_context(creds)

    def _interactive_login(self) -> Credentials:
        try:
            flow = InstalledAppFlow.from_client_secrets_file(self.credentials_json, self.SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent")
            if not isinstance(creds, Credentials):
                raise AuthLoginError("Google OAuth 回傳的 Credentials 型別無效。")
            return cast(Credentials, creds)
        except Exception as e:
            raise AuthLoginError(f"Google Photos 登入流程失敗: {e}")

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
                "Authorization": f"Bearer {creds.token}",
            },
            expires_at=safe_expires_at,
            metadata=merged_metadata,
        )
