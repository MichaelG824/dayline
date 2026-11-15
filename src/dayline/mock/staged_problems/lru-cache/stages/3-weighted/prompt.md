## Stage 3: entries have sizes

Entries are no longer equal: a cached image costs more than a cached flag.
`capacity` is now a size budget.

- `put(key, value, ttl=None, size=1)`: `size` is a positive integer.
- The total size of the cached entries must never go over `capacity`.
- One put may have to evict several least recently used entries to make room.
- Putting an existing key can change its size. Account for the old size correctly.
- Decide what happens when a single item is bigger than the whole capacity. Whatever you choose, that put must not leave the cache broken or needlessly empty.

With the default `size=1`, everything from the earlier stages behaves exactly as before.
