"""Unit tests for the unified setup entry point and setup orchestrator."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.app import create_app
from scripts.setup import SetupOrchestrator, update_or_create_env_file


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_update_or_create_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    example_file = tmp_path / ".env.example"
    example_file.write_text(
        "# Example\nDRIVE_UNIX_HOST=0.0.0.0\nDRIVE_UNIX_PORT=8000\nCUSTOM_VAR=keep_me\n",
        encoding="utf-8",
    )

    # First update: copies template and overrides specified keys
    update_or_create_env_file(
        env_file,
        {"DRIVE_UNIX_HOST": "127.0.0.1", "NEW_VAR": "val123"},
        example_file,
    )

    content = env_file.read_text(encoding="utf-8")
    assert "DRIVE_UNIX_HOST=127.0.0.1" in content
    assert "DRIVE_UNIX_PORT=8000" in content
    assert "CUSTOM_VAR=keep_me" in content
    assert "NEW_VAR=val123" in content

    # Second update: updates existing key in .env
    update_or_create_env_file(
        env_file,
        {"DRIVE_UNIX_PORT": "9000"},
    )
    content2 = env_file.read_text(encoding="utf-8")
    assert "DRIVE_UNIX_PORT=9000" in content2
    assert "DRIVE_UNIX_HOST=127.0.0.1" in content2
    assert "NEW_VAR=val123" in content2


def test_setup_orchestrator_non_interactive_pc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    args = argparse.Namespace(
        role="pc",
        host="127.0.0.1",
        port=8080,
        upstash_url=None,
        upstash_token=None,
        sync_key=None,
        passphrase=None,
        skip_upstash=True,
        skip_playwright=True,
        skip_service=True,
        start=False,
        non_interactive=True,
    )

    orchestrator = SetupOrchestrator(args)
    orchestrator.env_file = tmp_path / ".env"
    orchestrator.config_dir = tmp_path / "config"

    orchestrator.run()

    assert orchestrator.env_file.exists()
    content = orchestrator.env_file.read_text(encoding="utf-8")
    assert "DRIVE_UNIX_HOST=127.0.0.1" in content
    assert "DRIVE_UNIX_PORT=8080" in content
    assert orchestrator.config_dir.exists()


def test_cli_setup_help(runner: CliRunner) -> None:
    app = create_app()
    result = runner.invoke(app, ["setup", "--help"])
    assert result.exit_code == 0
    assert "drive-unix" in result.output
    assert "--role" in result.output
    assert "--upstash-url" in result.output
    assert "--non-interactive" in result.output
