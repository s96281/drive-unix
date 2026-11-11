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


def test_refresh_token_safely_does_not_skip_on_null_expiry_historical_token(tmp_path: Path):
    """Ensure refresh_token_safely does not treat historical expires_at: None as valid peer refresh."""
    mgr = _create_manager_with_upstash(tmp_path)
    client = MockMemoryUpstashClient()
    client.acquire_lock = lambda k, o, ttl=15: True
    client.release_lock = lambda k, o: True
    service = UpstashTokenService(mgr, client=client, device_id="dev-local")

    ident_key = "test-ident-legacy"
    # Seed Upstash with historical token that has expires_at: None and updated long ago
    historical_ctx = AuthContext(
        headers={"Cookie": "FedAuth=legacy_cookie"},
        expires_at=None,
    )
    assert service.try_put_token(ident_key, historical_ctx) is True

    # Artificially alter the bundle timestamp in client to simulate it was updated hours ago
    raw_json = client.get(service._token_key(ident_key))
    assert raw_json is not None

    refresh_called = 0

    def mock_refresh():
        nonlocal refresh_called
        refresh_called += 1
        return AuthContext(
            headers={"Cookie": "FedAuth=fresh_cookie"},
            expires_at=time.time() + 345_600,
        )

    # Calling with_distributed_refresh_lock must NOT pick the historical None token,
    # but must invoke mock_refresh and upload the new token!
    result = service.with_distributed_refresh_lock(ident_key, mock_refresh)
    assert refresh_called == 1
    assert result.headers["Cookie"] == "FedAuth=fresh_cookie"
    assert result.expires_at is not None
    assert result.expires_at > time.time() + 300_000


def test_config_manager_reload(tmp_path: Path):
    from core.config import LocalRemote
    mgr = _create_manager_with_upstash(tmp_path)
    assert "new_node" not in mgr.config.remotes

    # Simulate another process editing config.toml on disk
    mgr2 = ConfigManager(mgr.config_path, secret_store=mgr.secret_store)
    mgr2.add_remote("new_node", LocalRemote(type="local", root_path=str(tmp_path)))

    # Before reload, mgr does not have it in memory
    assert "new_node" not in mgr.config.remotes

    # After reload, mgr has it
    mgr.reload()
    assert "new_node" in mgr.config.remotes


def test_sync_topology_if_updated_and_hot_reload(tmp_path: Path):
    from application.upstash_sync_service import UpstashSyncService
    from core.config import OneDriveRemote

    client = MockMemoryUpstashClient()

    # 1. Setup machine A and push remote 'remote_a'
    dir_a = tmp_path / "machine_a"
    dir_a.mkdir()
    mgr_a = _create_manager_with_upstash(dir_a)
    mgr_a.config.remotes["remote_a"] = OneDriveRemote(
        type="onedrive",
        client_id="cid-a",
        tenant="common",
    )
    sync_a = UpstashSyncService(mgr_a, client=client)
    res_push = sync_a.push("sync-pass")
    assert res_push["status"] == "ok"

    # 2. Setup VPS machine (does not have remote_a initially)
    dir_vps = tmp_path / "machine_vps"
    dir_vps.mkdir()
    mgr_vps = _create_manager_with_upstash(dir_vps)
    assert "remote_a" not in mgr_vps.config.remotes

    vps_service = UpstashTokenService(mgr_vps, client=client, device_id="vps-daemon")

    events = []
    def progress_cb(data):
        events.append(data.get("event"))

    # 3. Detect and sync topology on VPS
    res_sync = vps_service.sync_topology_if_updated(progress_cb=progress_cb)
    assert res_sync is not None
    assert "remote_a" in res_sync["restored_remotes"]
    assert "topology_sync_start" in events
    assert "topology_sync_done" in events

    # Verify VPS config_manager was hot-reloaded and now has remote_a!
    assert "remote_a" in mgr_vps.config.remotes

    # 4. Running it again should skip because timestamp matches and no new remotes
    events.clear()
    res_again = vps_service.sync_topology_if_updated(progress_cb=progress_cb)
    assert res_again is None
    assert events == []

    # 5. When auto_pull_topology is disabled, it should return None
    mgr_vps.config.upstash.auto_pull_topology = False
    assert vps_service.sync_topology_if_updated() is None


def test_renew_all_tokens_auto_hot_reloads_new_remotes(tmp_path: Path):
    from application.upstash_sync_service import UpstashSyncService
    from core.config import OneDriveRemote

    client = MockMemoryUpstashClient()
    client.acquire_lock = lambda k, o, ttl=15: True
    client.release_lock = lambda k, o: True

    # 1. Machine A configures and pushes remote_x
    dir_a = tmp_path / "machine_a"
    dir_a.mkdir()
    mgr_a = _create_manager_with_upstash(dir_a)
    mgr_a.config.remotes["remote_x"] = OneDriveRemote(
        type="onedrive",
        client_id="cid-x",
        tenant="common",
    )
    sync_a = UpstashSyncService(mgr_a, client=client)
    sync_a.push("sync-pass")

    # 2. VPS starts with zero remotes
    dir_vps = tmp_path / "machine_vps"
    dir_vps.mkdir()
    mgr_vps = _create_manager_with_upstash(dir_vps)
    assert len(mgr_vps.config.remotes) == 0

    vps_service = UpstashTokenService(mgr_vps, client=client, device_id="vps-daemon")

    mock_auth_prov = MagicMock()
    mock_auth_prov.get_auth_context.return_value = AuthContext(
        headers={"Authorization": "Bearer test"},
        expires_at=time.time() + 3600,
    )
    mock_storage = MagicMock()
    mock_storage.auth_provider = mock_auth_prov

    with patch("storage.registry.DEFAULT_PROVIDER_REGISTRY.create", return_value=mock_storage):
        # 3. VPS runs renew_all_tokens - it should auto-pull remote_x and renew it!
        res = vps_service.renew_all_tokens(leeway_minutes=30)
        assert res["status"] == "ok"
        assert res["topology_synced"] is True
        assert "remote_x" in res["topology_new_remotes"]
        assert "remote_x" in mgr_vps.config.remotes
        assert "remote_x" in res["skipped_remotes"]
