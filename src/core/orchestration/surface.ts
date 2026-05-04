import {
  buildConfiguredMcpServerCatalog,
  buildLocalBridgeCatalog,
  buildLocalCapabilityCatalog,
  McpToolRegistry,
  readMcpServerConfigs,
  type McpPromptManifest,
  type McpResourceManifest,
  type McpResourceTemplateManifest,
  type McpServerManifest,
  type McpToolManifest,
  type ToolManifest,
} from '@/core/mcp';
import { capabilityRegistry } from '@/core/capabilities';
import { getBridgeToolManifest } from '@/core/capabilities/bridge-tools';

export type ExecutionSurfaceDiscoveryStatus = 'skipped' | 'ready' | 'degraded' | 'unavailable';

export type ExecutionSurfaceSnapshot = {
  local: {
    capabilities: ToolManifest[];
    bridgeTools: ToolManifest[];
  };
  mcp: {
    servers: McpServerManifest[];
    tools: McpToolManifest[];
    resources: McpResourceManifest[];
    resourceTemplates: McpResourceTemplateManifest[];
    prompts: McpPromptManifest[];
    discovery?: {
      attempted: boolean;
      status: ExecutionSurfaceDiscoveryStatus;
      error?: string;
    };
  };
};

function describeError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return 'MCP discovery failed';
}

export function buildExecutionSurfaceSnapshot(): ExecutionSurfaceSnapshot {
  const enabledCapabilities = capabilityRegistry.list();
  const bridgeEnabled = enabledCapabilities.some((capability) => capability.id === 'tool_bridge');
  const localCapabilities = buildLocalCapabilityCatalog(enabledCapabilities);
  const localBridgeTools = bridgeEnabled
    ? buildLocalBridgeCatalog(
        getBridgeToolManifest().map((tool) => ({
          ...tool,
          enabled: true,
        }))
      )
    : [];

  try {
    const servers = buildConfiguredMcpServerCatalog(readMcpServerConfigs());

    return {
      local: {
        capabilities: localCapabilities,
        bridgeTools: localBridgeTools,
      },
      mcp: {
        servers,
        tools: [],
        resources: [],
        resourceTemplates: [],
        prompts: [],
        discovery: {
          attempted: false,
          status: servers.length > 0 ? 'ready' : 'skipped',
        },
      },
    };
  } catch (error) {
    return {
      local: {
        capabilities: localCapabilities,
        bridgeTools: localBridgeTools,
      },
      mcp: {
        servers: [],
        tools: [],
        resources: [],
        resourceTemplates: [],
        prompts: [],
        discovery: {
          attempted: false,
          status: 'unavailable',
          error: describeError(error),
        },
      },
    };
  }
}

export async function refreshExecutionSurfaceWithLiveMcp(
  surface: ExecutionSurfaceSnapshot
): Promise<ExecutionSurfaceSnapshot> {
  if (surface.mcp.servers.length === 0) {
    return {
      ...surface,
      mcp: {
        ...surface.mcp,
        discovery: {
          attempted: false,
          status: surface.mcp.discovery?.status ?? 'skipped',
          error: surface.mcp.discovery?.error,
        },
      },
    };
  }

  let registry: McpToolRegistry | undefined;

  try {
    registry = new McpToolRegistry(readMcpServerConfigs());
    const [tools, resources, resourceTemplates, prompts] = await Promise.all([
      registry.listTools(),
      registry.listResources(),
      registry.listResourceTemplates(),
      registry.listPrompts(),
    ]);

    return {
      ...surface,
      mcp: {
        ...surface.mcp,
        tools,
        resources,
        resourceTemplates,
        prompts,
        discovery: {
          attempted: true,
          status: 'ready',
        },
      },
    };
  } catch (error) {
    return {
      ...surface,
      mcp: {
        ...surface.mcp,
        tools: [],
        resources: [],
        resourceTemplates: [],
        prompts: [],
        discovery: {
          attempted: true,
          status: 'degraded',
          error: describeError(error),
        },
      },
    };
  } finally {
    await registry?.close();
  }
}
