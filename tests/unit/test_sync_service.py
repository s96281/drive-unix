import unittest
from datetime import datetime, timezone, timedelta

from application.sync_service import SyncService
from domain.models import FileItem
from domain.sync.models import SyncOptions


class FakeStorage:
    def __init__(self, tree, *, events=None, label="storage"):
        self.tree = tree
        self.calls = []
        self.events = events
        self.label = label

    def _record(self, *call):
        self.calls.append(call)
        if self.events is not None:
            self.events.append((self.label, *call))

    def list_dir(self, path):
        return list(self.tree.get(path, []))

    def upload(self, local_path, remote_path, callback=None):
        self._record("upload", remote_path)
        if callback:
            callback(1, 1)
        return True

    def download(self, remote_path, local_path, recursive=False, callback=None):
        self._record("download", remote_path)
        if callback:
            callback(1, 1)
        return True

    def copy(self, source_path, dest_path, overwrite=False):
        self._record("copy", source_path, dest_path, overwrite)
        return True

    def mkdir(self, remote_path, parents=False):
        self._record("mkdir", remote_path, parents)
        return True

    def delete(self, remote_path, permanent=False):
        self._record("delete", remote_path, permanent)
        return True

    def move(self, source_path, dest_path, overwrite=False):
        self._record("move", source_path, dest_path)
        return True

    def get_hash(self, remote_path, algo):
        return "same"


