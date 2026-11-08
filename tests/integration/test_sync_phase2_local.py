from application.sync_service import SyncService
from domain.sync.models import SyncOptions
from providers.local import LocalStorage


class FailingUploadLocalStorage(LocalStorage):
    def upload(self, local_path: str, remote_path: str, callback=None) -> bool:
        if remote_path.endswith("new.txt"):
            return False
        return super().upload(local_path, remote_path, callback=callback)


def test_failed_transfer_does_not_run_independent_cleanup_delete(tmp_path):
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "new.txt").write_text("new", encoding="utf-8")
    (destination_root / "stale.txt").write_text(
        "keep-on-failure",
        encoding="utf-8",
    )

    service = SyncService(
        source_remote="source",
        source_storage=LocalStorage(str(source_root)),
        source_type="local",
        destination_remote="destination",
        destination_storage=FailingUploadLocalStorage(str(destination_root)),
        destination_type="local",
        source_path="/",
        destination_path="/",
    )
    source_snapshot, destination_snapshot = service.scan(
        strict=True,
        source_throttle=0,
        destination_throttle=0,
    )
    plan = service.build_plan(
        source_snapshot=source_snapshot,
        destination_snapshot=destination_snapshot,
        options=SyncOptions(delete=True),
    )

    assert [batch.name for batch in plan.batches] == [
        "transfer",
        "cleanup-delete-depth-1",
    ]

    result = service.execute(plan, workers=4)

    assert not result.success
    assert result.failed == 1
    assert result.skipped == 1
    assert (destination_root / "stale.txt").read_text(
        encoding="utf-8"
    ) == "keep-on-failure"
