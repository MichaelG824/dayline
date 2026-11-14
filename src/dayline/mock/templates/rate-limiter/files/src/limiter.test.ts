import { describe, expect, test } from 'vitest';
import { RateLimiter } from './limiter';

function limiter(capacity: number, refillPerSecond: number) {
  let now = 1_000_000;
  const rl = new RateLimiter(capacity, refillPerSecond, () => now);
  return { rl, advance: (ms: number) => (now += ms) };
}

describe('take', () => {
  test('allows up to capacity, then rejects', () => {
    const { rl } = limiter(3, 1);
    expect([1, 2, 3, 4].map(() => rl.take('a').allowed)).toEqual([true, true, true, false]);
  });

  test('clients have separate buckets', () => {
    const { rl } = limiter(1, 1);
    expect(rl.take('a').allowed).toBe(true);
    expect(rl.take('b').allowed).toBe(true);
  });

  test('refills at refillPerSecond, not faster', () => {
    const { rl, advance } = limiter(2, 1);
    rl.take('a');
    rl.take('a');
    advance(10);
    expect(rl.take('a').allowed).toBe(false);
    advance(990);
    expect(rl.take('a').allowed).toBe(true);
  });
});

describe('retryAfterMs', () => {
  test('is 0 when allowed', () => {
    const { rl } = limiter(1, 1);
    expect(rl.take('a').retryAfterMs).toBe(0);
  });

  test('says when the next token arrives', () => {
    const { rl, advance } = limiter(1, 2);
    rl.take('a');
    advance(100);
    expect(rl.take('a')).toEqual({ allowed: false, remaining: 0, retryAfterMs: 400 });
  });
});
