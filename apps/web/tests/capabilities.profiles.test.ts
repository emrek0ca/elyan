import { describe, expect, it } from 'vitest';
import {
  buildCapabilityProfileGuide,
  getCapabilityLibraryStrategy,
  listCapabilityLibraryStrategies,
  listCapabilityProfileGuides,
} from '@/core/capabilities';

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

    expect(guides).toHaveLength(11);
    expect(guides.map((guide) => guide.category)).toContain('optimization');
    expect(guides.every((guide) => Array.isArray(guide.libraries))).toBe(true);
  });

  it('documents active and planned JS primitives without pretending planned libraries are installed', () => {
    const strategies = listCapabilityLibraryStrategies();
    const code = getCapabilityLibraryStrategy('code');
    const process = getCapabilityLibraryStrategy('process');
    const research = getCapabilityLibraryStrategy('research');

    expect(strategies.length).toBeGreaterThanOrEqual(6);
    expect(research?.libraries).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ name: 'crawlee', status: 'active' }),
        expect.objectContaining({ name: 'playwright', status: 'active' }),
      ])
    );
    expect(code?.libraries).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ name: 'ts-morph', status: 'active' }),
        expect.objectContaining({ name: 'simple-git', status: 'active' }),
      ])
    );
    expect(process?.libraries).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ name: 'execa', status: 'planned' }),
      ])
    );
  });
});
