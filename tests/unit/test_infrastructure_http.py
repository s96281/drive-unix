import threading
import unittest

import requests

from infrastructure.http import HttpClient, HttpStatusError, RetryPolicy


class FakeSession:
    def __init__(self, responses=None, errors=None):
        self.responses = list(responses or [])
        self.errors = list(errors or [])
        self.calls = []
        self.auth = None
        self.headers = {}
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.errors:
            raise self.errors.pop(0)
        response = self.responses.pop(0)
        return response

    def close(self):
        self.closed = True


def make_response(status_code: int, url: str = "https://example.test/resource"):
    response = requests.Response()
    response.status_code = status_code
    response.url = url
    response.request = requests.Request("GET", url).prepare()
    response._content = b"error" if status_code >= 400 else b"ok"
    return response


class HttpClientTests(unittest.TestCase):
    def setUp(self):
        self.original_sleep = HttpClient._sleep
        HttpClient._sleep = staticmethod(lambda _delay: None)

    def tearDown(self):
        HttpClient._sleep = self.original_sleep

    def test_get_retries_transient_status(self):
        client = HttpClient(
            retry_policy=RetryPolicy(
                max_attempts=3,
                backoff_factor=0,
                jitter=0,
            )
        )
        fake = FakeSession([make_response(503), make_response(200)])
        client._local.session = fake

        response = client.get("https://example.test/resource")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[0][2]["timeout"], (10.0, 60.0))

    def test_post_is_not_retried_by_default(self):
        client = HttpClient(
            retry_policy=RetryPolicy(
                max_attempts=3,
                backoff_factor=0,
                jitter=0,
            )
        )
        fake = FakeSession([make_response(503)])
        client._local.session = fake

        response = client.post("https://example.test/upload")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(fake.calls), 1)

    def test_raise_for_status_preserves_response(self):
        client = HttpClient()
        response = make_response(404)

        with self.assertRaises(HttpStatusError) as caught:
            client.raise_for_status(response, context="download")

        self.assertEqual(caught.exception.status_code, 404)
        self.assertIs(caught.exception.response, response)
        self.assertIsInstance(caught.exception, requests.HTTPError)

    def test_close_releases_sessions_created_by_all_worker_threads(self):
        client = HttpClient()
        created = []
        original_session_factory = requests.Session

        def make_session():
            session = FakeSession()
            created.append(session)
            return session

        requests.Session = make_session
        try:
            threads = [threading.Thread(target=lambda: client.session) for _ in range(3)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(len(created), 3)
            client.close()

            self.assertTrue(all(session.closed for session in created))
            self.assertEqual(client._sessions, set())
        finally:
            requests.Session = original_session_factory

    def test_sessions_are_thread_local(self):
        client = HttpClient()
        sessions = []
        lock = threading.Lock()

        def worker():
            with lock:
                sessions.append(client.session)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(sessions), 2)
        self.assertIsNot(sessions[0], sessions[1])


if __name__ == "__main__":
    unittest.main()
