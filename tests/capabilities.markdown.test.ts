import { describe, expect, it } from 'vitest';
import { CapabilityAuditTrail, CapabilityRegistry } from '@/core/capabilities';

describe('Markdown capabilities', () => {
  it('renders sanitized markdown to html', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());

    const rendered = await registry.execute('markdown_render', {
      markdown: '# Title\n\n[Example](https://example.com)\n\n<script>alert(1)</script>',
    });

    expect(rendered.html).toContain('<h1>Title</h1>');
    expect(rendered.html).toContain('https://example.com');
    expect(rendered.html).not.toContain('<script');
  });
});
