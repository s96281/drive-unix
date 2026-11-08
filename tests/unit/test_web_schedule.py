"""Unit tests for Cron Schedule API (/api/schedule)."""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from core.config import ConfigManager
from core.secrets import SecretRepository
from web.app import create_app
from web.dependencies import get_config_manager


@pytest.fixture
def schedule_env(tmp_path: Path) -> Generator[ConfigManager, None, None]:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.toml"
    secrets_file = config_dir / "secrets.json"

    secret_store = SecretRepository(secrets_file)
    manager = ConfigManager(config_file, secret_store=secret_store)
    yield manager


@pytest.fixture
def client(schedule_env: ConfigManager) -> Generator[TestClient, None, None]:
    manager = schedule_env
    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_schedule_lifecycle(client: TestClient) -> None:
    # 1. Initially empty
    list_resp = client.get("/api/schedule")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 0

    # 2. Create task
    create_payload = {
        "name": "daily_backup",
        "schedule": "0 2 * * *",
        "command": "drive-unix sync local:/data remote:/backup",
        "enabled": True,
    }
    create_resp = client.post("/api/schedule", json=create_payload)
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["name"] == "daily_backup"
    assert created["enabled"] is True

    # 3. Toggle task
    toggle_resp = client.post("/api/schedule/daily_backup/toggle", json={"enabled": False})
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()["enabled"] is False

    # 4. Delete task
    del_resp = client.delete("/api/schedule/daily_backup")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"

    # Verify list is empty again
    final_list = client.get("/api/schedule")
    assert len(final_list.json()) == 0
