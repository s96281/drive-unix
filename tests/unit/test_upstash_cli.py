from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from typer.testing import CliRunner

from cli.app import create_app
from cli.context import CLIContext
from core.config import ConfigManager, LocalRemote
from core.secrets import SecretRepository

runner = CliRunner()


@pytest.fixture
def isolated_app(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / ".config" / "mycli"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"
    secrets_path = config_dir / "secrets.json"

    repo = SecretRepository(secrets_path, prefer_keyring=False)
    monkeypatch.setattr(
        "cli.context.CLIContext.create",
        lambda: CLIContext(config=ConfigManager(config_path, secret_store=repo)),
    )

    app = create_app()
    return app, config_path, secrets_path, repo


def test_upstash_cli_config(isolated_app):
    app, config_path, secrets_path, repo = isolated_app

    result = runner.invoke(
        app,
        ["upstash", "config", "--url", "https://test.upstash.io", "--token", "secret-token", "--sync-key", "my-key"],
    )
    assert result.exit_code == 0
    assert "Upstash 同步設定已更新" in result.output

    mgr = ConfigManager(config_path, secret_store=repo)
    url, token, key = mgr.get_upstash_config()
    assert url == "https://test.upstash.io"
    assert token == "secret-token"
    assert key == "my-key"


def test_upstash_cli_test_command(isolated_app):
    app, config_path, _, _ = isolated_app

    # Test failure when not configured
    result_fail = runner.invoke(app, ["upstash", "test"])
    assert result_fail.exit_code == 1

    # Configure first
    runner.invoke(
        app,
        ["upstash", "config", "--url", "https://test.upstash.io", "--token", "secret-token"],
    )

    with patch("infrastructure.upstash_client.UpstashClient.ping", return_value=True):
        result_ok = runner.invoke(app, ["upstash", "test"])
        assert result_ok.exit_code == 0
        assert "測試成功" in result_ok.output

        # Test --json flag
        result_json = runner.invoke(app, ["upstash", "test", "--json"])
        assert result_json.exit_code == 0
        data = json.loads(result_json.output.strip())
        assert data["status"] == "ok"
        assert data["ping"] is True


def test_upstash_cli_push_and_pull(isolated_app, tmp_path: Path):
    app, config_path, secrets_path, repo = isolated_app

    # Configure Upstash
    runner.invoke(
        app,
        ["upstash", "config", "--url", "https://test.upstash.io", "--token", "secret-token"],
    )

    # Add a local remote
    mgr = ConfigManager(config_path, secret_store=repo)
    mgr.add_remote("local_docs", LocalRemote(type="local", root_path=str(tmp_path)))

    cloud_db: dict[str, str] = {}

    def mock_get(self, key):
        return cloud_db.get(key)

    def mock_set(self, key, value, ex=None):
        cloud_db[key] = value

    with patch("infrastructure.upstash_client.UpstashClient.get", side_effect=mock_get, autospec=True), \
         patch("infrastructure.upstash_client.UpstashClient.set", side_effect=mock_set, autospec=True):

        # 1. Status when empty
        res_stat1 = runner.invoke(app, ["upstash", "status", "--json"])
        assert res_stat1.exit_code == 0
        data1 = json.loads(res_stat1.output)
        assert data1["exists"] is False

        # 2. Push with passphrase
        res_push = runner.invoke(app, ["upstash", "push", "--passphrase", "testpass", "--yes", "--json"])
        assert res_push.exit_code == 0
        push_json = json.loads(res_push.output)
        assert push_json["status"] == "ok"
        assert push_json["remotes_count"] == 1
        assert "drive-unix:sync:default" in cloud_db

        # 3. Status after push
        res_stat2 = runner.invoke(app, ["upstash", "status", "--json"])
        assert res_stat2.exit_code == 0
        data2 = json.loads(res_stat2.output)
        assert data2["exists"] is True
        assert data2["remotes_count"] == 1
        assert "local_docs" in data2["remote_names"]

        # 4. Pull dry-run
        res_dry = runner.invoke(app, ["upstash", "pull", "--passphrase", "testpass", "--dry-run", "--json"])
        assert res_dry.exit_code == 0
        dry_json = json.loads(res_dry.output)
        assert dry_json["status"] == "dry_run"
        assert "local_docs" in dry_json["incoming_remotes"]

        # 5. Remove local remote, then pull to restore
        mgr = ConfigManager(config_path, secret_store=repo)
        mgr.remove_remote("local_docs")
        assert len(mgr.config.remotes) == 0

        res_pull = runner.invoke(app, ["upstash", "pull", "--passphrase", "testpass", "--yes", "--json"])
        assert res_pull.exit_code == 0
        pull_json = json.loads(res_pull.output)
        assert pull_json["status"] == "ok"
        assert "local_docs" in pull_json["restored_remotes"]

        # Re-check config
        mgr = ConfigManager(config_path, secret_store=repo)
        assert "local_docs" in mgr.config.remotes


def test_upstash_cli_delete(isolated_app):
    app, config_path, _, _ = isolated_app

    runner.invoke(
        app,
        ["upstash", "config", "--url", "https://test.upstash.io", "--token", "secret-token"],
    )

    with patch("infrastructure.upstash_client.UpstashClient.delete", return_value=1):
        res = runner.invoke(app, ["upstash", "delete", "--yes"])
        assert res.exit_code == 0
        assert "已成功自 Upstash 刪除" in res.output
