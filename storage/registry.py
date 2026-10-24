from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.config import (
    AlistRemote,
    ConfigManager,
    FTPRemote,
    GoogleDriveRemote,
    GooglePhotosRemote,
    LocalRemote,
    OneDriveBusinessRemote,
    OneDriveRemote,
    PikPakRemote,
    RemoteConfig,
    SFTPRemote,
    SharePointRemote,
    WebDAVRemote,
)
from storage.base import StorageProvider

ProviderBuilder = Callable[[str, ConfigManager, RemoteConfig], StorageProvider]


def _missing_provider_extra(
    provider_name: str,
    extra: str,
    exc: ModuleNotFoundError,
    *,
    expected_modules: tuple[str, ...],
) -> RuntimeError:
    missing = exc.name or "optional dependency"
    root_module = missing.split(".", 1)[0]
    if root_module not in expected_modules:
        raise exc
    return RuntimeError(
        f"{provider_name} provider 缺少選用套件 '{missing}'。"
        f"請安裝: pip install 'drive-unix[{extra}]'"
    )


class ProviderRegistry:
    """Registry-based StorageProvider factory."""

    def __init__(self) -> None:
        self._builders: dict[str, ProviderBuilder] = {}

    def register(self, remote_type: str, builder: ProviderBuilder) -> None:
        key = remote_type.strip().lower()
        if not key:
            raise ValueError("Provider type cannot be empty.")
        if key in self._builders:
            raise ValueError(f"Provider type already registered: {remote_type}")
        self._builders[key] = builder

    def get(self, remote_type: str) -> ProviderBuilder:
        key = remote_type.strip().lower()
        try:
            return self._builders[key]
        except KeyError as exc:
            supported = ", ".join(sorted(self._builders))
            raise ValueError(
                f"未知的遠端節點型態 '{remote_type}'。支援類型: {supported}"
            ) from exc

    def create(self, remote_name: str, config_manager: ConfigManager) -> StorageProvider:
        remote_config = config_manager.get_remote(remote_name)
        return self.get(remote_config.type)(
            remote_name,
            config_manager,
            remote_config,
        )

    def supported_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._builders))


def _secret_or_legacy_env(
    config_manager: ConfigManager,
    reference: str | None,
    *,
    env_name: str | None,
    remote_name: str,
    label: str,
    required: bool = True,
) -> str | None:
    """Resolve Phase-4 secret refs with a compatibility env fallback."""
    if reference:
        return config_manager.resolve_secret(
            reference,
            remote_name=remote_name,
            label=label,
            required=required,
        )

    if env_name:
        value = os.getenv(env_name)
        if value:
            return value

    if required:
        hint = f" 或設定環境變數 {env_name}" if env_name else ""
        raise ValueError(
            f"遠端節點 '{remote_name}' 缺少 {label} secret reference{hint}。"
        )
    return None


def _get_token_service(config_manager: ConfigManager) -> Any:
    svc = getattr(config_manager, "_upstash_token_service", None)
    if svc is not None:
        return svc if svc.is_enabled() else None
    try:
        from application.upstash_token_service import UpstashTokenService

        svc = UpstashTokenService(config_manager)
        try:
            config_manager._upstash_token_service = svc
        except Exception:
            pass
        return svc if svc.is_enabled() else None
    except Exception:
        return None


def _cached_auth(
    *,
    provider: Any,
    namespace: str,
    cache_key: str,
    remote_token_service: Any = None,
    identity_key: str | None = None,
    raw_cache_path: Path | None = None,
    ttl_seconds: Any = "DEFAULT",
) -> Any:
    from auth.cache import AuthCache, CachedAuthProvider, DEFAULT_TTL_SECONDS

    effective_ttl = DEFAULT_TTL_SECONDS if ttl_seconds == "DEFAULT" else ttl_seconds
    return CachedAuthProvider(
        provider=provider,
        cache=AuthCache(namespace=namespace),
        cache_key=cache_key,
        remote_token_service=remote_token_service,
        identity_key=identity_key,
        raw_cache_path=raw_cache_path,
        ttl_seconds=effective_ttl,
    )


