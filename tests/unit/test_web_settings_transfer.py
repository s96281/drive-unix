"""Unit tests for transfer settings and bandwidth rate limit configuration (/api/settings)."""

from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from core.config import ConfigManager
from core.secrets import SecretRepository
from web.app import create_app
from web.bandwidth import bandwidth_limiter
from web.dependencies import get_config_manager


@pytest.fixture
def settings_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    manager = ConfigManager(config_dir / "config.toml", secret_store=SecretRepository(config_dir / "secrets.json"))

    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: manager

    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_update_transfer_settings(settings_client: TestClient):
    # Update transfer settings
    resp = settings_client.put(
        "/api/settings",
        json={"transfer": {"max_workers": 8, "bandwidth_limit_kbps": 5000, "log_level": "DEBUG"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["settings"]["transfer"]["max_workers"] == 8
    assert data["settings"]["transfer"]["bandwidth_limit_kbps"] == 5000
    assert data["settings"]["transfer"]["log_level"] == "DEBUG"

    # Verify limiter updated
    assert bandwidth_limiter.limit_kbps == 5000
