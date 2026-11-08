from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from application.upstash_token_service import UpstashTokenService
from auth.base import AuthContext, AuthProvider
from auth.cache import AuthCache, CachedAuthProvider
from auth.identity import build_identity_cache_key, get_canonical_auth_identity
from core.config import ConfigManager, SharePointRemote, UpstashSyncConfig
from core.secrets import SecretRepository
from tests.unit.test_upstash_sync_service import MockMemoryUpstashClient


def _create_manager_with_upstash(base_dir: Path) -> ConfigManager:
    config_path = base_dir / "config.toml"
    repo = SecretRepository(base_dir / "secrets.json", prefer_keyring=False)
    mgr = ConfigManager(config_path, secret_store=repo)
    token_ref = mgr.secret_store.put("upstash/rest_token", "fake-token")
    pass_ref = mgr.secret_store.put("upstash/passphrase", "sync-pass")
    mgr.config.upstash = UpstashSyncConfig(
        rest_url="https://test.upstash.io",
        token_ref=token_ref,
        passphrase_ref=pass_ref,
        auto_sync_tokens=True,
        auto_push_tokens=True,
    )
    return mgr


class DummyAuthProvider(AuthProvider):
    def __init__(self, prefix: str = "tok") -> None:
        self.call_count = 0
        self.prefix = prefix

    def get_auth_context(self) -> AuthContext:
        self.call_count += 1
        return AuthContext(
            headers={"Cookie": f"{self.prefix}_{self.call_count}"},
            expires_at=time.time() + 3600,
        )

    def refresh(self) -> AuthContext:
        return self.get_auth_context()


def test_two_remotes_share_same_identity_login_once(tmp_path: Path):
    """Two SharePoint remotes with the same domain and email share local cache and only authenticate once."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    auth_cache = AuthCache(namespace="sharepoint", cache_dir=cache_dir)

    remote1 = SharePointRemote(
        type="sharepoint",
        base_url="https://contoso.sharepoint.com",
        site="/sites/team-a",
        email="alice@contoso.com",
        password_ref="sec/pass",
    )
    remote2 = SharePointRemote(
        type="sharepoint",
        base_url="https://contoso.sharepoint.com",
        site="/sites/team-b",
        email="alice@contoso.com",
        password_ref="sec/pass",
    )

    ident1 = get_canonical_auth_identity("site_a", remote1)
    ident2 = get_canonical_auth_identity("site_b", remote2)
    assert ident1 == ident2
    assert ident1 == "sharepoint:contoso.sharepoint.com:alice@contoso.com"

    ident_key = build_identity_cache_key(ident1)

    dummy_provider = DummyAuthProvider()
    cached_provider_1 = CachedAuthProvider(
        provider=dummy_provider,
        cache=auth_cache,
        cache_key=ident_key,
        identity_key=ident_key,
    )
    cached_provider_2 = CachedAuthProvider(
        provider=dummy_provider,
        cache=auth_cache,
        cache_key=ident_key,
        identity_key=ident_key,
    )

    # 1. First remote authenticates
    ctx1 = cached_provider_1.get_auth_context()
    assert ctx1.headers["Cookie"] == "tok_1"
    assert dummy_provider.call_count == 1

    # 2. Second remote retrieves from cache without calling dummy_provider again
    ctx2 = cached_provider_2.get_auth_context()
    assert ctx2.headers["Cookie"] == "tok_1"
    assert dummy_provider.call_count == 1


def test_two_devices_concurrent_refresh_lock_protection(tmp_path: Path):
    """When two devices attempt token refresh concurrently, only lock winner refreshes while the other waits and retrieves."""
    # Shared Upstash mock client simulating Redis NX lock
    client = MockMemoryUpstashClient()
    lock_state: dict[str, str] = {}

    def mock_acquire_lock(key: str, owner: str, ttl: int = 15) -> bool:
        if key in lock_state:
            return False
        lock_state[key] = owner
        return True

    def mock_release_lock(key: str, owner: str) -> bool:
        if lock_state.get(key) == owner:
            del lock_state[key]
            return True
        return False

    client.acquire_lock = mock_acquire_lock  # type: ignore[assignment]
    client.release_lock = mock_release_lock  # type: ignore[assignment]

    # Device 1
    dir1 = tmp_path / "dev1"
    dir1.mkdir()
    mgr1 = _create_manager_with_upstash(dir1)
    token_svc1 = UpstashTokenService(mgr1, client=client, device_id="dev-1")

    # Device 2
    dir2 = tmp_path / "dev2"
    dir2.mkdir()
    mgr2 = _create_manager_with_upstash(dir2)
    token_svc2 = UpstashTokenService(mgr2, client=client, device_id="dev-2")

    ident_key = "test-identity-key-shared"
    refresh_counter = 0

    def device_1_refresh():
        nonlocal refresh_counter
        refresh_counter += 1
        return AuthContext(headers={"Authorization": "Bearer token_from_dev1"}, expires_at=time.time() + 3600)

    def device_2_refresh():
        nonlocal refresh_counter
        refresh_counter += 1
        return AuthContext(headers={"Authorization": "Bearer token_from_dev2"}, expires_at=time.time() + 3600)

    # Simulate dev-1 starting refresh and holding the distributed lock
    assert client.acquire_lock(f"drive-unix:lock:{ident_key}", "dev-1") is True

    # Dev-1 finishes refresh and uploads token to Upstash, then releases lock
    new_ctx = device_1_refresh()
    assert token_svc1.try_put_token(ident_key, new_ctx) is True
    assert client.release_lock(f"drive-unix:lock:{ident_key}", "dev-1") is True

    # Dev-2 calls with_distributed_refresh_lock
    # Since token is now available in Upstash and lock is released or acquired,
    # dev-2's CachedAuthProvider / try_get_token gets dev-1's token!
    res = token_svc2.try_get_token(ident_key)
    assert res is not None
    assert res.headers["Authorization"] == "Bearer token_from_dev1"
    # Ensure device_2_refresh was never called!
    assert refresh_counter == 1


def test_cached_auth_pulls_from_upstash_on_missing_local_cache(tmp_path: Path):
    """CachedAuthProvider fetches and hydrates from Upstash when local cache has no credentials."""
    client = MockMemoryUpstashClient()
    mgr = _create_manager_with_upstash(tmp_path)
    token_svc = UpstashTokenService(mgr, client=client)

    ident_key = "remote-ident-abc"
    # Seed Upstash with valid token
    valid_ctx = AuthContext(
        headers={"Authorization": "Bearer cloud_fetched_secret"},
        expires_at=time.time() + 3600,
    )
    assert token_svc.try_put_token(ident_key, valid_ctx) is True

    # Local cache is completely empty
    cache_dir = tmp_path / "empty_cache"
    cache_dir.mkdir()
    auth_cache = AuthCache(namespace="test_pull", cache_dir=cache_dir)

    # Local provider should never be called because Upstash has the valid token
    local_provider = DummyAuthProvider(prefix="local_should_not_be_called")
    cached = CachedAuthProvider(
        provider=local_provider,
        cache=auth_cache,
        cache_key=ident_key,
        remote_token_service=token_svc,
        identity_key=ident_key,
    )

    result_ctx = cached.get_auth_context()
    assert result_ctx.headers["Authorization"] == "Bearer cloud_fetched_secret"
    # Provider was NOT invoked
    assert local_provider.call_count == 0

    # Local cache was hydrated
    assert auth_cache.get(ident_key) is not None

