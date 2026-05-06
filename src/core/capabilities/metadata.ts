import { XMLParser } from 'fast-xml-parser';
import { parse as parseYaml } from 'yaml';
import { z } from 'zod';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';

class MetadataCapabilityError extends Error {
  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'MetadataCapabilityError';

    if (cause !== undefined) {
      (this as Error & { cause?: unknown }).cause = cause;
    }
  }
}

const metadataInputSchema = z.object({
  format: z.enum(['yaml', 'xml', 'frontmatter']),
  text: z.string().min(1),
});

const metadataOutputSchema = z.object({
  format: z.enum(['yaml', 'xml', 'frontmatter']),
  data: z.unknown(),
  body: z.string().optional(),
  keys: z.array(z.string()),
});

function topLevelKeys(value: unknown): string[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return [];
  }

  return Object.keys(value as Record<string, unknown>);
}

function parseFrontmatter(text: string) {
  const normalized = text.replace(/\r\n/g, '\n');

  if (!normalized.startsWith('---\n')) {
    throw new MetadataCapabilityError('Frontmatter documents must start with ---');
  }

  const closingMarker = normalized.indexOf('\n---\n', 4);
  if (closingMarker === -1) {
    throw new MetadataCapabilityError('Frontmatter closing marker not found');
  }

  const head = normalized.slice(4, closingMarker);
  const body = normalized.slice(closingMarker + 5).trimStart();
  const data = parseYaml(head);

  return {
    data,
    body,
    keys: topLevelKeys(data),
  };
}

function parseMetadata(text: string, format: z.output<typeof metadataInputSchema>['format']) {
  try {
    if (format === 'yaml') {
      const data = parseYaml(text);
      return {
        format,
        data,
        keys: topLevelKeys(data),
      };
    }

    if (format === 'frontmatter') {
      return {
        format,
        ...parseFrontmatter(text),
      };
    }

    const parser = new XMLParser({
      ignoreAttributes: false,
      attributeNamePrefix: '@_',
      allowBooleanAttributes: true,
      parseTagValue: true,
      parseAttributeValue: true,
      trimValues: true,
    });

    const data = parser.parse(text);
    return {
      format,
      data,
      keys: topLevelKeys(data),
    };
  } catch (error) {
    throw new MetadataCapabilityError(`Unable to parse ${format} metadata`, error);
  }
}

export const metadataCapability: CapabilityDefinition<
  typeof metadataInputSchema,
  typeof metadataOutputSchema
> = {
  id: 'metadata_parse',
  title: 'Metadata Parse',
  description: 'Parses YAML, XML, and frontmatter metadata deterministically.',
  library: 'yaml + fast-xml-parser',
  enabled: true,
  timeoutMs: 500,
  inputSchema: metadataInputSchema,
  outputSchema: metadataOutputSchema,
  run: async (input: z.output<typeof metadataInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    return parseMetadata(input.text, input.format);
  },
};
