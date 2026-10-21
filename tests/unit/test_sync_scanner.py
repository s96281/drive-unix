import unittest

from domain.errors import ScanIncompleteError
from domain.models import FileItem
from domain.sync.scanner import scan_storage_tree


class FakeStorage:
    def __init__(self, tree, failing=None):
        self.tree = tree
        self.failing = set(failing or [])

    def list_dir(self, path):
        if path in self.failing:
            raise PermissionError("denied")
        return list(self.tree.get(path, []))


class ScannerTests(unittest.TestCase):
    def test_scan_produces_flat_snapshot(self):
        storage = FakeStorage({
            "/root": [FileItem(name="docs", path="/root/docs", is_dir=True)],
            "/root/docs": [FileItem(name="a.txt", path="/root/docs/a.txt", is_dir=False, size=1)],
        })
        snapshot = scan_storage_tree(storage, "/root", strict=True, throttle=0)
        self.assertEqual(set(snapshot.items), {"docs", "docs/a.txt"})
        self.assertTrue(snapshot.complete)

    def test_non_strict_scan_marks_snapshot_incomplete(self):
        storage = FakeStorage(
            {"/root": [FileItem(name="docs", path="/root/docs", is_dir=True)]},
            failing=["/root/docs"],
        )
        snapshot = scan_storage_tree(storage, "/root", strict=False, throttle=0)
        self.assertFalse(snapshot.complete)

    def test_strict_scan_fails_instead_of_returning_partial_snapshot(self):
        storage = FakeStorage(
            {"/root": [FileItem(name="docs", path="/root/docs", is_dir=True)]},
            failing=["/root/docs"],
        )
        with self.assertRaises(ScanIncompleteError):
            scan_storage_tree(storage, "/root", strict=True, throttle=0)


if __name__ == "__main__":
    unittest.main()
