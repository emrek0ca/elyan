import { capabilityRegistry } from '@/core/capabilities';
import { readMcpServerConfigs, McpToolRegistry } from '@/core/mcp';
import { type ScrapedContent } from '@/types/search';
import { type ExecutionPolicy, type ExecutionTarget } from './types';
import type { ExecutionSurfaceSnapshot } from './surface';

type OperatorOutcome = {
  contextBlocks: string[];
  sources: ScrapedContent[];
  notes: string[];
  target?: ExecutionTarget;
};

type PromptArguments = Record<string, string>;

function stringifyValue(value: unknown): string {
  if (typeof value === 'string') {
    return value;
  }

  if (value === null || value === undefined) {
    return '';
  }

  if (Array.isArray(value)) {
    return value.map(stringifyValue).filter(Boolean).join('\n');
  }

  if (typeof value === 'object') {
    if ('messages' in value && Array.isArray((value as { messages?: unknown[] }).messages)) {
      return stringifyValue((value as { messages?: unknown[] }).messages);
    }

    if ('content' in value && Array.isArray((value as { content?: unknown[] }).content)) {
      return stringifyValue((value as { content?: unknown[] }).content);
    }

    return JSON.stringify(value, null, 2);
  }

  return String(value);
}

function toScrapedContent(url: string, title: string, content: string): ScrapedContent {
  return {
    url,
    title,
    content,
    wordCount: content.trim().length === 0 ? 0 : content.trim().split(/\s+/).length,
    extractedAt: new Date(),
  };
}

function extractFirstUrl(query: string) {
  return query.match(/https?:\/\/[^\s)]+/i)?.[0];
}

function extractMathExpression(query: string) {
  const match = query.match(/[-+*/().\d\s^]+/);

  if (!match) {
    return undefined;
  }

  const expression = match[0].trim();
  return /\d/.test(expression) ? expression : undefined;
}

function parseDecimalExpression(expression: string) {
  const match = expression.match(/^\s*(-?\d+(?:\.\d+)?)\s*([+\-*/])\s*(-?\d+(?:\.\d+)?)\s*$/);

  if (!match) {
    return undefined;
  }

  const [, left, operator, right] = match;
  const operation =
    operator === '+' ? 'add' : operator === '-' ? 'subtract' : operator === '*' ? 'multiply' : 'divide';

  return {
    left,
    right,
    operation,
  } as const;
}

function resolveBridgeToolId(query: string, target?: ExecutionTarget) {
  if (target?.id && target.id !== 'tool_bridge') {
    return target.id;
  }

  const normalized = query.toLowerCase();

  if (/\b(chart|plot|graph|visualize|visualise)\b/i.test(normalized)) {
    return 'chart_generate';
  }

  if (/\b(export|write|save)\b/i.test(normalized) && /\bcsv\b/i.test(normalized)) {
    return 'csv_export';
  }

  if (/\b(parse|read|load|import)\b/i.test(normalized) && /\bcsv\b/i.test(normalized)) {
    return 'csv_parse';
  }

  if (/\b(decimal|precision)\b/i.test(normalized)) {
    return 'math_decimal';
  }

  return 'math_exact';
}

function resolveTargetUrl(query: string, target?: ExecutionTarget) {
  if (target?.id && /^https?:\/\//i.test(target.id)) {
    return target.id;
  }

  return extractFirstUrl(query);
}

function isBrowserAutomationConfirmed(target: ExecutionTarget) {
  return target.kind !== 'browser_automation' || !target.requiresConfirmation;
}

function extractJsonObject(query: string) {
  const start = query.indexOf('{');
  if (start < 0) {
    return undefined;
  }

  let depth = 0;

  for (let index = start; index < query.length; index += 1) {
    const char = query[index];
    if (char === '{') {
      depth += 1;
    } else if (char === '}') {
      depth -= 1;

      if (depth === 0) {
        const candidate = query.slice(start, index + 1);

        try {
          const parsed = JSON.parse(candidate);
          return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
            ? (parsed as Record<string, unknown>)
            : undefined;
        } catch {
          return undefined;
        }
      }
    }
  }

  return undefined;
}

