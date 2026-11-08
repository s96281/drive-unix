# auth/cache.py

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Optional

from auth.base import AuthContext, AuthProvider

from auth.exceptions import (
    AuthCacheError,
    AuthCacheReadError,
    AuthCacheWriteError,
)

DEFAULT_CACHE_DIR = os.path.join(
    os.path.expanduser("~"),
    ".auth_cache",
)


def get_photos_token_cache_path(remote_name: str, cache_dir: str | Path = DEFAULT_CACHE_DIR) -> Path:
    """Return the isolated OAuth token cache path for a Google Photos remote."""
    return Path(cache_dir) / f"googlephotos_{remote_name}_token.json"


def get_drive_token_cache_path(remote_name: str, cache_dir: str | Path = DEFAULT_CACHE_DIR) -> Path:
    """Return the OAuth token cache path for a Google Drive remote."""
    return Path(cache_dir) / f"{remote_name}_gdrive_token.json"


DEFAULT_TTL_SECONDS = 60 * 60 * 20
DEFAULT_EXPIRY_LEEWAY_SECONDS = 60

# Legacy AuthContext versions could place provider secrets into metadata.
# These keys are never valid for the generic request context and are removed
# when reading old cache entries.
SENSITIVE_METADATA_KEYS = frozenset({
    "access_token",
    "refresh_token",
    "client_secret",
    "private_key",
    "password",
    "secret",
})

