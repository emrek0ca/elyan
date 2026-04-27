import { buildLocalCapabilityCatalog, buildLocalBridgeCatalog } from '@/core/mcp';
import { getBridgeToolManifest } from '@/core/capabilities/bridge-tools';
import { buildSkillDirectorySnapshot, type SkillDirectorySnapshot } from '@/core/skills';
import { capabilityRegistry } from './registry';
import { listCapabilityLibraryStrategies, type CapabilityLibraryStrategy } from './library-strategy';
import type { McpBridgeOutput } from './bridge';
import {
  buildCapabilityDirectoryEntry,
  buildCapabilityProfileGuide,
  listCapabilityProfileGuides,
} from './profiles';
import type {
  CapabilityApprovalLevel,
  CapabilityCategory,
  CapabilityDirectoryEntry,
  CapabilityDomainSnapshot,
  CapabilitySource,
} from './types';

const capabilityCategoryOrder: CapabilityCategory[] = [
  'documents',
  'research',
  'browser',
  'desktop',
  'ops',
  'memory',
  'calculation',
  'dev',
  'comms',
  'general',
];

function countBy<T extends string>(items: T[]) {
  return items.reduce<Record<T, number>>((accumulator, item) => {
    accumulator[item] = (accumulator[item] ?? 0) + 1;
    return accumulator;
  }, {} as Record<T, number>);
}

function buildDomainSnapshot(entries: CapabilityDirectoryEntry[]): CapabilityDomainSnapshot[] {
  return capabilityCategoryOrder
    .map((category) => {
      const domainEntries = entries.filter((entry) => entry.profile.category === category);
      if (domainEntries.length === 0) {
        return null;
      }

      const guide = buildCapabilityProfileGuide(category);
      const riskCounts = countBy(domainEntries.map((entry) => entry.profile.riskLevel));
      const approvalCounts = countBy(domainEntries.map((entry) => entry.profile.approvalLevel));
      const sourceCounts = countBy(domainEntries.map((entry) => entry.source));
      const libraries = [...new Set(domainEntries.map((entry) => entry.library))].sort();

      return {
        category,
        title: guide.title,
        summary: guide.summary,
        capabilityIds: domainEntries.map((entry) => entry.id),
        libraries,
        capabilityCount: domainEntries.length,
        enabledCapabilityCount: domainEntries.filter((entry) => entry.enabled).length,
        riskLevelCounts: {
          low: riskCounts.low ?? 0,
          medium: riskCounts.medium ?? 0,
          high: riskCounts.high ?? 0,
          critical: riskCounts.critical ?? 0,
        },
        approvalLevelCounts: {
          AUTO: approvalCounts.AUTO ?? 0,
          CONFIRM: approvalCounts.CONFIRM ?? 0,
          SCREEN: approvalCounts.SCREEN ?? 0,
          TWO_FA: approvalCounts.TWO_FA ?? 0,
        },
        sourceCounts: {
          local_module: sourceCounts.local_module ?? 0,
          local_bridge_tool: sourceCounts.local_bridge_tool ?? 0,
          mcp_surface: sourceCounts.mcp_surface ?? 0,
          browser_surface: sourceCounts.browser_surface ?? 0,
          direct: sourceCounts.direct ?? 0,
        },
      } satisfies CapabilityDomainSnapshot;
    })
    .filter((entry): entry is CapabilityDomainSnapshot => entry !== null);
}

