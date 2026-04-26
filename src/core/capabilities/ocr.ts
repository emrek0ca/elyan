import { recognize } from 'tesseract.js';
import { z } from 'zod';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';

class OcrCapabilityError extends Error {
  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'OcrCapabilityError';

    if (cause !== undefined) {
      (this as Error & { cause?: unknown }).cause = cause;
    }
  }
}

const ocrInputSchema = z.object({
  base64: z.string().min(1),
  language: z.string().min(1).default('eng'),
});

const ocrOutputSchema = z.object({
  language: z.string(),
  text: z.string(),
  confidence: z.number().min(0).max(100),
  wordCount: z.number().int().nonnegative(),
});

export async function runOcr(base64: string, language: string) {
  try {
    const result = await recognize(Buffer.from(base64, 'base64'), language);
    const normalizedText = result.data.text.trim();
    return {
      language,
      text: normalizedText,
      confidence: result.data.confidence ?? 0,
      wordCount: normalizedText.length > 0 ? normalizedText.split(/\s+/).filter(Boolean).length : 0,
    };
  } catch (error) {
    throw new OcrCapabilityError('Unable to recognize image text', error);
  }
}

export const ocrCapability: CapabilityDefinition<typeof ocrInputSchema, typeof ocrOutputSchema> = {
  id: 'ocr_image',
  title: 'OCR Image',
  description: 'Reads scanned images into text with Tesseract.js.',
  library: 'tesseract.js',
  enabled: true,
  timeoutMs: 12_000,
  inputSchema: ocrInputSchema,
  outputSchema: ocrOutputSchema,
  run: async (input: z.output<typeof ocrInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    return runOcr(input.base64, input.language);
  },
};
