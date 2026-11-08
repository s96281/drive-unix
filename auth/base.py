# auth/base.py

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Mapping, Optional
import time


@dataclass(frozen=True)
class AuthContext:
    """
    Represents authentication material required by an HTTP request.

    This class intentionally does not assume whether the authentication
    mechanism is Cookie, Bearer token, API key, or something else.

    Examples:
        SharePoint Cookie:
            AuthContext(
                headers={
                    "Cookie": "rtFa=...;FedAuth=..."
                }
            )

        Bearer token:
            AuthContext(
                headers={
                    "Authorization": "Bearer ..."
                }
            )

        API key in query string:
            AuthContext(
                query_params={
                    "key": "..."
                }
            )
    """

    headers: Dict[str, str] = field(default_factory=dict)
    query_params: Dict[str, str] = field(default_factory=dict)
    cookies: Dict[str, str] = field(default_factory=dict)

    # Optional expiry timestamp in Unix seconds.
    # None means the provider does not know the exact expiry.
    expires_at: Optional[float] = None

    # Optional provider-specific information.
    # Example:
    # {
    #     "provider": "sharepoint_cookie",
    #     "account": "user@example.com",
    #     "source": "sharepoint_main"
    # }
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self, *, leeway_seconds: int = 60) -> bool:
        """
        Returns True if this auth context is expired.

        leeway_seconds is used to refresh slightly before the actual expiry
        to avoid edge cases during long-running requests.
        """
        if self.expires_at is None:
            return False

        return time.time() >= self.expires_at - leeway_seconds

    def has_auth_material(self) -> bool:
        """
        Returns True if this context contains anything that can be applied
        to a request.
        """
        return bool(self.headers or self.query_params or self.cookies)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert AuthContext to a JSON-serializable dictionary.
        Useful for cache storage.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AuthContext":
        """
        Restore AuthContext from a dictionary.
        Useful when reading from cache.
        """
        return cls(
            headers=dict(data.get("headers") or {}),
            query_params=dict(data.get("query_params") or {}),
            cookies=dict(data.get("cookies") or {}),
            expires_at=data.get("expires_at"),
            metadata=dict(data.get("metadata") or {}),
        )


class AuthProvider(ABC):
    """
    Base interface for all authentication providers.

    Implementations may use:
    - SharePoint cookies
    - Microsoft Graph OAuth token
    - Google Drive API key
    - Google service account
    - Internal system token
    - Mock credentials for testing

    The caller should not care about the underlying authentication type.
    """

    @abstractmethod
    def get_auth_context(self) -> AuthContext:
        """
        Return a valid AuthContext.

        Implementations may:
        - return an existing in-memory credential
        - read from cache
        - refresh if expired
        - login again if necessary
        """
        raise NotImplementedError

    @abstractmethod
    def refresh(self) -> AuthContext:
        """
        Force refresh authentication material and return a new AuthContext.

        This should bypass stale in-memory state and obtain a fresh credential
        from the actual authentication source.
        """
        raise NotImplementedError


class StaticAuthProvider(AuthProvider):
    """
    Simple AuthProvider for static credentials.

    Useful for:
    - API keys
    - local development
    - tests
    - services whose credential does not need refresh

    Example:
        provider = StaticAuthProvider(
            AuthContext(
                headers={"x-api-key": "..."}
            )
        )
    """

    def __init__(self, auth_context: AuthContext):
        if not auth_context.has_auth_material():
            raise ValueError("auth_context does not contain any auth material.")

        self._auth_context = auth_context

    def get_auth_context(self) -> AuthContext:
        return self._auth_context

    def refresh(self) -> AuthContext:
        return self._auth_context


class NullAuthProvider(AuthProvider):
    """
    AuthProvider for services that do not require authentication.

    Useful for:
    - public endpoints
    - tests
    - local mock services
    """

    def get_auth_context(self) -> AuthContext:
        return AuthContext()

    def refresh(self) -> AuthContext:
        return AuthContext()
