from __future__ import annotations

import json
import threading
import time
import unittest
from unittest.mock import patch

import requests

from auth.providers.pikpak import PikPakAuthProvider


def make_mock_response(status_code: int, json_data: dict) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp._content = json.dumps(json_data).encode("utf-8")
    resp.headers["Content-Type"] = "application/json"
    return resp


class PikPakAuthTests(unittest.TestCase):
    def test_login_success_exchanges_tokens(self) -> None:
        provider = PikPakAuthProvider(
            username="user@example.com",
            password_resolver=lambda: "secret_pass",
        )

        mock_login_resp = make_mock_response(
            200,
            {
                "access_token": "acc_123",
                "refresh_token": "ref_456",
                "expires_in": 3600,
            },
        )

        with patch.object(provider.http, "post", return_value=mock_login_resp) as mock_post:
            ctx = provider.get_auth_context()

            self.assertEqual(ctx.headers.get("Authorization"), "Bearer acc_123")
            self.assertEqual(provider._access_token, "acc_123")
            self.assertEqual(provider._refresh_token, "ref_456")
            self.assertIsNotNone(provider._expires_at)
            mock_post.assert_called_once()
            _, kwargs = mock_post.call_args
            self.assertEqual(kwargs["json"]["username"], "user@example.com")
            self.assertEqual(kwargs["json"]["password"], "secret_pass")

    def test_refresh_token_flow(self) -> None:
        provider = PikPakAuthProvider(
            username="user@example.com",
            password_resolver=lambda: "secret_pass",
        )
        provider._refresh_token = "existing_ref_token"

        mock_refresh_resp = make_mock_response(
            200,
            {
                "access_token": "new_acc_789",
                "refresh_token": "new_ref_999",
                "expires_in": 7200,
            },
        )

        with patch.object(provider.http, "post", return_value=mock_refresh_resp) as mock_post:
            ctx = provider.refresh()

            self.assertEqual(ctx.headers.get("Authorization"), "Bearer new_acc_789")
            self.assertEqual(provider._access_token, "new_acc_789")
            self.assertEqual(provider._refresh_token, "new_ref_999")
            mock_post.assert_called_once()
            _, kwargs = mock_post.call_args
            self.assertEqual(kwargs["json"]["grant_type"], "refresh_token")
            self.assertEqual(kwargs["json"]["refresh_token"], "existing_ref_token")

    def test_refresh_failure_falls_back_to_password_signin(self) -> None:
        provider = PikPakAuthProvider(
            username="user@example.com",
            password_resolver=lambda: "secret_pass",
        )
        provider._refresh_token = "bad_ref_token"

        mock_refresh_fail = make_mock_response(400, {"error": "invalid_grant"})
        mock_login_success = make_mock_response(
            200,
            {
                "access_token": "fallback_acc",
                "refresh_token": "fallback_ref",
                "expires_in": 3600,
            },
        )

        with patch.object(
            provider.http, "post", side_effect=[mock_refresh_fail, mock_login_success]
        ) as mock_post:
            ctx = provider.refresh()

            self.assertEqual(ctx.headers.get("Authorization"), "Bearer fallback_acc")
            self.assertEqual(provider._access_token, "fallback_acc")
            self.assertEqual(provider._refresh_token, "fallback_ref")
            self.assertEqual(mock_post.call_count, 2)

    def test_concurrent_get_auth_context_triggers_only_single_refresh(self) -> None:
        refresh_call_count = 0
        call_lock = threading.Lock()

        def mock_post(url, **kwargs):
            nonlocal refresh_call_count
            with call_lock:
                refresh_call_count += 1
            time.sleep(0.05)
            return make_mock_response(
                200,
                {
                    "access_token": "concurrent_acc",
                    "refresh_token": "concurrent_ref",
                    "expires_in": 3600,
                },
            )

        provider = PikPakAuthProvider(
            username="user@example.com",
            password_resolver=lambda: "secret_pass",
        )

        with patch.object(provider.http, "post", side_effect=mock_post):
            results = []
            results_lock = threading.Lock()

            def worker():
                ctx = provider.get_auth_context()
                with results_lock:
                    results.append(ctx)

            threads = [threading.Thread(target=worker) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(len(results), 6)
            for res in results:
                self.assertEqual(res.headers.get("Authorization"), "Bearer concurrent_acc")
            self.assertEqual(refresh_call_count, 1)


if __name__ == "__main__":
    unittest.main()
