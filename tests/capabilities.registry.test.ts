import { describe, expect, it } from 'vitest';
import { z } from 'zod';
import { CapabilityAuditTrail, CapabilityDisabledError, CapabilityRegistry } from '@/core/capabilities';
import type { CapabilityDefinition } from '@/core/capabilities';

describe('CapabilityRegistry', () => {
  it('lists enabled capabilities and keeps disabled ones hidden', () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail(), {
      disabledCapabilityIds: ['math_exact'],
    });

    const enabled = registry.list();
    const all = registry.list({ includeDisabled: true });

    expect(enabled.some((capability) => capability.id === 'math_exact')).toBe(false);
    expect(all.some((capability) => capability.id === 'math_exact' && capability.enabled === false)).toBe(true);
  });

  it('records audits for successful capability execution', async () => {
    const auditTrail = new CapabilityAuditTrail();
    const registry = new CapabilityRegistry(auditTrail);

    const result = await registry.execute('math_decimal', {
      left: '0.1',
      right: '0.2',
      operation: 'add',
    });

    expect(result.value).toBe('0.3');
    expect(auditTrail.list()).toHaveLength(1);
    expect(auditTrail.list()[0]?.status).toBe('success');
  });

  it('blocks disabled capabilities', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail(), {
      disabledCapabilityIds: ['csv_parse'],
    });

    await expect(
      registry.execute('csv_parse', {
        csv: 'name,score\nElyan,1',
      })
    ).rejects.toBeInstanceOf(CapabilityDisabledError);
  });

  it('records invalid input attempts in the audit trail', async () => {
    const auditTrail = new CapabilityAuditTrail();
    const registry = new CapabilityRegistry(auditTrail);

    await expect(
      registry.execute('math_decimal', {
        left: '0.1',
        operation: 'add',
      })
    ).rejects.toBeInstanceOf(Error);

    expect(auditTrail.list()).toHaveLength(1);
    expect(auditTrail.list()[0]?.status).toBe('error');
  });

  it('rejects duplicate capability registrations', () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail(), {
      disabledCapabilityIds: ['math_exact'],
    });

    const duplicateCapability: CapabilityDefinition = {
      id: 'csv_parse',
      title: 'CSV Parse Copy',
      description: 'Duplicate test capability.',
      library: 'papaparse',
      enabled: true,
      timeoutMs: 100,
      inputSchema: z.object({}),
      outputSchema: z.object({}),
      run: async () => ({}),
    };

    expect(() => registry.register(duplicateCapability)).toThrow(/already registered/i);
  });
});
