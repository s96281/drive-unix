import threading
import time
import unittest
import tempfile

from auth.base import AuthContext, AuthProvider
from auth.cache import AuthCache, CachedAuthProvider


class FakeProvider(AuthProvider):
    def __init__(self):
        self.refresh_count = 0
        self.lock = threading.Lock()

    def get_auth_context(self):
        return self.refresh()

    def refresh(self):
        with self.lock:
            self.refresh_count += 1
        time.sleep(0.02)
        return AuthContext(headers={"Authorization": "Bearer test"})


class CachedAuthConcurrencyTests(unittest.TestCase):
    def test_expired_cache_refreshes_once(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            cache = AuthCache(cache_dir=cache_dir)
            provider = FakeProvider()
        cached = CachedAuthProvider(
            provider,
            cache,
            "test-key",
            ttl_seconds=3600,
            raise_on_cache_error=True,
        )

        results = []
        lock = threading.Lock()

        def worker():
            result = cached.get_auth_context()
            with lock:
                results.append(result)

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), 6)
        self.assertEqual(provider.refresh_count, 1)

        cache.delete("test-key")


if __name__ == "__main__":
    unittest.main()
