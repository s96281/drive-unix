import unittest
from datetime import datetime, timedelta, timezone

from domain.models import FileItem
from domain.errors import SyncConflictError
from domain.sync.models import SyncActionType, SyncOptions
from domain.sync.planner import SyncPlanner, should_exclude


class SyncPlannerTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.planner = SyncPlanner()

    def item(self, name, path, *, size=10, modified_at=None, is_dir=False):
        return FileItem(
            name=name,
            path=path,
            size=size,
            modified_at=modified_at or self.now,
            is_dir=is_dir,
        )

    def build(self, source, destination, options, checksum_comparator=None):
        return self.planner.build_plan(
            source_items=source,
            destination_items=destination,
            source_base_path="/src",
            destination_base_path="/dst",
            source_type="local",
            destination_type="local",
            options=options,
            checksum_comparator=checksum_comparator,
        )

    def test_new_file_becomes_copy_action(self):
        plan = self.build(
            {"a.txt": self.item("a.txt", "/src/a.txt")},
            {},
            SyncOptions(),
        )
        self.assertEqual(plan.count, 1)
        self.assertEqual(plan.actions[0].action_type, SyncActionType.COPY_TO_DEST)
        self.assertEqual(plan.actions[0].target_path, "/dst/a.txt")

    def test_newer_source_becomes_update(self):
        old = self.now - timedelta(minutes=5)
        plan = self.build(
            {"a.txt": self.item("a.txt", "/src/a.txt")},
            {"a.txt": self.item("a.txt", "/dst/a.txt", modified_at=old)},
            SyncOptions(),
        )
        self.assertEqual(plan.actions[0].reason, "更新 (來源檔案較新)")

    def test_compare_items_two_way_detects_newer_destination(self):
        old = self.now - timedelta(minutes=5)
        different, reason = self.planner.compare_items(
            self.item("a.txt", "/src/a.txt", modified_at=old),
            self.item("a.txt", "/dst/a.txt", modified_at=self.now),
            destination_type="local",
            options=SyncOptions(one_way=False),
        )

        self.assertTrue(different)
        self.assertEqual(reason, "修改時間不同")

    def test_compare_items_two_way_uses_mtime_tolerance(self):
        different, reason = self.planner.compare_items(
            self.item("a.txt", "/src/a.txt", modified_at=self.now),
            self.item(
                "a.txt",
                "/dst/a.txt",
                modified_at=self.now + timedelta(milliseconds=500),
            ),
            destination_type="local",
            options=SyncOptions(one_way=False),
        )

        self.assertFalse(different)
        self.assertEqual(reason, "")

    def test_compare_items_detects_file_directory_type_mismatch(self):
        different, reason = self.planner.compare_items(
            self.item("node", "/src/node"),
            self.item("node", "/dst/node", is_dir=True),
            destination_type="local",
            options=SyncOptions(one_way=False),
        )

        self.assertTrue(different)
        self.assertEqual(reason, "型態不同")

    def test_compare_items_two_way_uses_checksum_policy(self):
        calls = []

        def different_checksum(source_item, destination_item):
            calls.append((source_item.path, destination_item.path))
            return True, "內容已變更 (測試雜湊不符)"

        different, reason = self.planner.compare_items(
            self.item("a.txt", "/src/a.txt", size=100),
            self.item("a.txt", "/dst/a.txt", size=100),
            destination_type="local",
            options=SyncOptions(one_way=False, checksum=True),
            checksum_comparator=different_checksum,
        )

        self.assertTrue(different)
        self.assertEqual(reason, "內容已變更 (測試雜湊不符)")
        self.assertEqual(calls, [("/src/a.txt", "/dst/a.txt")])

    def test_same_size_add_delete_is_not_assumed_to_be_rename(self):
        plan = self.build(
            {"new.txt": self.item("new.txt", "/src/new.txt", size=10)},
            {"old.txt": self.item("old.txt", "/dst/old.txt", size=10)},
            SyncOptions(delete=True),
        )

        self.assertEqual(
            [action.action_type for action in plan.actions],
            [SyncActionType.COPY_TO_DEST, SyncActionType.DELETE_DEST],
        )
        self.assertEqual(plan.actions[0].target_path, "/dst/new.txt")
        self.assertEqual(plan.actions[1].target_path, "/dst/old.txt")

    def test_checksum_verified_identical_content_can_be_detected_as_rename(self):
        calls = []

        def same_checksum(source_item, destination_item):
            calls.append((source_item.path, destination_item.path))
            return False, ""

        plan = self.build(
            {"new.txt": self.item("new.txt", "/src/new.txt", size=10)},
            {"old.txt": self.item("old.txt", "/dst/old.txt", size=10)},
            SyncOptions(delete=True, checksum=True),
            checksum_comparator=same_checksum,
        )

        self.assertEqual(plan.count, 1)
        self.assertEqual(plan.actions[0].action_type, SyncActionType.RENAME_DEST)
        self.assertEqual(plan.actions[0].item.path, "/dst/old.txt")
        self.assertEqual(plan.actions[0].target_path, "/dst/new.txt")
        self.assertEqual(calls, [("/src/new.txt", "/dst/old.txt")])

    def test_conflict_rename_backs_up_destination_then_updates_canonical_path(self):
        old = self.now - timedelta(minutes=5)
        plan = self.build(
            {"a.txt": self.item("a.txt", "/src/a.txt", modified_at=self.now)},
            {"a.txt": self.item("a.txt", "/dst/a.txt", modified_at=old)},
            SyncOptions(conflict="rename"),
        )

        self.assertEqual(
            [action.action_type for action in plan.actions],
            [SyncActionType.RENAME_DEST, SyncActionType.COPY_TO_DEST],
        )
        self.assertEqual(plan.actions[0].item.path, "/dst/a.txt")
        self.assertEqual(
            plan.actions[0].target_path,
            f"/dst/a_{old.strftime('%Y%m%d_%H%M%S')}.txt",
        )
        self.assertEqual(plan.actions[1].target_path, "/dst/a.txt")

    def test_two_way_same_mtime_but_different_size_is_not_silently_ignored(self):
        plan = self.build(
            {"a.txt": self.item("a.txt", "/src/a.txt", size=100)},
            {"a.txt": self.item("a.txt", "/dst/a.txt", size=200)},
            SyncOptions(one_way=False),
        )

        self.assertEqual(plan.count, 2)
        self.assertEqual(
            [action.action_type for action in plan.actions],
            [SyncActionType.RENAME_DEST, SyncActionType.COPY_TO_DEST],
        )
        self.assertEqual(plan.actions[1].target_path, "/dst/a.txt")
        self.assertIn("無法安全判定較新版本", plan.actions[1].reason)
        self.assertNotIn("來源優先", plan.actions[1].reason)

    def test_two_way_checksum_detects_change_even_when_size_and_mtime_match(self):
        calls = []

        def different_checksum(source_item, destination_item):
            calls.append((source_item.path, destination_item.path))
            return True, "內容已變更 (測試雜湊不符)"

        plan = self.build(
            {"a.txt": self.item("a.txt", "/src/a.txt", size=100)},
            {"a.txt": self.item("a.txt", "/dst/a.txt", size=100)},
            SyncOptions(one_way=False, checksum=True),
            checksum_comparator=different_checksum,
        )

        self.assertEqual(plan.count, 2)
        self.assertEqual(
            [action.action_type for action in plan.actions],
            [SyncActionType.RENAME_DEST, SyncActionType.COPY_TO_DEST],
        )
        self.assertIn("測試雜湊不符", plan.actions[1].reason)
        self.assertEqual(calls, [("/src/a.txt", "/dst/a.txt")])

    def test_two_way_explicit_newer_aborts_when_winner_is_ambiguous(self):
        with self.assertRaises(SyncConflictError):
            self.build(
                {"a.txt": self.item("a.txt", "/src/a.txt", size=100)},
                {"a.txt": self.item("a.txt", "/dst/a.txt", size=200)},
                SyncOptions(one_way=False, conflict="newer"),
            )

    def test_two_way_prefer_destination_updates_source(self):
        plan = self.build(
            {"a.txt": self.item("a.txt", "/src/a.txt", size=100)},
            {"a.txt": self.item("a.txt", "/dst/a.txt", size=200)},
            SyncOptions(one_way=False, conflict="prefer-destination"),
        )
        self.assertEqual(plan.count, 1)
        self.assertEqual(plan.actions[0].action_type, SyncActionType.COPY_TO_SRC)

    def test_two_way_newer_destination_with_rename_backs_up_source_first(self):
        old = self.now - timedelta(minutes=10)
        plan = self.build(
            {"a.txt": self.item("a.txt", "/src/a.txt", size=10, modified_at=old)},
            {"a.txt": self.item("a.txt", "/dst/a.txt", size=20, modified_at=self.now)},
            SyncOptions(one_way=False, conflict="rename"),
        )

        self.assertEqual(
            [action.action_type for action in plan.actions],
            [SyncActionType.RENAME_SRC, SyncActionType.COPY_TO_SRC],
        )
        self.assertEqual(
            plan.actions[0].target_path,
            f"/src/a_{old.strftime('%Y%m%d_%H%M%S')}.txt",
        )
        self.assertEqual(plan.actions[1].target_path, "/src/a.txt")

    def test_file_replaces_destination_directory_after_leaf_first_delete(self):
        plan = self.build(
            {"node": self.item("node", "/src/node", size=5)},
            {
                "node": self.item("node", "/dst/node", is_dir=True),
                "node/old.txt": self.item(
                    "old.txt",
                    "/dst/node/old.txt",
                    size=3,
                ),
            },
            SyncOptions(),
        )

        self.assertEqual(
            [action.action_type for action in plan.actions],
            [
                SyncActionType.DELETE_DEST,
                SyncActionType.DELETE_DEST,
                SyncActionType.COPY_TO_DEST,
            ],
        )
        self.assertEqual(
            [action.target_path for action in plan.actions],
            ["/dst/node/old.txt", "/dst/node", "/dst/node"],
        )

    def test_directory_replaces_destination_file_before_syncing_children(self):
        plan = self.build(
            {
                "node": self.item("node", "/src/node", is_dir=True),
                "node/new.txt": self.item("new.txt", "/src/node/new.txt", size=3),
            },
            {"node": self.item("node", "/dst/node", size=5)},
            SyncOptions(),
        )

        self.assertEqual(
            [action.action_type for action in plan.actions],
            [
                SyncActionType.DELETE_DEST,
                SyncActionType.MKDIR_DEST,
                SyncActionType.COPY_TO_DEST,
            ],
        )
        self.assertEqual(
            [action.target_path for action in plan.actions],
            ["/dst/node", "/dst/node", "/dst/node/new.txt"],
        )

    def test_type_conflict_rename_preserves_old_directory_as_backup(self):
        old = self.now - timedelta(minutes=3)
        plan = self.build(
            {"node": self.item("node", "/src/node", size=5)},
            {
                "node": self.item("node", "/dst/node", is_dir=True, modified_at=old),
                "node/old.txt": self.item("old.txt", "/dst/node/old.txt", size=3),
            },
            SyncOptions(conflict="rename"),
        )

        self.assertEqual(
            [action.action_type for action in plan.actions],
            [SyncActionType.RENAME_DEST, SyncActionType.COPY_TO_DEST],
        )
        self.assertEqual(
            plan.actions[0].target_path,
            f"/dst/node_{old.strftime('%Y%m%d_%H%M%S')}",
        )
        self.assertEqual(plan.actions[1].target_path, "/dst/node")

    def test_delete_actions_are_leaf_first(self):
        source = {}
        destination = {
            "folder": self.item("folder", "/dst/folder", is_dir=True),
            "folder/file.txt": self.item("file.txt", "/dst/folder/file.txt"),
        }
        plan = self.build(source, destination, SyncOptions(delete=True))
        paths = [action.item.path for action in plan.actions]
        self.assertEqual(paths, ["/dst/folder/file.txt", "/dst/folder"])

    def test_two_way_delete_is_rejected(self):
        with self.assertRaises(ValueError):
            SyncOptions(one_way=False, delete=True).validate()

    def test_include_exclude_filters_are_applied(self):
        self.assertTrue(should_exclude("x.tmp", "*.pdf", None))
        self.assertTrue(should_exclude("x.tmp", None, "*.tmp"))
        self.assertFalse(should_exclude("x.pdf", "*.pdf", "*.tmp"))


