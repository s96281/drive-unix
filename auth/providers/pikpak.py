from __future__ import annotations

import threading
import time
from typing import Callable

from auth.base import AuthContext, AuthProvider
from infrastructure.http import HttpClient


class PikPakAuthProvider(AuthProvider):
    provider_name = "pikpak"
    SIGNIN_URL = "https://user.mypikpak.com/v1/auth/signin"
    REFRESH_URL = "https://user.mypikpak.com/v1/auth/token"
    DEFAULT_CLIENT_ID = "YNxT9w7GMdW5wX9q"

    def __init__(
        self,
        username: str,
        password_resolver: Callable[[], str],
        client_id: str | None = None,
    ) -> None:
        self.username = username
        self.password_resolver = password_resolver
        self.client_id = client_id or self.DEFAULT_CLIENT_ID
        self.http = HttpClient()
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float | None = None
        self._lock = threading.RLock()

    def get_auth_context(self) -> AuthContext:
        with self._lock:
            if not self._access_token or (
                self._expires_at is not None and time.time() >= self._expires_at - 60
            ):
                return self.refresh()
            return AuthContext(
                headers={"Authorization": f"Bearer {self._access_token}"},
                expires_at=self._expires_at,
            )

    def refresh(self) -> AuthContext:
        """刷新 Access Token；若無 Refresh Token 或過期則退回帳密登入。"""
        with self._lock:
            if self._refresh_token:
                payload = {
                    "client_id": self.client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                }
                resp = self.http.post(self.REFRESH_URL, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    self._access_token = data["access_token"]
                    self._refresh_token = data.get("refresh_token", self._refresh_token)
                    expires_in = data.get("expires_in")
                    self._expires_at = (
                        time.time() + float(expires_in) if expires_in else None
                    )
                    return AuthContext(
                        headers={"Authorization": f"Bearer {self._access_token}"},
                        expires_at=self._expires_at,
                    )

            # 完整帳密驗證登入
            password = self.password_resolver()
            login_payload = {
                "client_id": self.client_id,
                "username": self.username,
                "password": password,
            }
            resp = self.http.post(self.SIGNIN_URL, json=login_payload)
            self.http.raise_for_status(resp, context="PikPak 登入驗證")
            data = resp.json()
            self._access_token = data["access_token"]
            self._refresh_token = data.get("refresh_token")
            expires_in = data.get("expires_in")
            self._expires_at = time.time() + float(expires_in) if expires_in else None
            return AuthContext(
                headers={"Authorization": f"Bearer {self._access_token}"},
                expires_at=self._expires_at,
            )
