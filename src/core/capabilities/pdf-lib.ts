import { PDFDocument, PageSizes, StandardFonts, degrees, rgb } from 'pdf-lib';
import { z } from 'zod';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';

class PdfWorkflowCapabilityError extends Error {
  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'PdfWorkflowCapabilityError';

    if (cause !== undefined) {
      (this as Error & { cause?: unknown }).cause = cause;
    }
  }
}

const pdfParagraphSchema = z.string().min(1);

const pdfCreateInputSchema = z.object({
  operation: z.literal('create'),
  title: z.string().min(1).default('Elyan PDF'),
  paragraphs: z.array(pdfParagraphSchema).min(1),
});

const pdfMergeInputSchema = z.object({
  operation: z.literal('merge'),
  pdfs: z.array(z.string().min(1)).min(2),
});

const pdfSplitInputSchema = z.object({
  operation: z.literal('split'),
  base64: z.string().min(1),
});

const pdfAnnotateInputSchema = z.object({
  operation: z.literal('annotate'),
  base64: z.string().min(1),
  notes: z
    .array(
      z.object({
        pageIndex: z.number().int().min(0),
        text: z.string().min(1),
        x: z.number().nonnegative().optional(),
        y: z.number().nonnegative().optional(),
      })
    )
    .min(1),
});

const pdfWorkflowInputSchema = z.discriminatedUnion('operation', [
  pdfCreateInputSchema,
  pdfMergeInputSchema,
  pdfSplitInputSchema,
  pdfAnnotateInputSchema,
]);

const pdfCreateOutputSchema = z.object({
  operation: z.literal('create'),
  base64: z.string(),
  byteLength: z.number().int().positive(),
  pageCount: z.number().int().positive(),
});

const pdfMergeOutputSchema = z.object({
  operation: z.literal('merge'),
  base64: z.string(),
  byteLength: z.number().int().positive(),
  pageCount: z.number().int().positive(),
});

const pdfSplitOutputSchema = z.object({
  operation: z.literal('split'),
  pages: z.array(
    z.object({
      pageIndex: z.number().int().nonnegative(),
      base64: z.string(),
      byteLength: z.number().int().positive(),
    })
  ),
});

const pdfAnnotateOutputSchema = z.object({
  operation: z.literal('annotate'),
  base64: z.string(),
  byteLength: z.number().int().positive(),
  pageCount: z.number().int().positive(),
  annotationCount: z.number().int().positive(),
});

const pdfWorkflowOutputSchema = z.discriminatedUnion('operation', [
  pdfCreateOutputSchema,
  pdfMergeOutputSchema,
  pdfSplitOutputSchema,
  pdfAnnotateOutputSchema,
]);

async function loadPdf(base64: string) {
  try {
    return await PDFDocument.load(Buffer.from(base64, 'base64'), {
      ignoreEncryption: false,
      updateMetadata: false,
    });
  } catch (error) {
    throw new PdfWorkflowCapabilityError('Unable to read PDF document', error);
  }
}

async function savePdf(pdf: PDFDocument) {
  const bytes = await pdf.save({
    useObjectStreams: false,
  });

  return {
    base64: Buffer.from(bytes).toString('base64'),
    byteLength: bytes.byteLength,
  };
}

async function createPdf(title: string, paragraphs: string[]) {
  const pdf = await PDFDocument.create({ updateMetadata: false });
  const font = await pdf.embedFont(StandardFonts.Helvetica);
  pdf.setTitle(title);
  pdf.setCreator('Elyan');
  pdf.setProducer('Elyan');

  let page = pdf.addPage(PageSizes.A4);
  const { width, height } = page.getSize();
  const margin = 48;
  const maxWidth = width - margin * 2;
  let cursorY = height - margin;

  page.drawText(title, {
    x: margin,
    y: cursorY,
    size: 18,
    font,
    color: rgb(0.15, 0.18, 0.24),
  });

  cursorY -= 30;

  for (const paragraph of paragraphs) {
    const lines = paragraph.trim().split(/\n+/);

    for (const line of lines) {
      if (cursorY < margin + 48) {
        page = pdf.addPage(PageSizes.A4);
        cursorY = page.getHeight() - margin;
        page.drawText(title, {
          x: margin,
          y: cursorY,
          size: 18,
          font,
          color: rgb(0.15, 0.18, 0.24),
        });
        cursorY -= 30;
        page.drawText(line, {
          x: margin,
          y: cursorY,
          size: 12,
          font,
          color: rgb(0.1, 0.12, 0.15),
          maxWidth,
          lineHeight: 16,
        });
        cursorY -= 24;
        continue;
      }

      page.drawText(line, {
        x: margin,
        y: cursorY,
        size: 12,
        font,
        color: rgb(0.1, 0.12, 0.15),
        maxWidth,
        lineHeight: 16,
      });
      cursorY -= 24;
    }

    cursorY -= 12;
  }

  return pdf;
}