def test_conflict_rename_is_split_into_backup_and_transfer_batches():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    old = now - timedelta(minutes=5)
    planner = SyncPlanner()
    source = {
        "a.txt": FileItem(
            name="a.txt",
            path="/src/a.txt",
            is_dir=False,
            size=20,
            modified_at=now,
        )
    }
    destination = {
        "a.txt": FileItem(
            name="a.txt",
            path="/dst/a.txt",
            is_dir=False,
            size=10,
            modified_at=old,
        )
    }

    plan = planner.build_plan(
        source_items=source,
        destination_items=destination,
        source_base_path="/src",
        destination_base_path="/dst",
        source_type="local",
        destination_type="local",
        options=SyncOptions(conflict="rename"),
    )

    assert [batch.name for batch in plan.batches] == ["prepare-backup", "transfer"]
    assert [batch.count for batch in plan.batches] == [1, 1]


def test_type_replacement_delete_batches_are_leaf_first():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    planner = SyncPlanner()
    source = {
        "node": FileItem(
            name="node",
            path="/src/node",
            is_dir=False,
            size=5,
            modified_at=now,
        )
    }
    destination = {
        "node": FileItem(
            name="node",
            path="/dst/node",
            is_dir=True,
            modified_at=now,
        ),
        "node/old.txt": FileItem(
            name="old.txt",
            path="/dst/node/old.txt",
            is_dir=False,
            size=3,
            modified_at=now,
        ),
    }

    plan = planner.build_plan(
        source_items=source,
        destination_items=destination,
        source_base_path="/src",
        destination_base_path="/dst",
        source_type="local",
        destination_type="local",
        options=SyncOptions(),
    )

    assert [batch.name for batch in plan.batches] == [
        "prepare-delete-depth-3",
        "prepare-delete-depth-2",
        "transfer",
    ]
    assert [action.target_path for action in plan.batches[0].actions] == [
        "/dst/node/old.txt"
    ]
    assert [action.target_path for action in plan.batches[1].actions] == [
        "/dst/node"
    ]


def test_independent_cleanup_delete_runs_after_transfer_batch():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    planner = SyncPlanner()
    source = {
        "new.txt": FileItem(
            name="new.txt",
            path="/src/new.txt",
            is_dir=False,
            size=5,
            modified_at=now,
        )
    }
    destination = {
        "old.txt": FileItem(
            name="old.txt",
            path="/dst/old.txt",
            is_dir=False,
            size=3,
            modified_at=now,
        )
    }

    plan = planner.build_plan(
        source_items=source,
        destination_items=destination,
        source_base_path="/src",
        destination_base_path="/dst",
        source_type="local",
        destination_type="local",
        options=SyncOptions(delete=True),
    )

    assert [batch.name for batch in plan.batches] == [
        "transfer",
        "cleanup-delete-depth-2",
    ]


if __name__ == "__main__":
    unittest.main()
