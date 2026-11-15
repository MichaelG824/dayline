"""Stage 2: per-entry TTL, read through an injected clock."""

from lru_cache import LRUCache


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_an_entry_without_a_ttl_never_expires():
    clock = FakeClock()
    cache = LRUCache(2, clock=clock)
    cache.put("a", 1)
    clock.advance(10**9)
    assert cache.get("a") == 1


def test_an_entry_is_returned_until_its_ttl_is_up():
    clock = FakeClock()
    cache = LRUCache(2, clock=clock)
    cache.put("a", 1, ttl=10)
    clock.advance(9.999)
    assert cache.get("a") == 1


def test_an_entry_expires_when_its_ttl_is_up():
    clock = FakeClock()
    cache = LRUCache(2, clock=clock)
    cache.put("a", 1, ttl=10)
    clock.advance(10)
    assert cache.get("a") is None, "expired once clock() >= put time + ttl"


def test_expired_key_is_never_returned_while_still_stored():
    clock = FakeClock()
    cache = LRUCache(3, clock=clock)
    cache.put("a", "stale", ttl=5)
    cache.put("b", 2)
    clock.advance(6)
    # Nothing has been evicted, so a may still be in the map: it must not come back.
    assert cache.get("a") is None
    assert cache.get("a") is None, "a second get must not return it either"
    assert cache.get("b") == 2


def test_expired_key_stays_gone_after_other_operations():
    clock = FakeClock()
    cache = LRUCache(3, clock=clock)
    cache.put("a", "stale", ttl=1)
    clock.advance(2)
    cache.put("b", 2)
    cache.get("b")
    cache.put("c", 3)
    assert cache.get("a") is None


def test_put_replaces_the_ttl():
    clock = FakeClock()
    cache = LRUCache(2, clock=clock)
    cache.put("a", 1, ttl=5)
    clock.advance(4)
    cache.put("a", 2, ttl=5)
    clock.advance(4)
    assert cache.get("a") == 2, "the second put gave a a fresh 5 seconds"
    cache.put("a", 3)
    clock.advance(10**6)
    assert cache.get("a") == 3, "a put without a ttl never expires"


def test_an_expired_key_can_be_put_again():
    clock = FakeClock()
    cache = LRUCache(2, clock=clock)
    cache.put("a", 1, ttl=1)
    clock.advance(5)
    assert cache.get("a") is None
    cache.put("a", 2, ttl=1)
    assert cache.get("a") == 2


def test_entries_with_a_ttl_still_follow_lru_order():
    clock = FakeClock()
    cache = LRUCache(2, clock=clock)
    cache.put("a", 1, ttl=100)
    cache.put("b", 2, ttl=100)
    cache.get("a")
    cache.put("c", 3, ttl=100)
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_the_default_clock_works():
    cache = LRUCache(2)
    cache.put("a", 1, ttl=3600)
    assert cache.get("a") == 1
