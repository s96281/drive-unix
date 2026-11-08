from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from cli.app import create_app
from storage.base import managed_storage


runner = CliRunner()


class TrackingStorage:
    def __init__(self) -> None:
        self.close_calls = 0

    def list_dir(self, path):
        return []

    def close(self) -> None:
        self.close_calls += 1


class TrackingConfig:
    def __init__(self) -> None:
        self.config = SimpleNamespace(default_remote=None)

    def get_remote(self, name: str):
        return SimpleNamespace(type="local")


def test_managed_storage_closes_on_exception() -> None:
    storage = TrackingStorage()

    try:
        with managed_storage(storage):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert storage.close_calls == 1



def test_managed_storage_cleanup_error_does_not_mask_active_error() -> None:
    class BadCloseStorage(TrackingStorage):
        def close(self) -> None:
            raise OSError("close failed")

    storage = BadCloseStorage()
    caught = None
    try:
        with managed_storage(storage):
            raise RuntimeError("original failure")
    except Exception as exc:
        caught = exc

    assert isinstance(caught, RuntimeError)
    assert str(caught) == "original failure"

def test_sync_empty_plan_closes_both_providers(monkeypatch) -> None:
    storages: list[TrackingStorage] = []

    def create_storage(remote_name, config_manager):
        storage = TrackingStorage()
        storages.append(storage)
        return storage

    monkeypatch.setattr(
        "cli.commands.sync.CLIContext.create",
        lambda: SimpleNamespace(config=TrackingConfig()),
    )
    monkeypatch.setattr("cli.commands.sync.get_storage_provider", create_storage)

    result = runner.invoke(create_app(), ["sync", "src:/", "dst:/", "--dry-run", "--yes"])

    assert result.exit_code == 0, result.stdout
    assert len(storages) == 2
    assert [storage.close_calls for storage in storages] == [1, 1]


def test_sync_scan_exception_still_closes_both_providers(monkeypatch) -> None:
    storages: list[TrackingStorage] = []

    class FailingStorage(TrackingStorage):
        def list_dir(self, path):
            raise RuntimeError("scan failed")

    def create_storage(remote_name, config_manager):
        storage = FailingStorage()
        storages.append(storage)
        return storage

    monkeypatch.setattr(
        "cli.commands.sync.CLIContext.create",
        lambda: SimpleNamespace(config=TrackingConfig()),
    )
    monkeypatch.setattr("cli.commands.sync.get_storage_provider", create_storage)

    result = runner.invoke(create_app(), ["sync", "src:/", "dst:/", "--dry-run", "--yes"])

    assert result.exit_code == 1
    assert len(storages) == 2
    assert [storage.close_calls for storage in storages] == [1, 1]
