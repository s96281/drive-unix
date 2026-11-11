"""Unit tests for software upgrade engine, CLI command, and Web API."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from cli.app import create_app
from core.upgrade import (
    UpgradeStatus,
    check_for_updates,
    compare_versions,
    create_pre_upgrade_backup,
    detect_install_mode,
    parse_version,
    restart_service,
    upgrade_manager,
)
from web.app import create_app as create_web_app


def test_parse_version() -> None:
    assert parse_version("0.1.0") == (0, 1, 0)
    assert parse_version("v0.2.1") == (0, 2, 1)
    assert parse_version("1.0") == (1, 0, 0)
    assert parse_version("2") == (2, 0, 0)
    assert parse_version("invalid") == (0, 0, 0)


def test_compare_versions() -> None:
    assert compare_versions("0.1.0", "0.2.0") == -1
    assert compare_versions("0.2.0", "0.1.0") == 1
    assert compare_versions("0.1.0", "0.1.0") == 0
    assert compare_versions("v1.0.0", "1.0.0") == 0
    assert compare_versions("0.1.0", "0.1.1") == -1


def test_detect_install_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Docker mode by env
    monkeypatch.setenv("DRIVE_UNIX_DOCKER", "1")
    assert detect_install_mode(tmp_path) == "docker"

    monkeypatch.delenv("DRIVE_UNIX_DOCKER", raising=False)

    # Git mode
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    assert detect_install_mode(tmp_path) == "git"

    # Pip mode
    empty_dir = tmp_path / "empty_proj"
    empty_dir.mkdir()
    assert detect_install_mode(empty_dir) == "pip"


def test_create_pre_upgrade_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_config = tmp_path / "config"
    fake_config.mkdir()
    (fake_config / "config.toml").write_text("test = 123", encoding="utf-8")

    fake_cache = tmp_path / "cache"
    fake_cache.mkdir()
    (fake_cache / "auth.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr("core.upgrade.DEFAULT_CONFIG_DIR", fake_config)
    monkeypatch.setattr("core.upgrade.DEFAULT_CACHE_DIR", fake_cache)

    backup_file = create_pre_upgrade_backup()
    assert backup_file.is_file()
    assert backup_file.suffix == ".zip"
    assert backup_file.stat().st_size > 0


def test_upgrade_manager_dry_run() -> None:
    events = []

    def on_event(ev_type: str, data: dict):
        events.append((ev_type, data))

    unsub = upgrade_manager.subscribe(on_event)
    try:
        success = upgrade_manager.run_upgrade(dry_run=True, channel="stable")
        assert success is True
        assert len(events) > 0
        event_types = [e[0] for e in events]
        assert "log" in event_types
        assert "step" in event_types
        assert "completed" in event_types
    finally:
        unsub()


def test_cli_upgrade_help() -> None:
    runner = CliRunner()
    app = create_app()
    result = runner.invoke(app, ["upgrade", "--help"])
    assert result.exit_code == 0
    assert "檢查並升級 drive-unix 至最新版本" in result.output
    assert "--check" in result.output
    assert "--dry-run" in result.output


def test_cli_upgrade_dry_run() -> None:
    runner = CliRunner()
    app = create_app()
    result = runner.invoke(app, ["upgrade", "--dry-run", "--force"])
    assert result.exit_code == 0
    assert "開始執行 drive-unix 升級程序" in result.output
    assert "模擬升級成功" in result.output


def test_web_upgrade_api(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_web_app()
    client = TestClient(app)

    # 1. GET /api/upgrade/status
    resp = client.get("/api/upgrade/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "current_version" in data
    assert "latest_version" in data
    assert "has_update" in data
    assert "install_mode" in data

    # 2. POST /api/upgrade/check
    resp = client.post("/api/upgrade/check")
    assert resp.status_code == 200
    data = resp.json()
    assert "current_version" in data

    # 3. POST /api/upgrade/restart
    monkeypatch.setattr("core.upgrade.restart_service", lambda: True)
    resp = client.post("/api/upgrade/restart")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "restarting"
