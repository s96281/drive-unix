from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.app import create_app
from core.config import ConfigManager
from core.secrets import SecretRepository


runner = CliRunner()


def _file_repo(tmp_path: Path) -> SecretRepository:
    return SecretRepository(tmp_path / "secrets.json", prefer_keyring=False)


def test_legacy_inline_password_is_migrated_out_of_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[remotes.work]
type = "sharepoint"
base_url = "https://tenant.example"
site = "/sites/work"
email = "user@example.com"
password = "do-not-leave-me-in-toml"
""".strip(),
        encoding="utf-8",
    )
    repository = _file_repo(tmp_path)

    manager = ConfigManager(config_path, secret_store=repository)
    remote = manager.get_remote("work")

    assert remote.password_ref == "file:remote/work/password"
    assert manager.resolve_secret(
        remote.password_ref,
        remote_name="work",
        label="password",
    ) == "do-not-leave-me-in-toml"

    saved = config_path.read_text(encoding="utf-8")
    assert "do-not-leave-me-in-toml" not in saved
    assert "password =" not in saved
    assert 'password_ref = "file:remote/work/password"' in saved


def test_legacy_onedrive_client_secret_is_migrated(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[remotes.ms]
type = "onedrive"
client_id = "client-id"
client_secret = "legacy-secret"
tenant = "common"
""".strip(),
        encoding="utf-8",
    )
    manager = ConfigManager(config_path, secret_store=_file_repo(tmp_path))
    remote = manager.get_remote("ms")

    assert remote.client_secret_ref == "file:remote/ms/client-secret"
    assert "legacy-secret" not in config_path.read_text(encoding="utf-8")


