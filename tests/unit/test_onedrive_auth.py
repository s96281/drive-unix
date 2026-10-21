from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from requests_oauthlib import OAuth2Session

from auth.exceptions import AuthLoginError
from auth.providers.onedrive import OneDriveAuthProvider, OAuthCallbackHandler, OAuthCallbackServer


def test_onedrive_interactive_login_uses_pkce(tmp_path: Path) -> None:
    token_cache = tmp_path / "token.json"
    provider = OneDriveAuthProvider(
        client_id="test-client-id",
        client_secret="test-client-secret",
        tenant="common",
        token_cache_path=str(token_cache),
    )

    mock_oauth = MagicMock(spec=OAuth2Session)
    mock_oauth.authorization_url.return_value = ("https://login.microsoft.com/auth", "state123")
    mock_oauth.fetch_token.return_value = {
        "access_token": "mock-access-token",
        "refresh_token": "mock-refresh-token",
        "expires_in": 3600,
    }

    def fake_server_init(self, server_address, handler_class):
        self.auth_code = "mock-code-123"
        self.auth_error = None
        self.auth_response = "http://localhost:8080/?code=mock-code-123&state=state123"

    with patch.object(OAuthCallbackServer, "__init__", fake_server_init), \
         patch.object(OAuthCallbackServer, "handle_request", return_value=None), \
         patch.object(OAuthCallbackServer, "server_close", return_value=None), \
         patch("webbrowser.open", return_value=True):
        token = provider._interactive_login(mock_oauth)

    assert token["access_token"] == "mock-access-token"
    mock_oauth.authorization_url.assert_called_once()
    _, kwargs = mock_oauth.authorization_url.call_args
    assert "code_challenge" in kwargs
    assert kwargs["code_challenge_method"] == "S256"
    assert len(kwargs["code_challenge"]) > 30

    mock_oauth.fetch_token.assert_called_once()
    _, fetch_kwargs = mock_oauth.fetch_token.call_args
    assert fetch_kwargs["code"] == "mock-code-123"
    assert "code_verifier" in fetch_kwargs
    assert len(fetch_kwargs["code_verifier"]) > 30
    assert fetch_kwargs["client_secret"] == "test-client-secret"


def test_onedrive_interactive_login_aadsts9002325_diagnostic_message(tmp_path: Path) -> None:
    token_cache = tmp_path / "token.json"
    provider = OneDriveAuthProvider(
        client_id="test-client-id",
        client_secret="",
        tenant="common",
        token_cache_path=str(token_cache),
    )

    mock_oauth = MagicMock(spec=OAuth2Session)
    mock_oauth.authorization_url.return_value = ("https://login.microsoft.com/auth", "state123")

    def fake_server_init(self, server_address, handler_class):
        self.auth_code = None
        self.auth_error = (
            "AADSTS9002325: Proof Key for Code Exchange is required for cross-origin authorization code redemption."
        )
        self.auth_response = "http://localhost:8080/?error=invalid_request"

    with patch.object(OAuthCallbackServer, "__init__", fake_server_init), \
         patch.object(OAuthCallbackServer, "handle_request", return_value=None), \
         patch.object(OAuthCallbackServer, "server_close", return_value=None), \
         patch("webbrowser.open", return_value=True):
        with pytest.raises(AuthLoginError) as exc_info:
            provider._interactive_login(mock_oauth)

    error_text = str(exc_info.value)
    assert "AADSTS9002325" in error_text
    assert "Web (網頁)" in error_text
    assert "單頁應用程式" in error_text


def test_oauth_callback_handler_parses_success_and_error() -> None:
    # 測試成功 callback
    mock_server_success = MagicMock(spec=OAuthCallbackServer)
    mock_server_success.auth_code = None
    mock_server_success.auth_error = None

    handler_success = OAuthCallbackHandler.__new__(OAuthCallbackHandler)
    handler_success.server = mock_server_success
    handler_success.path = "/?code=sample_auth_code&state=sample_state"
    handler_success.send_response = MagicMock()
    handler_success.send_header = MagicMock()
    handler_success.end_headers = MagicMock()
    handler_success.wfile = io.BytesIO()

    handler_success.do_GET()
    assert mock_server_success.auth_code == "sample_auth_code"
    assert b"\xe6\x8e\x88\xe6\xac\x8a\xe6\x88\x90\xe5\x8a\x9f" in handler_success.wfile.getvalue()  # "授權成功"

    # 測試失敗 callback (帶 AADSTS9002325)
    mock_server_err = MagicMock(spec=OAuthCallbackServer)
    mock_server_err.auth_code = None
    mock_server_err.auth_error = None

    handler_err = OAuthCallbackHandler.__new__(OAuthCallbackHandler)
    handler_err.server = mock_server_err
    handler_err.path = "/?error=invalid_request&error_description=AADSTS9002325%3a+Proof+Key+for+Code+Exchange"
    handler_err.send_response = MagicMock()
    handler_err.send_header = MagicMock()
    handler_err.end_headers = MagicMock()
    handler_err.wfile = io.BytesIO()

    handler_err.do_GET()
    assert "AADSTS9002325" in mock_server_err.auth_error
    response_body = handler_err.wfile.getvalue().decode("utf-8")
    assert "OneDrive 授權失敗" in response_body
    assert "Web (網頁)" in response_body


