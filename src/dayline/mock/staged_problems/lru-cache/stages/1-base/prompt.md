## Stage 1: a basic LRU cache

Implement `LRUCache` in `lru_cache.py`.

- `LRUCache(capacity)` holds at most `capacity` entries. A capacity below 1 raises `ValueError`.
- `get(key)` returns the cached value, or `None` if the key is not cached. A hit makes the key the most recently used.
- `put(key, value)` inserts or updates. Updating an existing key replaces its value and makes it the most recently used.
- When an insert would go over capacity, evict the least recently used entry first.

Both operations should be O(1).
`collections.OrderedDict` is allowed, but be ready to explain what it does underneath.
