import { describe, expect, it } from 'vitest';
import { CapabilityAuditTrail, CapabilityRegistry } from '@/core/capabilities';

describe('Archive capabilities', () => {
  it('packs, lists, and extracts zip archives safely', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());

    const packed = await registry.execute('archive_zip', {
      operation: 'pack',
      files: [
        { path: 'docs/hello.txt', text: 'Hello Elyan' },
        { path: 'data/info.json', text: '{"ok":true}' },
      ],
    });

    const listed = await registry.execute('archive_zip', {
      operation: 'list',
      base64: packed.base64,
    });

    expect(listed.entries.map((entry) => entry.path)).toEqual(
      expect.arrayContaining(['data/info.json', 'docs/hello.txt'])
    );

    const extracted = await registry.execute('archive_zip', {
      operation: 'extract',
      base64: packed.base64,
    });

    expect(extracted.files).toHaveLength(2);
    expect(
      Buffer.from(extracted.files.find((file) => file.path === 'docs/hello.txt')?.base64 ?? '', 'base64').toString(
        'utf8'
      )
    ).toContain('Elyan');
  });

  it('rejects archive path traversal attempts', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());

    await expect(
      registry.execute('archive_zip', {
        operation: 'pack',
        files: [{ path: '../evil.txt', text: 'nope' }],
      })
    ).rejects.toThrow(/unsafe archive path/i);
  });
});