def build_cache_key(
    *,
    provider_type: str,
    source_name: str,
    account: Optional[str] = None,
    resource: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> str:
    """
    Build a stable cache key for an auth source.

    Do not include passwords, client secrets, private keys, refresh tokens,
    or other sensitive values in this key.

    Suggested inputs:
        provider_type:
            "sharepoint_cookie", "google_drive_api_key", "google_oauth", etc.

        source_name:
            Logical source name from config, e.g. "sharepoint_main".

        account:
            User email, service account email, or None.

        resource:
            Target resource URL, site URL, tenant ID, or API audience.

        extra:
            Non-sensitive values that distinguish this credential.
            Example:
                {
                    "scope": "https://graph.microsoft.com/.default"
                }
    """
    payload = {
        "provider_type": provider_type,
        "source_name": source_name,
        "account": account,
        "resource": resource,
        "extra": dict(extra or {}),
    }

    raw = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AuthCache:
    """
    File-based authentication cache.

    This cache stores serialized AuthContext objects as JSON.

    Cache file format:
        {
            "created_at": 1710000000.0,
            "updated_at": 1710000000.0,
            "auth_context": {
                "headers": {...},
                "query_params": {...},
                "cookies": {...},
                "expires_at": 1710003600.0,
                "metadata": {...}
            }
        }

    Important:
        Cached authentication material should be treated as sensitive.
        Do not commit the cache directory to source control.
    """

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        namespace: str = "default",
    ):
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR).expanduser()
        self.namespace = namespace
        self.namespace_dir = self.cache_dir / self.namespace
        self.namespace_dir.mkdir(parents=True, exist_ok=True)

        self._try_chmod_directory(self.cache_dir)
        self._try_chmod_directory(self.namespace_dir)

    def get(self, cache_key: str) -> Optional[AuthContext]:
        """
        Read an AuthContext from cache.

        Returns None if the cache file does not exist.

        Raises:
            AuthCacheReadError if the file exists but cannot be parsed.
        """
        path = self._path_for(cache_key)

        if not path.exists():
            return None

        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)

            auth_context_data = payload.get("auth_context")
            if not isinstance(auth_context_data, dict):
                raise AuthCacheReadError(
                    f"Invalid cache payload: missing auth_context in {path}"
                )

            auth_context = AuthContext.from_dict(auth_context_data)
            return self._sanitize_auth_context(auth_context)

        except AuthCacheReadError:
            raise
        except Exception as exc:
            raise AuthCacheReadError(
                f"Failed to read auth cache from {path}: {exc}"
            ) from exc

    @staticmethod
    def _sanitize_auth_context(auth_context: AuthContext) -> AuthContext:
        """Strip sensitive legacy metadata before exposing cached credentials."""
        metadata = {
            key: value
            for key, value in (auth_context.metadata or {}).items()
            if key.lower() not in SENSITIVE_METADATA_KEYS
        }

        return AuthContext(
            headers=dict(auth_context.headers),
            query_params=dict(auth_context.query_params),
            cookies=dict(auth_context.cookies),
            expires_at=auth_context.expires_at,
            metadata=metadata,
        )

    def set(self, cache_key: str, auth_context: AuthContext) -> None:
        """
        Write an AuthContext to cache.

        Uses atomic replace to reduce the chance of corrupted cache files.
        """
        path = self._path_for(cache_key)
        now = time.time()

        existing_created_at = now
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    existing_payload = json.load(f)
                existing_created_at = float(
                    existing_payload.get("created_at") or now
                )
            except Exception:
                existing_created_at = now

        safe_auth_context = self._sanitize_auth_context(auth_context)
        payload = {
            "created_at": existing_created_at,
            "updated_at": now,
            "auth_context": safe_auth_context.to_dict(),
        }

        try:
            self.namespace_dir.mkdir(parents=True, exist_ok=True)

            fd, temp_path_str = tempfile.mkstemp(
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=str(self.namespace_dir),
                text=True,
            )

            temp_path = Path(temp_path_str)

            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(
                        payload,
                        f,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    f.write("\n")

                self._try_chmod_file(temp_path)
                os.replace(temp_path, path)
                self._try_chmod_file(path)

            finally:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass

        except Exception as exc:
            raise AuthCacheWriteError(
                f"Failed to write auth cache to {path}: {exc}"
            ) from exc

    def delete(self, cache_key: str) -> None:
        """
        Delete a cache entry if it exists.
        """
        path = self._path_for(cache_key)

        try:
            if path.exists():
                path.unlink()
        except Exception as exc:
            raise AuthCacheWriteError(
                f"Failed to delete auth cache {path}: {exc}"
            ) from exc

    def clear(self) -> None:
        """
        Delete all cache files in the current namespace.
        """
        if not self.namespace_dir.exists():
            return

        for path in self.namespace_dir.glob("*.json"):
            try:
                path.unlink()
            except OSError:
                pass

    def is_valid(
        self,
        auth_context: AuthContext,
        *,
        ttl_seconds: Optional[int] = DEFAULT_TTL_SECONDS,
        leeway_seconds: int = DEFAULT_EXPIRY_LEEWAY_SECONDS,
    ) -> bool:
        """
        Check if an AuthContext is still valid.

        Validation rules:
            1. It must contain auth material.
            2. If AuthContext.expires_at exists, it must not be expired.
            3. If ttl_seconds is not None, metadata.cached_at must be within TTL.

        Note:
            ttl_seconds=None means do not apply TTL-based expiration.
        """
        if not auth_context.has_auth_material():
            return False

        if auth_context.is_expired(leeway_seconds=leeway_seconds):
            return False

        if ttl_seconds is None:
            return True

        cached_at = auth_context.metadata.get("cached_at")
        if cached_at is None:
            return False

        try:
            cached_at_float = float(cached_at)
        except TypeError:
            return False
        except ValueError:
            return False

        return time.time() < cached_at_float + ttl_seconds - leeway_seconds

    def _path_for(self, cache_key: str) -> Path:
        """
        Return cache file path for a cache key.
        """
        safe_key = self._sanitize_cache_key(cache_key)
        return self.namespace_dir / f"{safe_key}.json"

    @staticmethod
    def _sanitize_cache_key(cache_key: str) -> str:
        """
        Ensure the cache key is safe as a file name.

        If the key is already a SHA256 hex digest, this keeps it as is.
        Otherwise, hash it.
        """
        is_sha256_hex = (
            len(cache_key) == 64
            and all(c in "0123456789abcdef" for c in cache_key.lower())
        )

        if is_sha256_hex:
            return cache_key.lower()

        return hashlib.sha256(cache_key.encode("utf-8")).hexdigest()

    @staticmethod
    def _try_chmod_directory(path: Path) -> None:
        """
        Best-effort directory permission hardening.

        On Unix-like systems this sets directory permission to 0700.
        On unsupported systems this silently does nothing.
        """
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass

    @staticmethod
    def _try_chmod_file(path: Path) -> None:
        """
        Best-effort file permission hardening.

        On Unix-like systems this sets file permission to 0600.
        On unsupported systems this silently does nothing.
        """
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


class CachedAuthProvider(AuthProvider):
    """
    AuthProvider wrapper that adds cache behavior to any AuthProvider.

    This class does not care whether the underlying provider uses:
    - SharePoint Cookie
    - Bearer token
    - API key
    - Service account
    - Any other authentication mechanism

    It only caches AuthContext.
    """

    def __init__(
        self,
        provider: AuthProvider,
        cache: AuthCache,
        cache_key: str,
        ttl_seconds: Optional[int] = DEFAULT_TTL_SECONDS,
        leeway_seconds: int = DEFAULT_EXPIRY_LEEWAY_SECONDS,
        force_refresh: bool = False,
        raise_on_cache_error: bool = False,
        remote_token_service: Any = None,
        identity_key: Optional[str] = None,
        raw_cache_path: Optional[Path] = None,
    ):
        self.provider = provider
        self.cache = cache
        self.cache_key = cache_key
        self.ttl_seconds = ttl_seconds
        self.leeway_seconds = leeway_seconds
        self.force_refresh = force_refresh
        self.raise_on_cache_error = raise_on_cache_error
        self.remote_token_service = remote_token_service
        self.identity_key = identity_key or cache_key
        self.raw_cache_path = Path(raw_cache_path) if raw_cache_path else None
        self._refresh_lock = threading.Lock()

    def get_auth_context(self) -> AuthContext:
        """
        Return cached AuthContext if valid; otherwise refresh from provider.
        """
        if not self.force_refresh:
            cached = self._safe_cache_get()

            if cached and self.cache.is_valid(
                cached,
                ttl_seconds=self.ttl_seconds,
                leeway_seconds=self.leeway_seconds,
            ):
                return cached

            # Local cache is expired or missing. Try remote Upstash before local provider refresh.
            if self.remote_token_service and self.identity_key:
                remote_cached = self.remote_token_service.try_get_token(
                    self.identity_key,
                    raw_cache_path=self.raw_cache_path,
                    leeway_seconds=self.leeway_seconds,
                )
                if isinstance(remote_cached, AuthContext):
                    if "cached_at" not in remote_cached.metadata:
                        remote_cached = self._with_cached_at(remote_cached)
                    if self.cache.is_valid(
                        remote_cached,
                        ttl_seconds=self.ttl_seconds,
                        leeway_seconds=self.leeway_seconds,
                    ):
                        self._safe_cache_set(remote_cached)
                        return remote_cached

        # Re-check under the lock so concurrent workers do not all perform
        # the same browser/OAuth refresh when a shared cache expires.
        with self._refresh_lock:
            if not self.force_refresh:
                cached = self._safe_cache_get()
                if cached and self.cache.is_valid(
                    cached,
                    ttl_seconds=self.ttl_seconds,
                    leeway_seconds=self.leeway_seconds,
                ):
                    return cached

                if self.remote_token_service and self.identity_key:
                    remote_cached = self.remote_token_service.try_get_token(
                        self.identity_key,
                        raw_cache_path=self.raw_cache_path,
                        leeway_seconds=self.leeway_seconds,
                    )
                    if isinstance(remote_cached, AuthContext):
                        if "cached_at" not in remote_cached.metadata:
                            remote_cached = self._with_cached_at(remote_cached)
                        if self.cache.is_valid(
                            remote_cached,
                            ttl_seconds=self.ttl_seconds,
                            leeway_seconds=self.leeway_seconds,
                        ):
                            self._safe_cache_set(remote_cached)
                            return remote_cached

            return self.refresh()

    def refresh(self) -> AuthContext:
        """
        Force refresh from the wrapped provider and update cache.
        Coordinates with Upstash distributed lock to prevent token rotation race condition.
        """
        def _do_provider_refresh() -> AuthContext:
            auth_context = self.provider.refresh()
            auth_context = self._with_cached_at(auth_context)
            self._safe_cache_set(auth_context)
            return auth_context

        if self.remote_token_service and self.identity_key:
            res = self.remote_token_service.with_distributed_refresh_lock(
                self.identity_key,
                _do_provider_refresh,
                raw_cache_path=self.raw_cache_path,
            )
            if isinstance(res, AuthContext):
                if "cached_at" not in res.metadata:
                    res = self._with_cached_at(res)
                self._safe_cache_set(res)
                return res

        return _do_provider_refresh()

    def invalidate(self) -> None:
        """
        Delete the cached credential.

        Useful when an API call returns 401 or 403 and the caller wants
        to force re-authentication.
        """
        try:
            self.cache.delete(self.cache_key)
        except AuthCacheError:
            if self.raise_on_cache_error:
                raise

    def _safe_cache_get(self) -> Optional[AuthContext]:
        try:
            return self.cache.get(self.cache_key)
        except AuthCacheError:
            if self.raise_on_cache_error:
                raise
            return None

    def _safe_cache_set(self, auth_context: AuthContext) -> None:
        try:
            self.cache.set(self.cache_key, auth_context)
        except AuthCacheError:
            if self.raise_on_cache_error:
                raise

    @staticmethod
    def _with_cached_at(auth_context: AuthContext) -> AuthContext:
        """
        Return a copy of AuthContext with metadata.cached_at added.

        AuthContext is frozen, so we create a new instance instead of mutating it.
        """
        metadata = dict(auth_context.metadata or {})
        metadata["cached_at"] = time.time()

        return AuthContext(
            headers=dict(auth_context.headers),
            query_params=dict(auth_context.query_params),
            cookies=dict(auth_context.cookies),
            expires_at=auth_context.expires_at,
            metadata=metadata,
        )
