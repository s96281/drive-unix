import time
from unittest.mock import MagicMock
from auth.base import AuthContext
from auth.providers.sharepoint_cookie import (
    DEFAULT_SHAREPOINT_EXPIRY_SECONDS,
    SharePointCookieProvider,
    SharePointCookieResult,
)


def test_sharepoint_cookie_expiry_constant():
    # 1 day in seconds = 1 * 24 * 3600 = 86,400
    assert DEFAULT_SHAREPOINT_EXPIRY_SECONDS == 86_400


def test_sharepoint_cookie_provider_default_expiry():
    provider = SharePointCookieProvider(
        base_url="https://contoso.sharepoint.com",
        email="user@contoso.com",
        password="secretpassword",
    )
    assert provider.expires_in_seconds == DEFAULT_SHAREPOINT_EXPIRY_SECONDS
    assert provider.expires_in_seconds == 86_400


def test_sharepoint_cookie_provider_none_falls_back_to_default():
    provider = SharePointCookieProvider(
        base_url="https://contoso.sharepoint.com",
        email="user@contoso.com",
        password="secretpassword",
        expires_in_seconds=None,
    )
    assert provider.expires_in_seconds == 86_400


def test_sharepoint_cookie_result_to_auth_context_expiry():
    now = time.time()
    result = SharePointCookieResult(
        cookie_header="rtFa=abc; FedAuth=xyz",
        rtFa="abc",
        FedAuth="xyz",
        cookies=[{"name": "FedAuth", "value": "xyz"}],
        created_at=now,
    )
    ctx = result.to_auth_context(
        provider_name="sharepoint_cookie",
        account="user@contoso.com",
        resource="https://contoso.sharepoint.com",
        expires_at=result.created_at + DEFAULT_SHAREPOINT_EXPIRY_SECONDS,
    )
    assert ctx.expires_at == now + 86_400
    assert not ctx.is_expired(leeway_seconds=60)
