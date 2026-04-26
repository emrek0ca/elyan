import { describe, expect, it } from 'vitest';
import { CapabilityAuditTrail, CapabilityRegistry } from '@/core/capabilities';

describe('Metadata capabilities', () => {
  it('parses YAML metadata', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());

    const parsed = await registry.execute('metadata_parse', {
      format: 'yaml',
      text: 'name: Elyan\nnested:\n  enabled: true\n  count: 3',
    });

    expect(parsed.format).toBe('yaml');
    expect(parsed.keys).toEqual(expect.arrayContaining(['name', 'nested']));
    expect((parsed.data as { nested?: { enabled?: boolean } }).nested?.enabled).toBe(true);
  });

  it('parses frontmatter metadata and body content', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());

    const parsed = await registry.execute('metadata_parse', {
      format: 'frontmatter',
      text: ['---', 'title: Elyan', 'tags:', '  - runtime', '---', 'Body text'].join('\n'),
    });

    expect(parsed.format).toBe('frontmatter');
    expect(parsed.body).toBe('Body text');
    expect(parsed.keys).toContain('title');
  });

  it('parses XML metadata', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());

    const parsed = await registry.execute('metadata_parse', {
      format: 'xml',
      text: '<root><name>Elyan</name><enabled>true</enabled></root>',
    });

    expect(parsed.format).toBe('xml');
    expect(parsed.keys).toContain('root');
  });
});
