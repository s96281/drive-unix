# tests/unit/test_photos_config.py
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from auth.cache import get_drive_token_cache_path, get_photos_token_cache_path
from core.config import ConfigManager, GooglePhotosRemote, RemoteType
from storage.registry import DEFAULT_PROVIDER_REGISTRY


class GooglePhotosConfigTests(unittest.TestCase):
    def test_remote_type_enum(self) -> None:
        self.assertEqual(RemoteType.GOOGLE_PHOTOS.value, "googlephotos")

    def test_config_serialization_and_deserialization(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.toml"
            cm = ConfigManager(config_path=config_path)

            remote = GooglePhotosRemote(
                type="googlephotos",
                credentials_json="secret-files/myphotos_credentials.json",
                default_album="Vacation",
            )
            cm.add_remote("myphotos", remote)

            # Reload from disk
            cm_reloaded = ConfigManager(config_path=config_path)
            loaded_remote = cm_reloaded.get_remote("myphotos")

            self.assertIsInstance(loaded_remote, GooglePhotosRemote)
            self.assertEqual(loaded_remote.type, "googlephotos")
            self.assertEqual(loaded_remote.credentials_json, "secret-files/myphotos_credentials.json")
            self.assertEqual(loaded_remote.default_album, "Vacation")

    def test_token_cache_isolation_from_google_drive(self) -> None:
        name = "work_cloud"
        cache_dir = Path("/mock/cache")

        photos_cache = get_photos_token_cache_path(name, cache_dir)
        drive_cache = get_drive_token_cache_path(name, cache_dir)

        # Cache paths must not collide
        self.assertNotEqual(photos_cache, drive_cache)
        self.assertEqual(photos_cache.name, "googlephotos_work_cloud_token.json")
        self.assertEqual(drive_cache.name, "work_cloud_gdrive_token.json")
        self.assertTrue(photos_cache.name.startswith("googlephotos_"))

    def test_provider_registry_contains_googlephotos(self) -> None:
        self.assertIn("googlephotos", DEFAULT_PROVIDER_REGISTRY.supported_types())

    def test_token_scope_requirements(self) -> None:
        from auth.providers.google_photos import GooglePhotosAuthProvider

        with TemporaryDirectory() as tmp_dir:
            dummy_cred = Path(tmp_dir) / "dummy.json"
            dummy_cred.write_text("{}", encoding="utf-8")
            provider = GooglePhotosAuthProvider(
                credentials_json=str(dummy_cred),
                token_cache_path=str(Path(tmp_dir) / "token.json"),
            )
            self.assertIn("https://www.googleapis.com/auth/photoslibrary.appendonly", provider.SCOPES)
            self.assertIn("https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata", provider.SCOPES)
            self.assertIn("https://www.googleapis.com/auth/photoslibrary.edit.appcreateddata", provider.SCOPES)


if __name__ == "__main__":
    unittest.main()
