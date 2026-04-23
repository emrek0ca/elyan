import { describe, expect, it } from 'vitest';
import { chromium } from 'playwright';
import sharp from 'sharp';
import { CapabilityAuditTrail, CapabilityRegistry } from '@/core/capabilities';

async function buildPdf(text: string): Promise<Buffer> {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`<html><body><main>${text}</main></body></html>`);
    return Buffer.from(await page.pdf({ format: 'A4' }));
  } finally {
    await browser.close();
  }
}

describe('Document and media capabilities', () => {
  it('writes and reads DOCX content', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());

    const written = await registry.execute('docx_write', {
      paragraphs: ['First paragraph', 'Second paragraph'],
    });

    const readBack = await registry.execute('docx_read', {
      base64: written.base64,
    });

    expect(readBack.text).toContain('First paragraph');
    expect(readBack.text).toContain('Second paragraph');
  });

  it('writes deterministic DOCX output for the same paragraphs', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());

    const first = await registry.execute('docx_write', {
      paragraphs: ['First paragraph', 'Second paragraph'],
    });

    const second = await registry.execute('docx_write', {
      paragraphs: ['First paragraph', 'Second paragraph'],
    });

    expect(first.base64).toBe(second.base64);
    expect(first.byteLength).toBe(second.byteLength);
  });

  it('extracts text from PDF content', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());
    const pdfBase64 = (await buildPdf('Elyan PDF')).toString('base64');

    const extracted = await registry.execute('pdf_extract', {
      base64: pdfBase64,
    });

    expect(extracted.text).toContain('Elyan PDF');
    expect(extracted.totalPages).toBe(1);
  });

  it('reads image metadata and resizes images', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());
    const input = await sharp({
      create: {
        width: 4,
        height: 2,
        channels: 3,
        background: { r: 255, g: 0, b: 0 },
      },
    })
      .png()
      .toBuffer();

    const metadata = await registry.execute('image_process', {
      base64: input.toString('base64'),
      operation: 'metadata',
    });

    expect(metadata.width).toBe(4);
    expect(metadata.height).toBe(2);

    const resized = await registry.execute('image_process', {
      base64: input.toString('base64'),
      operation: 'resize',
      width: 1,
      format: 'png',
    });

    const resizedMetadata = await sharp(Buffer.from(resized.base64 ?? '', 'base64')).metadata();
    expect(resized.kind).toBe('image');
    expect(resizedMetadata.width).toBe(1);
  });
});
