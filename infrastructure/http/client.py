from __future__ import annotations

import threading
from typing import Any

import requests

from core.logging import get_logger
from .errors import HttpRequestError, HttpStatusError, HttpTimeoutError, format_response_error
from .retry import RetryPolicy


DEFAULT_TIMEOUT: tuple[float, float] = (10.0, 60.0)
logger = get_logger("http")


class HttpClient:
    """Shared HTTP transport with thread-local sessions, timeout and retry handling.

    Retries are intentionally limited to methods that are normally safe to replay.
    Upload POST/PUT/PATCH requests receive the mandatory timeout but are not retried
    automatically because request bodies may be non-replayable streams.
    """

    def __init__(
        self,
        *,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        retry_policy: RetryPolicy | None = None,
        auth: Any = None,
        user_agent: str | None = None,
    ):
        self.timeout = timeout
        self.retry_policy = retry_policy or RetryPolicy()
        self.auth = auth
        self.user_agent = user_agent
        self._local = threading.local()
        self._sessions: set[requests.Session] = set()
        self._sessions_lock = threading.Lock()

    @property
    def session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            if self.auth is not None:
                session.auth = self.auth
            if self.user_agent:
                session.headers.setdefault("User-Agent", self.user_agent)
            with self._sessions_lock:
                self._sessions.add(session)
            self._local.session = session
        return session

    def request(
        self,
        method: str,
        url: str,
        *,
        retry: bool | None = None,
        timeout: tuple[float, float] | float | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        method = method.upper()
        request_timeout = self.timeout if timeout is None else timeout
        should_retry = self.retry_policy.should_retry(method) if retry is None else retry
        attempts = self.retry_policy.max_attempts if should_retry else 1

        kwargs.setdefault("timeout", request_timeout)

        last_exception: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = self.session.request(method, url, **kwargs)

                if (
                    response.status_code in self.retry_policy.retryable_statuses
                    and should_retry
                    and attempt < attempts
                ):
                    delay = self.retry_policy.delay_for(
                        attempt,
                        response.headers.get("Retry-After"),
                    )
                    logger.debug("Retrying %s %s after %.2fs", method, url, delay)
                    self._sleep(delay)
                    continue

                return response

            except requests.Timeout as exc:
                last_exception = exc
                if attempt >= attempts:
                    raise HttpTimeoutError(
                        f"Request timeout after {attempt} attempt(s): {method} {url}"
                    ) from exc
            except requests.RequestException as exc:
                last_exception = exc
                if attempt >= attempts:
                    raise HttpRequestError(
                        f"HTTP transport error after {attempt} attempt(s): {method} {url}: {exc}"
                    ) from exc

            self._sleep(self.retry_policy.delay_for(attempt))

        # Defensive fallback; the loop either returns or raises above.
        raise HttpRequestError(
            f"HTTP request failed: {method} {url}"
        ) from last_exception

    @staticmethod
    def _sleep(delay: float) -> None:
        import time

        if delay > 0:
            time.sleep(delay)

    def raise_for_status(
        self,
        response: requests.Response,
        *,
        context: str | None = None,
    ) -> None:
        if response.ok:
            return

        prefix = f"{context}: " if context else ""
        raise HttpStatusError(
            prefix + format_response_error(response),
            response,
        )

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("DELETE", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("HEAD", url, **kwargs)

    def options(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("OPTIONS", url, **kwargs)

    def download_stream(
        self,
        url: str,
        local_path: str,
        callback: Any = None,
        chunk_size: int = 64 * 1024,
        **kwargs: Any,
    ) -> bool:
        from pathlib import Path

        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        resp = self.get(url, stream=True, **kwargs)
        self.raise_for_status(resp)
        total_size = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(local_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if callback:
                        callback(downloaded, total_size)
        return True

    def close(self) -> None:
        """Close every session created by this client, including worker threads."""
        with self._sessions_lock:
            sessions = tuple(self._sessions)
            self._sessions.clear()

        first_error: Exception | None = None
        for session in sessions:
            try:
                session.close()
            except Exception as exc:  # pragma: no cover - requests.Session.close is normally safe
                if first_error is None:
                    first_error = exc

        # Clear the current thread's cached reference. Other worker thread-local
        # references may still point at a closed Session, but those workers have
        # already completed when providers are closed by the CLI ownership scope.
        self._local.session = None

        if first_error is not None:
            raise first_error
