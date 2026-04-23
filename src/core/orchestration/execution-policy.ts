import type { SearchMode } from '@/types/search';
import type {
  ExecutionPolicy,
  ExecutionObjectKind,
  ExecutionTarget,
  IntentConfidence,
  ModelRoutingMode,
  TaskIntent,
  UncertaintyLevel,
} from './types';
import type { ExecutionSurfaceSnapshot } from './surface';

type ExecutionPolicyContext = {
  taskIntent: TaskIntent;
  routingMode: ModelRoutingMode;
  uncertainty: UncertaintyLevel;
  intentConfidence: IntentConfidence;
};

type ManifestLike = {
  id: string;
  title: string;
  description: string;
  enabled: boolean;
};

type McpCandidate = {
  kind: 'mcp_resource' | 'mcp_resource_template' | 'mcp_prompt' | 'mcp_tool';
  id: string;
  title: string;
  description: string;
  enabled: boolean;
  reason: string;
  explicitBoost: number;
};

function normalizeText(value: string) {
  return value.toLowerCase();
}

function extractUrls(query: string) {
  return query.match(/https?:\/\/[^\s)]+/gi) ?? [];
}

function hasKeyword(query: string, patterns: RegExp[]) {
  return patterns.some((pattern) => pattern.test(query));
}

function scoreText(haystack: string, needle: string) {
  const normalizedHaystack = normalizeText(haystack);
  const normalizedNeedle = normalizeText(needle);
  return normalizedHaystack.includes(normalizedNeedle) ? 1 : 0;
}

function scoreManifest(query: string, manifest: { id: string; title: string; description: string }) {
  const tokens = query
    .split(/[^a-z0-9]+/i)
    .map((token) => token.trim())
    .filter((token) => token.length >= 3);

  let score = 0;
  for (const token of tokens) {
    score += scoreText(manifest.id, token);
    score += scoreText(manifest.title, token);
    score += scoreText(manifest.description, token);
  }

  return score;
}

function toTarget(
  kind: ExecutionObjectKind,
  id: string | undefined,
  title: string | undefined,
  source: ExecutionTarget['source'],
  reason: string,
  requiresConfirmation = false
): ExecutionTarget {
  return {
    kind,
    id,
    title,
    source,
    reason,
    requiresConfirmation,
  };
}

function listEnabledLocalCandidates(surface: ExecutionSurfaceSnapshot): ManifestLike[] {
  return [...surface.local.capabilities, ...surface.local.bridgeTools].filter((manifest) => manifest.enabled);
}

function localKindFromManifestId(manifestId: string): ExecutionObjectKind {
  if (manifestId === 'web_read_dynamic') {
    return 'browser_read';
  }

  if (manifestId === 'browser_automation') {
    return 'browser_automation';
  }

  if (manifestId === 'web_crawl') {
    return 'crawl';
  }

  if (
    manifestId === 'tool_bridge' ||
    manifestId === 'math_exact' ||
    manifestId === 'math_decimal' ||
    manifestId === 'csv_parse' ||
    manifestId === 'csv_export' ||
    manifestId === 'chart_generate'
  ) {
    return 'local_bridge_tool';
  }

  return 'local_capability';
}

function selectBestLocalTarget(query: string, surface: ExecutionSurfaceSnapshot): ExecutionTarget | undefined {
  const localCandidates = listEnabledLocalCandidates(surface);
  let best: { score: number; target: ExecutionTarget } | undefined;

  for (const manifest of localCandidates) {
    if (manifest.id === 'mcp_bridge') {
      continue;
    }

    const score = scoreManifest(query, manifest);
    if (score === 0) {
      continue;
    }

    const kind = localKindFromManifestId(manifest.id);
    const target = toTarget(
      kind,
      manifest.id,
      manifest.title,
      'local',
      `Matched local capability: ${manifest.title}`,
      kind === 'browser_automation'
    );

    if (!best || score > best.score) {
      best = { score, target };
    }
  }

  return best?.target;
}

