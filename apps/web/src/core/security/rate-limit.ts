type RateLimitScope = 'ip' | 'user' | 'device';

type RateLimitBucket = {
  count: number;
  resetAt: number;
};

export type RateLimitResult = {
  allowed: boolean;
  scope: RateLimitScope;
  key: string;
  limit: number;
  remaining: number;
  resetAt: string;
  retryAfterMs: number;
};

type RateLimitInput = {
  scope: RateLimitScope;
  key: string;
  limit: number;
  windowMs: number;
  now?: number;
};

const buckets = new Map<string, RateLimitBucket>();
const cleanupIntervalMs = 5 * 60 * 1000;
let lastCleanupAt = 0;

function clampLimit(value: number) {
  return Number.isFinite(value) && value > 0 ? Math.trunc(value) : 0;
}

function cleanupBuckets(now: number) {
  if (now - lastCleanupAt < cleanupIntervalMs) {
    return;
  }

  lastCleanupAt = now;

  for (const [key, bucket] of buckets.entries()) {
    if (bucket.resetAt <= now) {
      buckets.delete(key);
    }
  }
}

export function buildRateLimitBucketKey(scope: RateLimitScope, key: string) {
  return `${scope}:${key.trim().toLowerCase()}`;
}

export function consumeFixedWindowRateLimit(input: RateLimitInput): RateLimitResult {
  const now = input.now ?? Date.now();
  const limit = clampLimit(input.limit);
  const windowMs = Math.max(1, Math.trunc(input.windowMs));
  const bucketKey = buildRateLimitBucketKey(input.scope, input.key);

  cleanupBuckets(now);

  if (limit <= 0 || !input.key.trim()) {
    return {
      allowed: false,
      scope: input.scope,
      key: bucketKey,
      limit,
      remaining: 0,
      resetAt: new Date(now + windowMs).toISOString(),
      retryAfterMs: windowMs,
    };
  }

  const bucket = buckets.get(bucketKey);
  if (!bucket || bucket.resetAt <= now) {
    const resetAt = now + windowMs;
    buckets.set(bucketKey, {
      count: 1,
      resetAt,
    });

    return {
      allowed: true,
      scope: input.scope,
      key: bucketKey,
      limit,
      remaining: Math.max(limit - 1, 0),
      resetAt: new Date(resetAt).toISOString(),
      retryAfterMs: windowMs,
    };
  }

  bucket.count += 1;

  const allowed = bucket.count <= limit;
  return {
    allowed,
    scope: input.scope,
    key: bucketKey,
    limit,
    remaining: Math.max(limit - bucket.count, 0),
    resetAt: new Date(bucket.resetAt).toISOString(),
    retryAfterMs: Math.max(bucket.resetAt - now, 0),
  };
}

