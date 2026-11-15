## Stage 2: entries expire

Some entries should only live for a while.

- `LRUCache(capacity, clock=time.monotonic)`: `clock()` returns the current time in seconds. Read the time only through it; the tests pass a fake clock.
- `put(key, value, ttl=None)`: `ttl` is how many seconds from now the entry lives. `None` means it never expires. Putting an existing key replaces its TTL as well as its value.
- An entry put at time `t` with TTL `ttl` is expired once `clock() >= t + ttl`.
- `get` must never return an expired entry, even if it is still physically in your map. Lazy deletion (removing an expired entry when you next touch it) is fine.

Everything from stage 1 must keep working.