function extractNamedArguments(query: string): PromptArguments {
  const matches = query.matchAll(/\b([a-zA-Z][a-zA-Z0-9_-]{1,32})\s*[:=]\s*("[^"]+"|'[^']+'|[^\s,;]+)/g);
  const args: PromptArguments = {};

  for (const match of matches) {
    const key = match[1]?.trim();
    const rawValue = match[2]?.trim();

    if (!key || !rawValue) {
      continue;
    }

    args[key] = rawValue.replace(/^['"]|['"]$/g, '');
  }

  return args;
}

function extractPromptArguments(query: string) {
  const args = extractNamedArguments(query);
  return Object.keys(args).length > 0 ? args : undefined;
}

function expandResourceTemplate(template: string, query: string) {
  const placeholders = [...template.matchAll(/\{([a-zA-Z][a-zA-Z0-9_-]*)\}/g)].map((match) => match[1]).filter(Boolean) as string[];
  if (placeholders.length === 0) {
    return {
      ok: true as const,
      uri: template,
    };
  }

  const args = extractNamedArguments(query);
  const missing = placeholders.filter((name) => !args[name]);

  if (missing.length > 0) {
    return {
      ok: false as const,
      reason: `Missing template arguments: ${missing.join(', ')}.`,
    };
  }

  let uri = template;
  for (const placeholder of placeholders) {
    uri = uri.replaceAll(`{${placeholder}}`, encodeURIComponent(args[placeholder]));
  }

  return {
    ok: true as const,
    uri,
  };
}

export async function runOperatorPreflight(
  query: string,
  policy: ExecutionPolicy,
  surface: ExecutionSurfaceSnapshot
): Promise<OperatorOutcome> {
  void surface;
  const outcome: OperatorOutcome = {
    contextBlocks: [],
    sources: [],
    notes: [...policy.notes],
    target: policy.primary,
  };

  if (policy.primary.kind === 'direct_answer') {
    return outcome;
  }

  if (policy.primary.kind === 'local_bridge_tool') {
    const bridgeToolId = resolveBridgeToolId(query, policy.primary);

    if (bridgeToolId === 'math_exact') {
      const expression = extractMathExpression(query);

      if (!expression) {
        outcome.notes.push('Local math bridge was selected, but no deterministic expression was available.');
        return outcome;
      }

      const result = await capabilityRegistry.execute('tool_bridge', {
        toolId: bridgeToolId,
        input: {
          expression,
        },
      });

      const serialized = stringifyValue(result);
      outcome.sources.push(
        toScrapedContent(`local://tool_bridge/${bridgeToolId}`, 'Local calculation', serialized)
      );
      outcome.contextBlocks.push(`Local tool result:\n${serialized}`);
      return outcome;
    }

    if (bridgeToolId === 'math_decimal') {
      const expression = extractMathExpression(query);
      const parsed = expression ? parseDecimalExpression(expression) : undefined;

      if (!parsed) {
        outcome.notes.push('Decimal math was selected, but the expression was not a simple binary operation.');
        return outcome;
      }

      const result = await capabilityRegistry.execute('tool_bridge', {
        toolId: bridgeToolId,
        input: parsed,
      });

      const serialized = stringifyValue(result);
      outcome.sources.push(
        toScrapedContent(`local://tool_bridge/${bridgeToolId}`, 'Local calculation', serialized)
      );
      outcome.contextBlocks.push(`Local tool result:\n${serialized}`);
      return outcome;
    }

    outcome.notes.push(
      `Local bridge path resolved to ${bridgeToolId}, but the current preflight only auto-runs math bridge inputs.`
    );
    return outcome;
  }

  if (policy.primary.kind === 'local_capability') {
    outcome.notes.push(
      `Local capability ${policy.primary.title ?? policy.primary.id ?? 'unknown'} was selected, but the current preflight only auto-runs browser and math paths.`
    );
    return outcome;
  }

  if (policy.primary.kind === 'browser_read') {
    const url = resolveTargetUrl(query, policy.primary);
    if (!url) {
      outcome.notes.push('Browser read path was selected, but no URL was available.');
      return outcome;
    }

    const snapshot = await capabilityRegistry.execute('web_read_dynamic', {
      url,
      settleMs: 250,
    }) as {
      url: string;
      title: string;
      text: string;
      links: Array<{ text: string; href: string }>;
    };

    outcome.sources.push(
      toScrapedContent(
        snapshot.url,
        snapshot.title || 'Rendered page',
        [snapshot.title, snapshot.text, snapshot.links.map((link) => `${link.text} ${link.href}`).join('\n')]
          .filter(Boolean)
          .join('\n\n')
      )
    );
    outcome.contextBlocks.push(`Browser snapshot from ${snapshot.url}`);
    return outcome;
  }

  if (policy.primary.kind === 'crawl') {
    const url = resolveTargetUrl(query, policy.primary);
    if (!url) {
      outcome.notes.push('Crawl path was selected, but no URL was available.');
      return outcome;
    }

    const crawlResult = await capabilityRegistry.execute('web_crawl', {
      startUrls: [url],
      maxPages: 8,
      maxDepth: 1,
      sameDomainOnly: true,
    }) as {
      pages: Array<{ url: string; title: string; text: string; depth: number }>;
      errors: Array<{ url: string; message: string }>;
    };

    for (const page of crawlResult.pages) {
      outcome.sources.push(toScrapedContent(page.url, page.title || 'Crawled page', page.text));
    }

    outcome.contextBlocks.push(`Crawl completed with ${crawlResult.pages.length} pages.`);
    return outcome;
  }

  if (policy.primary.kind === 'mcp_resource' || policy.primary.kind === 'mcp_prompt') {
    const serverConfigs = readMcpServerConfigs();
    const registry = new McpToolRegistry(serverConfigs);

    try {
      if (policy.primary.kind === 'mcp_resource') {
        const resource = await registry.readResource(policy.primary.id ?? '');
        const content = stringifyValue(resource);
        outcome.sources.push(
          toScrapedContent(
            `mcp://resource/${policy.primary.id}`,
            policy.primary.title ?? 'MCP resource',
            content
          )
        );
        outcome.contextBlocks.push(`MCP resource result from ${policy.primary.title ?? policy.primary.id}`);
        return outcome;
      }

      const prompt = await registry.getPrompt(policy.primary.id ?? '', extractPromptArguments(query));
      const content = stringifyValue(prompt);
      outcome.sources.push(
        toScrapedContent(`mcp://prompt/${policy.primary.id}`, policy.primary.title ?? 'MCP prompt', content)
      );
      outcome.contextBlocks.push(`MCP prompt result from ${policy.primary.title ?? policy.primary.id}`);
      return outcome;
    } finally {
      await registry.close();
    }
  }

  if (policy.primary.kind === 'mcp_tool') {
    if (policy.primary.requiresConfirmation) {
      outcome.notes.push('MCP tool execution requires explicit confirmation before the tool can run.');
      return outcome;
    }

    const toolId = policy.primary.id;
    if (!toolId) {
      outcome.notes.push('MCP tool path was selected, but no tool id was available.');
      return outcome;
    }

    const serverConfigs = readMcpServerConfigs();
    const registry = new McpToolRegistry(serverConfigs);

    try {
      const input = extractJsonObject(query) ?? {};
      const result = await registry.invokeTool(toolId, input);
      const content = stringifyValue(result);
      outcome.sources.push(
        toScrapedContent(`mcp://tool/${toolId}`, policy.primary.title ?? toolId, content)
      );
      outcome.contextBlocks.push(`MCP tool result from ${policy.primary.title ?? toolId}`);
      return outcome;
    } finally {
      await registry.close();
    }
  }

  if (policy.primary.kind === 'mcp_resource_template') {
    const template = policy.primary.id;
    if (!template) {
      outcome.notes.push('MCP resource template path was selected, but no template id was available.');
      return outcome;
    }

    const resolved = expandResourceTemplate(template, query);
    if (!resolved.ok) {
      outcome.notes.push(
        `MCP resource template could not be resolved. ${resolved.reason} Provide arguments like key=value in the request.`
      );
      return outcome;
    }

    const serverConfigs = readMcpServerConfigs();
    const registry = new McpToolRegistry(serverConfigs);

    try {
      const resource = await registry.readResource(resolved.uri);
      const content = stringifyValue(resource);
      outcome.sources.push(
        toScrapedContent(
          `mcp://resource-template/${resolved.uri}`,
          policy.primary.title ?? 'MCP resource template',
          content
        )
      );
      outcome.contextBlocks.push(`MCP resource template result from ${policy.primary.title ?? resolved.uri}`);
      return outcome;
    } finally {
      await registry.close();
    }
  }

  if (policy.primary.kind === 'browser_automation') {
    if (!isBrowserAutomationConfirmed(policy.primary)) {
      outcome.notes.push('Browser automation requires explicit confirmation before execution.');
      return outcome;
    }

    const url = resolveTargetUrl(query, policy.primary);
    if (!url) {
      outcome.notes.push('Browser automation path was selected, but no URL was available.');
      return outcome;
    }

    outcome.notes.push(
      'Browser automation was selected, but the query does not provide a safe action sequence. Waiting for explicit actions.'
    );
    return outcome;
  }

  return outcome;
}
