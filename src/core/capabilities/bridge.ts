import { z } from 'zod';
import {
  executeBridgeTool,
  getBridgeToolExecutionTimeoutMs,
  getBridgeToolManifest,
  type BridgeToolId,
} from './bridge-tools';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';
import {
  buildConfiguredMcpServerCatalog,
  buildLocalBridgeCatalog,
  McpToolRegistry,
  readMcpServerConfigs,
  mcpServerManifestSchema,
} from '@/core/mcp';
import {
  mcpPromptManifestSchema,
  mcpResourceManifestSchema,
  mcpResourceTemplateManifestSchema,
  mcpToolManifestSchema,
} from '@/core/mcp';

class ToolBridgeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ToolBridgeError';
  }
}

const bridgeToolIdSchema = z.enum([
  'math_exact',
  'math_decimal',
  'csv_parse',
  'csv_export',
  'chart_generate',
  'optimization_solve',
]);

const toolBridgeInputSchema = z.object({
  toolId: bridgeToolIdSchema,
  input: z.unknown(),
});

const toolBridgeOutputSchema = z.object({
  toolId: bridgeToolIdSchema,
  result: z.unknown(),
});

const mcpBridgeInputSchema = z.object({
  includeManifest: z.boolean().default(true),
});

const mcpBridgeOutputSchema = z.object({
  tools: z.array(
    z.object({
      id: z.string().min(1),
      title: z.string(),
      description: z.string(),
      library: z.string(),
      timeoutMs: z.number().int().positive(),
      enabled: z.boolean(),
      source: z.object({
        kind: z.literal('local'),
        scope: z.literal('bridge'),
      }),
    })
  ),
  mcpServers: z.array(mcpServerManifestSchema),
  mcpTools: z.array(mcpToolManifestSchema),
  mcpResources: z.array(mcpResourceManifestSchema),
  mcpResourceTemplates: z.array(mcpResourceTemplateManifestSchema),
  mcpPrompts: z.array(mcpPromptManifestSchema),
  aiSdkToolNames: z.array(z.string()),
  discovery: z.object({
    attempted: z.boolean(),
    status: z.enum(['skipped', 'ready', 'degraded', 'unavailable']),
    error: z.string().optional(),
    cached: z.boolean().default(false),
    lastHealthyAt: z.string().optional(),
  }),
});

export type McpBridgeOutput = z.output<typeof mcpBridgeOutputSchema>;

type CachedMcpBridgeSnapshot = Omit<McpBridgeOutput, 'discovery'> & {
  discovery: {
    attempted: boolean;
    status: z.output<typeof mcpBridgeOutputSchema>['discovery']['status'];
    error?: string;
    cached: boolean;
    lastHealthyAt?: string;
  };
  capturedAt: string;
};

const mcpBridgeCache = new Map<string, CachedMcpBridgeSnapshot>();

function buildMcpBridgeCacheKey(serverConfigs: ReturnType<typeof readMcpServerConfigs>) {
  return JSON.stringify(
    serverConfigs.map((server) => ({
      id: server.id,
      transport: server.transport,
      enabled: server.enabled,
      endpoint: server.transport === 'streamable-http' ? server.url : undefined,
      command: server.transport === 'stdio' ? server.command : undefined,
      args: server.transport === 'stdio' ? server.args : undefined,
      disabledToolNames: server.disabledToolNames,
    }))
  );
}

export function getBridgeToolNames(): BridgeToolId[] {
  return getBridgeToolManifest().map((tool) => tool.id);
}

export function getAiSdkBridgeToolNames(): string[] {
  return getBridgeToolManifest().map((tool) => tool.id);
}

function describeError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return 'MCP discovery failed';
}

export const toolBridgeCapability: CapabilityDefinition<
  typeof toolBridgeInputSchema,
  typeof toolBridgeOutputSchema
> = {
  id: 'tool_bridge',
  title: 'Tool Bridge',
  description: 'Executes a bounded bridge tool with schema, timeout, and audit support.',
  library: 'ai',
  enabled: true,
  timeoutMs: getBridgeToolExecutionTimeoutMs(),
  inputSchema: toolBridgeInputSchema,
  outputSchema: toolBridgeOutputSchema,
  run: async (input: z.output<typeof toolBridgeInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    try {
      return {
        toolId: input.toolId,
        result: await executeBridgeTool(input.toolId, input.input),
      };
    } catch (error) {
      throw new ToolBridgeError(
        error instanceof Error ? error.message : `Unable to execute tool bridge operation: ${input.toolId}`
      );
    }
  },
};

