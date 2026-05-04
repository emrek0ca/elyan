import { describe, expect, it } from 'vitest';
import { CapabilityAuditTrail, CapabilityRegistry, rankFuzzyItems } from '@/core/capabilities';

describe('Capability tools', () => {
  it('ranks fuzzy matches with Fuse.js', () => {
    const ranked = rankFuzzyItems(
      'aple',
      [
        {
          id: '1',
          title: 'Apple',
          url: 'https://en.wikipedia.org/wiki/Apple',
          tags: ['fruit'],
          metadata: {},
        },
        {
          id: '2',
          title: 'Orange',
          url: 'https://example.com/orange',
          tags: ['fruit'],
          metadata: {},
        },
      ],
      2
    );

    expect(ranked[0]?.item.id).toBe('1');
  });

  it('evaluates exact math and decimal math', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());

    const exact = await registry.execute('math_exact', {
      expression: '2 + 2 * 3',
    });
    const decimal = await registry.execute('math_decimal', {
      left: '0.1',
      right: '0.2',
      operation: 'add',
    });

    expect(exact.value).toBe('8');
    expect(decimal.value).toBe('0.3');
  });

  it('parses and exports CSV', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());

    const parsed = await registry.execute('csv_parse', {
      csv: 'name,score\nElyan,1\nIris,2',
    });

    expect(parsed.rows).toHaveLength(2);
    expect(parsed.rows[0]?.name).toBe('Elyan');

    const exported = await registry.execute('csv_export', {
      rows: parsed.rows,
    });

    expect(exported.csv).toContain('Elyan');
    expect(exported.csv).toContain('Iris');
  });
});
