from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

import requests

from auth.base import AuthContext, AuthProvider
from domain.models import FileItem
from providers.pikpak import PikPakStorage
from storage.base import DeleteCapability


def make_mock_response(status_code: int, json_data: dict) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp._content = json.dumps(json_data).encode("utf-8")
    resp.headers["Content-Type"] = "application/json"
    return resp


class FakeAuthProvider(AuthProvider):
    def __init__(self, token: str = "token_abc") -> None:
        self.token = token
        self.refresh_called = 0

    def get_auth_context(self) -> AuthContext:
        return AuthContext(headers={"Authorization": f"Bearer {self.token}"})

    def refresh(self) -> AuthContext:
        self.refresh_called += 1
        self.token = f"refreshed_token_{self.refresh_called}"
        return self.get_auth_context()


class PikPakStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = FakeAuthProvider()
        self.storage = PikPakStorage(auth_provider=self.auth, root_folder_id="root_001")

    def test_delete_capability_is_trash_and_permanent(self) -> None:
        self.assertEqual(
            self.storage.delete_capability,
            DeleteCapability.TRASH_AND_PERMANENT,
        )
        self.assertTrue(self.storage.delete_capability.supports_trash)
        self.assertTrue(self.storage.delete_capability.supports_permanent)

    def test_list_dir_pagination_exhausts_all_pages(self) -> None:
        # Generate 3 pages totaling 250 items: page1 (100), page2 (100), page3 (50)
        page1_files = [
            {
                "id": f"file_{i}",
                "name": f"video_{i}.mp4",
                "kind": "drive#file",
                "size": "1024",
                "modified_time": "2026-10-10T12:00:00Z",
                "md5_checksum": f"hash_{i}",
            }
            for i in range(100)
        ]
        page2_files = [
            {
                "id": f"file_{i}",
                "name": f"video_{i}.mp4",
                "kind": "drive#file",
                "size": "1024",
                "modified_time": "2026-10-10T12:00:00Z",
                "md5_checksum": f"hash_{i}",
            }
            for i in range(100, 200)
        ]
        page3_files = [
            {
                "id": f"file_{i}",
                "name": f"video_{i}.mp4",
                "kind": "drive#file",
                "size": "1024",
                "modified_time": "2026-10-10T12:00:00Z",
                "md5_checksum": f"hash_{i}",
            }
            for i in range(200, 250)
        ]

        responses = [
            make_mock_response(200, {"files": page1_files, "next_page_token": "tok_page2"}),
            make_mock_response(200, {"files": page2_files, "next_page_token": "tok_page3"}),
            make_mock_response(200, {"files": page3_files, "next_page_token": None}),
        ]

        with patch.object(self.storage.http, "get", side_effect=responses) as mock_get:
            items = self.storage.list_dir("/")

            self.assertEqual(len(items), 250)
            self.assertEqual(mock_get.call_count, 3)
            self.assertEqual(items[0].name, "video_0.mp4")
            self.assertEqual(items[249].name, "video_249.mp4")
            self.assertEqual(items[0].remote_hash, "hash_0")

    def test_rapid_upload_completes_without_put_and_invokes_callback(self) -> None:
        with TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "movie.mkv"
            file_path.write_bytes(b"rapid_upload_content_bytes")
            file_size = file_path.stat().st_size

            mock_create_resp = make_mock_response(
                200,
                {
                    "upload_type": "UPLOAD_TYPE_RESUME",
                    "phase": "PHASE_TYPE_COMPLETE",
                    "file": {"id": "rapid_file_id_999"},
                },
            )

            progress_calls = []

            def on_progress(transferred: int, total: int) -> None:
                progress_calls.append((transferred, total))

            with patch.object(self.storage.http, "post", return_value=mock_create_resp) as mock_post:
                with patch("requests.put") as mock_put:
                    success = self.storage.upload(
                        str(file_path),
                        "/movie.mkv",
                        callback=on_progress,
                    )

                    self.assertTrue(success)
                    mock_post.assert_called_once()
                    mock_put.assert_not_called()
                    self.assertEqual(progress_calls, [(file_size, file_size)])
                    self.assertEqual(self.storage._path_cache.get("/movie.mkv"), "rapid_file_id_999")

    def test_physical_upload_streams_to_presigned_url(self) -> None:
        with TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "large.bin"
            content = b"large_binary_stream_data_here"
            file_path.write_bytes(content)
            file_size = len(content)

            mock_create_resp = make_mock_response(
                200,
                {
                    "upload_type": "UPLOAD_TYPE_UNKNOWN",
                    "phase": "PHASE_TYPE_RUNNING",
                    "upload_url": "https://upload.pikpak.test/presigned?id=123",
                    "file": {"id": "uploaded_file_id_888"},
                },
            )

            mock_put_resp = requests.Response()
            mock_put_resp.status_code = 200

            progress_calls = []

            def on_progress(transferred: int, total: int) -> None:
                progress_calls.append((transferred, total))

            def fake_put(url, data=None, **kwargs):
                if hasattr(data, "read"):
                    while data.read(1024):
                        pass
                return mock_put_resp

            with patch.object(self.storage.http, "post", return_value=mock_create_resp):
                with patch("requests.put", side_effect=fake_put) as mock_put:
                    success = self.storage.upload(
                        str(file_path),
                        "/large.bin",
                        callback=on_progress,
                    )

                    self.assertTrue(success)
                    mock_put.assert_called_once()
                    args, kwargs = mock_put.call_args
                    self.assertEqual(args[0], "https://upload.pikpak.test/presigned?id=123")
                    self.assertTrue(len(progress_calls) > 0)
                    self.assertEqual(progress_calls[-1], (file_size, file_size))
                    self.assertEqual(self.storage._path_cache.get("/large.bin"), "uploaded_file_id_888")

    def test_delete_trash_vs_permanent(self) -> None:
        self.storage._path_cache["/target.mp4"] = "file_target_123"

        # 1. Non-permanent deletion: moves to trash via POST /drive/v1/files/trash
        mock_trash_resp = make_mock_response(200, {"task_id": "trash_task_1"})
        with patch.object(self.storage.http, "post", return_value=mock_trash_resp) as mock_post:
            success = self.storage.delete("/target.mp4", permanent=False)
            self.assertTrue(success)
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            self.assertTrue(args[0].endswith("/files/trash"))
            self.assertEqual(kwargs["json"], {"ids": ["file_target_123"]})
            self.assertNotIn("/target.mp4", self.storage._path_cache)

        # 2. Permanent deletion: calls DELETE /drive/v1/files/{file_id}
        self.storage._path_cache["/permanent.mp4"] = "file_perm_456"
        mock_delete_resp = requests.Response()
        mock_delete_resp.status_code = 204
        with patch.object(self.storage.http, "delete", return_value=mock_delete_resp) as mock_delete:
            success = self.storage.delete("/permanent.mp4", permanent=True)
            self.assertTrue(success)
            mock_delete.assert_called_once()
            args, _ = mock_delete.call_args
            self.assertTrue(args[0].endswith("/files/file_perm_456"))
            self.assertNotIn("/permanent.mp4", self.storage._path_cache)

    def test_download_invokes_download_stream_with_web_content_link(self) -> None:
        self.storage._path_cache["/video.mp4"] = "vid_id_1"

        mock_get_meta = make_mock_response(
            200,
            {
                "kind": "drive#file",
                "name": "video.mp4",
                "web_content_link": "https://dl.mypikpak.com/stream/video.mp4?sign=xyz",
            },
        )

        with patch.object(self.storage.http, "get", return_value=mock_get_meta):
            with patch.object(self.storage.http, "download_stream", return_value=True) as mock_dl:
                success = self.storage.download("/video.mp4", "./local_video.mp4")
                self.assertTrue(success)
                mock_dl.assert_called_once_with(
                    "https://dl.mypikpak.com/stream/video.mp4?sign=xyz",
                    "./local_video.mp4",
                    callback=None,
                )

    def test_stat_root_and_file(self) -> None:
        # Root stat
        root_stat = self.storage.stat("/")
        self.assertEqual(root_stat["type"], "folder")
        self.assertEqual(root_stat["size"], 0)

        # File stat
        self.storage._path_cache["/doc.pdf"] = "file_doc_id"
        mock_file_resp = make_mock_response(
            200,
            {
                "kind": "drive#file",
                "name": "doc.pdf",
                "size": "54321",
                "modified_time": "2026-10-10T08:30:00Z",
            },
        )
        with patch.object(self.storage.http, "get", return_value=mock_file_resp):
            file_stat = self.storage.stat("/doc.pdf")
            self.assertEqual(file_stat["type"], "file")
            self.assertEqual(file_stat["size"], 54321)
            self.assertEqual(file_stat["name"], "doc.pdf")
            self.assertIsNotNone(file_stat["modified"])

    def test_401_unauthorized_automatically_refreshes_token_and_retries(self) -> None:
        self.storage._path_cache["/secret.txt"] = "sec_123"

        resp_401 = requests.Response()
        resp_401.status_code = 401
        resp_401._content = b'{"error": "unauthorized"}'

        resp_200 = make_mock_response(
            200,
            {
                "kind": "drive#file",
                "name": "secret.txt",
                "size": "100",
                "modified_time": "2026-10-10T10:00:00Z",
            },
        )

        with patch.object(self.storage.http, "get", side_effect=[resp_401, resp_200]) as mock_get:
            st = self.storage.stat("/secret.txt")
            self.assertEqual(st["name"], "secret.txt")
            self.assertEqual(self.auth.refresh_called, 1)
            self.assertEqual(mock_get.call_count, 2)

    def test_get_thumbnail_link(self) -> None:
        self.storage._path_cache["/image.png"] = "img_123"
        mock_resp = make_mock_response(
            200,
            {
                "kind": "drive#file",
                "name": "image.png",
                "thumbnail_link": "https://mypikpak.com/thumb/img_123.jpg",
            },
        )
        with patch.object(self.storage.http, "get", return_value=mock_resp):
            thumb_url = self.storage.get_thumbnail_link("/image.png")
            self.assertEqual(thumb_url, "https://mypikpak.com/thumb/img_123.jpg")


if __name__ == "__main__":
    unittest.main()