function findLocalTargetById(surface: ExecutionSurfaceSnapshot, capabilityId: string, kind?: ExecutionObjectKind) {
  const manifest = listEnabledLocalCandidates(surface).find((entry) => entry.id === capabilityId);

  if (!manifest) {
    return undefined;
  }

  const resolvedKind = kind ?? localKindFromManifestId(manifest.id);

  return toTarget(
    resolvedKind,
    manifest.id,
    manifest.title,
    'local',
    `Matched local capability: ${manifest.title}`,
    resolvedKind === 'browser_automation'
  );
}

function shouldReadBrowser(query: string, urls: string[]) {
  return (
    urls.length > 0 &&
    hasKeyword(query, [
      /\b(read|inspect|summarize|summarise|explain|what does|what is on|render|view)\b/i,
      /\b(page|website|site|tab|article|document)\b/i,
    ])
  );
}

function shouldAutomateBrowser(query: string, urls: string[]) {
  return (
    urls.length > 0 &&
    hasKeyword(query, [
      /\b(click|fill|type|submit|open|navigate|log in|login|sign in|checkout|purchase)\b/i,
    ])
  );
}

function shouldCrawl(query: string, urls: string[]) {
  return (
    urls.length > 0 &&
    (urls.length > 1 ||
      hasKeyword(query, [
        /\b(crawl|crawl all|site map|site-wide|all pages|every page|links|site structure|spider)\b/i,
      ]))
  );
}

function shouldUseLocalBridge(query: string) {
  return hasKeyword(query, [
    /\b(calculate|math|sum|subtract|multiply|divide|percentage|ratio|decimal|precision)\b/i,
    /\b(csv|table|chart|plot|graph|spreadsheet)\b/i,
  ]);
}

function buildExplicitLocalTarget(
  query: string,
  surface: ExecutionSurfaceSnapshot,
  urls: string[]
): ExecutionTarget | undefined {
  if (shouldAutomateBrowser(query, urls)) {
    return findLocalTargetById(surface, 'browser_automation', 'browser_automation');
  }

  if (shouldCrawl(query, urls)) {
    return findLocalTargetById(surface, 'web_crawl', 'crawl');
  }

  if (shouldReadBrowser(query, urls)) {
    return findLocalTargetById(surface, 'web_read_dynamic', 'browser_read');
  }

  if (hasKeyword(query, [/\b(pdf|portable document format)\b/i])) {
    return findLocalTargetById(surface, 'pdf_extract', 'local_capability');
  }

  if (hasKeyword(query, [/\b(docx|word document|word file)\b/i])) {
    return findLocalTargetById(surface, 'docx_read', 'local_capability');
  }

  if (hasKeyword(query, [/\b(chart|plot|graph|visuali[sz]e)\b/i])) {
    return findLocalTargetById(surface, 'chart_generate', 'local_bridge_tool');
  }

  if (hasKeyword(query, [/\bcsv\b/i])) {
    if (hasKeyword(query, [/\b(export|write|save|serialize|serialise)\b/i])) {
      return findLocalTargetById(surface, 'csv_export', 'local_bridge_tool');
    }

    return findLocalTargetById(surface, 'csv_parse', 'local_bridge_tool');
  }

  if (hasKeyword(query, [/\b(decimal|precision)\b/i])) {
    return findLocalTargetById(surface, 'math_decimal', 'local_bridge_tool');
  }

  if (hasKeyword(query, [/\b(calculate|math|sum|subtract|multiply|divide|percentage|ratio)\b/i])) {
    return findLocalTargetById(surface, 'math_exact', 'local_bridge_tool');
  }

  return undefined;
}

function shouldUseMcp(query: string, surface: ExecutionSurfaceSnapshot, context: ExecutionPolicyContext) {
  if (surface.mcp.servers.length === 0) {
    return false;
  }

  return (
    context.taskIntent === 'personal_workflow' ||
    hasKeyword(query, [
      /\b(mcp|integration|prompt|resource|template|tool|connect|connected app|workspace)\b/i,
      /\b(slack|notion|calendar|gmail|drive|jira|linear|github)\b/i,
    ])
  );
}

