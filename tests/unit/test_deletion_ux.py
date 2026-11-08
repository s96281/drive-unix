from __future__ import annotations

from datetime import datetime, timezone

from cli.sync_ui import summarize_plan
from domain.models import FileItem
from domain.sync.models import SyncAction, SyncActionType, SyncPlan
from providers.local import LocalStorage
from providers.onedrive import OneDriveStorage
from storage.base import DeleteCapability


def test_local_delete_capability_is_explicitly_irreversible(tmp_path) -> None:
    storage = LocalStorage(str(tmp_path))
    assert storage.delete_capability == DeleteCapability.PERMANENT_ONLY
    assert storage.delete_capability.supports_trash is False
    assert storage.delete_capability.supports_permanent is True


def test_onedrive_graph_delete_is_trash_only() -> None:
    assert OneDriveStorage.delete_capability == DeleteCapability.TRASH_ONLY
    assert OneDriveStorage.delete_capability.supports_trash is True
    assert OneDriveStorage.delete_capability.supports_permanent is False


def test_plan_summary_counts_source_and_destination_deletes() -> None:
    now = datetime.now(timezone.utc)
    src = FileItem(name="src.txt", path="/src/src.txt", is_dir=False, size=10, modified_at=now)
    dst = FileItem(name="dst.txt", path="/dst/dst.txt", is_dir=False, size=20, modified_at=now)
    plan = SyncPlan.from_actions(
        [
            SyncAction(SyncActionType.DELETE_SRC, src, "/src/src.txt", "test"),
            SyncAction(SyncActionType.DELETE_DEST, dst, "/dst/dst.txt", "test"),
        ]
    )

    summary = summarize_plan(plan)
    assert summary.delete_source == 1
    assert summary.delete_destination == 1
    assert summary.deletes == 2
    assert summary.delete_bytes == 30


def test_rm_warns_when_provider_delete_is_irreversible(monkeypatch) -> None:
    from types import SimpleNamespace

    from typer.testing import CliRunner

    from cli.app import create_app
    from cli.commands import files

    deleted: list[tuple[str, bool]] = []

    class FakePermanentStorage:
        delete_capability = DeleteCapability.PERMANENT_ONLY

        def validate_delete_request(self, *, permanent: bool) -> None:
            assert permanent is False

        def delete(self, path: str, permanent: bool = False) -> bool:
            deleted.append((path, permanent))
            return True

    config_manager = SimpleNamespace(config=SimpleNamespace(default_remote="local"))
    monkeypatch.setattr(
        files.CLIContext,
        "create",
        classmethod(lambda cls: SimpleNamespace(config=config_manager)),
    )
    monkeypatch.setattr(files, "get_storage_provider", lambda *args: FakePermanentStorage())

    result = CliRunner().invoke(create_app(), ["rm", "local:/important"], input="y\n")

    assert result.exit_code == 0
    assert "永久刪除" in result.output
    assert "不支援回收桶" in result.output
    assert deleted == [("/important", False)]
