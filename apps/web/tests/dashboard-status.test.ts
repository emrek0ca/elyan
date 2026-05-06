import { describe, expect, it } from 'vitest';
import { GET } from '@/app/api/dashboard/status/route';

describe('Dashboard status API', () => {
  it('exposes the runtime state consumed by the manage surface', async () => {
    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.ok).toBe(true);
    expect(body.runtime).toBe('local-first');
    expect(body.connections).toBeDefined();
    expect(body.optimization).toBeDefined();
    expect(body.registry).toBeDefined();
    expect(body.operator).toBeDefined();
    expect(body.surfaces).toBeDefined();
    expect(body.registry.ml || body.registry.models).toBeDefined();
    expect(body.surfaces.local.ready).toBeTypeOf('boolean');
    expect(body.surfaces.shared.ready).toBeTypeOf('boolean');
    expect(body.surfaces.hosted.ready).toBeTypeOf('boolean');
  });
});