function selectBestMcpTarget(query: string, surface: ExecutionSurfaceSnapshot): ExecutionTarget | undefined {
  const wantsPrompt = hasKeyword(query, [/\b(prompt|workflow|instruction)\b/i]);
  const wantsResource = hasKeyword(query, [/\b(resource|dataset|context|file|knowledge|reference)\b/i]);
  const wantsTemplate = hasKeyword(query, [/\b(template|uri template|parameterized)\b/i]);
  const wantsTool = hasKeyword(query, [/\b(tool|action|execute|run|call|trigger)\b/i]);

  const candidates: McpCandidate[] = [
    ...surface.mcp.prompts.map((entry) => ({
      kind: 'mcp_prompt' as const,
      id: entry.name,
      title: entry.title ?? entry.name,
      description: entry.description ?? entry.name,
      enabled: entry.enabled,
      reason: `Matched MCP prompt: ${entry.name}`,
      explicitBoost: wantsPrompt ? 3 : 0,
    })),
    ...surface.mcp.resources.map((entry) => ({
      kind: 'mcp_resource' as const,
      id: entry.uri,
      title: entry.title ?? entry.name,
      description: entry.description ?? entry.name,
      enabled: entry.enabled,
      reason: `Matched MCP resource: ${entry.name}`,
      explicitBoost: wantsResource ? 3 : 0,
    })),
    ...surface.mcp.resourceTemplates.map((entry) => ({
      kind: 'mcp_resource_template' as const,
      id: entry.uriTemplate,
      title: entry.title ?? entry.name,
      description: entry.description ?? entry.name,
      enabled: entry.enabled,
      reason: `Matched MCP resource template: ${entry.name}`,
      explicitBoost: wantsTemplate ? 3 : 0,
    })),
    ...surface.mcp.tools.map((entry) => ({
      kind: 'mcp_tool' as const,
      id: entry.id,
      title: entry.title,
      description: entry.description,
      enabled: entry.enabled,
      reason: `Matched MCP tool: ${entry.title}`,
      explicitBoost: wantsTool ? 3 : 0,
    })),
  ].filter((entry) => entry.enabled);

  let best: { score: number; target: ExecutionTarget } | undefined;

  for (const manifest of candidates) {
    const score = manifest.explicitBoost + scoreManifest(query, manifest);
    if (score === 0) {
      continue;
    }

    const target = toTarget(manifest.kind, manifest.id, manifest.title, 'mcp', manifest.reason);

    if (!best || score > best.score) {
      best = { score, target };
    }
  }

  return best?.target;
}

function dedupeCandidates(candidates: ExecutionTarget[]) {
  const seen = new Set<string>();
  const deduped: ExecutionTarget[] = [];

  for (const candidate of candidates) {
    const key = [candidate.kind, candidate.id ?? '', candidate.source].join('::');
    if (seen.has(key)) {
      continue;
    }

    seen.add(key);
    deduped.push(candidate);
  }

  return deduped;
}

function shouldRetrieveForPolicy(
  mode: SearchMode,
  primary: ExecutionTarget,
  context: ExecutionPolicyContext
) {
  if (primary.kind !== 'direct_answer') {
    return false;
  }

  return (
    mode === 'research' ||
    context.taskIntent === 'research' ||
    context.taskIntent === 'comparison' ||
    context.uncertainty !== 'low'
  );
}