class SyncServiceTests(unittest.TestCase):
    def _service(self, source, destination):
        return SyncService(
            source_remote="src",
            source_storage=source,
            source_type="local",
            destination_remote="dst",
            destination_storage=destination,
            destination_type="local",
            source_path="/src",
            destination_path="/dst",
        )

    def test_build_and_execute_simple_copy(self):
        now = datetime.now(timezone.utc)
        source = FakeStorage(
            {
                "/src": [
                    FileItem(
                        name="a.txt",
                        path="/src/a.txt",
                        is_dir=False,
                        size=1,
                        modified_at=now,
                    )
                ]
            }
        )
        destination = FakeStorage({"/dst": []})
        service = self._service(source, destination)

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
        result = service.execute(plan, workers=1)

        self.assertTrue(result.success)
        self.assertEqual(result.succeeded, 1)
        self.assertTrue(any(call[0] == "upload" for call in destination.calls))

    def test_conflict_rename_executes_backup_before_canonical_write(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        old = now - timedelta(minutes=5)
        events = []
        source = FakeStorage(
            {
                "/src": [
                    FileItem(
                        name="a.txt",
                        path="/src/a.txt",
                        is_dir=False,
                        size=20,
                        modified_at=now,
                    )
                ]
            },
            events=events,
            label="src",
        )
        destination = FakeStorage(
            {
                "/dst": [
                    FileItem(
                        name="a.txt",
                        path="/dst/a.txt",
                        is_dir=False,
                        size=10,
                        modified_at=old,
                    )
                ]
            },
            events=events,
            label="dst",
        )
        service = self._service(source, destination)

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

        self.assertTrue(result.success)
        move_index = next(
            index
            for index, event in enumerate(events)
            if event[0] == "dst" and event[1] == "move"
        )
        upload_index = next(
            index
            for index, event in enumerate(events)
            if event[0] == "dst" and event[1] == "upload"
        )
        self.assertLess(move_index, upload_index)

    def test_two_way_destination_newer_rename_backs_up_source_before_write(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        old = now - timedelta(minutes=5)
        events = []
        source = FakeStorage(
            {
                "/src": [
                    FileItem(
                        name="a.txt",
                        path="/src/a.txt",
                        is_dir=False,
                        size=10,
                        modified_at=old,
                    )
                ]
            },
            events=events,
            label="src",
        )
        destination = FakeStorage(
            {
                "/dst": [
                    FileItem(
                        name="a.txt",
                        path="/dst/a.txt",
                        is_dir=False,
                        size=20,
                        modified_at=now,
                    )
                ]
            },
            events=events,
            label="dst",
        )
        service = self._service(source, destination)

        source_snapshot, destination_snapshot = service.scan(
            strict=True,
            source_throttle=0,
            destination_throttle=0,
        )
        plan = service.build_plan(
            source_snapshot=source_snapshot,
            destination_snapshot=destination_snapshot,
            options=SyncOptions(one_way=False, conflict="rename"),
        )
        result = service.execute(plan, workers=8)

        self.assertTrue(result.success)
        move_index = next(
            index
            for index, event in enumerate(events)
            if event[0] == "src" and event[1] == "move"
        )
        upload_index = next(
            index
            for index, event in enumerate(events)
            if event[0] == "src" and event[1] == "upload"
        )
        self.assertLess(move_index, upload_index)

    def test_type_replacement_deletes_directory_leaf_first_before_upload(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        events = []
        source = FakeStorage(
            {
                "/src": [
                    FileItem(
                        name="node",
                        path="/src/node",
                        is_dir=False,
                        size=20,
                        modified_at=now,
                    )
                ]
            },
            events=events,
            label="src",
        )
        destination = FakeStorage(
            {
                "/dst": [
                    FileItem(
                        name="node",
                        path="/dst/node",
                        is_dir=True,
                        modified_at=now,
                    )
                ],
                "/dst/node": [
                    FileItem(
                        name="old.txt",
                        path="/dst/node/old.txt",
                        is_dir=False,
                        size=1,
                        modified_at=now,
                    )
                ],
            },
            events=events,
            label="dst",
        )
        service = self._service(source, destination)

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

        self.assertTrue(result.success)
        delete_events = [
            event
            for event in events
            if event[0] == "dst" and event[1] == "delete"
        ]
        self.assertEqual(
            [event[2] for event in delete_events],
            ["/dst/node/old.txt", "/dst/node"],
        )
        last_delete_index = max(events.index(event) for event in delete_events)
        upload_index = next(
            index
            for index, event in enumerate(events)
            if event[0] == "dst" and event[1] == "upload"
        )
        self.assertLess(last_delete_index, upload_index)


class FailingMoveStorage(FakeStorage):
    def move(self, source_path, dest_path, overwrite=False):
        self._record("move", source_path, dest_path)
        return False


class SelectiveFailUploadStorage(FakeStorage):
    def upload(self, local_path, remote_path, callback=None):
        self._record("upload", remote_path)
        if remote_path.endswith("bad.txt"):
            return False
        if callback:
            callback(1, 1)
        return True


def test_failed_prerequisite_batch_skips_dependent_transfer():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    old = now - timedelta(minutes=5)
    source = FakeStorage(
        {
            "/src": [
                FileItem(
                    name="a.txt",
                    path="/src/a.txt",
                    is_dir=False,
                    size=20,
                    modified_at=now,
                )
            ]
        }
    )
    destination = FailingMoveStorage(
        {
            "/dst": [
                FileItem(
                    name="a.txt",
                    path="/dst/a.txt",
                    is_dir=False,
                    size=10,
                    modified_at=old,
                )
            ]
        }
    )
    service = SyncServiceTests()._service(source, destination)

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

    assert not result.success
    assert result.failed == 1
    assert result.skipped == 1
    assert not any(call[0] == "upload" for call in destination.calls)


def test_transfer_batch_aggregates_false_provider_result_without_skipping_peers():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    source = FakeStorage(
        {
            "/src": [
                FileItem(name="good.txt", path="/src/good.txt", is_dir=False, size=1, modified_at=now),
                FileItem(name="bad.txt", path="/src/bad.txt", is_dir=False, size=1, modified_at=now),
            ]
        }
    )
    destination = SelectiveFailUploadStorage({"/dst": []})
    service = SyncServiceTests()._service(source, destination)

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
    result = service.execute(plan, workers=2)

    assert not result.success
    assert result.succeeded == 1
    assert result.failed == 1
    assert result.skipped == 0


if __name__ == "__main__":
    unittest.main()