def test_onedrive_interactive_login_handles_scope_change_warning(tmp_path: Path) -> None:
    token_cache = tmp_path / "token.json"
    provider = OneDriveAuthProvider(
        client_id="test-client-id",
        client_secret="test-client-secret",
        tenant="common",
        token_cache_path=str(token_cache),
    )

    mock_oauth = MagicMock(spec=OAuth2Session)
    mock_oauth.authorization_url.return_value = ("https://login.microsoft.com/auth", "state123")

    warn = Warning('Scope has changed from "offline_access Files.ReadWrite.All" to "profile email Files.ReadWrite.All openid"')
    warn.token = {
        "access_token": "mock-scope-changed-token",
        "refresh_token": "mock-refresh-token",
        "expires_in": 3600,
    }
    warn.new_scope = ["profile", "email", "Files.ReadWrite.All", "openid"]
    mock_oauth.fetch_token.side_effect = warn

    def fake_server_init(self, server_address, handler_class):
        self.auth_code = "mock-code-123"
        self.auth_error = None
        self.auth_response = "http://localhost:8080/?code=mock-code-123"

    with patch.object(OAuthCallbackServer, "__init__", fake_server_init), \
         patch.object(OAuthCallbackServer, "handle_request", return_value=None), \
         patch.object(OAuthCallbackServer, "server_close", return_value=None), \
         patch("webbrowser.open", return_value=True):
        token = provider._interactive_login(mock_oauth)

    assert token["access_token"] == "mock-scope-changed-token"


def test_onedrive_refresh_handles_scope_change_warning(tmp_path: Path) -> None:
    token_cache = tmp_path / "token.json"
    import json
    with open(token_cache, "w") as f:
        json.dump({"access_token": "old", "refresh_token": "old-rt"}, f)

    provider = OneDriveAuthProvider(
        client_id="test-client-id",
        client_secret="test-client-secret",
        tenant="common",
        token_cache_path=str(token_cache),
    )

    warn = Warning('Scope has changed from "offline_access Files.ReadWrite.All" to "profile email Files.ReadWrite.All openid"')
    warn.token = {
        "access_token": "refreshed-token",
        "refresh_token": "new-rt",
        "expires_in": 3600,
    }

    with patch("auth.providers.onedrive.OAuth2Session") as mock_session_cls:
        mock_oauth = MagicMock()
        mock_oauth.refresh_token.side_effect = warn
        mock_session_cls.return_value = mock_oauth

        ctx = provider.refresh()
        assert ctx.headers["Authorization"] == "Bearer refreshed-token"


def test_onedrive_storage_get_item_url_formatting() -> None:
    from providers.onedrive import OneDriveStorage

    mock_auth = MagicMock()
    storage = OneDriveStorage(auth_provider=mock_auth)

    # Root paths
    assert storage._get_item_url("") == "https://graph.microsoft.com/v1.0/me/drive/root"
    assert storage._get_item_url("/") == "https://graph.microsoft.com/v1.0/me/drive/root"
    assert (
        storage._get_item_url("/", suffix=":/children?$top=999")
        == "https://graph.microsoft.com/v1.0/me/drive/root/children?$top=999"
    )

    # Subfolder paths (must never generate double colons ::)
    subfolder_url = storage._get_item_url("/文件/", suffix=":/children?$top=999")
    assert "::" not in subfolder_url
    assert subfolder_url == "https://graph.microsoft.com/v1.0/me/drive/root:/%E6%96%87%E4%BB%B6:/children?$top=999"

    # Single item
    item_url = storage._get_item_url("/文件/report.docx")
    assert "::" not in item_url
    assert item_url == "https://graph.microsoft.com/v1.0/me/drive/root:/%E6%96%87%E4%BB%B6/report.docx"

    # Query params
    query_url = storage._get_item_url("/文件/", suffix="?$select=id")
    assert "::" not in query_url
    assert query_url == "https://graph.microsoft.com/v1.0/me/drive/root:/%E6%96%87%E4%BB%B6?$select=id"