def _build_sharepoint(
    remote_name: str,
    config_manager: ConfigManager,
    remote: RemoteConfig,
) -> StorageProvider:
    try:
        from auth.identity import build_identity_cache_key, get_canonical_auth_identity
        from auth.providers.sharepoint_cookie import (
            DEFAULT_SHAREPOINT_EXPIRY_SECONDS,
            SharePointCookieProvider,
        )
        from providers.sharepoint import SharePointStorage
    except ModuleNotFoundError as exc:
        raise _missing_provider_extra(
            "SharePoint",
            "sharepoint",
            exc,
            expected_modules=("playwright",),
        ) from exc

    assert isinstance(remote, SharePointRemote)
    password = _secret_or_legacy_env(
        config_manager, remote.password_ref, env_name="SHAREPOINT_PASSWORD",
        remote_name=remote_name, label="SharePoint password",
    )
    base_provider = SharePointCookieProvider(
        base_url=remote.base_url,
        email=remote.email,
        password=password,
        headless=True,
        metadata={"source_name": remote_name},
    )
    ident = get_canonical_auth_identity(remote_name, remote, config_manager)
    ident_key = build_identity_cache_key(ident)
    token_svc = _get_token_service(config_manager)

    cached = _cached_auth(
        provider=base_provider,
        namespace="sharepoint",
        cache_key=ident_key,
        remote_token_service=token_svc,
        identity_key=ident_key,
        ttl_seconds=DEFAULT_SHAREPOINT_EXPIRY_SECONDS,
    )
    return SharePointStorage(
        auth_provider=cached,
        base_url=remote.base_url,
        site=remote.site,
    )


def _build_onedrive_business(
    remote_name: str,
    config_manager: ConfigManager,
    remote: RemoteConfig,
) -> StorageProvider:
    try:
        from auth.identity import build_identity_cache_key, get_canonical_auth_identity
        from auth.providers.sharepoint_cookie import (
            DEFAULT_SHAREPOINT_EXPIRY_SECONDS,
            SharePointCookieProvider,
        )
        from providers.onedrive_business import OneDriveBusinessStorage
    except ModuleNotFoundError as exc:
        raise _missing_provider_extra(
            "OneDrive Business",
            "sharepoint",
            exc,
            expected_modules=("playwright",),
        ) from exc

    assert isinstance(remote, OneDriveBusinessRemote)
    password = _secret_or_legacy_env(
        config_manager, remote.password_ref, env_name="ONEDRIVE_BUSINESS_PASSWORD",
        remote_name=remote_name, label="OneDrive Business password",
    )
    base_provider = SharePointCookieProvider(
        base_url=remote.base_url,
        email=remote.email,
        password=password,
        headless=True,
        metadata={"source_name": remote_name},
    )
    ident = get_canonical_auth_identity(remote_name, remote, config_manager)
    ident_key = build_identity_cache_key(ident)
    token_svc = _get_token_service(config_manager)

    cached = _cached_auth(
        provider=base_provider,
        namespace="onedrive_business",
        cache_key=ident_key,
        remote_token_service=token_svc,
        identity_key=ident_key,
        ttl_seconds=DEFAULT_SHAREPOINT_EXPIRY_SECONDS,
    )
    return OneDriveBusinessStorage(
        auth_provider=cached,
        base_url=remote.base_url,
        site=remote.site,
    )


def _build_google_drive(
    remote_name: str,
    config_manager: ConfigManager,
    remote: RemoteConfig,
) -> StorageProvider:
    try:
        from auth.cache import DEFAULT_CACHE_DIR
        from auth.identity import build_identity_cache_key, get_canonical_auth_identity
        from auth.providers.google_drive import GoogleDriveAuthProvider
        from providers.google_drive import GoogleDriveStorage
    except ModuleNotFoundError as exc:
        raise _missing_provider_extra(
            "Google Drive",
            "google",
            exc,
            expected_modules=("google", "google_auth_oauthlib", "googleapiclient"),
        ) from exc

    assert isinstance(remote, GoogleDriveRemote)
    token_cache_path = Path(DEFAULT_CACHE_DIR) / f"{remote_name}_gdrive_token.json"
    credentials_path = Path(remote.credentials_json).expanduser()
    if not credentials_path.is_absolute():
        credentials_path = config_manager.config_path.parent / credentials_path
    base_provider = GoogleDriveAuthProvider(
        credentials_json=str(credentials_path),
        token_cache_path=str(token_cache_path),
        metadata={"source_name": remote_name},
    )
    ident = get_canonical_auth_identity(remote_name, remote, config_manager)
    ident_key = build_identity_cache_key(ident)
    token_svc = _get_token_service(config_manager)

    cached = _cached_auth(
        provider=base_provider,
        namespace="google_drive",
        cache_key=ident_key,
        remote_token_service=token_svc,
        identity_key=ident_key,
        raw_cache_path=token_cache_path,
    )
    return GoogleDriveStorage(
        auth_provider=cached,
        root_folder_id=remote.root_folder_id,
    )


