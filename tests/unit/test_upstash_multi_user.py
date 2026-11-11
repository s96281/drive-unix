"""Unit tests for multi-user / multi-tenant Upstash Redis synchronization."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from application.upstash_sync_service import UpstashSyncService
from application.upstash_token_service import UpstashTokenService
from cli.app import create_app as create_cli_app
from core.config import ConfigManager
from infrastructure.upstash_client import UpstashClient
from web.app import create_app as create_web_app


class MockUpstashStorage:
    def __init__(self):
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str) -> None:
        self.data[key] = value

    def delete(self, key: str) -> int:
        return 1 if self.data.pop(key, None) is not None else 0

    def keys(self, pattern: str = "*") -> list[str]:
        import fnmatch
        return [k for k in self.data.keys() if fnmatch.fnmatch(k, pattern)]

    def mget(self, keys: list[str]) -> list[str | None]:
        return [self.data.get(k) for k in keys]

    def exists(self, key: str) -> bool:
        return key in self.data


@pytest.fixture
def mock_redis():
    storage = MockUpstashStorage()
    with patch.object(UpstashClient, "get", lambda self, k: storage.get(k)), \
         patch.object(UpstashClient, "set", lambda self, k, v, *a, **kw: storage.set(k, v)), \
         patch.object(UpstashClient, "delete", lambda self, k: storage.delete(k)), \
         patch.object(UpstashClient, "keys", lambda self, pattern="*": storage.keys(pattern)), \
         patch.object(UpstashClient, "mget", lambda self, keys: storage.mget(keys)), \
         patch.object(UpstashClient, "exists", lambda self, k: storage.exists(k)):
        yield storage


def test_multi_user_push_pull_isolation(tmp_path: Path, mock_redis: MockUpstashStorage) -> None:
    config_file = tmp_path / "config.toml"
    config_mgr = ConfigManager(config_file)
    config_mgr.set_upstash_config(
        rest_url="https://fake.upstash.io",
        rest_token="fake_token",
        sync_key="drive-unix:sync:default",
    )

    service = UpstashSyncService(config_mgr)

    # 1. Push as default user
    res_def = service.push("pw123", user="default")
    assert res_def["sync_key"] == "drive-unix:sync:default"
    assert "drive-unix:sync:default" in mock_redis.data

    # 2. Push as user1
    res_u1 = service.push("pw123", user="user1")
    assert res_u1["sync_key"] == "drive-unix:sync:user1"
    assert "drive-unix:sync:user1" in mock_redis.data

    # 3. Both exist simultaneously in the same Redis
    assert "drive-unix:sync:default" in mock_redis.data
    assert "drive-unix:sync:user1" in mock_redis.data

    # 4. List users
    users = service.list_users()
    user_names = [u["user"] for u in users]
    assert "default" in user_names
    assert "user1" in user_names

    # 5. Pull for user1 only
    pulled_u1 = service.pull("pw123", user="user1", dry_run=True)
    assert pulled_u1["status"] == "dry_run"

    # 6. Delete user1
    deleted = service.delete_bundle(user="user1")
    assert deleted is True
    assert "drive-unix:sync:user1" not in mock_redis.data
    assert "drive-unix:sync:default" in mock_redis.data


def test_multi_user_token_namespace_isolation(tmp_path: Path, mock_redis: MockUpstashStorage) -> None:
    config_file1 = tmp_path / "config1.toml"
    cm1 = ConfigManager(config_file1)
    cm1.set_upstash_config(
        rest_url="https://fake.upstash.io",
        rest_token="fake_token",
        sync_key="drive-unix:sync:default",
        passphrase="secret",
    )
    token_svc_default = UpstashTokenService(cm1)

    config_file2 = tmp_path / "config2.toml"
    cm2 = ConfigManager(config_file2)
    cm2.set_upstash_config(
        rest_url="https://fake.upstash.io",
        rest_token="fake_token",
        sync_key="drive-unix:sync:user1",
        passphrase="secret",
    )
    token_svc_user1 = UpstashTokenService(cm2)

    # Verify key isolation
    key_def = token_svc_default._token_key("google:test@gmail.com")
    key_u1 = token_svc_user1._token_key("google:test@gmail.com")

    assert key_def == "drive-unix:token:google:test@gmail.com"
    assert key_u1 == "drive-unix:token:user1:google:test@gmail.com"
    assert key_def != key_u1

    lock_def = token_svc_default._lock_key("google:test@gmail.com")
    lock_u1 = token_svc_user1._lock_key("google:test@gmail.com")

    assert lock_def == "drive-unix:lock:google:test@gmail.com"
    assert lock_u1 == "drive-unix:lock:user1:google:test@gmail.com"
    assert lock_def != lock_u1


def test_web_upstash_users_endpoint(mock_redis: MockUpstashStorage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://fake.upstash.io")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "fake_token")

    app = create_web_app()
    client = TestClient(app)

    metadata = {
        "metadata": {
            "created_at": "2026-11-11T20:00:00Z",
            "device_name": "worker-1",
            "remotes_count": 3,
            "remote_names": ["gdrive", "onedrive", "local"],
        }
    }
    mock_redis.set("drive-unix:sync:user1", json.dumps(metadata))

    resp = client.get("/api/upstash/users")
    assert resp.status_code == 200
    users = resp.json()
    user_keys = [u["sync_key"] for u in users]
    assert "drive-unix:sync:user1" in user_keys


def test_cli_upstash_list_users() -> None:
    runner = CliRunner()
    app = create_cli_app()
    result = runner.invoke(app, ["upstash", "list-users", "--help"])
    assert result.exit_code == 0
    assert "list-users" in result.output
