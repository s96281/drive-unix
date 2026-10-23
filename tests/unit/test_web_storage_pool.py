"""Unit tests for Web connection pooling and provider connection reuse."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from core.config import ConfigManager, FTPRemote, LocalRemote
from core.secrets import SecretRepository
from domain.models import FileItem
from storage.base import DeleteCapability, StorageProvider, managed_storage
from web.app import create_app
from web.dependencies import get_config_manager, resolve_storage
from web.storage_pool import (
    FATAL_CONNECTION_ERRORS,
    PooledStorageProxy,
    WebStoragePool,
    compute_remote_config_hash,
)


class DummyStorage(StorageProvider):
    def __init__(self, name: str = "dummy") -> None:
        self.name = name
        self.closed = False
        self.close_count = 0
        self.list_dir_count = 0

    def list_dir(self, remote_path: str, offset: int = 0, limit: int | None = None) -> list[FileItem]:
        self.list_dir_count += 1
        return [FileItem(name="file1.txt", path="/file1.txt", is_dir=False, size=100)]

    def upload(self, local_path: str, remote_path: str, callback=None) -> bool:
        return True

    def download(self, remote_path: str, local_path: str, callback=None, recursive=True) -> bool:
        return True

    def delete(self, remote_path: str, permanent: bool = False) -> bool:
        return True

    def move(self, src: str, dst: str, overwrite: bool = False) -> bool:
        return True

    def copy(self, src: str, dst: str, overwrite: bool = False) -> bool:
        return True

    def mkdir(self, remote_path: str, parents: bool = False) -> bool:
        return True

    def stat(self, remote_path: str):
        return {"name": "root", "type": "folder", "size": 0}

    def get_hash(self, remote_path: str, algo: str) -> str:
        return "dummy_hash"

    def get_share_link(self, remote_path: str) -> str:
        return "https://example.com/share"

    def close(self) -> None:
        self.closed = True
        self.close_count += 1


@pytest.fixture
def temp_config(tmp_path: Path) -> ConfigManager:
    config_file = tmp_path / "config.toml"
    secrets_file = tmp_path / "secrets.json"
    repo = SecretRepository(secrets_file)
    manager = ConfigManager(config_file, secret_store=repo)
    path_a = tmp_path / "a"
    path_b = tmp_path / "b"
    path_a.mkdir(parents=True, exist_ok=True)
    path_b.mkdir(parents=True, exist_ok=True)
    manager.add_remote("node_a", LocalRemote(type="local", root_path=str(path_a)))
    manager.add_remote("node_b", LocalRemote(type="local", root_path=str(path_b)))
    return manager


def test_pool_basic_acquire_and_reuse(temp_config: ConfigManager) -> None:
    pool = WebStoragePool(idle_timeout_seconds=60)
    dummy = DummyStorage()

    with patch("web.storage_pool.get_storage_provider", return_value=dummy) as mock_get:
        # First acquire
        proxy1 = pool.acquire("node_a", temp_config)
        assert isinstance(proxy1, PooledStorageProxy)
        assert proxy1.target is dummy
        assert mock_get.call_count == 1

        # Second acquire - should reuse dummy from pool without re-calling factory
        proxy2 = pool.acquire("node_a", temp_config)
        assert isinstance(proxy2, PooledStorageProxy)
        assert proxy2.target is dummy
        assert mock_get.call_count == 1

        stats = pool.stats()
        assert stats["cached_remotes_count"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1


def test_managed_storage_does_not_close_underlying_connection(temp_config: ConfigManager) -> None:
    pool = WebStoragePool(idle_timeout_seconds=60)
    dummy = DummyStorage()

    with patch("web.storage_pool.get_storage_provider", return_value=dummy):
        proxy = pool.acquire("node_a", temp_config)

        # Simulate web router using with managed_storage(...)
        with managed_storage(proxy) as provider:
            items = provider.list_dir("/")
            assert len(items) == 1

        # managed_storage exited and called proxy.close(), but dummy MUST NOT be closed!
        assert dummy.closed is False
        assert dummy.close_count == 0

        # Further acquire still gets the alive dummy
        proxy_again = pool.acquire("node_a", temp_config)
        assert proxy_again.target is dummy
        assert dummy.closed is False


def test_config_hash_and_mutation_invalidation(temp_config: ConfigManager) -> None:
    pool = WebStoragePool(idle_timeout_seconds=60)
    dummy1 = DummyStorage("first")
    dummy2 = DummyStorage("second")

    with patch("web.storage_pool.get_storage_provider", side_effect=[dummy1, dummy2]):
        p1 = pool.acquire("node_a", temp_config)
        assert p1.target is dummy1

        # Mutate configuration for node_a (e.g. change root_path)
        temp_config.config.remotes["node_a"] = LocalRemote(type="local", root_path="/different/path")

        # Next acquire should detect config hash change, close old dummy1, and create dummy2
        p2 = pool.acquire("node_a", temp_config)
        assert p2.target is dummy2
        assert dummy1.closed is True
        assert dummy1.close_count == 1
        assert dummy2.closed is False


def test_idle_timeout_cleanup(temp_config: ConfigManager) -> None:
    pool = WebStoragePool(idle_timeout_seconds=1.0)
    dummy = DummyStorage()

    with patch("web.storage_pool.get_storage_provider", return_value=dummy):
        proxy = pool.acquire("node_a", temp_config)
        proxy.close()  # release from active in_use_count

        assert dummy.closed is False

        # Cleanup before timeout: should not evict
        evicted = pool.cleanup_idle(max_idle_seconds=10.0)
        assert evicted == 0
        assert dummy.closed is False

        # Cleanup with simulated elapsed time
        evicted = pool.cleanup_idle(max_idle_seconds=-1.0)  # force expired
        assert evicted == 1
        assert dummy.closed is True
        assert dummy.close_count == 1
        assert pool.stats()["cached_remotes_count"] == 0


def test_explicit_evict_and_clear(temp_config: ConfigManager) -> None:
    pool = WebStoragePool()
    dummy_a = DummyStorage("a")
    dummy_b = DummyStorage("b")

    with patch("web.storage_pool.get_storage_provider", side_effect=[dummy_a, dummy_b]):
        pool.acquire("node_a", temp_config)
        pool.acquire("node_b", temp_config)

        # Evict node_a
        assert pool.evict("node_a") is True
        assert dummy_a.closed is True
        assert dummy_b.closed is False

        # Clear pool
        pool.clear()
        assert dummy_b.closed is True
        assert pool.stats()["cached_remotes_count"] == 0


def test_fatal_connection_error_eviction(temp_config: ConfigManager) -> None:
    pool = WebStoragePool()
    dummy = DummyStorage()

    # Make list_dir raise a fatal socket error
    def faulty_list_dir(*args, **kwargs):
        raise ConnectionResetError("Connection reset by peer")

    dummy.list_dir = faulty_list_dir

    with patch("web.storage_pool.get_storage_provider", return_value=dummy):
        proxy = pool.acquire("node_a", temp_config)
        with pytest.raises(ConnectionResetError):
            proxy.list_dir("/")

        # Node_a should have been evicted automatically
        assert pool.stats()["cached_remotes_count"] == 0


def test_resolve_storage_integration(temp_config: ConfigManager) -> None:
    from web.dependencies import resolve_storage
    from web.storage_pool import storage_pool

    storage_pool.clear()
    try:
        # Default use_pool=True
        storage_pooled = resolve_storage("node_a", temp_config)
        assert isinstance(storage_pooled, PooledStorageProxy)

        # Explicit use_pool=False
        storage_raw = resolve_storage("node_a", temp_config, use_pool=False)
        assert not isinstance(storage_raw, PooledStorageProxy)
    finally:
        storage_pool.clear()


def test_web_api_connection_pool_stats_and_clear(temp_config: ConfigManager) -> None:
    from web.cache import directory_cache
    directory_cache.clear()

    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: temp_config
    client = TestClient(app)

    # 1. Browse files to populate pool (with refresh=True to bypass directory cache)
    res_ls = client.get("/api/fs/node_a/ls?path=/&refresh=true")
    assert res_ls.status_code == 200

    # 2. Query pool stats
    res_stats = client.get("/api/settings/connections")
    assert res_stats.status_code == 200
    stats = res_stats.json()
    assert stats["enabled"] is True
    assert stats["cached_remotes_count"] >= 1
    assert any(r["remote"] == "node_a" for r in stats["remotes"])

    # 3. Disconnect specific node
    res_disc = client.post("/api/remotes/node_a/disconnect")
    assert res_disc.status_code == 200
    assert res_disc.json()["status"] == "disconnected"

    # 4. Clear all connections
    res_clear = client.post("/api/settings/connections/clear")
    assert res_clear.status_code == 200
    assert res_clear.json()["stats"]["cached_remotes_count"] == 0


def test_ftp_connection_reuse_across_web_requests(temp_config: ConfigManager) -> None:
    """Verify that multiple Web API requests reuse the same underlying FTP connection."""
    from providers.ftp import FTPStorage
    from tests.unit.test_connection_reuse import FakeFTP
    from web.cache import directory_cache
    directory_cache.clear()

    class FakeFTPWithMLSD(FakeFTP):
        def cwd(self, path):
            return "250 OK"

        def mlsd(self, path):
            return [("test.txt", {"type": "file", "size": "100", "modify": "20261023120000"})]

    temp_config.add_remote("ftp_node", FTPRemote(type="ftp", host="ftp.example.com", port=21, user="test"))

    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: temp_config
    client = TestClient(app)

    fake_ftp = FakeFTPWithMLSD()

    with patch.object(FTPStorage, "_create_connection", return_value=fake_ftp) as mock_create_conn:
        # First Web API request -> creates FTP connection
        res1 = client.get("/api/fs/ftp_node/ls?path=/&refresh=true")
        assert res1.status_code == 200
        assert res1.json()["total_count"] == 1
        assert res1.json()["items"][0]["name"] == "test.txt"

        # Second Web API request -> reuses connection from pool (NOOP probe)
        res2 = client.get("/api/fs/ftp_node/ls?path=/sub&refresh=true")
        assert res2.status_code == 200

    # Ensure the FTP connection was not closed between requests
    assert fake_ftp.closed is False
    # Check that _create_connection was called only once across multiple web requests!
    assert mock_create_conn.call_count == 1
    # Check that NOOP was called during reuse
    assert fake_ftp.noop_calls >= 1


def test_sftp_connection_reuse_across_web_requests(temp_config: ConfigManager) -> None:
    """Verify that multiple Web API requests reuse the same underlying SFTP connection."""
    from core.config import SFTPRemote
    from providers.sftp import SFTPStorage
    from tests.unit.test_connection_reuse import FakeSSH, FakeSFTP
    from web.cache import directory_cache
    directory_cache.clear()

    class FakeSFTPAttr:
        filename = "sftp_file.txt"
        st_mode = 0o100644  # regular file
        st_size = 100
        st_mtime = 1700000000

    class FakeSFTPWithList(FakeSFTP):
        def chdir(self, path):
            pass

        def listdir_attr(self, path):
            return [FakeSFTPAttr()]

    pw_ref = temp_config.store_remote_secret("sftp_node", "password", "dummy_password")
    temp_config.add_remote(
        "sftp_node",
        SFTPRemote(type="sftp", host="sftp.example.com", port=22, username="test", password_ref=pw_ref),
    )

    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: temp_config
    client = TestClient(app)

    fake_ssh = FakeSSH()
    fake_sftp = FakeSFTPWithList()
    pair = (fake_ssh, fake_sftp)

    with patch.object(SFTPStorage, "_create_connection", return_value=pair) as mock_create_conn:
        # First Web API request -> creates SFTP connection
        res1 = client.get("/api/fs/sftp_node/ls?path=/&refresh=true")
        assert res1.status_code == 200
        assert res1.json()["total_count"] == 1
        assert res1.json()["items"][0]["name"] == "sftp_file.txt"

        # Second Web API request -> reuses SFTP connection
        res2 = client.get("/api/fs/sftp_node/ls?path=/sub&refresh=true")
        assert res2.status_code == 200

    # _create_connection was called only once across multiple web requests!
    assert mock_create_conn.call_count == 1
