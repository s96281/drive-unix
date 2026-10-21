from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from auth.providers.sharepoint_cookie import (
    SharePointCookieNotFoundError,
    SharePointLoginRecorder,
    SharePointLoginTimeoutError,
    _capture_failure_artifact,
    _detect_microsoft_authenticator_challenge,
    _save_active_mfa_status,
    _wait_for_condition_with_recording,
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


def test_sharepoint_login_recorder_cleanup_on_success(tmp_path: Path):
    recorder = SharePointLoginRecorder(base_dir=tmp_path)
    assert recorder.session_dir is not None
    assert recorder.session_dir.exists()

    mock_page = MagicMock()
    frame1 = recorder.capture(mock_page, step_label="step1")
    frame2 = recorder.capture(mock_page, step_label="step2")

    assert len(recorder.frames) == 2
    assert mock_page.screenshot.call_count == 2
    assert "📸 登入歷程連環截圖" in recorder.get_summary()

    # Success cleanup
    recorder.cleanup_on_success()
    assert not recorder.session_dir.exists()


def test_wait_for_condition_with_recording_polls_and_captures(tmp_path: Path):
    recorder = SharePointLoginRecorder(base_dir=tmp_path)
    mock_page = MagicMock()

    calls = 0

    def check():
        nonlocal calls
        calls += 1
        return calls >= 3

    ok = _wait_for_condition_with_recording(
        mock_page,
        check,
        timeout_ms=5000,
        step_name="test_step",
        recorder=recorder,
        poll_interval_ms=10,
    )

    assert ok is True
    assert calls >= 3
    assert len(recorder.frames) >= 2


def test_web_debug_screenshot_endpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SHAREPOINT_SCREENSHOT_DIR", str(tmp_path))

    # Create dummy screenshot in root
    img1 = tmp_path / "sharepoint_timeout_20261022_000100.png"
    img1.write_bytes(b"\x89PNG\r\n\x1a\nfakeimagebytes1")

    # Create dummy screenshot in subfolder (recorded session)
    sub_dir = tmp_path / "sharepoint_session_20261022_000200"
    sub_dir.mkdir()
    img2 = sub_dir / "frame_001_00s_email.png"
    img2.write_bytes(b"\x89PNG\r\n\x1a\nfakeimagebytes2")

    app = create_app()
    client = TestClient(app)

    # 1. List screenshots (should find both root and session frames)
    res = client.get("/api/settings/debug/screenshots")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    filenames = {d["filename"] for d in data}
    assert img1.name in filenames
    assert img2.name in filenames

    # 2. Get existing screenshot in subfolder
    sub_url = next(d["url"] for d in data if d["filename"] == img2.name)
    res_img2 = client.get(sub_url)
    assert res_img2.status_code == 200
    assert res_img2.headers["content-type"] == "image/png"
    assert res_img2.content == b"\x89PNG\r\n\x1a\nfakeimagebytes2"

    # 3. Non-existent screenshot -> 404
    res_404 = client.get("/api/settings/debug/screenshots/non_existent.png")
    assert res_404.status_code == 404

    # 4. Path traversal attempt -> 400 or 404 (Starlette URL path normalizer)
    res_traversal = client.get("/api/settings/debug/screenshots/../test.png")
    assert res_traversal.status_code in (400, 404)


def test_detect_microsoft_authenticator_challenge_number_matching():
    # 1. Element with richContext_display contains number 42
    mock_page = MagicMock()
    mock_loc = MagicMock()
    mock_loc.count.return_value = 1
    mock_loc.first.inner_text.return_value = " 42 "
    mock_page.locator.return_value = mock_loc

    is_mfa, number = _detect_microsoft_authenticator_challenge(mock_page)
    assert is_mfa is True
    assert number == "42"


def test_detect_microsoft_authenticator_challenge_push_no_number():
    # 2. General push title without number
    mock_page = MagicMock()
    # loc count 0 for richContext, but 1 for SAASTO title
    def loc_side_effect(sel):
        m = MagicMock()
        if "SAASTO" in sel:
            m.count.return_value = 1
            m.first.is_visible.return_value = True
            m.first.inner_text.return_value = "Approve sign in request"
        else:
            m.count.return_value = 0
        return m
    mock_page.locator.side_effect = loc_side_effect

    is_mfa, number = _detect_microsoft_authenticator_challenge(mock_page)
    assert is_mfa is True
    assert number is None


def test_mfa_status_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SHAREPOINT_SCREENSHOT_DIR", str(tmp_path))
    app = create_app()
    client = TestClient(app)

    # 1. Initially inactive
    res = client.get("/api/settings/debug/mfa-status")
    assert res.status_code == 200
    assert res.json()["active"] is False

    # 2. When challenge is active
    status_file = tmp_path / "mfa_challenge.json"
    import time
    status_file.write_text('{"active": true, "number": "88", "updated_at": ' + str(time.time()) + '}', encoding="utf-8")

    res_active = client.get("/api/settings/debug/mfa-status")
    assert res_active.status_code == 200
    assert res_active.json()["active"] is True
    assert res_active.json()["number"] == "88"
