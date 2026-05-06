import { mcpServerPolicySchema, type McpServerPolicy } from './types';

export type McpSurfaceKind = 'tool' | 'resource' | 'resourceTemplate' | 'prompt';

const SURFACE_SCOPE_BY_KIND: Record<McpSurfaceKind, 'tools' | 'resources' | 'resourceTemplates' | 'prompts'> = {
  tool: 'tools',
  resource: 'resources',
  resourceTemplate: 'resourceTemplates',
  prompt: 'prompts',
};

function buildRedactionMatchers(policy: McpServerPolicy) {
  const keyMatchers = policy.redactionKeys.map((value) => value.toLowerCase()).filter(Boolean);
  const patternMatchers = policy.redactionPatterns
    .map((pattern) => {
      try {
        return new RegExp(pattern, 'i');
      } catch {
        return undefined;
      }
    })
    .filter((value): value is RegExp => Boolean(value));

  return {
    keyMatchers,
    patternMatchers,
  };
}

export function normalizeMcpServerPolicy(policy?: Partial<McpServerPolicy>): McpServerPolicy {
  return mcpServerPolicySchema.parse(policy ?? {});
}

export function isMcpItemAllowed(kind: McpSurfaceKind, identifier: string, policy: McpServerPolicy): boolean {
  const scope = SURFACE_SCOPE_BY_KIND[kind];
  const blocked = policy.block?.[scope] ?? [];
  const allowed = policy.allow?.[scope] ?? [];

  if (blocked.includes(identifier)) {
    return false;
  }

  if (allowed.length > 0) {
    return allowed.includes(identifier);
  }

  return true;
}

export function filterMcpItems<T extends { identifier: string }>(items: T[], kind: McpSurfaceKind, policy: McpServerPolicy) {
  return items.filter((item) => isMcpItemAllowed(kind, item.identifier, policy));
}

export function estimatePayloadSize(value: unknown) {
  try {
    return Buffer.byteLength(JSON.stringify(value), 'utf8');
  } catch {
    return Buffer.byteLength(String(value ?? ''), 'utf8');
  }
}

export function redactMcpValue<T>(value: T, policy: McpServerPolicy): T {
  const { keyMatchers, patternMatchers } = buildRedactionMatchers(policy);

  function redact(valueToRedact: unknown, depth = 0, key?: string): unknown {
    if (depth > 6) {
      return '[Redacted]';
    }

    if (typeof valueToRedact === 'string') {
      if (
        (key && keyMatchers.some((matcher) => key.toLowerCase().includes(matcher))) ||
        patternMatchers.some((pattern) => pattern.test(valueToRedact))
      ) {
        return '[Redacted]';
      }

      return valueToRedact;
    }

    if (Array.isArray(valueToRedact)) {
      return valueToRedact.map((entry) => redact(entry, depth + 1));
    }

    if (valueToRedact && typeof valueToRedact === 'object') {
      const next: Record<string, unknown> = {};

      for (const [nextKey, nextValue] of Object.entries(valueToRedact as Record<string, unknown>)) {
        const shouldRedactKey =
          keyMatchers.some((matcher) => nextKey.toLowerCase().includes(matcher)) ||
          patternMatchers.some((pattern) => pattern.test(nextKey));
        next[nextKey] = shouldRedactKey ? '[Redacted]' : redact(nextValue, depth + 1, nextKey);
      }

      return next;
    }

    return valueToRedact;
  }

  return redact(value) as T;
}

export function serializeMcpPreview(value: unknown, policy: McpServerPolicy, maxBytes = 1_024) {
  const redacted = redactMcpValue(value, policy);

  try {
    const serialized = JSON.stringify(redacted);
    if (!serialized) {
      return '';
    }

    if (Buffer.byteLength(serialized, 'utf8') <= maxBytes) {
      return serialized;
    }

    return `${serialized.slice(0, maxBytes)}…`;
  } catch {
    const fallback = String(redacted ?? '');
    return fallback.length <= maxBytes ? fallback : `${fallback.slice(0, maxBytes)}…`;
  }
}

