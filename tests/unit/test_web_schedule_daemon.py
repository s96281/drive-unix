"""Unit tests for schedule next_run calculation, PUT task, and daemon status (/api/schedule)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Generator

import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from application.scheduling import next_cron_occurrence, validate_cron_expression
from core.config import ConfigManager
from core.secrets import SecretRepository
from web.app import create_app
from web.dependencies import get_config_manager


def test_next_cron_occurrence_patterns():
    # 1. Every 5 minutes
    now = datetime(2026, 10, 22, 10, 3, 0)
    nxt = next_cron_occurrence("*/5 * * * *", now)
    assert nxt == datetime(2026, 10, 22, 10, 5, 0)

    # 2. Daily at 02:00
    now = datetime(2026, 10, 22, 10, 30, 0)
    nxt = next_cron_occurrence("0 2 * * *", now)
    assert nxt == datetime(2026, 10, 23, 2, 0, 0)

    # 3. Specific month and day
    now = datetime(2026, 10, 22, 0, 0, 0)
    nxt = next_cron_occurrence("0 0 1 12 *", now)
    assert nxt == datetime(2026, 12, 1, 0, 0, 0)


@pytest.fixture
def sched_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    manager = ConfigManager(config_dir / "config.toml", secret_store=SecretRepository(config_dir / "secrets.json"))

    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: manager

    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_schedule_crud_and_next_run(sched_client: TestClient):
    # 1. Create task
    res = sched_client.post(
        "/api/schedule",
        json={"name": "daily_backup", "schedule": "0 2 * * *", "command": "drive-unix sync a: b:", "enabled": True},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["next_run"] is not None
    assert " 02:00:00" in data["next_run"]

    # 2. Update task via PUT
    put_res = sched_client.put(
        "/api/schedule/daily_backup",
        json={"schedule": "*/15 * * * *"},
    )
    assert put_res.status_code == 200
    assert put_res.json()["schedule"] == "*/15 * * * *"

    # 3. Invalid cron validation
    bad_res = sched_client.put(
        "/api/schedule/daily_backup",
        json={"schedule": "invalid cron format"},
    )
    assert bad_res.status_code == 422


def test_daemon_status_endpoint(sched_client: TestClient):
    res = sched_client.get("/api/schedule/daemon/status")
    assert res.status_code == 200
    data = res.json()
    assert "installed" in data
    assert "running" in data
    assert "backend" in data
    assert "log_tail" in data
