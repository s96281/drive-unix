"""Unit tests for Virtual Filesystem API (/api/fs)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from core.config import ConfigManager, LocalRemote
from core.secrets import SecretRepository
from web.app import create_app
from web.dependencies import get_config_manager


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
    manager.add_remote("local_node", LocalRemote(type="local", root_path=str(local_root)))

    yield manager, local_root


@pytest.fixture
def client(temp_env: tuple[ConfigManager, Path]) -> Generator[TestClient, None, None]:
    manager, _ = temp_env
    app = create_app()
    app.dependency_overrides[get_config_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_filesystem_lifecycle(client: TestClient, temp_env: tuple[ConfigManager, Path]) -> None:
    _, local_root = temp_env

    # 1. Initially empty directory
    ls_resp = client.get("/api/fs/local_node/ls?path=/")
    assert ls_resp.status_code == 200
    data = ls_resp.json()
    assert data["total_count"] == 0

    # 2. Make directory
    mkdir_resp = client.post(
        "/api/fs/local_node/mkdir",
        json={"path": "/subfolder", "parents": False},
    )
    assert mkdir_resp.status_code == 201

    # 3. Upload a file into /subfolder
    file_content = b"Hello, drive-unix web storage!"
    upload_resp = client.post(
        "/api/fs/local_node/upload",
        data={"target_dir": "/subfolder"},
        files={"file": ("hello.txt", io.BytesIO(file_content), "text/plain")},
    )
    assert upload_resp.status_code == 201
    upload_data = upload_resp.json()
    assert upload_data["status"] == "uploaded"
    assert upload_data["path"] == "/subfolder/hello.txt"
    assert upload_data["size"] == len(file_content)

    # 4. List directory again
    ls_sub = client.get("/api/fs/local_node/ls?path=/subfolder")
    assert ls_sub.status_code == 200
    items = ls_sub.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "hello.txt"
    assert items[0]["size"] == len(file_content)
    assert items[0]["is_dir"] is False

    # 5. Stat file
    stat_resp = client.get("/api/fs/local_node/stat?path=/subfolder/hello.txt")
    assert stat_resp.status_code == 200
    assert stat_resp.json()["name"] == "hello.txt"

    # 6. Download file
    dl_resp = client.get("/api/fs/local_node/download?path=/subfolder/hello.txt")
    assert dl_resp.status_code == 200
    assert dl_resp.content == file_content

    # 7. Delete file
    del_file = client.post(
        "/api/fs/local_node/delete",
        json={"path": "/subfolder/hello.txt", "permanent": True},
    )
    assert del_file.status_code == 200

    # 8. Delete directory
    del_dir = client.post(
        "/api/fs/local_node/delete",
        json={"path": "/subfolder", "permanent": True},
    )
    assert del_dir.status_code == 200

    # Verify directory is empty again
    ls_final = client.get("/api/fs/local_node/ls?path=/")
    assert ls_final.status_code == 200
    assert ls_final.json()["total_count"] == 0


def test_path_traversal_rejection(client: TestClient) -> None:
    # Attempting to read outside boundary
    resp = client.get("/api/fs/local_node/ls?path=/../../../../windows")
    assert resp.status_code == 400


def test_thumbnail_endpoint_unsupported(client: TestClient, temp_env: tuple[ConfigManager, Path]) -> None:
    # LocalStorage raises NotImplementedError, which returns 501
    resp = client.get("/api/fs/local_node/thumbnail?path=/sample.jpg")
    assert resp.status_code == 501
    assert "不支援獲取縮圖" in resp.json()["detail"]


def test_thumbnail_endpoint_success_and_redirect(
    client: TestClient,
    temp_env: tuple[ConfigManager, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock
    from web.routers import files as files_router

    mock_provider = MagicMock()
    mock_provider.get_thumbnail_link.return_value = "https://cdn.example.com/thumb.jpg"

    monkeypatch.setattr(files_router, "resolve_storage", lambda remote, cm: mock_provider)

    # 1. JSON response
    resp = client.get("/api/fs/local_node/thumbnail?path=/photo.jpg")
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == "https://cdn.example.com/thumb.jpg"
    assert data["thumbnail_url"] == "https://cdn.example.com/thumb.jpg"
    assert data["remote"] == "local_node"
    assert data["path"] == "/photo.jpg"

    # 2. Redirect response
    resp_redirect = client.get(
        "/api/fs/local_node/thumbnail?path=/photo.jpg&redirect=true",
        follow_redirects=False,
    )
    assert resp_redirect.status_code == 307
    assert resp_redirect.headers["location"] == "https://cdn.example.com/thumb.jpg"

    # 3. Alias endpoint /thumbnail-link
    resp_alias = client.get("/api/fs/local_node/thumbnail-link?path=/photo.jpg")
    assert resp_alias.status_code == 200
    assert resp_alias.json()["url"] == "https://cdn.example.com/thumb.jpg"


def test_thumbnail_endpoint_error_handling(
    client: TestClient,
    temp_env: tuple[ConfigManager, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock
    import requests
    from infrastructure.http import HttpStatusError
    from web.routers import files as files_router

    mock_provider = MagicMock()

    # 1. ValueError maps to 404
    mock_provider.get_thumbnail_link.side_effect = ValueError("此檔案無可用縮圖")
    monkeypatch.setattr(files_router, "resolve_storage", lambda remote, cm: mock_provider)
    resp = client.get("/api/fs/local_node/thumbnail?path=/video.mp4")
    assert resp.status_code == 404
    assert "此檔案無可用縮圖" in resp.json()["detail"]

    # 2. HttpStatusError 404 maps to 404
    fake_404 = requests.Response()
    fake_404.status_code = 404
    fake_404.url = "https://example.com"
    fake_404.request = requests.Request("GET", "https://example.com").prepare()
    mock_provider.get_thumbnail_link.side_effect = HttpStatusError("Not found", response=fake_404)
    resp_404 = client.get("/api/fs/local_node/thumbnail?path=/doc.pdf")
    assert resp_404.status_code == 404
    assert "無法取得縮圖" in resp_404.json()["detail"]

    # 3. Unexpected RuntimeError maps to 500
    mock_provider.get_thumbnail_link.side_effect = RuntimeError("Something unexpected")
    resp_500 = client.get("/api/fs/local_node/thumbnail?path=/unexpected.bin")
    assert resp_500.status_code == 500
    assert "取得縮圖失敗" in resp_500.json()["detail"]


def test_raw_and_link_endpoints(
    client: TestClient,
    temp_env: tuple[ConfigManager, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock
    from web.routers import files as files_router

    manager, local_root = temp_env
    test_file = local_root / "sample.mp4"
    test_file.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    # 1. LocalStorage raw streaming returns inline content-disposition and video/mp4
    resp_raw = client.get("/api/fs/local_node/raw?path=/sample.mp4")
    assert resp_raw.status_code == 200
    assert "video/mp4" in resp_raw.headers.get("content-type", "")
    assert "inline" in resp_raw.headers.get("content-disposition", "")
    assert resp_raw.content == b"\x00\x00\x00\x18ftypmp42"

    # 2. Direct link endpoint with mock
    mock_provider = MagicMock()
    mock_provider.get_download_link.return_value = "https://cdn.example.com/direct/sample.mp4"
    monkeypatch.setattr(files_router, "resolve_storage", lambda remote, cm: mock_provider)

    resp_link = client.get("/api/fs/local_node/link?path=/sample.mp4")
    assert resp_link.status_code == 200
    assert resp_link.json()["url"] == "https://cdn.example.com/direct/sample.mp4"

    resp_link_redirect = client.get(
        "/api/fs/local_node/link?path=/sample.mp4&redirect=true",
        follow_redirects=False,
    )
    assert resp_link_redirect.status_code == 307
    assert resp_link_redirect.headers["location"] == "https://cdn.example.com/direct/sample.mp4"