def test_environment_reference_does_not_persist_secret(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WORK_PASSWORD", "from-env")
    repository = _file_repo(tmp_path)
    manager = ConfigManager(tmp_path / "config.toml", secret_store=repository)

    reference = manager.environment_secret_ref("WORK_PASSWORD")

    assert reference == "env:WORK_PASSWORD"
    assert manager.resolve_secret(reference, remote_name="work", label="password") == "from-env"
    assert not repository.file_path.exists()


def test_file_secret_store_permissions_are_private(tmp_path: Path) -> None:
    repository = _file_repo(tmp_path)
    reference = repository.put("remote/work/password", "secret")

    assert reference == "file:remote/work/password"
    if os.name != "nt":
        assert repository.file_path.stat().st_mode & 0o777 == 0o600
        assert repository.file_path.parent.stat().st_mode & 0o777 == 0o700


def test_remove_remote_deletes_owned_file_secret(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    repository = _file_repo(tmp_path)
    config_path.write_text(
        """
[remotes.work]
type = "webdav"
base_url = "https://dav.example"
username = "user"
password = "legacy-secret"
""".strip(),
        encoding="utf-8",
    )
    manager = ConfigManager(config_path, secret_store=repository)
    reference = manager.get_remote("work").password_ref
    assert reference is not None

    manager.remove_remote("work")

    assert repository.get(reference) is None


def test_cli_rejects_plaintext_password_option() -> None:
    result = runner.invoke(
        create_app(),
        [
            "add-sp", "work", "https://tenant.example", "/sites/work", "u@example.com",
            "--password", "visible-in-process-list",
        ],
    )

    assert result.exit_code != 0
    assert "No such option" in result.output


def test_cli_rejects_plaintext_onedrive_secret_option() -> None:
    result = runner.invoke(
        create_app(),
        ["add-onedrive", "ms", "client-id", "--secret", "visible-secret"],
    )

    assert result.exit_code != 0
    assert "No such option" in result.output


def test_export_excludes_secret_material_by_default(tmp_path: Path, monkeypatch) -> None:
    import cli.commands.environment as environment

    config_dir = tmp_path / "config"
    cache_dir = tmp_path / "cache"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('default_remote = "local"\n', encoding="utf-8")
    (config_dir / "secrets.json").write_text('{"x":"secret"}\n', encoding="utf-8")
    secret_files = config_dir / "secret-files"
    secret_files.mkdir()
    (secret_files / "oauth.json").write_text('{"client_secret":"secret"}', encoding="utf-8")
    legacy_secret_files = config_dir / "secrets"
    legacy_secret_files.mkdir()
    (legacy_secret_files / "old.json").write_text("secret", encoding="utf-8")

    monkeypatch.setattr(environment, "DEFAULT_CONFIG_DIR", config_dir)
    monkeypatch.setattr(environment, "DEFAULT_CONFIG_PATH", config_dir / "config.toml")
    monkeypatch.setattr(environment, "DEFAULT_CACHE_DIR", str(cache_dir))

    output = tmp_path / "environment.zip"
    result = runner.invoke(create_app(), ["export-env", str(output)])

    assert result.exit_code == 0, result.stdout
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    assert "config/config.toml" in names
    assert "config/secrets.json" not in names
    assert "config/secret-files/oauth.json" not in names
    assert "config/secrets/old.json" not in names


def test_export_can_include_secrets_explicitly(tmp_path: Path, monkeypatch) -> None:
    import cli.commands.environment as environment

    config_dir = tmp_path / "config"
    cache_dir = tmp_path / "cache"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("", encoding="utf-8")
    (config_dir / "secrets.json").write_text(json.dumps({"x": "secret"}), encoding="utf-8")

    monkeypatch.setattr(environment, "DEFAULT_CONFIG_DIR", config_dir)
    monkeypatch.setattr(environment, "DEFAULT_CONFIG_PATH", config_dir / "config.toml")
    monkeypatch.setattr(environment, "DEFAULT_CACHE_DIR", str(cache_dir))

    output = tmp_path / "environment.zip"
    result = runner.invoke(
        create_app(),
        ["export-env", str(output), "--include-secrets"],
    )

    assert result.exit_code == 0, result.stdout
    with zipfile.ZipFile(output) as archive:
        assert "config/secrets.json" in archive.namelist()


def test_keyring_is_preferred_when_backend_is_available(tmp_path: Path, monkeypatch) -> None:
    class FakeKeyring:
        def __init__(self) -> None:
            self.values: dict[tuple[str, str], str] = {}

        def set_password(self, service: str, key: str, value: str) -> None:
            self.values[(service, key)] = value

        def get_password(self, service: str, key: str) -> str | None:
            return self.values.get((service, key))

        def delete_password(self, service: str, key: str) -> None:
            self.values.pop((service, key), None)

    backend = FakeKeyring()
    repository = SecretRepository(tmp_path / "secrets.json")
    monkeypatch.setattr(repository, "_keyring_module", lambda: backend)

    reference = repository.put("remote/work/password", "keyring-secret")

    assert reference == "keyring:remote/work/password"
    assert repository.get(reference) == "keyring-secret"
    assert not repository.file_path.exists()
    repository.delete(reference)
    assert repository.get(reference) is None


def test_add_sharepoint_with_env_persists_only_reference(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace
    import cli.commands.nodes as nodes

    monkeypatch.setenv("WORK_SP_PASSWORD", "never-write-this-value")
    repository = _file_repo(tmp_path)
    manager = ConfigManager(tmp_path / "config.toml", secret_store=repository)
    monkeypatch.setattr(
        nodes.CLIContext,
        "create",
        lambda: SimpleNamespace(config=manager),
    )

    result = runner.invoke(
        create_app(),
        [
            "add-sp", "work", "https://tenant.example", "/sites/work", "u@example.com",
            "--password-env", "WORK_SP_PASSWORD",
        ],
    )

    assert result.exit_code == 0, result.output
    remote = manager.get_remote("work")
    assert remote.password_ref == "env:WORK_SP_PASSWORD"
    saved = manager.config_path.read_text(encoding="utf-8")
    assert "never-write-this-value" not in saved
    assert "WORK_SP_PASSWORD" in saved
    assert not repository.file_path.exists()


def test_missing_password_environment_variable_returns_nonzero(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace
    import cli.commands.nodes as nodes

    monkeypatch.delenv("MISSING_PASSWORD", raising=False)
    manager = ConfigManager(tmp_path / "config.toml", secret_store=_file_repo(tmp_path))
    monkeypatch.setattr(
        nodes.CLIContext,
        "create",
        lambda: SimpleNamespace(config=manager),
    )

    result = runner.invoke(
        create_app(),
        [
            "add-sp", "work", "https://tenant.example", "/sites/work", "u@example.com",
            "--password-env", "MISSING_PASSWORD",
        ],
    )

    assert result.exit_code == 1
    assert "MISSING_PASSWORD" in result.output
    assert "work" not in manager.config.remotes


def test_export_migrates_legacy_inline_secret_before_archiving(tmp_path: Path, monkeypatch) -> None:
    import cli.commands.environment as environment

    config_dir = tmp_path / "config"
    cache_dir = tmp_path / "cache"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        """
[remotes.work]
type = "webdav"
base_url = "https://dav.example"
username = "user"
password = "must-not-enter-archive"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(environment, "DEFAULT_CONFIG_DIR", config_dir)
    monkeypatch.setattr(environment, "DEFAULT_CONFIG_PATH", config_dir / "config.toml")
    monkeypatch.setattr(environment, "DEFAULT_CACHE_DIR", str(cache_dir))

    output = tmp_path / "environment.zip"
    result = runner.invoke(create_app(), ["export-env", str(output)])

    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(output) as archive:
        config_text = archive.read("config/config.toml").decode("utf-8")
        names = set(archive.namelist())
    assert "must-not-enter-archive" not in config_text
    assert "password =" not in config_text
    assert "password_ref" in config_text
    assert "config/secrets.json" not in names


def test_google_client_credentials_use_portable_relative_path(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace
    import cli.commands.nodes as nodes

    credential_source = tmp_path / "client.json"
    credential_source.write_text('{"installed": {"client_secret": "s"}}', encoding="utf-8")
    manager = ConfigManager(tmp_path / "config" / "config.toml", secret_store=_file_repo(tmp_path))
    monkeypatch.setattr(
        nodes.CLIContext,
        "create",
        lambda: SimpleNamespace(config=manager),
    )

    result = runner.invoke(create_app(), ["add-gdrive", "g", str(credential_source)])

    assert result.exit_code == 0, result.output
    remote = manager.get_remote("g")
    assert remote.credentials_json == "secret-files/g_client_secret.json"
    assert (manager.config_path.parent / remote.credentials_json).exists()
