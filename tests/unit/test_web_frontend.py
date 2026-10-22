"""Unit tests for Web static frontend mounting and delivery."""

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
def test_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.toml"
    secrets_file = config_dir / "secrets.json"

    secret_store = SecretRepository(secrets_file)
    manager = ConfigManager(config_file, secret_store=secret_store)

    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: manager
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_static_index_html_delivery(test_client: TestClient) -> None:
    resp = test_client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "drive-unix" in resp.text
    assert 'id="root"' in resp.text
    assert "assets/index-" in resp.text


def test_spa_deep_links(test_client: TestClient) -> None:
    for route in ["/remotes", "/files", "/sync", "/schedule", "/settings"]:
        resp = test_client.get(route)
        assert resp.status_code == 200
        assert 'id="root"' in resp.text


def test_legacy_html_delivery(test_client: TestClient) -> None:
    resp = test_client.get("/legacy.html")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "drive-unix" in resp.text
    assert "Pane A" in resp.text
    assert "Pane B" in resp.text
    assert "fluent-acrylic" in resp.text
    assert "目錄快取" in resp.text
    assert "網頁設定" in resp.text

