# auth/__init__.py
from auth.exceptions import (
    AuthError,
    AuthConfigurationError,
    AuthProviderError,
    AuthRefreshError,
    AuthCredentialNotFoundError,
    AuthCacheError,
    AuthCacheReadError,
    AuthCacheWriteError,
    AuthLoginError,
    AuthTimeoutError,
)

__all__ = [
    "AuthError",
    "AuthConfigurationError",
    "AuthProviderError",
    "AuthRefreshError",
    "AuthCredentialNotFoundError",
    "AuthCacheError",
    "AuthCacheReadError",
    "AuthCacheWriteError",
    "AuthLoginError",
    "AuthTimeoutError",
]