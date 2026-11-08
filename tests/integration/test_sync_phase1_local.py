import os
import time
from pathlib import Path

from application.sync_service import SyncService
from domain.sync.models import SyncOptions
from providers.local import LocalStorage


def _service(source_root: Path, destination_root: Path) -> SyncService:
    return SyncService(
        source_remote="source",
        source_storage=LocalStorage(str(source_root)),
        source_type="local",
        destination_remote="destination",
        destination_storage=LocalStorage(str(destination_root)),
        destination_type="local",
        source_path="/",
        destination_path="/",
    )


def test_conflict_rename_preserves_old_file_and_updates_canonical_path(tmp_path):
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "a.txt").write_text("new-content", encoding="utf-8")
    (destination_root / "a.txt").write_text("old-content", encoding="utf-8")
    old_timestamp = time.time() - 300
    os.utime(destination_root / "a.txt", (old_timestamp, old_timestamp))

    service = _service(source_root, destination_root)
    source_snapshot, destination_snapshot = service.scan(
        strict=True,
        source_throttle=0,
        destination_throttle=0,
    )
    plan = service.build_plan(
        source_snapshot=source_snapshot,
        destination_snapshot=destination_snapshot,
        options=SyncOptions(conflict="rename"),
    )
    result = service.execute(plan, workers=8)

    assert result.success
    assert (destination_root / "a.txt").read_text(encoding="utf-8") == "new-content"
    backups = [path for path in destination_root.iterdir() if path.name != "a.txt"]
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "old-content"


def test_file_replaces_non_empty_directory_end_to_end(tmp_path):
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()

    (source_root / "node").write_text("source-file", encoding="utf-8")
    (destination_root / "node").mkdir()
    (destination_root / "node" / "old.txt").write_text("old", encoding="utf-8")

    service = _service(source_root, destination_root)
    source_snapshot, destination_snapshot = service.scan(
        strict=True,
        source_throttle=0,
        destination_throttle=0,
    )
    plan = service.build_plan(
        source_snapshot=source_snapshot,
        destination_snapshot=destination_snapshot,
        options=SyncOptions(),
    )
    result = service.execute(plan, workers=8)

    assert result.success
    assert (destination_root / "node").is_file()
    assert (destination_root / "node").read_text(encoding="utf-8") == "source-file"
