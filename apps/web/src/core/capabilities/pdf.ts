import { z } from 'zod';
import { CapabilityDisabledError } from './errors';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';

type PdfJsModule = typeof import('pdfjs-dist/legacy/build/pdf.mjs');

function ensurePromiseWithResolvers() {
  const promiseConstructor = Promise as PromiseConstructor & {
    withResolvers?: <T>() => {
      promise: Promise<T>;
      resolve: (value: T | PromiseLike<T>) => void;
      reject: (reason?: unknown) => void;
    };
  };

  if (typeof promiseConstructor.withResolvers === 'function') {
    return;
  }

  promiseConstructor.withResolvers = <T>() => {
    let resolve!: (value: T | PromiseLike<T>) => void;
    let reject!: (reason?: unknown) => void;

    const promise = new Promise<T>((resolvePromise, rejectPromise) => {
      resolve = resolvePromise;
      reject = rejectPromise;
    });

    return { promise, resolve, reject };
  };
}

const pdfExtractInputSchema = z.object({
  base64: z.string().min(1),
});

const pdfExtractOutputSchema = z.object({
  text: z.string(),
  totalPages: z.number().int().positive(),
});

function isPdfJsRuntimeSupported() {
  return typeof window !== 'undefined' && typeof Uint8Array !== 'undefined';
}

async function loadPdfJs(): Promise<PdfJsModule> {
  if (!isPdfJsRuntimeSupported()) {
    throw new CapabilityDisabledError('pdf_extract', 'PDF extraction is unavailable in this runtime');
  }

  return import('pdfjs-dist/legacy/build/pdf.mjs');
}

function decodeBase64(base64: string) {
  if (typeof Buffer !== 'undefined') {
    return Uint8Array.from(Buffer.from(base64, 'base64'));
  }

  const binary = window.atob(base64);
  const data = new Uint8Array(binary.length);

  for (let index = 0; index < binary.length; index += 1) {
    data[index] = binary.charCodeAt(index);
  }

  return data;
}

function flattenTextItems(items: Array<{ str?: string }>): string {
  return items
    .map((item) => item.str?.trim() ?? '')
    .filter(Boolean)
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export const pdfExtractCapability: CapabilityDefinition<
  typeof pdfExtractInputSchema,
  typeof pdfExtractOutputSchema
> = {
  id: 'pdf_extract',
  title: 'PDF Extract',
  description: 'Extracts text from PDFs with PDF.js.',
  library: 'pdfjs-dist',
  enabled: true,
  timeoutMs: 5000,
  inputSchema: pdfExtractInputSchema,
  outputSchema: pdfExtractOutputSchema,
  run: async (input: z.output<typeof pdfExtractInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;

    ensurePromiseWithResolvers();

    const { getDocument } = await import('pdfjs-dist/legacy/build/pdf.mjs');

    if (typeof getDocument !== 'function') {
      throw new Error('PDF extraction is unavailable in this runtime.');
    }

    const data = Uint8Array.from(Buffer.from(input.base64, 'base64'));
    const loadingTask = getDocument({
      data,
      useWorkerFetch: false,
      isEvalSupported: false,
      disableFontFace: true,
    });

    const pdf = await loadingTask.promise;

    try {
      const pageTexts: string[] = [];

      for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
        const page = await pdf.getPage(pageNumber);
        const content = await page.getTextContent();
        pageTexts.push(flattenTextItems(content.items as Array<{ str?: string }>));
      }

      return {
        text: pageTexts.filter(Boolean).join('\n').trim(),
        totalPages: pdf.numPages,
      };
    } finally {
      await pdf.destroy().catch(() => undefined);
    }
  },
};
