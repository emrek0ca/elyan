import { createHash } from 'crypto';
import { SearxNGResult, SearchOptions } from '@/types/search';

type CacheEntry = {
  expiresAt: number;
  results: SearxNGResult[];
};

const cache = new Map<string, CacheEntry>();
const availabilityCache = new Map<string, { ok: boolean; checkedAt: number }>();
const AVAILABILITY_TTL_MS = 5 * 60 * 1000;

export class SearxNGClient {
  private baseUrl: string;

  constructor() {
    this.baseUrl = process.env.SEARXNG_URL || 'http://localhost:8080';
  }

  async isAvailable(forceRefresh = false): Promise<boolean> {
    const availabilityKey = this.baseUrl.replace(/\/$/, '');
    const cached = availabilityCache.get(availabilityKey);

    if (!forceRefresh && cached && Date.now() - cached.checkedAt < AVAILABILITY_TTL_MS) {
      return cached.ok;
    }

    try {
      const response = await fetch(`${availabilityKey}/healthz`, {
        signal: AbortSignal.timeout(1500),
      });
      const ok = response.ok;
      availabilityCache.set(availabilityKey, { ok, checkedAt: Date.now() });
      return ok;
    } catch {
      availabilityCache.set(availabilityKey, { ok: false, checkedAt: Date.now() });
      return false;
    }
  }

  async search(query: string, options?: SearchOptions): Promise<SearxNGResult[]> {
    if (!(await this.isAvailable())) {
      return [];
    }

    const cacheKey = `search:${createHash('md5').update(query + JSON.stringify(options)).digest('hex')}`;

    const cached = cache.get(cacheKey);
    if (cached && cached.expiresAt > Date.now()) {
      return cached.results;
    }

    if (cached) {
      cache.delete(cacheKey);
    }

    const params = new URLSearchParams({
      q: query,
      format: 'json',
      ...(options?.categories && { categories: options.categories.join(',') }),
      ...(options?.engines && { engines: options.engines.join(',') }),
      ...(options?.language && { language: options.language }),
      ...(options?.timeRange && { time_range: options.timeRange }),
      ...(options?.pageNo && { pageno: String(options.pageNo) }),
    });

    let response: Response;

    try {
      response = await fetch(`${this.baseUrl}/search?${params}`, {
        signal: options?.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(5_000)]) : AbortSignal.timeout(5_000),
      });
    } catch {
      availabilityCache.set(this.baseUrl.replace(/\/$/, ''), { ok: false, checkedAt: Date.now() });
      return [];
    }

    if (!response.ok) {
      availabilityCache.set(this.baseUrl.replace(/\/$/, ''), { ok: false, checkedAt: Date.now() });
      return [];
    }

    const data = await response.json();
    const results = Array.isArray(data.results) ? data.results : [];

    cache.set(cacheKey, {
      expiresAt: Date.now() + 15 * 60 * 1000,
      results,
    });

    return results;
  }
}

export const searchClient = new SearxNGClient();
