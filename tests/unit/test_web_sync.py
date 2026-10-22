"""Unit tests for Sync Planning and Execution API (/api/sync)."""

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


@pytest.fixture
def sync_env(tmp_path: Path) -> Generator[tuple[ConfigManager, Path, Path], None, None]:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.toml"
    secrets_file = config_dir / "secrets.json"

    secret_store = SecretRepository(secrets_file)
    manager = ConfigManager(config_file, secret_store=secret_store)

    src_root = tmp_path / "source"
    src_root.mkdir(parents=True, exist_ok=True)
    (src_root / "test1.txt").write_text("Hello Sync 1", encoding="utf-8")
    (src_root / "nested").mkdir(parents=True, exist_ok=True)
    (src_root / "nested" / "test2.txt").write_text("Hello Sync 2", encoding="utf-8")

    dst_root = tmp_path / "dest"
    dst_root.mkdir(parents=True, exist_ok=True)

    manager.add_remote("src_node", LocalRemote(type="local", root_path=str(src_root)))
    manager.add_remote("dst_node", LocalRemote(type="local", root_path=str(dst_root)))

    yield manager, src_root, dst_root


@pytest.fixture
def client(sync_env: tuple[ConfigManager, Path, Path]) -> Generator[TestClient, None, None]:
    manager, _, _ = sync_env
    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_sync_plan_creation(client: TestClient) -> None:
    req = {
        "source_uri": "src_node:/",
        "dest_uri": "dst_node:/",
        "two_way": False,
        "conflict": "auto",
        "delete": False,
    }
    resp = client.post("/api/sync/plan", json=req)
    assert resp.status_code == 200
    plan_data = resp.json()
    assert plan_data["total_actions"] >= 2
    action_types = [a["type"] for a in plan_data["actions"]]
    assert "COPY_TO_DEST" in action_types
    assert "capabilities" in plan_data
    assert plan_data["has_destructive"] is False


def test_sync_execution_and_events(
    client: TestClient,
    sync_env: tuple[ConfigManager, Path, Path],
) -> None:
    _, _, dst_root = sync_env

    req = {
        "source_uri": "src_node:/",
        "dest_uri": "dst_node:/",
        "two_way": False,
        "conflict": "auto",
        "delete": False,
        "workers": 2,
    }
    resp = client.post("/api/sync/execute", json=req)
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "started"
    task_id = data["task_id"]

    # Wait for background sync execution to finish
    completed = False
    for _ in range(50):
        st_resp = client.get(f"/api/sync/tasks/{task_id}/status")
        if st_resp.status_code == 200:
            st_data = st_resp.json()
            if st_data.get("status") in {"completed", "failed"}:
                assert st_data["status"] == "completed"
                completed = True
                break
        time.sleep(0.1)

    assert completed, "Sync worker did not complete within timeout"

    # Verify files now exist on destination
    assert (dst_root / "test1.txt").exists()
    assert (dst_root / "test1.txt").read_text(encoding="utf-8") == "Hello Sync 1"
    assert (dst_root / "nested" / "test2.txt").exists()
    assert (dst_root / "nested" / "test2.txt").read_text(encoding="utf-8") == "Hello Sync 2"


def test_sync_cancel_task(client: TestClient) -> None:
    req = {
        "source_uri": "src_node:/",
        "dest_uri": "dst_node:/",
        "two_way": False,
        "conflict": "auto",
        "delete": False,
    }
    resp = client.post("/api/sync/execute", json=req)
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]

    # Cancel immediately
    cancel_resp = client.post(f"/api/sync/tasks/{task_id}/cancel")
    assert cancel_resp.status_code in {200, 404}
