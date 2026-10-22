"""Unit tests for Upstash token metadata inspection and lock release (/api/upstash/tokens)."""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from core.config import ConfigManager, LocalRemote, OneDriveRemote
from core.secrets import SecretRepository
from web.app import create_app
from web.dependencies import get_config_manager


@pytest.fixture
def upstash_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    manager = ConfigManager(config_dir / "config.toml", secret_store=SecretRepository(config_dir / "secrets.json"))

    # Add an OAuth remote
    manager.add_remote("od_work", OneDriveRemote(type="onedrive", client_id="test_client_id"))
    manager.add_remote("local_node", LocalRemote(type="local", root_path=str(tmp_path)))

    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: manager

    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_list_tokens_endpoint(upstash_client: TestClient):
    resp = upstash_client.get("/api/upstash/tokens")
    assert resp.status_code == 200
    tokens = resp.json()
    assert isinstance(tokens, list)
    assert any("od_work" in t["remotes"] for t in tokens)
