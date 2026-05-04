import sharp from 'sharp';
import { z } from 'zod';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';

const imageProcessInputSchema = z.object({
  base64: z.string().min(1),
  operation: z.enum(['metadata', 'resize']),
  width: z.number().int().positive().optional(),
  height: z.number().int().positive().optional(),
  format: z.enum(['png', 'jpeg', 'webp']).default('png'),
  quality: z.number().int().min(1).max(100).optional(),
});

const imageProcessOutputSchema = z.object({
  kind: z.enum(['metadata', 'image']),
  width: z.number().int().positive().nullable().optional(),
  height: z.number().int().positive().nullable().optional(),
  format: z.string().optional(),
  contentType: z.string().optional(),
  base64: z.string().optional(),
});

export const imageProcessCapability: CapabilityDefinition<
  typeof imageProcessInputSchema,
  typeof imageProcessOutputSchema
> = {
  id: 'image_process',
  title: 'Image Process',
  description: 'Reads metadata or resizes images with sharp.',
  library: 'sharp',
  enabled: true,
  timeoutMs: 750,
  inputSchema: imageProcessInputSchema,
  outputSchema: imageProcessOutputSchema,
  run: async (input: z.output<typeof imageProcessInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    const image = sharp(Buffer.from(input.base64, 'base64'));

    if (input.operation === 'metadata') {
      const metadata = await image.metadata();
      return {
        kind: 'metadata',
        width: metadata.width ?? null,
        height: metadata.height ?? null,
        format: metadata.format,
      };
    }

    const pipeline = image.resize(input.width, input.height, {
      fit: 'inside',
      withoutEnlargement: true,
    });

    const outputBuffer = await pipeline
      .toFormat(input.format, input.format === 'jpeg' ? { quality: input.quality ?? 90 } : undefined)
      .toBuffer();

    return {
      kind: 'image',
      contentType: `image/${input.format}`,
      base64: outputBuffer.toString('base64'),
    };
  },
};
