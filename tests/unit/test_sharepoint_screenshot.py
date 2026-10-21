from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from auth.providers.sharepoint_cookie import (
    SharePointCookieNotFoundError,
    SharePointLoginTimeoutError,
    _capture_failure_artifact,
)
from fastapi.testclient import TestClient
from web.app import create_app


def test_capture_failure_artifact_saves_screenshot_and_error(tmp_path: Path):
    mock_page = MagicMock()
    mock_page.title.return_value = "Sign in to Microsoft"
    mock_page.url = "https://login.microsoftonline.com/common/login"

    mock_locator = MagicMock()
    mock_locator.count.return_value = 1
    mock_locator.first.inner_text.return_value = "密碼不正確，請重新輸入。"
    mock_page.locator.return_value = mock_locator

    screenshot_path, title, url, err_text = _capture_failure_artifact(
        mock_page,
        reason="bad_password",
        screenshot_dir=tmp_path,
    )

    assert title == "Sign in to Microsoft"
    assert url == "https://login.microsoftonline.com/common/login"
    assert err_text == "密碼不正確，請重新輸入。"
    assert screenshot_path is not None
    assert screenshot_path.parent == tmp_path
    assert "bad_password" in screenshot_path.name
    mock_page.screenshot.assert_called_once()


def test_web_debug_screenshot_endpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SHAREPOINT_SCREENSHOT_DIR", str(tmp_path))

    # Create dummy screenshot
    img1 = tmp_path / "sharepoint_timeout_20261022_000100.png"
    img1.write_bytes(b"\x89PNG\r\n\x1a\nfakeimagebytes")

    app = create_app()
    client = TestClient(app)

    # 1. List screenshots
    res = client.get("/api/settings/debug/screenshots")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["filename"] == img1.name
    assert data[0]["size_bytes"] == len(b"\x89PNG\r\n\x1a\nfakeimagebytes")
    assert data[0]["url"] == f"/api/settings/debug/screenshots/{img1.name}"

    # 2. Get existing screenshot
    res_img = client.get(f"/api/settings/debug/screenshots/{img1.name}")
    assert res_img.status_code == 200
    assert res_img.headers["content-type"] == "image/png"
    assert res_img.content == b"\x89PNG\r\n\x1a\nfakeimagebytes"

    # 3. Non-existent screenshot -> 404
    res_404 = client.get("/api/settings/debug/screenshots/non_existent.png")
    assert res_404.status_code == 404

    # 4. Path traversal attempt -> 400
    res_traversal = client.get("/api/settings/debug/screenshots/../test.png")
    assert res_traversal.status_code in (400, 404)
