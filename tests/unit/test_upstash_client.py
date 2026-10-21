from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
import requests

from infrastructure.upstash_client import (
    UpstashAuthError,
    UpstashClient,
    UpstashConnectionError,
    UpstashError,
)


def test_upstash_client_init_validation():
    with pytest.raises(ValueError, match="URL cannot be empty"):
        UpstashClient("", "token")

    with pytest.raises(ValueError, match="必須以 https:// 開頭"):
        UpstashClient("ftp://upstash.io", "token")

    with pytest.raises(ValueError, match="Token cannot be empty"):
        UpstashClient("https://upstash.io", "   ")


@patch("requests.Session.post")
def test_upstash_client_ping_success(mock_post):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"result": "PONG"}
    mock_post.return_value = mock_resp

    client = UpstashClient("https://example.upstash.io", "test-token")
    assert client.ping() is True

    mock_post.assert_called_once_with(
        "https://example.upstash.io",
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
        json=["PING"],
        timeout=10.0,
    )


@patch("requests.Session.post")
def test_upstash_client_get_and_set(mock_post):
    mock_resp_set = MagicMock()
    mock_resp_set.ok = True
    mock_resp_set.status_code = 200
    mock_resp_set.json.return_value = {"result": "OK"}

    mock_resp_get = MagicMock()
    mock_resp_get.ok = True
    mock_resp_get.status_code = 200
    mock_resp_get.json.return_value = {"result": "my_value"}

    mock_post.side_effect = [mock_resp_set, mock_resp_get]

    client = UpstashClient("https://example.upstash.io", "test-token")
    client.set("my_key", "my_value")
    val = client.get("my_key")
    assert val == "my_value"


@patch("requests.Session.post")
def test_upstash_client_auth_error_401(mock_post):
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 401
    mock_resp.json.return_value = {"error": "Unauthorized"}
    mock_post.return_value = mock_resp

    client = UpstashClient("https://example.upstash.io", "invalid-token")
    with pytest.raises(UpstashAuthError):
        client.ping()


@patch("requests.Session.post")
def test_upstash_client_timeout_error(mock_post):
    mock_post.side_effect = requests.Timeout("timed out")

    client = UpstashClient("https://example.upstash.io", "test-token")
    with pytest.raises(UpstashConnectionError, match="逾時"):
        client.ping()


@patch("requests.Session.post")
def test_upstash_client_delete_and_exists(mock_post):
    mock_resp_del = MagicMock()
    mock_resp_del.ok = True
    mock_resp_del.status_code = 200
    mock_resp_del.json.return_value = {"result": 1}

    mock_resp_exists = MagicMock()
    mock_resp_exists.ok = True
    mock_resp_exists.status_code = 200
    mock_resp_exists.json.return_value = {"result": 1}

    mock_post.side_effect = [mock_resp_del, mock_resp_exists]

    client = UpstashClient("https://example.upstash.io", "test-token")
    assert client.delete("key") == 1
    assert client.exists("key") is True
