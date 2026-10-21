# auth/exceptions.py
"""
Common exception hierarchy for authentication-related modules.

The goal of this file is to let upper layers catch authentication errors
without depending on a specific provider implementation such as SharePoint,
Google Drive, Microsoft Graph, or any future source.
"""

from __future__ import annotations


class AuthError(Exception):
    """Base exception for all authentication-related errors."""


class AuthConfigurationError(AuthError):
    """Raised when authentication configuration is missing or invalid."""


class AuthProviderError(AuthError):
    """Raised when an authentication provider fails."""


class AuthRefreshError(AuthProviderError):
    """Raised when authentication material cannot be refreshed."""


class AuthCredentialNotFoundError(AuthProviderError):
    """Raised when required credential material cannot be found."""


class AuthCacheError(AuthError):
    """Base exception for authentication cache errors."""


class AuthCacheReadError(AuthCacheError):
    """Raised when cached authentication data cannot be read or parsed."""


class AuthCacheWriteError(AuthCacheError):
    """Raised when cached authentication data cannot be written or deleted."""


class AuthLoginError(AuthProviderError):
    """Raised when an interactive or browser-based login flow fails."""


class AuthTimeoutError(AuthLoginError):
    """Raised when an authentication flow times out."""