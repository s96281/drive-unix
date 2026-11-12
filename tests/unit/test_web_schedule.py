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


def test_schedule_create_and_update_with_cron_alias(client: TestClient) -> None:
    # Test create with cron field instead of schedule
    create_payload = {
        "name": "cron_alias_task",
        "cron": "0 3 * * *",
        "command": "drive-unix sync local:/data remote:/backup --mirror",
        "enabled": True,
    }
    create_resp = client.post("/api/schedule", json=create_payload)
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["name"] == "cron_alias_task"
    assert created["schedule"] == "0 3 * * *"
    assert created["cron"] == "0 3 * * *"

    # Test update with cron field
    update_payload = {"cron": "30 4 * * *"}
    update_resp = client.put("/api/schedule/cron_alias_task", json=update_payload)
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["schedule"] == "30 4 * * *"
    assert updated["cron"] == "30 4 * * *"

    # Clean up
    client.delete("/api/schedule/cron_alias_task")


def test_schedule_run_task_now(client: TestClient, monkeypatch) -> None:
    from unittest.mock import Mock

    # Create a task with drive-unix command without prefix
    create_payload = {
        "name": "manual_sync_task",
        "schedule": "0 1 * * *",
        "command": 'sync --delete 桌面:/ "dest:/backup"',
        "enabled": True,
    }
    client.post("/api/schedule", json=create_payload)

    # Mock subprocess.run inside worker thread to avoid real subprocess execution in unit test
    mock_sub = Mock(returncode=0)
    monkeypatch.setattr("web.routers.schedule.subprocess.run", lambda *args, **kwargs: mock_sub)

    resp = client.post("/api/schedule/manual_sync_task/run")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "triggered"
    assert data["name"] == "manual_sync_task"
    assert "attempted_at" in data

    # 404 for non-existing task
    resp_404 = client.post("/api/schedule/non_existent_task/run")
    assert resp_404.status_code == 404

    # Clean up
    client.delete("/api/schedule/manual_sync_task")


def test_resolve_task_command() -> None:
    from web.routers.schedule import resolve_task_command

    # 1. Subcommand without prefix
    cmd1 = resolve_task_command('sync --delete 桌面:/ "remote:/data"')
    assert "sync" in cmd1
    assert "--delete" in cmd1
    assert any("main.py" in str(arg) for arg in cmd1)

    # 2. Command with drive-unix prefix
    cmd2 = resolve_task_command("drive-unix copy remoteA:/ remoteB:/")
    assert "copy" in cmd2
    assert "remoteA:/" in cmd2
    assert "drive-unix" not in cmd2[2:]  # stripped from subcommand args

