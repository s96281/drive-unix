"""Upstash Redis REST API client.

Stateless, lightweight HTTPS client communicating with Upstash serverless Redis.
"""

from __future__ import annotations

import json
from typing import Any

import requests


class UpstashError(RuntimeError):
    """Base exception for Upstash Redis operations."""


class UpstashAuthError(UpstashError):
    """Raised when authentication with Upstash fails (e.g. invalid token)."""


class UpstashConnectionError(UpstashError):
    """Raised when connecting to Upstash REST API fails."""


class UpstashClient:
    """REST client for Upstash Serverless Redis."""

    def __init__(
        self,
        rest_url: str,
        rest_token: str,
        *,
        timeout: float = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        clean_url = rest_url.strip().rstrip("/")
        if not clean_url:
            raise ValueError("Upstash REST URL cannot be empty.")
        if not clean_url.startswith("https://") and not clean_url.startswith("http://"):
            raise ValueError(f"Upstash REST URL 必須以 https:// 開頭: {clean_url}")
        if not rest_token.strip():
            raise ValueError("Upstash REST Token cannot be empty.")

        self.rest_url = clean_url
        self.rest_token = rest_token.strip()
        self.timeout = timeout
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.rest_token}",
            "Content-Type": "application/json",
        }

    def _execute(self, command: list[Any]) -> Any:
        try:
            response = self.session.post(
                self.rest_url,
                headers=self._headers(),
                json=command,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise UpstashConnectionError(f"連線至 Upstash 逾時 ({self.timeout}s): {exc}") from exc
        except requests.RequestException as exc:
            raise UpstashConnectionError(f"連線至 Upstash 失敗: {exc}") from exc

        if response.status_code == 401:
            raise UpstashAuthError("Upstash 認證失敗：REST Token 無效或未授權。")

        try:
            data = response.json()
        except ValueError as exc:
            raise UpstashError(f"Upstash 回傳非預期非 JSON 回應 ({response.status_code}): {response.text[:200]}") from exc

        if not response.ok or "error" in data:
            error_msg = data.get("error", response.text)
            if "unauthorized" in str(error_msg).lower():
                raise UpstashAuthError(f"Upstash 認證錯誤: {error_msg}")
            raise UpstashError(f"Upstash 執行失敗 ({response.status_code}): {error_msg}")

        return data.get("result")

    def ping(self) -> bool:
        """Send PING command to verify connection and credentials."""
        res = self._execute(["PING"])
        return str(res).upper() == "PONG"

    def get(self, key: str) -> str | None:
        """Fetch string value for key from Upstash Redis."""
        res = self._execute(["GET", key])
        if res is None:
            return None
        return str(res)

    def set(self, key: str, value: str, ex_seconds: int | None = None) -> None:
        """Store string value in Upstash Redis."""
        cmd: list[Any] = ["SET", key, value]
        if ex_seconds is not None:
            cmd.extend(["EX", ex_seconds])
        res = self._execute(cmd)
        if res != "OK":
            raise UpstashError(f"Upstash SET 指令未回傳 OK (實際: {res})")

    def delete(self, key: str) -> int:
        """Delete key from Upstash Redis."""
        res = self._execute(["DEL", key])
        try:
            return int(res)
        except (ValueError, TypeError):
            return 0

    def exists(self, key: str) -> bool:
        """Check if key exists in Upstash Redis."""
        res = self._execute(["EXISTS", key])
        return bool(res == 1 or res is True)

    def acquire_lock(self, lock_key: str, owner_id: str, ttl_seconds: int = 15) -> bool:
        """Acquire an atomic distributed lock via Redis SET NX EX.

        Returns True if the lock was acquired; False if already held by another device.
        """
        cmd: list[Any] = ["SET", lock_key, owner_id, "NX", "EX", ttl_seconds]
        res = self._execute(cmd)
        return bool(res == "OK")

    def release_lock(self, lock_key: str, owner_id: str) -> bool:
        """Release the distributed lock only if owned by owner_id."""
        current_owner = self.get(lock_key)
        if current_owner == owner_id:
            self.delete(lock_key)
            return True
        return False