async function mergePdfs(pdfs: string[]) {
  const merged = await PDFDocument.create({ updateMetadata: false });

  for (const pdfBase64 of pdfs) {
    const source = await loadPdf(pdfBase64);
    const pages = await merged.copyPages(source, source.getPageIndices());

    for (const page of pages) {
      merged.addPage(page);
    }
  }

  return merged;
}

async function splitPdf(base64: string) {
  const source = await loadPdf(base64);
  const pages = await Promise.all(
    source.getPageIndices().map(async (pageIndex) => {
      const splitDoc = await PDFDocument.create({ updateMetadata: false });
      const [copiedPage] = await splitDoc.copyPages(source, [pageIndex]);
      splitDoc.addPage(copiedPage);
      const serialized = await savePdf(splitDoc);

      return {
        pageIndex,
        base64: serialized.base64,
        byteLength: serialized.byteLength,
      };
    })
  );

  return {
    operation: 'split' as const,
    pages,
  };
}

async function annotatePdf(base64: string, notes: z.output<typeof pdfAnnotateInputSchema>['notes']) {
  const pdf = await loadPdf(base64);
  const font = await pdf.embedFont(StandardFonts.Helvetica);
  const pageCount = pdf.getPageCount();

  for (const note of notes) {
    if (note.pageIndex >= pageCount) {
      throw new PdfWorkflowCapabilityError(`Annotation page index is out of range: ${note.pageIndex}`);
    }

    const page = pdf.getPage(note.pageIndex);
    const { width, height } = page.getSize();
    const x = note.x ?? 48;
    const y = note.y ?? height - 72;

    page.drawText(note.text, {
      x,
      y,
      size: 11,
      font,
      color: rgb(0.15, 0.18, 0.24),
      rotate: degrees(0),
      maxWidth: Math.max(24, width - x - 48),
      lineHeight: 14,
    });
  }

  const serialized = await savePdf(pdf);

  return {
    operation: 'annotate' as const,
    base64: serialized.base64,
    byteLength: serialized.byteLength,
    pageCount,
    annotationCount: notes.length,
  };
}

export const pdfWorkflowCapability: CapabilityDefinition<
  typeof pdfWorkflowInputSchema,
  typeof pdfWorkflowOutputSchema
> = {
  id: 'pdf_workflow',
  title: 'PDF Workflow',
  description: 'Creates, merges, splits, and annotates PDFs with pdf-lib.',
  library: 'pdf-lib',
  enabled: true,
  timeoutMs: 4_000,
  inputSchema: pdfWorkflowInputSchema,
  outputSchema: pdfWorkflowOutputSchema,
  run: async (input: z.output<typeof pdfWorkflowInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;

    switch (input.operation) {
      case 'create': {
        const pdf = await createPdf(input.title, input.paragraphs);
        const serialized = await savePdf(pdf);
        return {
          operation: 'create' as const,
          ...serialized,
          pageCount: pdf.getPageCount(),
        };
      }
      case 'merge': {
        const pdf = await mergePdfs(input.pdfs);
        const serialized = await savePdf(pdf);
        return {
          operation: 'merge' as const,
          ...serialized,
          pageCount: pdf.getPageCount(),
        };
      }
      case 'split':
        return splitPdf(input.base64);
      case 'annotate':
        return annotatePdf(input.base64, input.notes);
    }
  },
};