export function buildExecutionPolicy(
  query: string,
  mode: SearchMode,
  surface: ExecutionSurfaceSnapshot,
  context: ExecutionPolicyContext
): ExecutionPolicy {
  const urls = extractUrls(query);
  const useMcp = shouldUseMcp(query, surface, context);
  const explicitLocalTarget = buildExplicitLocalTarget(query, surface, urls);
  const localTarget = explicitLocalTarget ?? selectBestLocalTarget(query, surface);
  const mcpTarget = useMcp ? selectBestMcpTarget(query, surface) : undefined;
  const useBrowserRead = shouldReadBrowser(query, urls);
  const useBrowserAutomation = shouldAutomateBrowser(query, urls);
  const useCrawl = shouldCrawl(query, urls);
  const useLocalBridge = shouldUseLocalBridge(query);
  const mcpDiscoveryAttempted = surface.mcp.discovery?.attempted === true;

  const candidates = dedupeCandidates(
    [
      localTarget,
      useLocalBridge
        ? findLocalTargetById(surface, 'tool_bridge', 'local_bridge_tool') ??
          toTarget(
            'local_bridge_tool',
            'tool_bridge',
            'Tool Bridge',
            'local',
            'Deterministic local tools can answer this request.'
          )
        : undefined,
      mcpTarget,
      useBrowserRead
        ? toTarget('browser_read', urls[0], urls[0], 'local', 'The URL should be read with Playwright.')
        : undefined,
      useBrowserAutomation
        ? toTarget(
            'browser_automation',
            urls[0],
            urls[0],
            'local',
            'The URL needs controlled browser interaction.',
            true
          )
        : undefined,
      useCrawl
        ? toTarget('crawl', urls[0], urls[0], 'local', 'The request needs bounded multi-page crawl coverage.')
        : undefined,
    ].filter((candidate): candidate is ExecutionTarget => Boolean(candidate))
  );

  const primary =
    candidates[0] ??
    toTarget(
      'direct_answer',
      undefined,
      'Direct answer',
      'none',
      'No capability path is clearly better than a direct answer.'
    );
  const shouldDiscoverMcp = useMcp && !mcpTarget && surface.mcp.servers.length > 0 && !mcpDiscoveryAttempted;
  const shouldRetrieve = shouldRetrieveForPolicy(mode, primary, context);
  const requiresConfirmation = candidates.some((candidate) => candidate.requiresConfirmation);
  const shouldEscalateModel =
    context.uncertainty === 'high' || mode === 'research' || context.taskIntent === 'comparison';
  const fallbackReason =
    primary.kind === 'direct_answer'
      ? shouldDiscoverMcp
        ? 'A live MCP lookup is needed before Elyan can choose a concrete prompt, resource, or tool.'
        : useMcp && mcpDiscoveryAttempted
          ? 'MCP discovery finished without a prompt, resource, template, or tool that matched the request strongly enough.'
          : 'No local, browser, crawl, or MCP path matched the request strongly enough, so Elyan stays on the direct-answer path.'
      : undefined;

  return {
    preferredOrder: [
      ...new Set([
        ...(localTarget ? [localTarget.kind] : []),
        ...(useLocalBridge ? ['local_bridge_tool'] : []),
        ...(mcpTarget
          ? [mcpTarget.kind]
          : shouldDiscoverMcp
            ? ['mcp_prompt', 'mcp_resource', 'mcp_resource_template', 'mcp_tool']
            : []),
        ...(useBrowserRead ? ['browser_read'] : []),
        ...(useBrowserAutomation ? ['browser_automation'] : []),
        ...(useCrawl ? ['crawl'] : []),
        'direct_answer',
      ]),
    ] as ExecutionObjectKind[],
    primary,
    candidates,
    shouldRetrieve,
    shouldDiscoverMcp,
    shouldEscalateModel,
    requiresConfirmation,
    decisionSummary:
      primary.kind === 'direct_answer'
        ? 'Primary path: direct answer.'
        : `Primary path: ${primary.kind}${primary.title ? ` via ${primary.title}` : ''}.`,
    fallbackReason,
    notes: [
      useBrowserRead ? 'Browser read path was selected for rendered-page content.' : 'Browser read was not needed.',
      useBrowserAutomation
        ? 'Browser automation requires explicit user intent and confirmation.'
        : 'Browser automation was not needed.',
      useCrawl ? 'Crawl path was selected for bounded multi-page coverage.' : 'Crawl was not needed.',
      shouldRetrieve
        ? 'Search retrieval remains enabled because the answer still benefits from external evidence.'
        : 'Search retrieval is skipped because a deterministic local, browser, crawl, or MCP path already covers the request.',
      shouldDiscoverMcp
        ? 'Live MCP discovery is required before selecting a concrete MCP object.'
        : useMcp && mcpTarget
          ? `MCP target selected: ${mcpTarget.title ?? mcpTarget.id}.`
          : useMcp && mcpDiscoveryAttempted
            ? `MCP discovery ${surface.mcp.discovery?.status ?? 'completed'}, but no concrete target matched.`
            : 'MCP discovery is not required.',
      fallbackReason ?? 'A concrete execution path was selected.',
    ],
  };
}
