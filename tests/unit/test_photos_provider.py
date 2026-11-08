# tests/unit/test_photos_provider.py
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from domain.models import FileItem
from providers.google.photos import GooglePhotosStorage
from storage.base import DeleteCapability


class FakeGooglePhotosClient:
    def __init__(self) -> None:
        self.albums: list[dict[str, Any]] = [
            {"id": "alb-1", "title": "Trip2026", "productUrl": "https://photos.google.com/album/alb-1"},
            {"id": "alb-2", "title": "Family", "productUrl": "https://photos.google.com/album/alb-2"},
        ]
        self.library_items: list[dict[str, Any]] = [
            {
                "id": "item-1",
                "filename": "sunset.jpg",
                "baseUrl": "https://lh3.googleusercontent.com/sunset",
                "mediaMetadata": {
                    "creationTime": "2026-05-01T12:00:00Z",
                    "width": "4000",
                    "height": "3000",
                },
            },
            {
                "id": "item-2",
                "filename": "clip.mp4",
                "baseUrl": "https://lh3.googleusercontent.com/clip",
                "mediaMetadata": {
                    "creationTime": "2026-05-02T15:30:00Z",
                    "width": "1920",
                    "height": "1080",
                },
            },
        ]
        self.album_items: dict[str, list[dict[str, Any]]] = {
            "alb-1": [
                {
                    "id": "item-3",
                    "filename": "fuji.jpg",
                    "baseUrl": "https://lh3.googleusercontent.com/fuji",
                    "mediaMetadata": {
                        "creationTime": "2026-05-03T09:15:00Z",
                        "width": "3000",
                        "height": "2000",
                    },
                }
            ],
            "alb-2": [],
        }
        self.uploaded_raw: list[tuple[str, Any]] = []
        self.created_items: list[tuple[str, str, str | None]] = []
        self.removed_items: list[tuple[str, list[str]]] = []
        self.created_albums: list[str] = []

    def list_albums(self) -> list[dict[str, Any]]:
        return list(self.albums)

    def create_album(self, title: str) -> dict[str, Any]:
        self.created_albums.append(title)
        new_album = {"id": f"alb-{len(self.albums)+1}", "title": title}
        self.albums.append(new_album)
        self.album_items[new_album["id"]] = []
        return new_album

    def list_library_items(self) -> list[dict[str, Any]]:
        return list(self.library_items)

    def list_album_items(self, album_id: str) -> list[dict[str, Any]]:
        return list(self.album_items.get(album_id, []))

    def upload_raw_bytes(self, local_path: str, callback: Any = None) -> str:
        self.uploaded_raw.append((local_path, callback))
        return "mock_upload_token_xyz"

    def create_media_item(self, upload_token: str, filename: str, album_id: str | None = None) -> bool:
        self.created_items.append((upload_token, filename, album_id))
        return True

    def download_stream(self, download_url: str, local_path: str, callback: Any = None) -> bool:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        Path(local_path).write_bytes(b"downloaded_bytes")
        if callback:
            callback(16, 16)
        return True

    def remove_from_album(self, album_id: str, media_item_ids: list[str]) -> bool:
        self.removed_items.append((album_id, media_item_ids))
        return True


class GooglePhotosProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeGooglePhotosClient()
        self.storage = GooglePhotosStorage(client=self.client, remote_name="my_photos")

    def test_delete_capability_is_permanent_only(self) -> None:
        self.assertEqual(self.storage.delete_capability, DeleteCapability.PERMANENT_ONLY)
        self.assertFalse(self.storage.delete_capability.supports_trash)
        self.assertTrue(self.storage.delete_capability.supports_permanent)

    def test_root_virtual_hierarchy_listing(self) -> None:
        root_items = self.storage.list_dir("/")
        item_names = [item.name for item in root_items]
        self.assertIn("Trip2026", item_names)
        self.assertIn("Family", item_names)
        self.assertIn("_all", item_names)

        all_dir = next(i for i in root_items if i.name == "_all")
        self.assertTrue(all_dir.is_dir)
        self.assertEqual(all_dir.path, "/_all")

        trip_dir = next(i for i in root_items if i.name == "Trip2026")
        self.assertTrue(trip_dir.is_dir)
        self.assertEqual(trip_dir.path, "/Trip2026")

    def test_library_all_virtual_folder_listing(self) -> None:
        all_items = self.storage.list_dir("/_all")
        self.assertEqual(len(all_items), 2)
        filenames = [i.name for i in all_items]
        self.assertIn("sunset.jpg", filenames)
        self.assertIn("clip.mp4", filenames)
        for item in all_items:
            self.assertFalse(item.is_dir)
            self.assertTrue(item.path.startswith("/_all/"))
            self.assertIsNone(item.remote_hash)
            self.assertIsInstance(item.modified_at, datetime)

    def test_album_folder_listing(self) -> None:
        album_items = self.storage.list_dir("/Trip2026")
        self.assertEqual(len(album_items), 1)
        self.assertEqual(album_items[0].name, "fuji.jpg")
        self.assertEqual(album_items[0].path, "/Trip2026/fuji.jpg")
        self.assertFalse(album_items[0].is_dir)
        self.assertIsNone(album_items[0].remote_hash)

    def test_deep_nested_directory_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "不支援多層巢狀目錄結構"):
            self.storage.list_dir("/Trip2026/SubAlbum")

        with self.assertRaisesRegex(ValueError, "不支援多層巢狀目錄結構"):
            self.storage.upload("test.jpg", "/Trip2026/Sub/test.jpg")

    def test_upload_supported_mime_types(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            jpg_file = Path(tmp_dir) / "photo.jpg"
            jpg_file.write_bytes(b"dummy_jpg")
            mp4_file = Path(tmp_dir) / "video.mp4"
            mp4_file.write_bytes(b"dummy_mp4")

            # Upload to album
            self.assertTrue(self.storage.upload(str(jpg_file), "/Trip2026/photo.jpg"))
            self.assertEqual(len(self.client.created_items), 1)
            token, fname, alb_id = self.client.created_items[0]
            self.assertEqual(token, "mock_upload_token_xyz")
            self.assertEqual(fname, "photo.jpg")
            self.assertEqual(alb_id, "alb-1")

            # Upload to root / library
            self.assertTrue(self.storage.upload(str(mp4_file), "/video.mp4"))
            self.assertEqual(len(self.client.created_items), 2)
            token2, fname2, alb_id2 = self.client.created_items[1]
            self.assertEqual(fname2, "video.mp4")
            self.assertIsNone(alb_id2)

    def test_upload_unsupported_mime_types_rejected(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            pdf_file = Path(tmp_dir) / "document.pdf"
            pdf_file.write_bytes(b"dummy_pdf")
            bin_file = Path(tmp_dir) / "data.bin"
            bin_file.write_bytes(b"dummy_bin")

            with self.assertRaisesRegex(ValueError, "不支援的媒體格式"):
                self.storage.upload(str(pdf_file), "/Trip2026/document.pdf")

            with self.assertRaisesRegex(ValueError, "不支援的媒體格式"):
                self.storage.upload(str(bin_file), "/Trip2026/data.bin")

    def test_delete_protection_rejects_global_library_delete(self) -> None:
        with self.assertRaisesRegex(NotImplementedError, "不支援自相簿庫全域刪除照片"):
            self.storage.delete("/_all/sunset.jpg")

        with self.assertRaisesRegex(NotImplementedError, "不支援自相簿庫全域刪除照片"):
            self.storage.delete("/sunset.jpg")

    def test_delete_from_album_removes_association(self) -> None:
        self.assertTrue(self.storage.delete("/Trip2026/fuji.jpg"))
        self.assertEqual(len(self.client.removed_items), 1)
        alb_id, item_ids = self.client.removed_items[0]
        self.assertEqual(alb_id, "alb-1")
        self.assertEqual(item_ids, ["item-3"])

    def test_stat_root_and_folder_and_file(self) -> None:
        root_stat = self.storage.stat("/")
        self.assertEqual(root_stat["type"], "remote")

        album_stat = self.storage.stat("/Trip2026")
        self.assertEqual(album_stat["type"], "folder")

        file_stat = self.storage.stat("/Trip2026/fuji.jpg")
        self.assertEqual(file_stat["type"], "file")
        self.assertEqual(file_stat["name"], "fuji.jpg")
        self.assertIsInstance(file_stat["modified"], datetime)

    def test_mkdir_creates_album(self) -> None:
        self.assertTrue(self.storage.mkdir("/NewAlbum"))
        self.assertIn("NewAlbum", self.client.created_albums)

        with self.assertRaisesRegex(ValueError, "不支援多層巢狀目錄結構"):
            self.storage.mkdir("/Album/SubAlbum")

    def test_get_thumbnail_link_and_list_dir_thumbnails(self) -> None:
        # 1. get_thumbnail_link
        thumb_url = self.storage.get_thumbnail_link("/Trip2026/fuji.jpg")
        self.assertEqual(thumb_url, "https://lh3.googleusercontent.com/fuji=w300-h300")

        # 2. list_dir has thumbnail_url populated
        items = self.storage.list_dir("/Trip2026")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].thumbnail_url, "https://lh3.googleusercontent.com/fuji=w300-h300")


if __name__ == "__main__":
    unittest.main()
