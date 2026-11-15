## Stage 4: many threads

The cache is going to be shared by a web server's worker threads.

- Make `LRUCache` safe to call from many threads at once. Every public method must behave as if the calls happened one at a time, and the size budget must hold at every moment.
- Keep all the single-threaded behaviour from the earlier stages.

Before you code it, tell the interviewer what you plan to lock, and why.
Be ready to discuss the alternatives: lock granularity, read-write locks, and what you would do if one lock became the bottleneck.
