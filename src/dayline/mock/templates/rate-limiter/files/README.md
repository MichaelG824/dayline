# Rate limiter

A token-bucket rate limiter for an API gateway. Run the tests with `vitest run`.

Each client gets a bucket of `capacity` tokens that refills at `refillPerSecond`.
A request spends one token; with no token left it is rejected.

## Part 1 - the bug

Clients that hit the limit are let back in almost immediately.
`src/limiter.test.ts` reproduces it.

## Part 2 - retryAfter

When a request is rejected, `take()` should also return `retryAfterMs`: how long until the next token arrives, rounded up to a whole millisecond.
Allowed requests return `retryAfterMs: 0`.

## Talk through

- What happens to memory with a million distinct clients? How would you fix it?
- How would this work across several gateway instances?
