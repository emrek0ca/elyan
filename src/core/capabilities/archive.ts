import JSZip from 'jszip';
import { z } from 'zod';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';

class ArchiveCapabilityError extends Error {
  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'ArchiveCapabilityError';

    if (cause !== undefined) {
      (this as Error & { cause?: unknown }).cause = cause;
    }
  }
}

const archiveSourceSchema = z.object({
  path: z.string().min(1),
  base64: z.string().min(1).optional(),
  text: z.string().optional(),
});

const archiveInputSchema = z.discriminatedUnion('operation', [
  z.object({
    operation: z.literal('list'),
    base64: z.string().min(1),
  }),
  z.object({
    operation: z.literal('extract'),
    base64: z.string().min(1),
  }),
  z.object({
    operation: z.literal('pack'),
    files: z.array(archiveSourceSchema).min(1),
  }),
]);

const archiveListOutputSchema = z.object({
  operation: z.literal('list'),
  entries: z.array(
    z.object({
      path: z.string(),
      isDirectory: z.boolean(),
      compressedSize: z.number().int().nonnegative().optional(),
      uncompressedSize: z.number().int().nonnegative().optional(),
    })
  ),
});

const archiveExtractOutputSchema = z.object({
  operation: z.literal('extract'),
  files: z.array(
    z.object({
      path: z.string(),
      base64: z.string(),
      byteLength: z.number().int().nonnegative(),
    })
  ),
});

const archivePackOutputSchema = z.object({
  operation: z.literal('pack'),
  base64: z.string(),
  byteLength: z.number().int().positive(),
  entryCount: z.number().int().positive(),
});

const archiveOutputSchema = z.discriminatedUnion('operation', [
  archiveListOutputSchema,
  archiveExtractOutputSchema,
  archivePackOutputSchema,
]);

function normalizeArchivePath(path: string) {
  const normalized = path.trim().replace(/\\/g, '/').replace(/^\/+/, '').replace(/^\.\/+/, '');

  if (
    !normalized ||
    normalized === '.' ||
    normalized === '..' ||
    normalized.includes('/../') ||
    normalized.startsWith('../') ||
    /^[a-zA-Z]:/.test(normalized)
  ) {
    throw new ArchiveCapabilityError(`Unsafe archive path: ${path}`);
  }

  return normalized;
}

function toBase64(data: Uint8Array | Buffer) {
  if (Buffer.isBuffer(data)) {
    return data.toString('base64');
  }

  return Buffer.from(data).toString('base64');
}

async function loadArchive(base64: string) {
  try {
    return await JSZip.loadAsync(Buffer.from(base64, 'base64'));
  } catch (error) {
    throw new ArchiveCapabilityError('Unable to read archive', error);
  }
}

export async function inspectArchive(base64: string) {
  const archive = await loadArchive(base64);

  return {
    operation: 'list' as const,
    entries: Object.values(archive.files)
      .map((entry) => ({
        path: entry.name,
        isDirectory: entry.dir,
      }))
      .sort((left, right) => left.path.localeCompare(right.path)),
  };
}

export async function extractArchive(base64: string) {
  const archive = await loadArchive(base64);
  const files = [] as Array<{ path: string; base64: string; byteLength: number }>;

  for (const entry of Object.values(archive.files)) {
    if (entry.dir) {
      continue;
    }

    const path = normalizeArchivePath(entry.name);
    const data = await entry.async('uint8array');
    files.push({
      path,
      base64: toBase64(data),
      byteLength: data.byteLength,
    });
  }

  return {
    operation: 'extract' as const,
    files: files.sort((left, right) => left.path.localeCompare(right.path)),
  };
}

export async function packArchive(files: z.output<typeof archiveSourceSchema>[]) {
  try {
    const archive = new JSZip();

    for (const file of files) {
      const path = normalizeArchivePath(file.path);

      if (file.base64) {
        archive.file(path, Buffer.from(file.base64, 'base64'));
        continue;
      }

      if (file.text !== undefined) {
        archive.file(path, file.text);
        continue;
      }

      throw new ArchiveCapabilityError(`Archive file is missing content: ${path}`);
    }

    const buffer = await archive.generateAsync({
      type: 'nodebuffer',
      compression: 'DEFLATE',
      compressionOptions: {
        level: 6,
      },
    });

    return {
      operation: 'pack' as const,
      base64: buffer.toString('base64'),
      byteLength: buffer.byteLength,
      entryCount: files.length,
    };
  } catch (error) {
    if (error instanceof ArchiveCapabilityError) {
      throw error;
    }

    throw new ArchiveCapabilityError('Unable to write archive', error);
  }
}

export const archiveCapability: CapabilityDefinition<
  typeof archiveInputSchema,
  typeof archiveOutputSchema
> = {
  id: 'archive_zip',
  title: 'Archive ZIP',
  description: 'Lists, extracts, and packs ZIP archives with JSZip.',
  library: 'jszip',
  enabled: true,
  timeoutMs: 1_500,
  inputSchema: archiveInputSchema,
  outputSchema: archiveOutputSchema,
  run: async (input: z.output<typeof archiveInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;

    switch (input.operation) {
      case 'list':
        return inspectArchive(input.base64);
      case 'extract':
        return extractArchive(input.base64);
      case 'pack':
        return packArchive(input.files);
    }
  },
};
