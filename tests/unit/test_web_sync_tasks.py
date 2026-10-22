"""Unit tests for Sync Task list, pause, resume, and retry (/api/sync/tasks)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Generator

import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from core.config import ConfigManager, LocalRemote
from core.secrets import SecretRepository
from web.app import create_app
from web.dependencies import get_config_manager
from web.events import task_event_manager


@pytest.fixture
def sync_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    manager = ConfigManager(config_dir / "config.toml", secret_store=SecretRepository(config_dir / "secrets.json"))

    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "sample.txt").write_text("Hello Sync", encoding="utf-8")

    dst = tmp_path / "dst"
    dst.mkdir(parents=True, exist_ok=True)

    manager.add_remote("src", LocalRemote(type="local", root_path=str(src)))
    manager.add_remote("dst", LocalRemote(type="local", root_path=str(dst)))

    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: manager

    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_sync_task_listing_and_lifecycle(sync_client: TestClient):
    # 1. Execute sync
    resp = sync_client.post(
        "/api/sync/execute",
        json={"source_uri": "src:/", "dest_uri": "dst:/", "two_way": False, "conflict": "auto", "delete": False},
    )
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]

    # 2. List tasks
    resp_list = sync_client.get("/api/sync/tasks")
    assert resp_list.status_code == 200
    tasks = resp_list.json()
    assert any(t["id"] == task_id for t in tasks)

    # 3. Test pause and resume
    # Register dummy running task to test pause/resume deterministically
    dummy_id = "test-pause-task-id"
    task_event_manager.register_task(dummy_id, kind="sync", title="Test Pause")

    p_resp = sync_client.post(f"/api/sync/tasks/{dummy_id}/pause")
    assert p_resp.status_code == 200
    assert p_resp.json()["status"] == "paused"
    assert task_event_manager.get_record(dummy_id).status == "paused"

    r_resp = sync_client.post(f"/api/sync/tasks/{dummy_id}/resume")
    assert r_resp.status_code == 200
    assert r_resp.json()["status"] == "resumed"
    assert task_event_manager.get_record(dummy_id).status == "running"

    # 4. Test retry
    retry_resp = sync_client.post(f"/api/sync/tasks/{task_id}/retry")
    assert retry_resp.status_code == 202
    new_task_id = retry_resp.json()["task_id"]
    assert new_task_id != task_id