def _build_google_photos(
    remote_name: str,
    config_manager: ConfigManager,
    remote: RemoteConfig,
) -> StorageProvider:
    try:
        from auth.cache import DEFAULT_CACHE_DIR
        from auth.identity import build_identity_cache_key, get_canonical_auth_identity
        from auth.providers.google_photos import GooglePhotosAuthProvider
        from providers.google.photos import GooglePhotosClient, GooglePhotosStorage
    except ModuleNotFoundError as exc:
        raise _missing_provider_extra(
            "Google Photos",
            "google",
            exc,
            expected_modules=("google", "google_auth_oauthlib", "googleapiclient"),
        ) from exc

    assert isinstance(remote, GooglePhotosRemote)
    token_cache_path = Path(DEFAULT_CACHE_DIR) / f"googlephotos_{remote_name}_token.json"
    credentials_path = Path(remote.credentials_json).expanduser()
    if not credentials_path.is_absolute():
        credentials_path = config_manager.config_path.parent / credentials_path
    base_provider = GooglePhotosAuthProvider(
        credentials_json=str(credentials_path),
        token_cache_path=str(token_cache_path),
        metadata={"source_name": remote_name},
    )
    ident = get_canonical_auth_identity(remote_name, remote, config_manager)
    ident_key = build_identity_cache_key(ident)
    token_svc = _get_token_service(config_manager)

    cached = _cached_auth(
        provider=base_provider,
        namespace="googlephotos",
        cache_key=ident_key,
        remote_token_service=token_svc,
        identity_key=ident_key,
        raw_cache_path=token_cache_path,
    )
    client = GooglePhotosClient(auth_provider=cached)
    return GooglePhotosStorage(
        client=client,
        remote_name=remote_name,
    )


def _build_onedrive(
    remote_name: str,
    config_manager: ConfigManager,
    remote: RemoteConfig,
) -> StorageProvider:
    try:
        from auth.cache import DEFAULT_CACHE_DIR
        from auth.identity import build_identity_cache_key, get_canonical_auth_identity
        from auth.providers.onedrive import OneDriveAuthProvider
        from providers.onedrive import OneDriveStorage
    except ModuleNotFoundError as exc:
        raise _missing_provider_extra(
            "OneDrive",
            "onedrive",
            exc,
            expected_modules=("requests_oauthlib",),
        ) from exc

    assert isinstance(remote, OneDriveRemote)
    token_cache_path = Path(DEFAULT_CACHE_DIR) / f"{remote_name}_onedrive_token.json"
    client_secret = _secret_or_legacy_env(
        config_manager, remote.client_secret_ref, env_name="ONEDRIVE_CLIENT_SECRET",
        remote_name=remote_name, label="OneDrive client secret", required=False,
    ) or ""
    base_provider = OneDriveAuthProvider(
        client_id=remote.client_id,
        client_secret=client_secret,
        tenant=remote.tenant,
        token_cache_path=str(token_cache_path),
        metadata={"source_name": remote_name},
    )
    ident = get_canonical_auth_identity(remote_name, remote, config_manager)
    ident_key = build_identity_cache_key(ident)
    token_svc = _get_token_service(config_manager)

    cached = _cached_auth(
        provider=base_provider,
        namespace="onedrive",
        cache_key=ident_key,
        remote_token_service=token_svc,
        identity_key=ident_key,
        raw_cache_path=token_cache_path,
    )
    return OneDriveStorage(auth_provider=cached)


