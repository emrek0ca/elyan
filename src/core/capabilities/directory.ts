import { buildLocalCapabilityCatalog, buildLocalBridgeCatalog } from '@/core/mcp';
import { getBridgeToolManifest } from '@/core/capabilities/bridge-tools';
import { capabilityRegistry } from './registry';
import type { McpBridgeOutput } from './bridge';

export type CapabilityDirectorySnapshot = {
  local: {
    capabilities: ReturnType<typeof buildLocalCapabilityCatalog>;
    bridgeTools: ReturnType<typeof buildLocalBridgeCatalog>;
  };
  mcp: McpBridgeOutput;
  mcpStatus: 'ready' | 'unavailable';
  mcpError?: string;
  discovery: {
    includeLiveMcp: boolean;
    mcp: McpBridgeOutput['discovery'];
  };
  selectionGuide: Array<{
    kind: 'local_module' | 'local_bridge_tool' | 'mcp_resource' | 'mcp_prompt' | 'mcp_tool' | 'browser' | 'crawl' | 'direct_answer';
    title: string;
    when: string;
    why: string;
  }>;
  summary: {
    localCapabilityCount: number;
    enabledLocalCapabilityCount: number;
    bridgeToolCount: number;
    enabledBridgeToolCount: number;
    mcpServerCount: number;
    mcpToolCount: number;
    mcpResourceCount: number;
    mcpPromptCount: number;
  };
};

export async function buildCapabilityDirectorySnapshot(includeLiveMcp = true): Promise<CapabilityDirectorySnapshot> {
  const localCapabilityList = capabilityRegistry.list({ includeDisabled: true });
  const localCapabilities = buildLocalCapabilityCatalog(localCapabilityList);
  const bridgeEnabled = localCapabilityList.some(
    (capability) => capability.id === 'tool_bridge' && capability.enabled
  );
  const localBridgeTools = buildLocalBridgeCatalog(
    getBridgeToolManifest().map((tool) => ({
      ...tool,
      enabled: bridgeEnabled,
    }))
  );

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
      },
    };
  }

  return {
    local: {
      capabilities: localCapabilities,
      bridgeTools: localBridgeTools,
    },
    mcp,
    mcpStatus,
    mcpError,
    discovery: {
      includeLiveMcp,
      mcp: mcp.discovery,
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
    summary: {
      localCapabilityCount: localCapabilities.length,
      enabledLocalCapabilityCount: localCapabilities.filter((capability) => capability.enabled).length,
      bridgeToolCount: localBridgeTools.length,
      enabledBridgeToolCount: localBridgeTools.filter((tool) => tool.enabled).length,
      mcpServerCount: mcp.mcpServers.length,
      mcpToolCount: mcp.mcpTools.length,
      mcpResourceCount: mcp.mcpResources.length + mcp.mcpResourceTemplates.length,
      mcpPromptCount: mcp.mcpPrompts.length,
    },
  };
}
