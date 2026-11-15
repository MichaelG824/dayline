Stage 2 adds time. Ground every question in how they changed their stage 1 code.

Probe:
- Where the expiry check lives. Point at their `get`: what happens to an expired node there (is it unlinked and removed from the map, or just skipped)?
- Expired-but-present entries: with lazy deletion an expired entry still takes a slot, so a full cache can evict a live LRU entry while a dead one sits in the map. Ask whether that matters and how they would fix it (purge expired entries before evicting live ones, a min-heap or timer wheel keyed by expiry, a periodic sweep) and what each costs.
- The clock: why inject it (deterministic tests, monotonic vs wall-clock time jumping backwards with NTP).
- Re-putting a key with no TTL: should it clear the old TTL? (The spec says yes.)
- Memory: with only lazy deletion, keys that are never read again stay forever until evicted. Is that acceptable?

Signals:
- Strong: one small change to `get` plus an `expires_at` on the node; a clear answer on proactive cleanup and its complexity.
- Weak: calling `time.time()` directly, returning stale values, expiry checks that refresh recency of dead entries.
