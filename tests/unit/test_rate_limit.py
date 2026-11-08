import threading
import unittest
from unittest.mock import patch

from infrastructure.rate_limit import RateLimiter


class RateLimiterTests(unittest.TestCase):
    def test_negative_interval_rejected(self):
        with self.assertRaises(ValueError):
            RateLimiter(-0.1)

    def test_reservations_are_monotonic(self):
        limiter = RateLimiter(0.01)
        sleep_delays: list[float] = []
        delays_lock = threading.Lock()

        def record_sleep(delay: float) -> None:
            with delays_lock:
                sleep_delays.append(delay)

        # Keep the clock fixed so the test verifies the reservation algorithm,
        # not OS thread scheduling or timer resolution. The first worker gets an
        # immediate permit; the next two must reserve +10 ms and +20 ms slots.
        with (
            patch("infrastructure.rate_limit.time.monotonic", return_value=100.0),
            patch("infrastructure.rate_limit.time.sleep", side_effect=record_sleep),
        ):
            threads = [threading.Thread(target=limiter.acquire) for _ in range(3)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(len(sleep_delays), 2)
        first_delay, second_delay = sorted(sleep_delays)
        self.assertAlmostEqual(first_delay, 0.01, places=9)
        self.assertAlmostEqual(second_delay, 0.02, places=9)


if __name__ == "__main__":
    unittest.main()
