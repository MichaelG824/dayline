export interface Decision {
  allowed: boolean;
  remaining: number;
  retryAfterMs: number;
}

interface Bucket {
  tokens: number;
  updatedAt: number;
}

export class RateLimiter {
  private buckets = new Map<string, Bucket>();

  constructor(
    private readonly capacity: number,
    private readonly refillPerSecond: number,
    private readonly now: () => number = Date.now,
  ) {}

  take(clientId: string): Decision {
    const now = this.now();
    const bucket = this.buckets.get(clientId) ?? { tokens: this.capacity, updatedAt: now };

    const elapsed = now - bucket.updatedAt;
    bucket.tokens = Math.min(this.capacity, bucket.tokens + elapsed * this.refillPerSecond);
    bucket.updatedAt = now;
    this.buckets.set(clientId, bucket);

    if (bucket.tokens < 1) {
      return { allowed: false, remaining: 0, retryAfterMs: 0 };
    }
    bucket.tokens -= 1;
    return { allowed: true, remaining: Math.floor(bucket.tokens), retryAfterMs: 0 };
  }
}
