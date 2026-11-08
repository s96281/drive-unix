from __future__ import annotations

import requests


class HttpError(requests.RequestException):
    """Base exception for failures produced by the shared HTTP client."""


class HttpTimeoutError(HttpError, requests.Timeout):
    """A request exceeded the configured timeout."""


class HttpRequestError(HttpError):
    """A transport-level request failure after retries are exhausted."""


class HttpStatusError(HttpError, requests.HTTPError):
    """An unsuccessful HTTP response after retries are exhausted."""

    def __init__(self, message: str, response: requests.Response):
        super().__init__(message, response=response)
        self.http_response: requests.Response = response
        self.status_code = response.status_code


def format_response_error(response: requests.Response) -> str:
    try:
        body = response.text.strip()
    except Exception:
        body = ""

    if len(body) > 500:
        body = body[:500] + "..."

    suffix = f": {body}" if body else ""
    return f"HTTP {response.status_code} for {response.request.method} {response.url}{suffix}"
