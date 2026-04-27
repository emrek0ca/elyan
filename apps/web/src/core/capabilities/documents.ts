import mammoth from 'mammoth';
import { Document, Packer, Paragraph } from 'docx';
import JSZip from 'jszip';
import { z } from 'zod';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';

class DocumentCapabilityError extends Error {
  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'DocumentCapabilityError';

    if (cause !== undefined) {
      (this as Error & { cause?: unknown }).cause = cause;
    }
  }
}

const DOCX_CORE_TIMESTAMP = '2000-01-01T00:00:00.000Z';
const DOCX_ZIP_TIMESTAMP = new Date(DOCX_CORE_TIMESTAMP);
const DOCX_CORE_PROPERTIES_OVERRIDE = [
  {
    path: 'docProps/core.xml',
    data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:creator>Un-named</dc:creator><cp:lastModifiedBy>Un-named</cp:lastModifiedBy><cp:revision>1</cp:revision><dcterms:created xsi:type="dcterms:W3CDTF">${DOCX_CORE_TIMESTAMP}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">${DOCX_CORE_TIMESTAMP}</dcterms:modified></cp:coreProperties>`,
  },
] as const;

async function normalizeDocxZipBuffer(buffer: Buffer) {
  const source = await JSZip.loadAsync(buffer);
  const normalized = new JSZip();
  const entries = Object.values(source.files).sort((left, right) => left.name.localeCompare(right.name));

  for (const entry of entries) {
    if (entry.dir) {
      continue;
    }

    normalized.file(entry.name, await entry.async('nodebuffer'), {
      date: DOCX_ZIP_TIMESTAMP,
      compression: 'DEFLATE',
      createFolders: false,
    });
  }

  return normalized.generateAsync({
    type: 'nodebuffer',
    compression: 'DEFLATE',
    platform: 'DOS',
  });
}

const docxReadInputSchema = z.object({
  base64: z.string().min(1),
});

const docxReadOutputSchema = z.object({
  text: z.string(),
  messageCount: z.number().int().nonnegative(),
});

const docxWriteInputSchema = z.object({
  paragraphs: z.array(z.string().min(1)).min(1),
});

const docxWriteOutputSchema = z.object({
  base64: z.string(),
  byteLength: z.number().int().positive(),
});

export const docxReadCapability: CapabilityDefinition<
  typeof docxReadInputSchema,
  typeof docxReadOutputSchema
> = {
  id: 'docx_read',
  title: 'DOCX Read',
  description: 'Extracts plain text from DOCX files with Mammoth.',
  library: 'mammoth',
  enabled: true,
  timeoutMs: 5_000,
  inputSchema: docxReadInputSchema,
  outputSchema: docxReadOutputSchema,
  run: async (input: z.output<typeof docxReadInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    try {
      const result = await mammoth.extractRawText({
        buffer: Buffer.from(input.base64, 'base64'),
      });

      return {
        text: result.value.trim(),
        messageCount: result.messages.length,
      };
    } catch (error) {
      throw new DocumentCapabilityError('Unable to read DOCX content', error);
    }
  },
};

export const docxWriteCapability: CapabilityDefinition<
  typeof docxWriteInputSchema,
  typeof docxWriteOutputSchema
> = {
  id: 'docx_write',
  title: 'DOCX Write',
  description: 'Creates simple DOCX documents with docx.',
  library: 'docx',
  enabled: true,
  timeoutMs: 5_000,
  inputSchema: docxWriteInputSchema,
  outputSchema: docxWriteOutputSchema,
  run: async (input: z.output<typeof docxWriteInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    try {
      const document = new Document({
        sections: [
          {
            children: input.paragraphs.map((paragraph) => new Paragraph({ text: paragraph })),
          },
        ],
      });

      const buffer = await normalizeDocxZipBuffer(await Packer.toBuffer(document, false, DOCX_CORE_PROPERTIES_OVERRIDE));
      return {
        base64: buffer.toString('base64'),
        byteLength: buffer.byteLength,
      };
    } catch (error) {
      throw new DocumentCapabilityError('Unable to write DOCX content', error);
    }
  },
};
