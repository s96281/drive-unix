from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from cli.app import create_app
import cli.commands.nodes as nodes
from core.config import ConfigManager, PikPakRemote
from core.secrets import SecretRepository

runner = CliRunner()


def _file_repo(tmp_path: Path) -> SecretRepository:
    return SecretRepository(tmp_path / "secrets.json", prefer_keyring=False)


def test_add_pikpak_rejects_plaintext_password_option(tmp_path: Path, monkeypatch) -> None:
    manager = ConfigManager(tmp_path / "config.toml", secret_store=_file_repo(tmp_path))
    monkeypatch.setattr(
        nodes.CLIContext,
        "create",
        lambda: SimpleNamespace(config=manager),
    )

    result = runner.invoke(
        create_app(),
        ["add-pikpak", "mypik", "user@example.com", "--password", "plaintext_pass"],
    )

    assert result.exit_code != 0
    assert "禁止使用 --password" in result.output or "Plaintext password flag is prohibited" in result.output
    assert "mypik" not in manager.config.remotes


def test_add_pikpak_with_password_env_stores_reference_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PIKPAK_SECRET", "super_secret_env_pass")
    config_path = tmp_path / "config.toml"
    manager = ConfigManager(config_path, secret_store=_file_repo(tmp_path))
    monkeypatch.setattr(
        nodes.CLIContext,
        "create",
        lambda: SimpleNamespace(config=manager),
    )

    result = runner.invoke(
        create_app(),
        ["add-pikpak", "mypik", "user@example.com", "--password-env", "PIKPAK_SECRET"],
    )

    assert result.exit_code == 0, result.output
    remote = manager.get_remote("mypik")
    assert remote.type == "pikpak"
    assert remote.username == "user@example.com"
    assert remote.password_ref == "env:PIKPAK_SECRET"

    config_text = config_path.read_text(encoding="utf-8")
    assert "super_secret_env_pass" not in config_text
    assert 'password_ref = "env:PIKPAK_SECRET"' in config_text
    assert "password =" not in config_text


def test_add_pikpak_interactive_prompt_stores_in_secret_repo(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    repository = _file_repo(tmp_path)
    manager = ConfigManager(config_path, secret_store=repository)
    monkeypatch.setattr(
        nodes.CLIContext,
        "create",
        lambda: SimpleNamespace(config=manager),
    )

    result = runner.invoke(
        create_app(),
        ["add-pikpak", "mypik", "user@example.com"],
        input="my_interactive_password\n",
    )

    assert result.exit_code == 0, result.output
    remote = manager.get_remote("mypik")
    assert isinstance(remote, PikPakRemote)
    assert remote.password_ref == "file:remote/mypik/password"

    resolved = manager.resolve_secret(remote.password_ref, remote_name="mypik", label="password")
    assert resolved == "my_interactive_password"

    config_text = config_path.read_text(encoding="utf-8")
    assert "my_interactive_password" not in config_text
    assert 'password_ref = "file:remote/mypik/password"' in config_text
    assert "password =" not in config_text


def test_legacy_inline_password_migrated_out_of_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[remotes.mypik]
type = "pikpak"
username = "user@example.com"
password = "legacy_inline_pass"
""".strip(),
        encoding="utf-8",
    )
    repository = _file_repo(tmp_path)
    manager = ConfigManager(config_path, secret_store=repository)
    remote = manager.get_remote("mypik")
    assert isinstance(remote, PikPakRemote)

    assert remote.password_ref == "file:remote/mypik/password"
    assert manager.resolve_secret(remote.password_ref, remote_name="mypik", label="password") == "legacy_inline_pass"

    saved = config_path.read_text(encoding="utf-8")
    assert "legacy_inline_pass" not in saved
    assert "password =" not in saved
    assert 'password_ref = "file:remote/mypik/password"' in saved
