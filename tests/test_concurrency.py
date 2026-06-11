import threading
import time

from gpdedup.concurrency import AdaptiveLimiter


def test_start_clamped_to_max():
    assert AdaptiveLimiter(start=50, maximum=20).limit == 20


def test_additive_increase_clamps_at_max():
    lim = AdaptiveLimiter(start=4, maximum=6, increase=0.5)
    for _ in range(100):
        lim.on_success()
    assert lim.limit == 6


def test_multiplicative_decrease_clamps_at_min():
    lim = AdaptiveLimiter(start=8, maximum=20, minimum=1, decrease=0.5)
    for _ in range(100):
        lim.on_rate_limited()
    assert lim.limit == 1


def test_slot_never_exceeds_the_cap():
    lim = AdaptiveLimiter(start=20, maximum=4)   # start clamped to 4
    peak = cur = 0
    lock = threading.Lock()

    def task():
        nonlocal peak, cur
        with lim.slot():
            with lock:
                cur += 1
                peak = max(peak, cur)
            time.sleep(0.01)
            with lock:
                cur -= 1
            lim.on_success()

    threads = [threading.Thread(target=task) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak <= 4


def test_rate_limit_cooldown_blocks_next_acquire():
    lim = AdaptiveLimiter(start=4, maximum=4)
    lim.on_rate_limited(retry_after=0.1)
    t0 = time.monotonic()
    with lim.slot():
        pass
    assert time.monotonic() - t0 >= 0.08    # held off for ~the cooldown