function buildApprovalMatrix(entries: CapabilityDirectoryEntry[]) {
  const grouped = countBy(entries.map((entry) => entry.profile.approvalLevel));

  return [
    {
      level: 'AUTO' as CapabilityApprovalLevel,
      title: 'Auto',
      summary: 'Safe, deterministic work that should execute without a prompt.',
      capabilityCount: grouped.AUTO ?? 0,
      enabledCapabilityCount: entries.filter((entry) => entry.enabled && entry.profile.approvalLevel === 'AUTO').length,
    },
    {
      level: 'CONFIRM' as CapabilityApprovalLevel,
      title: 'Confirm',
      summary: 'Bounded actions that should be acknowledged before execution.',
      capabilityCount: grouped.CONFIRM ?? 0,
      enabledCapabilityCount: entries.filter((entry) => entry.enabled && entry.profile.approvalLevel === 'CONFIRM').length,
    },
    {
      level: 'SCREEN' as CapabilityApprovalLevel,
      title: 'Screen',
      summary: 'Visible or stateful actions that need preview and human review.',
      capabilityCount: grouped.SCREEN ?? 0,
      enabledCapabilityCount: entries.filter((entry) => entry.enabled && entry.profile.approvalLevel === 'SCREEN').length,
    },
    {
      level: 'TWO_FA' as CapabilityApprovalLevel,
      title: '2FA',
      summary: 'High-risk operations that must pass elevated approval gates.',
      capabilityCount: grouped.TWO_FA ?? 0,
      enabledCapabilityCount: entries.filter((entry) => entry.enabled && entry.profile.approvalLevel === 'TWO_FA').length,
    },
  ];
}

function countMcpServerStates(mcp: McpBridgeOutput) {
  const counts = {
    configured: 0,
    reachable: 0,
    degraded: 0,
    blocked: 0,
    disabled: 0,
  };

  for (const server of mcp.mcpServers) {
    const state = server.state ?? (server.enabled ? 'configured' : 'disabled');

    if (state === 'configured') {
      counts.configured += 1;
    } else if (state === 'reachable') {
      counts.reachable += 1;
    } else if (state === 'degraded') {
      counts.degraded += 1;
    } else if (state === 'blocked') {
      counts.blocked += 1;
    } else {
      counts.disabled += 1;
    }
  }

  return counts;
}

function buildCapabilityEntries() {
  return capabilityRegistry.list({ includeDisabled: true }).map((capability) =>
    buildCapabilityDirectoryEntry(capability)
  );
}

function buildDirectoryFilters(entries: CapabilityDirectoryEntry[]) {
  const sources = [...new Set(entries.map((entry) => entry.source))].sort() as CapabilitySource[];
  const domains = [...new Set(entries.map((entry) => entry.profile.category))].sort();
  const approvals = [...new Set(entries.map((entry) => entry.profile.approvalLevel))].sort() as CapabilityApprovalLevel[];
  const riskLevels = [...new Set(entries.map((entry) => entry.profile.riskLevel))].sort();
  const libraries = [...new Set(entries.map((entry) => entry.library))].sort();

  return {
    domains,
    approvals,
    riskLevels,
    sources,
    libraries,
  };
}

export type CapabilityDirectorySnapshot = {
  local: {
    capabilities: ReturnType<typeof buildLocalCapabilityCatalog>;
    bridgeTools: ReturnType<typeof buildLocalBridgeCatalog>;
  };
  capabilities: CapabilityDirectoryEntry[];
  domains: CapabilityDomainSnapshot[];
  approvalMatrix: Array<{
    level: CapabilityApprovalLevel;
    title: string;
    summary: string;
    capabilityCount: number;
    enabledCapabilityCount: number;
  }>;
  skills: SkillDirectorySnapshot;
  mcp: McpBridgeOutput;
  mcpStatus: 'ready' | 'unavailable';
  mcpError?: string;
  discovery: {
    includeLiveMcp: boolean;
    mcp: McpBridgeOutput['discovery'];
    skills: SkillDirectorySnapshot['discovery'];
  };
  selectionGuide: Array<{
    kind: 'local_module' | 'local_bridge_tool' | 'mcp_resource' | 'mcp_prompt' | 'mcp_tool' | 'browser' | 'crawl' | 'direct_answer';
    title: string;
    when: string;
    why: string;
  }>;
  capabilityGuides: ReturnType<typeof listCapabilityProfileGuides>;
  libraryStrategies: CapabilityLibraryStrategy[];
  filters: {
    domains: CapabilityCategory[];
    approvals: CapabilityApprovalLevel[];
    riskLevels: Array<'low' | 'medium' | 'high' | 'critical'>;
    sources: CapabilitySource[];
    libraries: string[];
  };
  recentAudits: ReturnType<typeof capabilityRegistry.getAuditTrail>;
  summary: {
    localCapabilityCount: number;
    enabledLocalCapabilityCount: number;
    bridgeToolCount: number;
    enabledBridgeToolCount: number;
    browserEnabled: boolean;
    crawlEnabled: boolean;
    skillCount: number;
    enabledSkillCount: number;
    installedSkillCount: number;
    mcpServerCount: number;
    mcpConfiguredServerCount: number;
    mcpReachableServerCount: number;
    mcpDegradedServerCount: number;
    mcpBlockedServerCount: number;
    mcpDisabledServerCount: number;
    mcpToolCount: number;
    mcpResourceCount: number;
    mcpPromptCount: number;
    categoryCount: number;
    libraryCount: number;
    autoApprovalCapabilityCount: number;
    confirmApprovalCapabilityCount: number;
    screenApprovalCapabilityCount: number;
    twoFaApprovalCapabilityCount: number;
    highRiskCapabilityCount: number;
    safeByDefaultCapabilityCount: number;
  };
};

