"""Unit tests for virtual filesystem file operations (/api/fs rename, move, copy, transfer)."""

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
def fs_env(tmp_path: Path) -> Generator[tuple[TestClient, Path, Path], None, None]:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    manager = ConfigManager(config_dir / "config.toml", secret_store=SecretRepository(config_dir / "secrets.json"))

    src_root = tmp_path / "local_a"
    src_root.mkdir(parents=True, exist_ok=True)
    dst_root = tmp_path / "local_b"
    dst_root.mkdir(parents=True, exist_ok=True)

    manager.add_remote("node_a", LocalRemote(type="local", root_path=str(src_root)))
    manager.add_remote("node_b", LocalRemote(type="local", root_path=str(dst_root)))

    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: manager

    with TestClient(app) as client:
        yield client, src_root, dst_root
    app.dependency_overrides.clear()


def test_fs_rename_file(fs_env: tuple[TestClient, Path, Path]):
    client, src_root, _ = fs_env
    file_path = src_root / "old_name.txt"
    file_path.write_text("Hello Rename", encoding="utf-8")

    resp = client.post(
        "/api/fs/node_a/rename",
        json={"path": "/old_name.txt", "new_name": "new_name.txt"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "renamed"
    assert data["new_path"] == "/new_name.txt"
    assert not file_path.exists()
    assert (src_root / "new_name.txt").exists()


def test_fs_move_file(fs_env: tuple[TestClient, Path, Path]):
    client, src_root, _ = fs_env
    sub_dir = src_root / "sub"
    sub_dir.mkdir(parents=True, exist_ok=True)
    file_path = src_root / "move_me.txt"
    file_path.write_text("Move Content", encoding="utf-8")

    resp = client.post(
        "/api/fs/node_a/move",
        json={"source": "/move_me.txt", "destination": "/sub/move_me.txt", "overwrite": False},
    )
    assert resp.status_code == 200
    assert not file_path.exists()
    assert (sub_dir / "move_me.txt").exists()


def test_fs_copy_file(fs_env: tuple[TestClient, Path, Path]):
    client, src_root, _ = fs_env
    file_path = src_root / "copy_me.txt"
    file_path.write_text("Copy Content", encoding="utf-8")

    resp = client.post(
        "/api/fs/node_a/copy",
        json={"source": "/copy_me.txt", "destination": "/copied.txt", "overwrite": False},
    )
    assert resp.status_code == 200
    assert file_path.exists()
    assert (src_root / "copied.txt").exists()
    assert (src_root / "copied.txt").read_text(encoding="utf-8") == "Copy Content"


def test_fs_cross_remote_transfer(fs_env: tuple[TestClient, Path, Path]):
    client, src_root, dst_root = fs_env
    file_a = src_root / "file_a.txt"
    file_a.write_text("Cross transfer file A", encoding="utf-8")

    resp = client.post(
        "/api/fs/transfer",
        json={"sources": ["node_a:/file_a.txt"], "dest_dir": "node_b:/", "mode": "copy"},
    )
    assert resp.status_code == 202
    task_id = resp.json()["task_id"]

    # Wait briefly for background worker
    for _ in range(30):
        st = task_event_manager.get_status(task_id)
        if st and st.get("status") in ("completed", "failed"):
            break
        time.sleep(0.1)

    assert (dst_root / "file_a.txt").exists()
    assert (dst_root / "file_a.txt").read_text(encoding="utf-8") == "Cross transfer file A"
    assert file_a.exists()  # mode was copy
