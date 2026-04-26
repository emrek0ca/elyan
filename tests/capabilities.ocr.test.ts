import { describe, expect, it } from 'vitest';
import sharp from 'sharp';
import { CapabilityAuditTrail, CapabilityRegistry } from '@/core/capabilities';

function buildTextImage(text: string): Promise<Buffer> {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="420" height="140">
    <rect width="100%" height="100%" fill="white"/>
    <text x="24" y="88" font-size="68" font-family="Arial, Helvetica, sans-serif" font-weight="700" fill="black">${text}</text>
  </svg>`;

  return sharp(Buffer.from(svg)).png().toBuffer();
}

describe('OCR capabilities', () => {
  it(
    'reads high-contrast text from images',
    { timeout: 45_000 },
    async () => {
      const registry = new CapabilityRegistry(new CapabilityAuditTrail());
      const image = await buildTextImage('HELLO');

      const ocr = await registry.execute('ocr_image', {
        base64: image.toString('base64'),
        language: 'eng',
      });

      expect(ocr.text.toUpperCase()).toContain('HELLO');
      expect(ocr.confidence).toBeGreaterThanOrEqual(0);
    }
  );
});