export async function buildCapabilityDirectorySnapshot(includeLiveMcp = true): Promise<CapabilityDirectorySnapshot> {
  const localCapabilityList = capabilityRegistry.list({ includeDisabled: true });
  const localCapabilities = buildLocalCapabilityCatalog(localCapabilityList);
  const bridgeEnabled = localCapabilityList.some(
    (capability) => capability.id === 'tool_bridge' && capability.enabled
  );
  const skills = await buildSkillDirectorySnapshot(true);
  const localBridgeTools = buildLocalBridgeCatalog(
    getBridgeToolManifest().map((tool) => ({
      ...tool,
      enabled: bridgeEnabled,
    }))
  );
  const capabilities = buildCapabilityEntries();
  const domains = buildDomainSnapshot(capabilities);
  const approvalMatrix = buildApprovalMatrix(capabilities);
  const filters = buildDirectoryFilters(capabilities);
  const libraryStrategies = listCapabilityLibraryStrategies();
  const recentAudits = capabilityRegistry.getAuditTrail().slice(-12).reverse();

  let mcp: McpBridgeOutput;
  let mcpStatus: CapabilityDirectorySnapshot['mcpStatus'] = 'ready';
  let mcpError: string | undefined;

  try {
    mcp = (await capabilityRegistry.execute('mcp_bridge', {
      includeManifest: includeLiveMcp,
    })) as McpBridgeOutput;
    mcpStatus = mcp.discovery.status === 'unavailable' ? 'unavailable' : 'ready';
    mcpError = mcp.discovery.error;
  } catch (error) {
    mcpStatus = 'unavailable';
    mcpError = error instanceof Error ? error.message : 'MCP discovery failed';
      mcp = {
      tools: localBridgeTools as McpBridgeOutput['tools'],
      mcpServers: [],
      mcpTools: [],
      mcpResources: [],
      mcpResourceTemplates: [],
      mcpPrompts: [],
      aiSdkToolNames: [],
      discovery: {
        attempted: false,
        status: 'unavailable',
        error: mcpError,
        cached: false,
      },
    };
  }
  const mcpStateCounts = countMcpServerStates(mcp);

  return {
    local: {
      capabilities: localCapabilities,
      bridgeTools: localBridgeTools,
    },
    capabilities,
    domains,
    approvalMatrix,
    skills,
    mcp,
    mcpStatus,
    mcpError,
    discovery: {
      includeLiveMcp,
      mcp: mcp.discovery,
      skills: skills.discovery,
    },
    selectionGuide: [
      {
        kind: 'local_module',
        title: 'Local runtime module',
        when: 'The task can be solved on this machine with a built-in capability.',
        why: 'Fastest and most private path. Prefer local modules for files, documents, charts, calculations, and browser reads.',
      },
      {
        kind: 'local_bridge_tool',
        title: 'Local bridge tool',
        when: 'The task needs a deterministic helper like math, CSV parsing, CSV export, or chart rendering.',
        why: 'Keeps structured work inside the local runtime without external hops.',
      },
      {
        kind: 'mcp_resource',
        title: 'MCP resource',
        when: 'The task needs structured external context such as a file, page, dataset, or workspace object.',
        why: 'Resources are read-only context surfaces and should be preferred before tool execution when possible.',
      },
      {
        kind: 'mcp_prompt',
        title: 'MCP prompt',
        when: 'The task benefits from a server-provided prompt or workflow template.',
        why: 'Prompts let remote systems provide curated instruction without hardcoding logic in Elyan.',
      },
      {
        kind: 'mcp_tool',
        title: 'MCP tool',
        when: 'The task requires an external action against a connected app or service.',
        why: 'Tools are the correct MCP surface for real actions and should stay auditable and explicit.',
      },
      {
        kind: 'browser',
        title: 'Playwright browser',
        when: 'The task requires rendered page inspection or controlled browser interaction.',
        why: 'Use browser automation only when the page is dynamic or cannot be answered from static context.',
      },
      {
        kind: 'crawl',
        title: 'Crawlee crawl',
        when: 'The task requires bounded multi-page retrieval across a site or section.',
        why: 'Crawling should stay narrow, bounded, and explicit rather than turning into broad scraping.',
      },
      {
        kind: 'direct_answer',
        title: 'Direct answer',
        when: 'No external capability improves the answer.',
        why: 'Avoid unnecessary tool use when the model can respond directly and clearly.',
      },
    ],
    capabilityGuides: listCapabilityProfileGuides(),
    libraryStrategies,
    filters,
    recentAudits,
    summary: {
      localCapabilityCount: localCapabilities.length,
      enabledLocalCapabilityCount: localCapabilities.filter((capability) => capability.enabled).length,
      bridgeToolCount: localBridgeTools.length,
      enabledBridgeToolCount: localBridgeTools.filter((tool) => tool.enabled).length,
      browserEnabled: localCapabilities.some((capability) => capability.id === 'web_read_dynamic' && capability.enabled),
      crawlEnabled: localCapabilities.some((capability) => capability.id === 'web_crawl' && capability.enabled),
      skillCount: skills.summary.builtInSkillCount,
      enabledSkillCount: skills.summary.enabledBuiltInSkillCount,
      installedSkillCount: skills.summary.installedSkillCount,
      mcpServerCount: mcp.mcpServers.length,
      mcpConfiguredServerCount: mcpStateCounts.configured,
      mcpReachableServerCount: mcpStateCounts.reachable,
      mcpDegradedServerCount: mcpStateCounts.degraded,
      mcpBlockedServerCount: mcpStateCounts.blocked,
      mcpDisabledServerCount: mcpStateCounts.disabled,
      mcpToolCount: mcp.mcpTools.length,
      mcpResourceCount: mcp.mcpResources.length + mcp.mcpResourceTemplates.length,
      mcpPromptCount: mcp.mcpPrompts.length,
      categoryCount: domains.length,
      autoApprovalCapabilityCount: approvalMatrix.find((entry) => entry.level === 'AUTO')?.capabilityCount ?? 0,
      confirmApprovalCapabilityCount: approvalMatrix.find((entry) => entry.level === 'CONFIRM')?.capabilityCount ?? 0,
      screenApprovalCapabilityCount: approvalMatrix.find((entry) => entry.level === 'SCREEN')?.capabilityCount ?? 0,
      twoFaApprovalCapabilityCount: approvalMatrix.find((entry) => entry.level === 'TWO_FA')?.capabilityCount ?? 0,
      highRiskCapabilityCount: capabilities.filter((entry) => ['high', 'critical'].includes(entry.profile.riskLevel)).length,
      safeByDefaultCapabilityCount: capabilities.filter((entry) => entry.profile.safeByDefault).length,
      libraryCount: filters.libraries.length,
    },
  };
}
