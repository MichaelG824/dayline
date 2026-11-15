"""Stage 4: thread safety.

Threads switch every microsecond here, so a cache whose operations are not
atomic shows it within a few thousand calls. The checks after each run catch
a corrupted map, recency list, or size count.
"""

import random
import sys
import threading

import pytest
from lru_cache import LRUCache

THREADS = 8


@pytest.fixture(autouse=True)
def switch_threads_often():
    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    yield
    sys.setswitchinterval(previous)


def _run_threads(work):
    errors = []

    def guarded(index):
        try:
            work(index)
        except BaseException as exc:  # Report anything a thread hit.
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=guarded, args=(i,)) for i in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, f"{len(errors)} thread(s) failed, the first with {errors[0]}"


def _assert_consistent(cache, capacity, keys):
    """The cache holds at most `capacity` entries, and still evicts in order."""
    present = [key for key in keys if cache.get(key) is not None]
    assert len(present) <= capacity, f"{len(present)} entries cached with capacity {capacity}"
    fresh = [f"fresh-{i}" for i in range(capacity)]
    for key in fresh:
        cache.put(key, key)
    assert [cache.get(key) for key in fresh] == fresh, "the cache lost entries it just stored"
    leftovers = [key for key in keys if cache.get(key) is not None]
    assert not leftovers, f"{len(leftovers)} old entries survived {capacity} fresh puts"


def test_concurrent_puts_and_gets_keep_the_cache_consistent():
    capacity, keys = 16, list(range(64))
    cache = LRUCache(capacity)

    def work(index):
        rng = random.Random(index)
        for _ in range(4000):
            key = rng.choice(keys)
            if rng.random() < 0.5:
                cache.put(key, (key, index))
            else:
                value = cache.get(key)
                assert value is None or value[0] == key, f"get({key}) returned {value}"

    _run_threads(work)
    _assert_consistent(cache, capacity, keys)


def test_concurrent_reads_keep_the_cache_consistent():
    capacity = 32
    keys = list(range(capacity))
    cache = LRUCache(capacity)
    for key in keys:
        cache.put(key, key)

    def work(index):
        rng = random.Random(100 + index)
        for _ in range(4000):
            key = rng.choice(keys)
            value = cache.get(key)
            assert value == key, f"get({key}) returned {value} with nothing evicted"

    _run_threads(work)
    _assert_consistent(cache, capacity, keys)


def test_single_threaded_behaviour_is_unchanged():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")
    cache.put("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 1
