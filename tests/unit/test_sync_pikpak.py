from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

from typer.testing import CliRunner

from auth.base import AuthContext, AuthProvider
from cli.app import create_app
from cli.sync_ui import render_delete_risks, summarize_plan
from core.config import ConfigManager, LocalRemote, PikPakRemote
from core.secrets import SecretRepository
from domain.models import FileItem
from domain.sync.models import SyncAction, SyncActionType, SyncOptions, SyncPlan
from domain.sync.planner import SyncPlanner
from providers.local import LocalStorage
from providers.pikpak import PikPakStorage

runner = CliRunner()


class FakeAuthProvider(AuthProvider):
    def get_auth_context(self) -> AuthContext:
        return AuthContext(headers={"Authorization": "Bearer fake"})

    def refresh(self) -> AuthContext:
        return self.get_auth_context()


class SyncPikPakTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.now(timezone.utc)
        self.planner = SyncPlanner()

    def test_sync_planner_uses_remote_hash_and_skips_identical_files(self) -> None:
        source_item = FileItem(
            name="video.mp4",
            path="/src/video.mp4",
            is_dir=False,
            size=1024,
            modified_at=self.now,
            remote_hash="c4ca4238a0b923820dcc509a6f75849b",
        )
        # Destination modified_at is different, but remote_hash is identical
        dest_item = FileItem(
            name="video.mp4",
            path="/dst/video.mp4",
            is_dir=False,
            size=1024,
            modified_at=self.now - timedelta(hours=2),
            remote_hash="c4ca4238a0b923820dcc509a6f75849b",
        )

        differ, reason = self.planner.compare_items(
            source_item,
            dest_item,
            destination_type="pikpak",
            options=SyncOptions(one_way=True),
        )
        self.assertFalse(differ)
        self.assertEqual(reason, "")

        # Full plan building: identical files are skipped (0 actions)
        plan = self.planner.build_plan(
            source_items={"video.mp4": source_item},
            destination_items={"video.mp4": dest_item},
            source_base_path="/src",
            destination_base_path="/dst",
            source_type="local",
            destination_type="pikpak",
            options=SyncOptions(one_way=True),
        )
        self.assertEqual(plan.count, 0)

    def test_sync_planner_detects_difference_when_remote_hash_mismatches(self) -> None:
        source_item = FileItem(
            name="video.mp4",
            path="/src/video.mp4",
            is_dir=False,
            size=1024,
            modified_at=self.now,
            remote_hash="c4ca4238a0b923820dcc509a6f75849b",
        )
        dest_item_diff = FileItem(
            name="video.mp4",
            path="/dst/video.mp4",
            is_dir=False,
            size=1024,
            modified_at=self.now,
            remote_hash="different_remote_hash_val",
        )

        differ, reason = self.planner.compare_items(
            source_item,
            dest_item_diff,
            destination_type="pikpak",
            options=SyncOptions(one_way=True),
        )
        self.assertTrue(differ)
        self.assertIn("遠端雜湊不符", reason)

        plan = self.planner.build_plan(
            source_items={"video.mp4": source_item},
            destination_items={"video.mp4": dest_item_diff},
            source_base_path="/src",
            destination_base_path="/dst",
            source_type="local",
            destination_type="pikpak",
            options=SyncOptions(one_way=True),
        )
        self.assertEqual(plan.count, 1)
        self.assertEqual(plan.actions[0].action_type, SyncActionType.COPY_TO_DEST)

    def test_sync_dry_run_declares_deletes_recoverable_for_pikpak(self) -> None:
        src_storage = LocalStorage(root_path=".")
        dst_storage = PikPakStorage(auth_provider=FakeAuthProvider())

        dest_item = FileItem(
            name="obsolete.mkv",
            path="/dst/obsolete.mkv",
            is_dir=False,
            size=2048,
            modified_at=self.now,
        )
        plan = SyncPlan.from_actions(
            [
                SyncAction(
                    SyncActionType.DELETE_DEST,
                    dest_item,
                    "/dst/obsolete.mkv",
                    "來源已無此檔案",
                )
            ]
        )

        summary = summarize_plan(plan)
        self.assertEqual(summary.deletes, 1)
        self.assertEqual(summary.delete_destination, 1)

        irreversible = render_delete_risks(
            plan,
            source_storage=src_storage,
            destination_storage=dst_storage,
        )
        # PikPak supports trash, so irreversible count must be 0 (recoverable)
        self.assertEqual(irreversible, 0)


if __name__ == "__main__":
    unittest.main()
