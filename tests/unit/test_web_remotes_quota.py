"""Unit tests for remote quota endpoint and health latency inspection (/api/remotes/{name}/quota)."""

from __future__ import annotations

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
def remote_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    manager = ConfigManager(config_dir / "config.toml", secret_store=SecretRepository(config_dir / "secrets.json"))

    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    manager.add_remote("local_storage", LocalRemote(type="local", root_path=str(storage_dir)))

    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: manager

    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_remote_quota_and_health_integration(remote_client: TestClient):
    # 1. Test connection
    t_resp = remote_client.post("/api/remotes/local_storage/test", json={"write": False})
    assert t_resp.status_code == 200
    assert t_resp.json()["status"] == "success"

    # 2. List remotes and check health attached
    l_resp = remote_client.get("/api/remotes")
    assert l_resp.status_code == 200
    remotes = l_resp.json()["remotes"]
    loc = next(r for r in remotes if r["name"] == "local_storage")
    assert loc["health"] is not None
    assert loc["health"]["status"] == "success"

    # 3. Quota check
    q_resp = remote_client.get("/api/remotes/local_storage/quota")
    assert q_resp.status_code == 200
    data = q_resp.json()
    assert data["name"] == "local_storage"
    assert "supported" in data
