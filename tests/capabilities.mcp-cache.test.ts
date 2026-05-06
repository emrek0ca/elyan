import { describe, expect, it, vi } from 'vitest';

vi.mock('@/core/mcp', async () => {
  const actual = await vi.importActual<typeof import('@/core/mcp')>('@/core/mcp');
  type McpServerConfig = import('@/core/mcp').McpServerConfig;

  const serverConfig: McpServerConfig = {
    id: 'mock-mcp',
    transport: 'stdio',
    command: 'node',
    args: [],
    enabled: true,
    connectTimeoutMs: 5_000,
    requestTimeoutMs: 10_000,
    shutdownTimeoutMs: 2_000,
    disabledToolNames: [],
  };

  let instanceCount = 0;

  class MockMcpToolRegistry {
    private readonly instanceId: number;

    constructor(private readonly configs: McpServerConfig[]) {
      void this.configs;
      this.instanceId = ++instanceCount;
    }

    async listTools() {
      if (this.instanceId === 2) {
        throw new Error('MCP offline');
      }

      return [
        {
          id: 'mock-mcp::echo',
          title: 'Echo',
          description: 'Echo text back.',
          library: 'test',
          timeoutMs: 1_000,
          enabled: true,
          source: {
            kind: 'mcp' as const,
            serverId: 'mock-mcp',
            transport: 'stdio' as const,
          },
          toolName: 'echo',
        },
      ];
    }

    async listResources() {
      if (this.instanceId === 2) {
        throw new Error('MCP offline');
      }

      return [
        {
          uri: 'mock://resource',
          name: 'resource',
          title: 'Resource',
          description: 'Cached resource.',
          enabled: true,
          source: {
            kind: 'mcp' as const,
            serverId: 'mock-mcp',
            transport: 'stdio' as const,
          },
        },
      ];
    }

    async listResourceTemplates() {
      if (this.instanceId === 2) {
        throw new Error('MCP offline');
      }

      return [
        {
          uriTemplate: 'mock://resource/{id}',
          name: 'resource-template',
          title: 'Resource template',
          description: 'Cached resource template.',
          enabled: true,
          source: {
            kind: 'mcp' as const,
            serverId: 'mock-mcp',
            transport: 'stdio' as const,
          },
        },
      ];
    }

    async listPrompts() {
      if (this.instanceId === 2) {
        throw new Error('MCP offline');
      }

      return [
        {
          name: 'summary-template',
          title: 'Summary template',
          description: 'Cached prompt.',
          arguments: [],
          enabled: true,
          source: {
            kind: 'mcp' as const,
            serverId: 'mock-mcp',
            transport: 'stdio' as const,
          },
        },
      ];
    }

    listServers() {
      return [
        actual.normalizeMcpServerManifest(serverConfig, {
          state: 'reachable',
          stateReason: 'reachable',
          lastCheckedAt: '2026-04-24T00:00:00.000Z',
        }),
      ];
    }

    async close() {
      return undefined;
    }
  }

  return {
    ...actual,
    readMcpServerConfigs: () => [serverConfig],
    McpToolRegistry: MockMcpToolRegistry,
  };
});

import { CapabilityAuditTrail, CapabilityRegistry } from '@/core/capabilities';

describe('MCP bridge cache', () => {
  it('reuses the last known good MCP snapshot when live discovery fails', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());

    const first = await registry.execute('mcp_bridge', {
      includeManifest: true,
    });

    const second = await registry.execute('mcp_bridge', {
      includeManifest: true,
    });

    expect(first.discovery.cached).toBe(false);
    expect(first.discovery.status).toBe('ready');
    expect(first.mcpServers.some((server) => server.id === 'mock-mcp')).toBe(true);
    expect(second.discovery.cached).toBe(true);
    expect(second.discovery.status).toBe('degraded');
    expect(second.discovery.lastHealthyAt).toBeDefined();
    expect(second.mcpServers.some((server) => server.id === 'mock-mcp')).toBe(true);
    expect(second.mcpTools.some((tool) => tool.toolName === 'echo')).toBe(true);
    expect(second.mcpPrompts.some((prompt) => prompt.name === 'summary-template')).toBe(true);
  });
});
