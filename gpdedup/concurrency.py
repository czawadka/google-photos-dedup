"""Adaptive concurrency limiter (AIMD) for rate-limited fan-out.

When fanning out many small requests to an API that may throttle, a fixed
parallelism is wrong: too low wastes the link, too high trips rate limits. This
limiter does **AIMD** — additive-increase on success, multiplicative-decrease on
a rate-limit signal — so the effective concurrency drifts up to whatever the
server tolerates and snaps back down when throttled, never exceeding a hard cap.

Usage (thread-safe):

    lim = AdaptiveLimiter(start=4, maximum=20)
    with lim.slot():                 # blocks until in-flight < floor(limit)
        try:
            do_request()
            lim.on_success()
        except RateLimited as e:
            lim.on_rate_limited(e.retry_after)
            raise
"""

from __future__ import annotations

import contextlib
import threading
import time


class AdaptiveLimiter:
    def __init__(self, start: float = 4.0, maximum: int = 20, minimum: float = 1.0,
                 increase: float = 0.5, decrease: float = 0.5):
        self.maximum = float(maximum)
        self.minimum = float(minimum)
        self._limit = max(minimum, min(float(start), maximum))
        self._increase = increase          # additive step per success
        self._decrease = decrease          # multiplicative factor on throttle
        self._in_flight = 0
        self._cooldown_until = 0.0          # wall-clock time to hold off until
        self._cv = threading.Condition()

    @property
    def limit(self) -> float:
        with self._cv:
            return self._limit

    @property
    def in_flight(self) -> int:
        with self._cv:
            return self._in_flight

    @contextlib.contextmanager
    def slot(self):
        self._acquire()
        try:
            yield
        finally:
            self._release()

    def _acquire(self) -> None:
        with self._cv:
            while True:
                now = time.monotonic()
                if now >= self._cooldown_until and self._in_flight < int(self._limit):
                    self._in_flight += 1
                    return
                # Wait for a freed slot or the cooldown to elapse (wait() releases
                # the lock meanwhile; on_success/on_rate_limited/_release notify).
                wait = None if now >= self._cooldown_until else self._cooldown_until - now
                self._cv.wait(timeout=wait)

    def _release(self) -> None:
        with self._cv:
            self._in_flight -= 1
            self._cv.notify_all()

    def on_success(self) -> None:
        with self._cv:
            if self._limit < self.maximum:
                self._limit = min(self.maximum, self._limit + self._increase)
                self._cv.notify_all()

    def on_rate_limited(self, retry_after: float = 0.0) -> None:
        """Halve the ceiling and, if given, hold all slots for `retry_after`s."""
        with self._cv:
            self._limit = max(self.minimum, self._limit * self._decrease)
            if retry_after and retry_after > 0:
                self._cooldown_until = max(
                    self._cooldown_until, time.monotonic() + retry_after)
            self._cv.notify_all()
