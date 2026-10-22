from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from cli.app import create_app as create_cli_app
from core.config import ConfigManager, LocalRemote
from core.secrets import SecretRepository
from providers.local import LocalStorage
from providers.onedrive import OneDriveStorage
from web.app import create_app as create_web_app
from web.dependencies import get_config_manager


def test_local_storage_pagination(tmp_path: Path):
    folder = tmp_path / "test_folder"
    folder.mkdir()
    for i in range(25):
        (folder / f"file_{i:02d}.txt").write_text(f"content {i}")

    storage = LocalStorage(str(tmp_path))

    # All items
    all_items = storage.list_dir("/test_folder")
    assert len(all_items) == 25

    # Page 1: offset=0, limit=10
    page1 = storage.list_dir("/test_folder", offset=0, limit=10)
    assert len(page1) == 10

    # Page 2: offset=10, limit=10
    page2 = storage.list_dir("/test_folder", offset=10, limit=10)
    assert len(page2) == 10

    # Page 3: offset=20, limit=10
    page3 = storage.list_dir("/test_folder", offset=20, limit=10)
    assert len(page3) == 5

    # Offset beyond available items
    page_empty = storage.list_dir("/test_folder", offset=50, limit=10)
    assert len(page_empty) == 0

    # Zero limit
    assert storage.list_dir("/test_folder", limit=0) == []


def test_onedrive_sliding_window_pagination():
    mock_auth = MagicMock()
    mock_auth.get_auth_context.return_value = MagicMock(headers={"Authorization": "Bearer token"})
    storage = OneDriveStorage(mock_auth)
    storage.session = MagicMock()

    # User requests offset=150, limit=50 -> target_end = 200
    # Let max_page_size = 999
    # In 1 request, target_end < 999, so first_window = 200
    mock_items = [
        {"name": f"od_file_{i}.txt", "fileSystemInfo": {"lastModifiedDateTime": "2026-10-01T12:00:00Z"}}
        for i in range(200)
    ]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"value": mock_items}
    storage.session.get.return_value = mock_resp

    items = storage.list_dir("/documents", offset=150, limit=50)
    assert len(items) == 50
    assert items[0].name == "od_file_150.txt"
    assert items[-1].name == "od_file_199.txt"

    # Verify only 1 request was sent with $top=200
    assert storage.session.get.call_count == 1
    call_url = storage.session.get.call_args[0][0]
    qs = parse_qs(urlparse(call_url).query)
    assert qs["$top"] == ["200"]


def test_api_list_dir_pagination(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    manager = ConfigManager(
        config_dir / "config.toml",
        secret_store=SecretRepository(config_dir / "secrets.json"),
    )

    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    for i in range(20):
        (storage_root / f"file_{i:02d}.txt").write_text("data")

    manager.add_remote("local_node", LocalRemote(type="local", root_path=str(storage_root)))

    app = create_web_app()
    app.dependency_overrides[get_config_manager] = lambda: manager
    with TestClient(app) as client:
        # Request with offset=5, limit=5
        resp = client.get("/api/fs/local_node/ls?path=/&offset=5&limit=5&refresh=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 20
        assert len(data["items"]) == 5
        assert data["items"][0]["name"] == "file_05.txt"
        assert data["items"][4]["name"] == "file_09.txt"


def test_cli_ls_pagination(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    manager = ConfigManager(
        config_dir / "config.toml",
        secret_store=SecretRepository(config_dir / "secrets.json"),
    )

    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    for i in range(15):
        (storage_root / f"doc_{i:02d}.txt").write_text("data")

    manager.add_remote("local", LocalRemote(type="local", root_path=str(storage_root)))
    manager.config.default_remote = "local"

    from cli.context import CLIContext
    monkeypatch.setattr(CLIContext, "create", lambda: MagicMock(config=manager))

    runner = CliRunner()
    cli_app = create_cli_app()

    result = runner.invoke(cli_app, ["ls", "local:/", "--offset", "2", "--limit", "3", "--json"])
    assert result.exit_code == 0
    import json
    parsed = json.loads(result.stdout)
    assert len(parsed["items"]) == 3
    assert parsed["items"][0]["name"] == "doc_02.txt"
    assert parsed["items"][2]["name"] == "doc_04.txt"
