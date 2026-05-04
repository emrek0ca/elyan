import { afterEach, describe, expect, it, vi } from 'vitest';

describe('environment placeholder handling', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it('treats placeholder hosted env values as absent during validation', async () => {
    vi.stubEnv('DATABASE_URL', '<DB_NAME>');
    vi.stubEnv('NEXTAUTH_URL', 'https://elyan.dev');
    vi.stubEnv('SEARXNG_URL', 'http://localhost:8080');
    vi.stubEnv('OLLAMA_URL', 'http://127.0.0.1:11434');

    const { inspectEnv } = await import('@/lib/env');
    const result = inspectEnv();

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data.DATABASE_URL).toBeUndefined();
      expect(result.data.NEXTAUTH_URL).toBe('https://elyan.dev');
    }
  });
});
