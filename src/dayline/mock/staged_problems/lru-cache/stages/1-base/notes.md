Stage 1 is the warm-up. It sets up the design every later stage has to extend, so look hard at the data structures.

Probe, one at a time, grounded in their code:
- The complexity of `get` and `put`, and why. With a plain dict plus a list, `list.remove` is O(n): ask them to find it.
- With `OrderedDict`: what `move_to_end` and `popitem(last=False)` do underneath (a hash map whose entries are also linked in a doubly linked list) and why both are O(1).
- With their own linked list: why doubly linked (unlinking a node needs its predecessor), and whether sentinel head/tail nodes simplify the edge cases.
- Why each node also stores its key (eviction removes the map entry for the tail node).
- That `get` changes recency: a read is a write to the order. Remember this; stage 4 depends on it.

Signals:
- Strong: O(1) both ways with a clear reason, update path never evicts, small private helpers (`_unlink`, `_push_front`) that later stages can reuse.
- Weak: O(n) recency updates, `if value:` checks that drop falsy values, eviction before checking whether the key already exists.