def _build_local(
    _remote_name: str,
    _config_manager: ConfigManager,
    remote: RemoteConfig,
) -> StorageProvider:
    from providers.local import LocalStorage

    assert isinstance(remote, LocalRemote)
    return LocalStorage(root_path=remote.root_path)


def _build_ftp(
    remote_name: str,
    config_manager: ConfigManager,
    remote: RemoteConfig,
) -> StorageProvider:
    from providers.ftp import FTPStorage

    assert isinstance(remote, FTPRemote)
    password = _secret_or_legacy_env(
        config_manager, remote.password_ref, env_name="FTP_PASSWORD",
        remote_name=remote_name, label="FTP password",
        required=remote.username.lower() != "anonymous",
    )
    return FTPStorage(
        host=remote.host,
        port=remote.port,
        username=remote.username,
        password=password or "",
        tls=remote.tls,
        passive=remote.passive,
        root_path=remote.root_path,
    )


def _build_webdav(
    remote_name: str,
    config_manager: ConfigManager,
    remote: RemoteConfig,
) -> StorageProvider:
    from providers.webdav import WebDAVStorage

    assert isinstance(remote, WebDAVRemote)
    password = _secret_or_legacy_env(
        config_manager, remote.password_ref, env_name="WEBDAV_PASSWORD",
        remote_name=remote_name, label="WebDAV password", required=False,
    )
    return WebDAVStorage(
        base_url=remote.base_url,
        username=remote.username,
        password=password or "",
    )


def _build_sftp(
    remote_name: str,
    config_manager: ConfigManager,
    remote: RemoteConfig,
) -> StorageProvider:
    try:
        from providers.sftp import SFTPStorage
    except ModuleNotFoundError as exc:
        raise _missing_provider_extra(
            "SFTP",
            "sftp",
            exc,
            expected_modules=("paramiko",),
        ) from exc

    assert isinstance(remote, SFTPRemote)
    password = _secret_or_legacy_env(
        config_manager, remote.password_ref, env_name="SFTP_PASSWORD",
        remote_name=remote_name, label="SFTP password",
        required=not bool(remote.key_filename),
    )
    return SFTPStorage(
        host=remote.host,
        port=remote.port,
        username=remote.username,
        password=password,
        key_filename=remote.key_filename,
        known_hosts=remote.known_hosts,
        root_path=remote.root_path,
    )


def _build_alist(
    _remote_name: str,
    _config_manager: ConfigManager,
    remote: RemoteConfig,
) -> StorageProvider:
    assert isinstance(remote, AlistRemote)
    raise NotImplementedError("Alist 儲存提供者尚未實作。")


def _build_pikpak(
    remote_name: str,
    config_manager: ConfigManager,
    remote: RemoteConfig,
) -> StorageProvider:
    from auth.providers.pikpak import PikPakAuthProvider
    from providers.pikpak import PikPakStorage

    assert isinstance(remote, PikPakRemote)
    password = _secret_or_legacy_env(
        config_manager,
        remote.password_ref,
        env_name="PIKPAK_PASSWORD",
        remote_name=remote_name,
        label="PikPak password",
        required=True,
    )
    assert password is not None
    base_auth = PikPakAuthProvider(
        username=remote.username,
        password_resolver=lambda: password,
        client_id=remote.client_id,
    )
    return PikPakStorage(
        auth_provider=base_auth,
        root_folder_id=remote.root_folder_id,
    )


def build_default_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register("sharepoint", _build_sharepoint)
    registry.register("onedrive_business", _build_onedrive_business)
    registry.register("google_drive", _build_google_drive)
    registry.register("googlephotos", _build_google_photos)
    registry.register("onedrive", _build_onedrive)
    registry.register("local", _build_local)
    registry.register("ftp", _build_ftp)
    registry.register("webdav", _build_webdav)
    registry.register("sftp", _build_sftp)
    registry.register("alist", _build_alist)
    registry.register("pikpak", _build_pikpak)
    return registry


DEFAULT_PROVIDER_REGISTRY = build_default_registry()

__all__ = ["ProviderRegistry", "DEFAULT_PROVIDER_REGISTRY"]
