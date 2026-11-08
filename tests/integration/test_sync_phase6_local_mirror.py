from __future__ import annotations

import os
import time
from pathlib import Path

from application.sync_service import SyncService
from domain.sync.models import SyncOptions
from providers.local import LocalStorage


def _files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in root.rglob("*")
        if path.is_file()
    }


def test_local_mirror_scan_plan_execute_matches_source_filesystem(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "nested").mkdir(parents=True)
    (destination / "nested").mkdir(parents=True)

    (source / "keep.txt").write_text("source-current", encoding="utf-8")
    (source / "nested" / "new.txt").write_text("new-file", encoding="utf-8")
    (destination / "keep.txt").write_text("destination-old", encoding="utf-8")
    (destination / "stale.txt").write_text("remove-me", encoding="utf-8")
    (destination / "nested" / "stale-nested.txt").write_text("remove-me-too", encoding="utf-8")

    old = time.time() - 300
    os.utime(destination / "keep.txt", (old, old))

    service = SyncService(
        source_remote="source",
        source_storage=LocalStorage(str(source)),
        source_type="local",
        destination_remote="destination",
        destination_storage=LocalStorage(str(destination)),
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
    result = service.execute(plan, workers=4)

    assert result.success
    assert _files(destination) == _files(source)
    assert not (destination / "stale.txt").exists()
    assert not (destination / "nested" / "stale-nested.txt").exists()
