Stage 4 is half discussion, half code. Start with the discussion before they write the lock.

Probe:
- What the lock protects: the map, the linked list, and the running size total must change together, so one lock around each public method is the simple correct answer. Ask what goes wrong without it (two threads unlinking neighbouring nodes, the map and list disagreeing, the total drifting).
- The read-write lock trap. If they suggest an RW lock so readers don't block each other, point at their own `get`: it moves the node to the front (and with TTL may delete an expired entry), so every read is a write. Concurrent readers under a shared lock corrupt the list. Ask how they would make reads truly read-only (approximate LRU: record accesses in a buffer or set a "referenced" bit and reorder later, CLOCK / second-chance, sampled eviction like Redis).
- The GIL: does CPython's GIL make this safe already? No: it makes single bytecodes atomic, not their multi-step updates.
- Scaling: one lock serialises everything. Lock striping / sharding the cache by key hash (N independent LRUs, each with its own lock and budget) and what you give up (global LRU order, per-shard capacity).
- Work under the lock: never call user code (size functions, loaders) while holding it; how they would add a "load on miss" without a thundering herd (per-key futures / single-flight).

Signals:
- Strong: one `threading.Lock` (or `RLock` with a reason), held for the whole operation and nothing slow inside it; spots that `get` mutates without being told.
- Weak: locking only `put`, a read-write lock with `get` under the shared side, relying on the GIL.
