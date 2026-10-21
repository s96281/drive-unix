from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from application.upstash_token_service import UpstashTokenService
from auth.base import AuthContext
from core.config import ConfigManager, UpstashSyncConfig
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


def test_upstash_token_put_and_get(tmp_path: Path):
    mgr = _create_manager_with_upstash(tmp_path)
    client = MockMemoryUpstashClient()
    service = UpstashTokenService(mgr, client=client, device_id="dev-1")

    now = time.time()
    ctx = AuthContext(
        headers={"Authorization": "Bearer ya29.test1234"},
        expires_at=now + 3600,
    )

    raw_file = tmp_path / "raw_token.json"
    raw_file.write_text('{"token": "ya29.test1234"}', encoding="utf-8")

    # 1. Put token
    ok = service.try_put_token("auth-hash-1", ctx, raw_cache_path=raw_file)
    assert ok is True
    assert "drive-unix:token:auth-hash-1" in client.store

    # 2. Get token on another instance
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    mgr2 = _create_manager_with_upstash(dest_dir)
    service2 = UpstashTokenService(mgr2, client=client, device_id="dev-2")

    dest_raw_file = dest_dir / "restored_token.json"
    retrieved = service2.try_get_token("auth-hash-1", raw_cache_path=dest_raw_file)
    assert retrieved is not None
    assert retrieved.headers["Authorization"] == "Bearer ya29.test1234"
    assert retrieved.expires_at == ctx.expires_at

    # Verify underlying raw token was also restored
    assert dest_raw_file.exists()
    assert dest_raw_file.read_text(encoding="utf-8") == '{"token": "ya29.test1234"}'


def test_expired_cloud_token_is_ignored(tmp_path: Path):
    mgr = _create_manager_with_upstash(tmp_path)
    client = MockMemoryUpstashClient()
    service = UpstashTokenService(mgr, client=client)

    # Token expired 10 minutes ago
    expired_ctx = AuthContext(
        headers={"Authorization": "Bearer expired"},
        expires_at=time.time() - 600,
    )
    service.try_put_token("auth-hash-expired", expired_ctx)

    got = service.try_get_token("auth-hash-expired")
    assert got is None


def test_with_distributed_refresh_lock(tmp_path: Path):
    mgr = _create_manager_with_upstash(tmp_path)
    client = MockMemoryUpstashClient()
    # Mock acquire_lock and release_lock on client
    client.acquire_lock = lambda k, o, ttl=15: True
    client.release_lock = lambda k, o: True

    service = UpstashTokenService(mgr, client=client)

    refreshed_called = False

    def mock_refresh():
        nonlocal refreshed_called
        refreshed_called = True
        return AuthContext(headers={"Authorization": "Bearer new_tok"}, expires_at=time.time() + 3600)

    result = service.with_distributed_refresh_lock("ident-1", mock_refresh)
    assert refreshed_called is True
    assert result.headers["Authorization"] == "Bearer new_tok"
    assert "drive-unix:token:ident-1" in client.store


def test_renew_all_tokens_reporting_and_progress(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("UPSTASH_SYNC_PASSPHRASE", raising=False)
    from core.config import OneDriveRemote
    mgr = _create_manager_with_upstash(tmp_path)
    # Add a mock OneDrive remote
    mgr.config.remotes["od_test"] = OneDriveRemote(
        type="onedrive",
        client_id="client-123",
        tenant="common",
    )

    client = MockMemoryUpstashClient()
    client.acquire_lock = lambda k, o, ttl=15: True
    client.release_lock = lambda k, o: True
    service = UpstashTokenService(mgr, client=client)

    events: list[str] = []

    def mock_progress(data: dict):
        events.append(data.get("event", ""))

    mock_auth_prov = MagicMock()
    mock_auth_prov.get_auth_context.return_value = AuthContext(
        headers={"Authorization": "Bearer old"},
        expires_at=time.time() - 100,  # Expired
    )
    mock_auth_prov.refresh.return_value = AuthContext(
        headers={"Authorization": "Bearer new"},
        expires_at=time.time() + 3600,
    )

    mock_storage = MagicMock()
    mock_storage.auth_provider = mock_auth_prov

    with patch("storage.registry.DEFAULT_PROVIDER_REGISTRY.create", return_value=mock_storage):
        # 1. When cloud sync is enabled (has passphrase)
        res = service.renew_all_tokens(leeway_minutes=30, progress_cb=mock_progress)
        assert res["status"] == "ok"
        assert res["cloud_enabled"] is True
        assert "od_test" in res["renewed_remotes"]
        assert "start" in events
        assert "checking" in events
        assert "refreshing" in events
        assert "renewed" in events

        # 2. When cloud sync is disabled (remove passphrase)
        mgr.config.upstash.passphrase_ref = None
        service2 = UpstashTokenService(mgr, client=client)
        res_disabled = service2.renew_all_tokens(leeway_minutes=30)
        assert res_disabled["cloud_enabled"] is False
        assert "Passphrase" in (res_disabled["cloud_disabled_reason"] or "")
