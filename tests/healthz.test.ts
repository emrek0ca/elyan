import { describe, expect, it } from 'vitest';
import { GET } from '@/app/api/healthz/route';

describe('Health endpoint', () => {
  it('reports Elyan as healthy', async () => {
    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toMatchObject({
      ok: true,
      service: 'elyan',
      runtime: 'local-first',
    });
    expect(typeof body.ready).toBe('boolean');
    expect(body.checks).toBeDefined();
    expect(Array.isArray(body.nextSteps)).toBe(true);
  });
});