export const mcpBridgeCapability: CapabilityDefinition<
  typeof mcpBridgeInputSchema,
  typeof mcpBridgeOutputSchema
> = {
  id: 'mcp_bridge',
  title: 'MCP Bridge',
  description:
    'Exposes machine-readable manifests for the local bridge surface and configured MCP tools, resources, and prompts.',
  library: 'ai',
  enabled: true,
  timeoutMs: 3_000,
  inputSchema: mcpBridgeInputSchema,
  outputSchema: mcpBridgeOutputSchema,
  run: async (input: z.output<typeof mcpBridgeInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    let serverConfigs = [] as ReturnType<typeof readMcpServerConfigs>;
    let configError: string | undefined;

    try {
      serverConfigs = readMcpServerConfigs();
    } catch (error) {
      configError = describeError(error);
    }

    const shouldDiscoverLiveSurface = input.includeManifest && configError === undefined && serverConfigs.length > 0;
    const liveRegistry = shouldDiscoverLiveSurface ? new McpToolRegistry(serverConfigs) : undefined;
    const cacheKey = buildMcpBridgeCacheKey(serverConfigs);
    const cachedSnapshot = mcpBridgeCache.get(cacheKey);

    try {
      const tools = (input.includeManifest
        ? buildLocalBridgeCatalog(
            getBridgeToolManifest().map((tool) => ({
              ...tool,
              enabled: true,
            }))
          )
        : []) as z.output<typeof mcpBridgeOutputSchema>['tools'];
      let mcpServers = input.includeManifest
        ? liveRegistry
          ? liveRegistry.listServers()
          : buildConfiguredMcpServerCatalog(serverConfigs)
        : [];
      let mcpTools: z.output<typeof mcpBridgeOutputSchema>['mcpTools'] = [];
      let mcpResources: z.output<typeof mcpBridgeOutputSchema>['mcpResources'] = [];
      let mcpResourceTemplates: z.output<typeof mcpBridgeOutputSchema>['mcpResourceTemplates'] = [];
      let mcpPrompts: z.output<typeof mcpBridgeOutputSchema>['mcpPrompts'] = [];
      let discoveryStatus: z.output<typeof mcpBridgeOutputSchema>['discovery']['status'] =
        input.includeManifest && serverConfigs.length > 0 ? 'ready' : 'skipped';
      let discoveryError = configError;
      let discoveryCached = false;
      let discoveryLastHealthyAt: string | undefined;

      if (input.includeManifest && liveRegistry) {
        try {
          [mcpTools, mcpResources, mcpResourceTemplates, mcpPrompts] = await Promise.all([
            liveRegistry.listTools(),
            liveRegistry.listResources(),
            liveRegistry.listResourceTemplates(),
            liveRegistry.listPrompts(),
          ]);
          mcpServers = liveRegistry.listServers();
          const capturedAt = new Date().toISOString();
          mcpBridgeCache.set(cacheKey, {
            tools,
            mcpServers,
            mcpTools,
            mcpResources,
            mcpResourceTemplates,
            mcpPrompts,
            aiSdkToolNames: getAiSdkBridgeToolNames(),
            discovery: {
              attempted: true,
              status: discoveryStatus,
              cached: false,
              lastHealthyAt: capturedAt,
            },
            capturedAt,
          });
        } catch (error) {
          if (cachedSnapshot) {
            discoveryStatus = 'degraded';
            discoveryError = `${describeError(error)}. Using last known good MCP snapshot.`;
            discoveryCached = true;
            discoveryLastHealthyAt = cachedSnapshot.capturedAt;

            return {
              ...cachedSnapshot,
              discovery: {
                attempted: true,
                status: discoveryStatus,
                error: discoveryError,
                cached: discoveryCached,
                lastHealthyAt: discoveryLastHealthyAt,
              },
            };
          }

          discoveryStatus = 'degraded';
          discoveryError = describeError(error);
        }
      } else if (configError) {
        discoveryStatus = 'unavailable';
      }

      return {
        tools,
        mcpServers,
        mcpTools,
        mcpResources,
        mcpResourceTemplates,
        mcpPrompts,
        aiSdkToolNames: getAiSdkBridgeToolNames(),
        discovery: {
          attempted: input.includeManifest && serverConfigs.length > 0,
          status: discoveryStatus,
          error: discoveryError,
          cached: discoveryCached,
          lastHealthyAt: discoveryLastHealthyAt,
        },
      };
    } finally {
      await liveRegistry?.close();
    }
  },
};
