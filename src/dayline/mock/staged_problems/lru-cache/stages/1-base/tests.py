"""Stage 1: get/put with LRU eviction."""

import random

import pytest
from lru_cache import LRUCache


def test_get_missing_key_returns_none():
    assert LRUCache(2).get("missing") is None


def test_put_then_get():
    cache = LRUCache(2)
    cache.put("a", 1)
    assert cache.get("a") == 1


def test_evicts_the_least_recently_used_entry():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.get("a") is None, "a was the least recently used, so it should be evicted"
    assert cache.get("b") == 2
    assert cache.get("c") == 3


def test_get_makes_a_key_most_recently_used():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")
    cache.put("c", 3)
    assert cache.get("b") is None, "get('a') made b the least recently used"
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_put_existing_key_updates_value_and_recency():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 10)
    cache.put("c", 3)
    assert cache.get("a") == 10
    assert cache.get("b") is None, "re-putting a made b the least recently used"


def test_updating_a_key_never_evicts():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("b", 20)
    assert cache.get("a") == 1, "updating an existing key must not evict anything"
    assert cache.get("b") == 20


def test_falsy_values_are_cached():
    cache = LRUCache(3)
    cache.put("zero", 0)
    cache.put("empty", "")
    cache.put("false", False)
    assert cache.get("zero") == 0
    assert cache.get("empty") == ""
    assert cache.get("false") is False


def test_capacity_one():
    cache = LRUCache(1)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") is None
    assert cache.get("b") == 2


@pytest.mark.parametrize("capacity", [0, -1])
def test_capacity_below_one_is_rejected(capacity):
    with pytest.raises(ValueError):
        LRUCache(capacity)


def test_random_operations_match_a_simple_model():
    rng = random.Random(7)
    capacity = 5
    cache = LRUCache(capacity)
    model = []  # (key, value) pairs, least recently used first.
    for step in range(3000):
        key = rng.randrange(12)
        if rng.random() < 0.5:
            expected = None
            for i, (k, v) in enumerate(model):
                if k == key:
                    expected = v
                    model.append(model.pop(i))
                    break
            assert cache.get(key) == expected, f"step {step}: get({key})"
        else:
            model = [(k, v) for k, v in model if k != key]
            model.append((key, step))
            if len(model) > capacity:
                model.pop(0)
            cache.put(key, step)
