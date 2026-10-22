"""Unit tests for Web API remotes management and connection testing."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Generator

import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from core.config import ConfigManager, LocalRemote
from core.secrets import SecretRepository
from web.app import create_app
from web.dependencies import get_config_manager


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Generator[tuple[ConfigManager, Path], None, None]:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.toml"
    secrets_file = config_dir / "secrets.json"

    secret_store = SecretRepository(secrets_file)
    manager = ConfigManager(config_file, secret_store=secret_store)

    # Setup a local remote root
    local_root = tmp_path / "local_storage"
    local_root.mkdir(parents=True, exist_ok=True)
    manager.add_remote("my_local", LocalRemote(type="local", root_path=str(local_root)))

    yield manager, local_root


@pytest.fixture
def client(temp_workspace: tuple[ConfigManager, Path]) -> Generator[TestClient, None, None]:
    manager, _ = temp_workspace
    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_check(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_list_remotes(client: TestClient) -> None:
    resp = client.get("/api/remotes")
    assert resp.status_code == 200
    data = resp.json()
    assert "supported_types" in data
    assert "remotes" in data
    assert any(r["name"] == "my_local" for r in data["remotes"])


def test_create_and_delete_remote_with_secret(
    client: TestClient,
    temp_workspace: tuple[ConfigManager, Path],
) -> None:
    manager, _ = temp_workspace

    # 1. Create SFTP remote with plaintext password
    payload = {
        "name": "backup_sftp",
        "type": "sftp",
        "password": "super-secret-password-123",
        "params": {
            "host": "192.168.1.100",
            "port": 22,
            "username": "admin",
            "root_path": "/data",
        },
    }
    resp = client.post("/api/remotes", json=payload)
    assert resp.status_code == 201
    created = resp.json()
    assert created["name"] == "backup_sftp"
    assert created["type"] == "sftp"
    # Verify zero password leakage in response
    assert "super-secret-password-123" not in str(created)
    assert created["details"].get("password_ref") is not None

    # Verify secret is stored securely in secret store
    pw_ref = created["details"]["password_ref"]
    assert manager.secret_store.get(pw_ref) == "super-secret-password-123"

    # 2. Get remote by name
    get_resp = client.get("/api/remotes/backup_sftp")
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "backup_sftp"
    assert "super-secret-password-123" not in str(get_resp.json())

    # 3. Delete remote
    del_resp = client.delete("/api/remotes/backup_sftp")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"

    # Verify secret reference is purged
    assert manager.secret_store.get(pw_ref) is None
    assert "backup_sftp" not in manager.config.remotes


def test_test_remote_connection(client: TestClient) -> None:
    # Test read only
    resp = client.post("/api/remotes/my_local/test", json={"write": False})
    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "success"
    assert result["read_ok"] is True
    assert result["write_ok"] is False

    # Test read + write
    resp_write = client.post("/api/remotes/my_local/test", json={"write": True})
    assert resp_write.status_code == 200
    result_write = resp_write.json()
    assert result_write["status"] == "success"
    assert result_write["read_ok"] is True
    assert result_write["write_ok"] is True
    assert result_write["delete_capability"] is not None


def test_remote_duplicate_and_not_found(client: TestClient) -> None:
    # 404 for unknown remote
    resp = client.get("/api/remotes/non_existent")
    assert resp.status_code == 404

    # 409 for duplicate create
    resp_dup = client.post(
        "/api/remotes",
        json={"name": "my_local", "type": "local", "params": {"root_path": "/tmp"}},
    )
    assert resp_dup.status_code == 409
