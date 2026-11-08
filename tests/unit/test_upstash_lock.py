from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from infrastructure.upstash_client import UpstashClient


@patch("requests.Session.post")
def test_acquire_lock_success(mock_post):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"result": "OK"}
    mock_post.return_value = mock_resp

    client = UpstashClient("https://example.upstash.io", "test-token")
    acquired = client.acquire_lock("drive-unix:lock:test", "dev-1", ttl_seconds=15)
    assert acquired is True

    mock_post.assert_called_once_with(
        "https://example.upstash.io",
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
        json=["SET", "drive-unix:lock:test", "dev-1", "NX", "EX", 15],
        timeout=10.0,
    )


@patch("requests.Session.post")
def test_acquire_lock_already_held(mock_post):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"result": None}  # Redis SET NX returns nil when already exists
    mock_post.return_value = mock_resp

    client = UpstashClient("https://example.upstash.io", "test-token")
    acquired = client.acquire_lock("drive-unix:lock:test", "dev-2", ttl_seconds=15)
    assert acquired is False


@patch("requests.Session.post")
def test_release_lock_owned_vs_unowned(mock_post):
    mock_resp_get = MagicMock()
    mock_resp_get.ok = True
    mock_resp_get.status_code = 200
    mock_resp_get.json.return_value = {"result": "dev-1"}

    mock_resp_del = MagicMock()
    mock_resp_del.ok = True
    mock_resp_del.status_code = 200
    mock_resp_del.json.return_value = {"result": 1}

    mock_post.side_effect = [mock_resp_get, mock_resp_del]

    client = UpstashClient("https://example.upstash.io", "test-token")
    # Release by true owner
    assert client.release_lock("drive-unix:lock:test", "dev-1") is True

    # Attempt to release by wrong owner
    mock_resp_get2 = MagicMock()
    mock_resp_get2.ok = True
    mock_resp_get2.status_code = 200
    mock_resp_get2.json.return_value = {"result": "dev-1"}
    mock_post.side_effect = [mock_resp_get2]

    assert client.release_lock("drive-unix:lock:test", "dev-other") is False
