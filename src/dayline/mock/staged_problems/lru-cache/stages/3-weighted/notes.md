Stage 3 turns a count into a budget. This is where a design either extends cleanly or falls apart.

Probe, grounded in their `put`:
- The order of operations when an existing key changes size: is the old entry removed (and its size released) before evicting? If they evict first, the key being updated can evict itself, or others get evicted for room that was already there.
- The oversized item: what did they choose (raise `ValueError`, silently refuse, or store and evict everything) and why? Storing it would break the size invariant; evicting everything first and then refusing empties the cache for nothing. Ask what a caller would want to know.
- An oversized put on a key that already exists: does the old value survive, or is the stale value removed? Either can be argued; they should have a reason.
- Expired entries and size: with lazy deletion, expired entries still count toward the budget. Should eviction drop expired entries first?
- Complexity: one put can evict k entries, so it is O(k), amortised O(1) since each entry is evicted at most once.

Signals:
- Strong: a running `total` kept in step in exactly one place, removal reused from earlier helpers, a deliberate oversized policy.
- Weak: recomputing the total by walking the list, a `while` loop that can spin forever on an oversized item, rewriting the class from scratch.
