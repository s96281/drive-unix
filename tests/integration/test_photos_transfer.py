# tests/integration/test_photos_transfer.py
from __future__ import annotations

import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import MagicMock, patch

import requests

from domain.models import FileItem
from domain.sync.models import SyncActionType, SyncOptions
from domain.sync.planner import SyncPlanner
from providers.google.photos import GooglePhotosClient, GooglePhotosStorage


class GooglePhotosTransferIntegrationTests(unittest.TestCase):
    def test_two_stage_upload_workflow(self) -> None:
        """Verify byte stream upload yields uploadToken and sends correct batchCreate JSON."""
        recorded_requests: list[dict[str, Any]] = []

        def mock_request(method: str, url: str, **kwargs: Any) -> requests.Response:
            resp = requests.Response()
            resp.status_code = 200

            if url == GooglePhotosClient.UPLOAD_URL:
                # Stage 1: upload raw bytes
                data = kwargs.get("data")
                if hasattr(data, "__iter__"):
                    body = b"".join(data)
                else:
                    body = data or b""
                recorded_requests.append({
                    "stage": "upload_raw",
                    "url": url,
                    "headers": kwargs.get("headers"),
                    "bytes_len": len(body),
                })
                resp._content = b"CAIS_token_mock_12345"
                return resp

            if url == f"{GooglePhotosClient.BASE_URL}/mediaItems:batchCreate":
                # Stage 2: batchCreate
                recorded_requests.append({
                    "stage": "batch_create",
                    "url": url,
                    "json": kwargs.get("json"),
                })
                resp._content = json.dumps({
                    "newMediaItemResults": [
                        {
                            "uploadToken": "CAIS_token_mock_12345",
                            "status": {"message": "Success", "code": 0},
                            "mediaItem": {
                                "id": "media_item_999",
                                "filename": "sample.jpg",
                                "baseUrl": "https://lh3.googleusercontent.com/sample",
                            },
                        }
                    ]
                }).encode("utf-8")
                return resp

            if url == f"{GooglePhotosClient.BASE_URL}/albums":
                resp._content = json.dumps({
                    "albums": [{"id": "album_vacation_id", "title": "Vacation2026"}]
                }).encode("utf-8")
                return resp

            return resp

        mock_session = MagicMock(spec=requests.Session)
        mock_session.post.side_effect = lambda url, **kwargs: mock_request("POST", url, **kwargs)
        mock_session.get.side_effect = lambda url, **kwargs: mock_request("GET", url, **kwargs)

        client = GooglePhotosClient(session=mock_session, token="oauth_mock_access_token")
        storage = GooglePhotosStorage(client=client, remote_name="test_remote")

        with TemporaryDirectory() as tmp_dir:
            test_file = Path(tmp_dir) / "sample.jpg"
            test_file.write_bytes(b"\xFF\xD8\xFF\xE0" + b"A" * 1024)

            progress_calls: list[tuple[int, int]] = []

            def on_progress(sent: int, total: int) -> None:
                progress_calls.append((sent, total))

            success = storage.upload(
                local_path=str(test_file),
                remote_path="/Vacation2026/sample.jpg",
                callback=on_progress,
            )

            self.assertTrue(success)
            self.assertTrue(len(progress_calls) > 0)
            self.assertEqual(progress_calls[-1][0], len(test_file.read_bytes()))

            # Verify Stage 1 and Stage 2 payloads
            self.assertEqual(len(recorded_requests), 2)
            raw_req = recorded_requests[0]
            self.assertEqual(raw_req["stage"], "upload_raw")
            self.assertEqual(raw_req["headers"]["X-Goog-Upload-Protocol"], "raw")
            self.assertEqual(raw_req["headers"]["X-Goog-Upload-Content-Type"], "image/jpeg")
            self.assertEqual(raw_req["bytes_len"], test_file.stat().st_size)

            batch_req = recorded_requests[1]
            self.assertEqual(batch_req["stage"], "batch_create")
            self.assertEqual(batch_req["json"]["albumId"], "album_vacation_id")
            new_item = batch_req["json"]["newMediaItems"][0]
            self.assertEqual(new_item["simpleMediaItem"]["uploadToken"], "CAIS_token_mock_12345")
            self.assertEqual(new_item["simpleMediaItem"]["fileName"], "sample.jpg")

    def test_download_workflow_appends_d_parameter_and_reports_progress(self) -> None:
        """Verify download automatically appends =d suffix and streams data."""
        requested_urls: list[str] = []

        def mock_get(url: str, **kwargs: Any) -> requests.Response:
            requested_urls.append(url)
            resp = requests.Response()
            resp.status_code = 200
            data = b"ORIGINAL_HIGH_RES_IMAGE_BYTES_2026"
            resp.headers["content-length"] = str(len(data))
            resp.raw = io.BytesIO(data)
            resp.iter_content = lambda chunk_size=64 * 1024: [data]
            return resp

        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.side_effect = mock_get

        client = GooglePhotosClient(session=mock_session, token="oauth_mock_token")
        storage = GooglePhotosStorage(client=client, remote_name="test_remote")

        # Mock resolve media item
        storage._resolve_media_item = MagicMock(return_value={
            "id": "media-photo-1",
            "filename": "fuji.jpg",
            "baseUrl": "https://lh3.googleusercontent.com/photos/fuji_raw_base",
            "mediaMetadata": {"creationTime": "2026-06-01T10:00:00Z"},
        })

        with TemporaryDirectory() as tmp_dir:
            download_dest = Path(tmp_dir) / "fuji_downloaded.jpg"
            progress_history: list[tuple[int, int]] = []

            def on_download_progress(transferred: int, total: int) -> None:
                progress_history.append((transferred, total))

            success = storage.download(
                remote_path="/Vacation/fuji.jpg",
                local_path=str(download_dest),
                callback=on_download_progress,
            )

            self.assertTrue(success)
            self.assertTrue(download_dest.exists())
            self.assertEqual(download_dest.read_bytes(), b"ORIGINAL_HIGH_RES_IMAGE_BYTES_2026")

            # Verify request URL appends =d
            self.assertEqual(len(requested_urls), 1)
            self.assertEqual(requested_urls[0], "https://lh3.googleusercontent.com/photos/fuji_raw_base=d")

            # Verify progress callback was triggered
            self.assertTrue(len(progress_history) > 0)
            self.assertEqual(progress_history[-1], (34, 34))

    def test_sync_planning_prevents_duplicate_uploads_and_skips_non_media(self) -> None:
        """Verify SyncPlanner skips unsupported files and suppresses duplicate uploads."""
        now = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
        older = now - timedelta(hours=2)

        planner = SyncPlanner()

        source_items = {
            "vacation/photo1.jpg": FileItem(
                name="photo1.jpg",
                path="/local/vacation/photo1.jpg",
                size=5_000_000,  # 5 MB locally
                modified_at=now,
                is_dir=False,
            ),
            "vacation/notes.txt": FileItem(
                name="notes.txt",
                path="/local/vacation/notes.txt",
                size=1024,
                modified_at=now,
                is_dir=False,
            ),
            "vacation/new_video.mp4": FileItem(
                name="new_video.mp4",
                path="/local/vacation/new_video.mp4",
                size=50_000_000,
                modified_at=now,
                is_dir=False,
            ),
        }

        # Destination has photo1.jpg with same modified_at but remote_hash=None and size=0 (from Google Photos)
        destination_items = {
            "vacation/photo1.jpg": FileItem(
                name="photo1.jpg",
                path="/Vacation/photo1.jpg",
                size=0,  # Google Photos API does not return byte size
                modified_at=now,
                remote_hash=None,
                is_dir=False,
            ),
        }

        plan = planner.build_plan(
            source_items=source_items,
            destination_items=destination_items,
            source_base_path="/local",
            destination_base_path="/Vacation",
            source_type="local",
            destination_type="googlephotos",
            options=SyncOptions(one_way=True),
        )

        # 1. notes.txt must be skipped because it is not an image/video
        action_targets = [action.target_path for action in plan.actions]
        self.assertNotIn("/Vacation/vacation/notes.txt", action_targets)

        # 2. photo1.jpg has matching mtime, so it must NOT trigger an update / re-upload
        self.assertNotIn("/Vacation/vacation/photo1.jpg", action_targets)

        # 3. new_video.mp4 is media and missing on remote, so it must be scheduled for copy
        self.assertIn("/Vacation/vacation/new_video.mp4", action_targets)
        self.assertEqual(plan.count, 1)
        self.assertEqual(plan.actions[0].action_type, SyncActionType.COPY_TO_DEST)


if __name__ == "__main__":
    unittest.main()
