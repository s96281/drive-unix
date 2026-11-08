"""Unit tests for Directory Cache and Web Settings Management."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Generator
import time

import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from core.config import ConfigManager, LocalRemote
from core.secrets import SecretRepository
from domain.models import FileItem
from web.app import create_app
from web.cache import DirectoryCacheManager, directory_cache
from web.dependencies import get_config_manager
from web.settings import WebSettingsManager, web_settings_manager


def test_directory_cache_basic_operations() -> None:
    cache = DirectoryCacheManager(default_ttl=10, max_entries=5)

    item1 = FileItem(name="doc.txt", path="/doc.txt", is_dir=False, size=100)
    assert cache.get("local", "/") is None
    stats = cache.get_stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 0

    cache.put("local", "/", [item1])
    cached = cache.get("local", "/")
    assert cached is not None
    assert len(cached) == 1
    assert cached[0].name == "doc.txt"

    stats = cache.get_stats()
    assert stats["hits"] == 1
    assert stats["current_entries"] == 1
    assert "local" in stats["cached_remotes"]


def test_directory_cache_expiry() -> None:
    cache = DirectoryCacheManager(default_ttl=1, max_entries=5)
    item = FileItem(name="temp.txt", path="/temp.txt", is_dir=False, size=50)

    cache.put("local", "/", [item], ttl=0)  # Immediate expiry
    time.sleep(0.01)
    res = cache.get("local", "/")
    assert res is None


def test_directory_cache_eviction() -> None:
    cache = DirectoryCacheManager(default_ttl=60, max_entries=2)
    item = FileItem(name="a.txt", path="/a.txt", is_dir=False, size=10)

    cache.put("remote1", "/dir1", [item])
    cache.put("remote1", "/dir2", [item])
    assert cache.get_stats()["current_entries"] == 2

    cache.put("remote1", "/dir3", [item])
    # Should still be <= 2
    assert cache.get_stats()["current_entries"] == 2


def test_directory_cache_invalidation() -> None:
    cache = DirectoryCacheManager(default_ttl=60, max_entries=10)
    item = FileItem(name="file.txt", path="/a/b/file.txt", is_dir=False, size=10)

    cache.put("s3", "/", [item])
    cache.put("s3", "/a", [item])
    cache.put("s3", "/a/b", [item])
    cache.put("gcs", "/other", [item])

    # Invalidate /a in s3 (should invalidate /a, /a/b, and parent /)
    invalidated = cache.invalidate("s3", "/a")
    assert invalidated >= 2
    assert cache.get("s3", "/a") is None

    # Clear all
    cleared = cache.clear()
    assert cleared >= 1
    assert cache.get_stats()["current_entries"] == 0


def test_web_settings_persistence(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "web_cfg"
    mgr = WebSettingsManager(config_dir=cfg_dir)

    assert mgr.settings.site_title() if callable(mgr.settings.ui.site_title) else mgr.settings.ui.site_title == "drive-unix"
    assert mgr.settings.cache.ttl_seconds == 300

    mgr.update({"ui": {"site_title": "Custom Cloud Drive"}, "cache": {"ttl_seconds": 600}})
    assert mgr.settings.ui.site_title == "Custom Cloud Drive"
    assert mgr.settings.cache.ttl_seconds == 600

    # Reload from file
    mgr2 = WebSettingsManager(config_dir=cfg_dir)
    assert mgr2.settings.ui.site_title == "Custom Cloud Drive"
    assert mgr2.settings.cache.ttl_seconds == 600


@pytest.fixture
def temp_env(tmp_path: Path) -> Generator[tuple[ConfigManager, Path], None, None]:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.toml"
    secrets_file = config_dir / "secrets.json"

    secret_store = SecretRepository(secrets_file)
    manager = ConfigManager(config_file, secret_store=secret_store)

    local_root = tmp_path / "storage"
    local_root.mkdir(parents=True, exist_ok=True)
    manager.add_remote("node1", LocalRemote(type="local", root_path=str(local_root)))

    yield manager, local_root


@pytest.fixture
def client(temp_env: tuple[ConfigManager, Path]) -> Generator[TestClient, None, None]:
    manager, _ = temp_env
    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_settings_api_lifecycle(client: TestClient) -> None:
    # 1. Get settings
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "settings" in data
    assert "cache_stats" in data
    assert "cache" in data["settings"]

    # 2. Update settings
    update_resp = client.put(
        "/api/settings",
        json={
            "cache": {"ttl_seconds": 450, "max_entries": 2000},
            "ui": {"site_title": "My Enterprise Cloud"},
        },
    )
    assert update_resp.status_code == 200
    updated_data = update_resp.json()
    assert updated_data["settings"]["cache"]["ttl_seconds"] == 450
    assert updated_data["settings"]["ui"]["site_title"] == "My Enterprise Cloud"
    assert directory_cache.default_ttl == 450

    # 3. Cache stats endpoint
    stats_resp = client.get("/api/settings/cache/stats")
    assert stats_resp.status_code == 200
    assert "hit_ratio_percent" in stats_resp.json()

    # 4. Clear cache endpoint
    clear_resp = client.post("/api/settings/cache/clear")
    assert clear_resp.status_code == 200
    assert clear_resp.json()["status"] == "cleared"


def test_fs_directory_caching_integration(client: TestClient, temp_env: tuple[ConfigManager, Path]) -> None:
    _, local_root = temp_env
    directory_cache.clear()
    directory_cache.reset_stats()

    # 1. First listing (Cache MISS)
    resp1 = client.get("/api/fs/node1/ls?path=/")
    assert resp1.status_code == 200
    stats1 = directory_cache.get_stats()
    assert stats1["misses"] == 1
    assert stats1["hits"] == 0

    # 2. Second listing (Cache HIT)
    resp2 = client.get("/api/fs/node1/ls?path=/")
    assert resp2.status_code == 200
    stats2 = directory_cache.get_stats()
    assert stats2["hits"] == 1

    # 3. Force refresh (Bypass Cache)
    resp3 = client.get("/api/fs/node1/ls?path=/&refresh=true")
    assert resp3.status_code == 200

    # 4. Create directory invalidates cache
    mkdir_resp = client.post("/api/fs/node1/mkdir", json={"path": "/cached_folder"})
    assert mkdir_resp.status_code == 201

    # Next listing without refresh should re-fetch because mkdir invalidated "/"
    stats_before = directory_cache.get_stats()
    resp4 = client.get("/api/fs/node1/ls?path=/")
    assert resp4.status_code == 200
    items = [it["name"] for it in resp4.json()["items"]]
    assert "cached_folder" in items


def test_directory_cache_disk_persistence_restart(tmp_path: Path) -> None:
    db_file = tmp_path / "cache_persist.db"

    # 1. First process session: populate cache and persist to SQLite
    cache_session1 = DirectoryCacheManager(
        default_ttl=300,
        max_entries=100,
        persist_to_disk=True,
        db_path=db_file,
    )
    items = [
        FileItem(name="video.mp4", path="/media/video.mp4", is_dir=False, size=1048576, thumbnail_url="https://cdn/thumb.jpg"),
        FileItem(name="doc.pdf", path="/media/doc.pdf", is_dir=False, size=2048),
    ]
    cache_session1.put("cloud_remote", "/media", items)
    stats1 = cache_session1.get_stats()
    assert stats1["current_entries"] == 1
    assert stats1["persisted_dirs"] == 1
    cache_session1.close()

    # 2. Simulate application restart: instantiate a fresh DirectoryCacheManager with the same DB file
    cache_session2 = DirectoryCacheManager(
        default_ttl=300,
        max_entries=100,
        persist_to_disk=True,
        db_path=db_file,
    )
    # Warmup should have loaded the items into memory upon startup
    stats2 = cache_session2.get_stats()
    assert stats2["current_entries"] == 1
    assert stats2["persisted_dirs"] == 1
    assert "cloud_remote" in stats2["cached_remotes"]

    # Retrieval after restart must be a cache HIT without contacting provider
    retrieved = cache_session2.get("cloud_remote", "/media")
    assert retrieved is not None
    assert len(retrieved) == 2
    assert retrieved[0].name == "video.mp4"
    assert retrieved[0].thumbnail_url == "https://cdn/thumb.jpg"
    assert cache_session2.get_stats()["hits"] == 1
    cache_session2.close()


def test_thumbnail_cache_persistence_restart(tmp_path: Path) -> None:
    db_file = tmp_path / "thumb_persist.db"

    # Session 1: cache thumbnail
    c1 = DirectoryCacheManager(persist_to_disk=True, db_path=db_file)
    c1.put_thumbnail("onedrive", "/photos/pic.jpg", "https://onedrive.live.com/thumb/123.jpg")
    assert c1.get_thumbnail("onedrive", "/photos/pic.jpg") == "https://onedrive.live.com/thumb/123.jpg"
    c1.close()

    # Session 2 (restart)
    c2 = DirectoryCacheManager(persist_to_disk=True, db_path=db_file)
    # Warmup restores thumbnail
    assert c2.get_thumbnail("onedrive", "/photos/pic.jpg") == "https://onedrive.live.com/thumb/123.jpg"
    stats = c2.get_stats()
    assert stats["persisted_thumbs"] == 1
    c2.close()


def test_persistent_cache_invalidation_and_clear(tmp_path: Path) -> None:
    db_file = tmp_path / "inv_test.db"
    c1 = DirectoryCacheManager(persist_to_disk=True, db_path=db_file)
    item = FileItem(name="f.txt", path="/dir/sub/f.txt", is_dir=False, size=10)
    c1.put("r1", "/dir", [item])
    c1.put("r1", "/dir/sub", [item])
    c1.put_thumbnail("r1", "/dir/sub/f.txt", "https://thumb/f.jpg")
    assert c1.get_stats()["persisted_dirs"] == 2

    # Invalidate /dir should clear /dir, /dir/sub, and the thumbnail
    c1.invalidate("r1", "/dir")
    assert c1.get_stats()["persisted_dirs"] == 0
    assert c1.get_thumbnail("r1", "/dir/sub/f.txt") is None
    c1.close()

    # Restart session: verify disk state is empty
    c2 = DirectoryCacheManager(persist_to_disk=True, db_path=db_file)
    assert c2.get("r1", "/dir") is None
    assert c2.get_stats()["persisted_dirs"] == 0
    c2.close()


def test_persistent_cache_expired_pruning_on_restart(tmp_path: Path) -> None:
    db_file = tmp_path / "expiry_test.db"
    c1 = DirectoryCacheManager(persist_to_disk=True, db_path=db_file)
    item = FileItem(name="exp.txt", path="/exp.txt", is_dir=False, size=5)
    # Store with 0-second TTL (immediate expiration)
    c1.put("r1", "/", [item], ttl=0)
    c1.put_thumbnail("r1", "/exp.txt", "https://thumb", ttl=0)
    time.sleep(0.02)
    c1.close()

    # Restart session: startup prune cleans expired rows
    c2 = DirectoryCacheManager(persist_to_disk=True, db_path=db_file)
    assert c2.get("r1", "/") is None
    assert c2.get_thumbnail("r1", "/exp.txt") is None
    assert c2.get_stats()["persisted_dirs"] == 0
    assert c2.get_stats()["persisted_thumbs"] == 0
    c2.close()

