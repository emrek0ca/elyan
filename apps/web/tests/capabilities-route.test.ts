import { describe, expect, it } from 'vitest';
import { GET } from '@/app/api/capabilities/route';

describe('Capabilities API', () => {
  it('exposes the unified runtime registry contract', async () => {
    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.ok).toBe(true);
    expect(body.registry).toBeDefined();
    expect(body.registry.summary).toBeDefined();
    expect(body.registry.runs).toBeDefined();
    expect(body.registry.approvals).toBeDefined();
    expect(body.registry.operator).toBeDefined();
    expect(body.registry.skills).toBeDefined();
    expect(body.registry.mcp).toBeDefined();
    expect(body.registry.ml).toBeDefined();
    expect(body.registry.models).toBeDefined();
    expect(body.health).toBeDefined();
    expect(body.health.latest).toBeDefined();
  });
});
