import { describe, expect, it } from 'vitest';
import { buildCapabilityProfileGuide, listCapabilityProfileGuides } from '@/core/capabilities/profiles';

describe('Capability profile guides', () => {
  it('exposes ready library hints for the main lanes', () => {
    const documents = buildCapabilityProfileGuide('documents');
    const browser = buildCapabilityProfileGuide('browser');
    const memory = buildCapabilityProfileGuide('memory');

    expect(documents.libraries).toEqual(
      expect.arrayContaining(['pdfjs-dist', 'pdf-lib', 'docx', 'mammoth', 'exceljs'])
    );
    expect(browser.libraries).toEqual(['playwright']);
    expect(memory.libraries).toEqual(expect.arrayContaining(['@orama/orama', 'fuse.js']));
  });

  it('keeps the guide list aligned with the supported capability categories', () => {
    const guides = listCapabilityProfileGuides();

    expect(guides).toHaveLength(10);
    expect(guides.every((guide) => Array.isArray(guide.libraries))).toBe(true);
  });
});
