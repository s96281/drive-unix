from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from core.config import ConfigManager, LocalRemote
from core.secrets import SecretRepository
from web.app import create_app
from web.dependencies import get_config_manager


@pytest.fixture
def temp_workspace(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.toml"
    secrets_file = config_dir / "secrets.json"

    secret_store = SecretRepository(secrets_file, prefer_keyring=False)
    manager = ConfigManager(config_file, secret_store=secret_store)

    local_root = tmp_path / "local_storage"
    local_root.mkdir(parents=True, exist_ok=True)
    manager.add_remote("my_local", LocalRemote(type="local", root_path=str(local_root)))

    return manager, local_root


@pytest.fixture
def client(temp_workspace):
    manager, _ = temp_workspace
    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: manager
    return TestClient(app)


def test_web_upstash_config_endpoints(client: TestClient):
    # 1. Get initial config
    res1 = client.get("/api/upstash/config")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["has_token"] is False

    # 2. Update config
    res2 = client.post(
        "/api/upstash/config",
        json={
            "rest_url": "https://test.upstash.io",
            "rest_token": "secret-token-123",
            "sync_key": "custom:key",
        },
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["rest_url"] == "https://test.upstash.io"
    assert data2["has_token"] is True
    assert data2["sync_key"] == "custom:key"


def test_web_upstash_test_endpoint(client: TestClient):
    client.post(
        "/api/upstash/config",
        json={"rest_url": "https://test.upstash.io", "rest_token": "token"},
    )

    with patch("infrastructure.upstash_client.UpstashClient.ping", return_value=True):
        res = client.post("/api/upstash/test")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"
        assert res.json()["ping"] is True


def test_web_upstash_push_and_pull(client: TestClient):
    client.post(
        "/api/upstash/config",
        json={"rest_url": "https://test.upstash.io", "rest_token": "token"},
    )

    cloud_db = {}

    def mock_get(self, key):
        return cloud_db.get(key)

    def mock_set(self, key, value, ex=None):
        cloud_db[key] = value

    with patch("infrastructure.upstash_client.UpstashClient.get", side_effect=mock_get, autospec=True), \
         patch("infrastructure.upstash_client.UpstashClient.set", side_effect=mock_set, autospec=True):

        # Push
        res_push = client.post("/api/upstash/push", json={"passphrase": "my-secret-pw"})
        assert res_push.status_code == 200
        assert res_push.json()["status"] == "ok"
        assert res_push.json()["remotes_count"] == 1

        # Status
        res_stat = client.get("/api/upstash/status")
        assert res_stat.status_code == 200
        assert res_stat.json()["exists"] is True
        assert res_stat.json()["remotes_count"] == 1

        # Pull Dry Run
        res_dry = client.post("/api/upstash/pull", json={"passphrase": "my-secret-pw", "dry_run": True})
        assert res_dry.status_code == 200
        assert res_dry.json()["status"] == "dry_run"

        # Pull Wrong Passphrase -> 403 Forbidden
        res_wrong = client.post("/api/upstash/pull", json={"passphrase": "wrong-pw"})
        assert res_wrong.status_code == 403

        # Pull Success
        res_pull = client.post("/api/upstash/pull", json={"passphrase": "my-secret-pw", "strategy": "merge"})
        assert res_pull.status_code == 200
        assert res_pull.json()["status"] == "ok"


def test_web_upstash_extended_config_and_renew_tokens(client: TestClient):
    # 1. Update config with passphrase and token sync switches
    res = client.post(
        "/api/upstash/config",
        json={
            "rest_url": "https://test.upstash.io",
            "rest_token": "token-xyz",
            "passphrase": "master-passphrase",
            "auto_sync_tokens": True,
            "auto_push_tokens": False,
            "renew_leeway_minutes": 45,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["has_token"] is True
    assert data["has_passphrase"] is True
    assert data["auto_sync_tokens"] is True
    assert data["auto_push_tokens"] is False
    assert data["renew_leeway_minutes"] == 45

    # 2. Call renew-tokens endpoint
    with patch("application.upstash_token_service.UpstashTokenService.renew_all_tokens") as mock_renew:
        mock_renew.return_value = {
            "status": "ok",
            "unique_identities_count": 1,
            "renewed_remotes": ["site_a"],
            "skipped_remotes": [],
            "errors": {},
        }
        res_renew = client.post(
            "/api/upstash/renew-tokens",
            json={"leeway_minutes": 45},
        )
        assert res_renew.status_code == 200
        renew_data = res_renew.json()
        assert renew_data["status"] == "ok"
        assert renew_data["renewed_remotes"] == ["site_a"]
        mock_renew.assert_called_once_with(leeway_minutes=45, remote_filter=None)

