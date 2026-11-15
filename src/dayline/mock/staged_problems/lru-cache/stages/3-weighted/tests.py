"""Stage 3: capacity is a size budget."""

import contextlib

from lru_cache import LRUCache


def test_the_total_size_never_goes_over_capacity():
    cache = LRUCache(10)
    cache.put("a", "A", size=4)
    cache.put("b", "B", size=4)
    cache.put("c", "C", size=4)
    assert cache.get("a") is None, "4 + 4 + 4 > 10, so the least recently used (a) goes"
    assert cache.get("b") == "B"
    assert cache.get("c") == "C"


def test_one_put_can_evict_several_entries():
    cache = LRUCache(10)
    for key in "abcd":
        cache.put(key, key.upper(), size=2)
    cache.put("e", "E", size=5)
    assert cache.get("a") is None
    assert cache.get("b") is None, "8 + 5 > 10 needs two evictions, not one"
    assert cache.get("c") == "C"
    assert cache.get("d") == "D"
    assert cache.get("e") == "E"


def test_eviction_by_size_follows_recency():
    cache = LRUCache(10)
    for key in "abcd":
        cache.put(key, key.upper(), size=2)
    cache.get("a")
    cache.get("b")
    cache.put("e", "E", size=5)
    assert cache.get("c") is None
    assert cache.get("d") is None
    assert cache.get("a") == "A"
    assert cache.get("b") == "B"
    assert cache.get("e") == "E"


def test_an_item_exactly_as_big_as_capacity_fits():
    cache = LRUCache(5)
    cache.put("a", "A")
    cache.put("big", "BIG", size=5)
    assert cache.get("big") == "BIG"
    assert cache.get("a") is None


def test_an_oversized_item_leaves_the_cache_intact():
    cache = LRUCache(5)
    cache.put("a", "A")
    cache.put("b", "B")
    with contextlib.suppress(ValueError):  # Rejecting it loudly is a fine choice.
        cache.put("big", "BIG", size=6)
    assert cache.get("big") is None, "an item bigger than the capacity cannot be cached"
    assert cache.get("a") == "A", "nothing should be evicted for an item that can never fit"
    assert cache.get("b") == "B"
    with contextlib.suppress(ValueError):
        cache.put("a", "A2", size=6)
    assert cache.get("a") != "A2", "an oversized update cannot be stored either"
    assert cache.get("b") == "B"


def test_growing_a_key_evicts_others_but_never_itself():
    cache = LRUCache(10)
    cache.put("a", "A", size=3)
    cache.put("b", "B", size=3)
    cache.put("c", "C", size=3)
    cache.put("a", "A2", size=6)
    assert cache.get("a") == "A2"
    assert cache.get("b") is None, "6 + 3 + 3 > 10: b is the least recently used other entry"
    assert cache.get("c") == "C"
    cache.put("d", "D", size=1)
    assert cache.get("c") == "C", "6 + 3 + 1 = 10 fits without evicting"
    assert cache.get("d") == "D"


def test_shrinking_a_key_frees_room():
    cache = LRUCache(10)
    cache.put("a", "A", size=6)
    cache.put("b", "B", size=4)
    cache.put("a", "A2", size=1)
    cache.put("c", "C", size=5)
    assert cache.get("a") == "A2", "1 + 4 + 5 = 10 fits"
    assert cache.get("b") == "B"
    assert cache.get("c") == "C"


def test_the_default_size_is_one():
    cache = LRUCache(3)
    for key in "abc":
        cache.put(key, key)
    assert [cache.get(k) for k in "abc"] == ["a", "b", "c"]
    cache.put("d", "d")
    assert cache.get("a") is None
