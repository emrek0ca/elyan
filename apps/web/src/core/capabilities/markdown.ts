import { z } from 'zod';
import { renderMarkdownToHtml } from '@/core/content/markdown';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';

class MarkdownCapabilityError extends Error {
  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'MarkdownCapabilityError';

    if (cause !== undefined) {
      (this as Error & { cause?: unknown }).cause = cause;
    }
  }
}

const markdownRenderInputSchema = z.object({
  markdown: z.string().min(1),
});

const markdownRenderOutputSchema = z.object({
  html: z.string(),
  characterCount: z.number().int().nonnegative(),
});

export async function renderSafeMarkdown(markdown: string) {
  try {
    return {
      html: await renderMarkdownToHtml(markdown),
      characterCount: markdown.length,
    };
  } catch (error) {
    throw new MarkdownCapabilityError('Unable to render markdown safely', error);
  }
}

export const markdownRenderCapability: CapabilityDefinition<
  typeof markdownRenderInputSchema,
  typeof markdownRenderOutputSchema
> = {
  id: 'markdown_render',
  title: 'Markdown Render',
  description: 'Renders Markdown to sanitized HTML with unified.',
  library: 'unified',
  enabled: true,
  timeoutMs: 500,
  inputSchema: markdownRenderInputSchema,
  outputSchema: markdownRenderOutputSchema,
  run: async (input: z.output<typeof markdownRenderInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    return renderSafeMarkdown(input.markdown);
  },
};
