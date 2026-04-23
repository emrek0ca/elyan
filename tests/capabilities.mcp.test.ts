import { describe, expect, it } from 'vitest';
import type { JSONRPCMessage } from '@modelcontextprotocol/sdk/types.js';
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js';
import {
  LiveMcpClient,
  McpAuditTrail,
  McpCancelledError,
  McpBlockedError,
  McpDisabledError,
  McpMalformedResponseError,
  McpTimeoutError,
  McpToolRegistry,
} from '@/core/mcp';
import type { McpServerConfig } from '@/core/mcp';

type MockTool = {
  name: string;
  title?: string;
  description?: string;
};

type MockScenario = {
  tools?: MockTool[];
  resources?: Array<{
    uri: string;
    name: string;
    title?: string;
    description?: string;
    mimeType?: string;
  }>;
  resourceTemplates?: Array<{
    uriTemplate: string;
    name: string;
    title?: string;
    description?: string;
    mimeType?: string;
  }>;
  prompts?: Array<{
    name: string;
    title?: string;
    description?: string;
    arguments?: Array<{
      name: string;
      description?: string;
      required?: boolean;
    }>;
  }>;
  listResult?: unknown;
  callResult?: unknown;
  listDelayMs?: number;
  callDelayMs?: number;
  initializeDelayMs?: number;
};

class MockMcpTransport implements Transport {
  onclose?: () => void;
  onerror?: (error: Error) => void;
  onmessage?: <T extends JSONRPCMessage>(message: T) => void;
  sessionId?: string;
  setProtocolVersion?: (version: string) => void;

  public closed = false;
  public started = false;
  public receivedMethods: string[] = [];

  constructor(private readonly scenario: MockScenario) {}

  async start() {
    this.started = true;
  }

  async send(message: JSONRPCMessage) {
    if (this.closed) {
      throw new Error('transport closed');
    }

    if (!('method' in message) || typeof message.id === 'undefined') {
      return;
    }

    this.receivedMethods.push(message.method);

    const respond = (result: unknown, delayMs = 0) => {
      setTimeout(() => {
        if (this.closed) {
          return;
        }

        this.onmessage?.({
          jsonrpc: '2.0',
          id: message.id,
          result,
        } as JSONRPCMessage);
      }, delayMs);
    };

    if (message.method === 'initialize') {
      respond(
        {
          protocolVersion: '2025-11-25',
          capabilities: {
            tools: {},
          },
          serverInfo: {
            name: 'Mock MCP',
            version: '1.0.0',
          },
        },
        this.scenario.initializeDelayMs
      );
      return;
    }

    if (message.method === 'notifications/initialized') {
      return;
    }

    if (message.method === 'tools/list') {
      respond(
        this.scenario.listResult ?? {
          tools: (this.scenario.tools ?? []).map((tool) => ({
            name: tool.name,
            title: tool.title,
            description: tool.description,
            inputSchema: {
              type: 'object',
              properties: {},
            },
          })),
        },
        this.scenario.listDelayMs
      );
      return;
    }

    if (message.method === 'resources/list') {
      respond({
        resources: (this.scenario.resources ?? []).map((resource) => ({
          uri: resource.uri,
          name: resource.name,
          title: resource.title,
          description: resource.description,
          mimeType: resource.mimeType,
        })),
      });
      return;
    }

    if (message.method === 'resources/templates/list') {
      respond({
        resourceTemplates: (this.scenario.resourceTemplates ?? []).map((template) => ({
          uriTemplate: template.uriTemplate,
          name: template.name,
          title: template.title,
          description: template.description,
          mimeType: template.mimeType,
        })),
      });
      return;
    }

    if (message.method === 'prompts/list') {
      respond({
        prompts: (this.scenario.prompts ?? []).map((prompt) => ({
          name: prompt.name,
          title: prompt.title,
          description: prompt.description,
          arguments: prompt.arguments,
        })),
      });
      return;
    }

    if (message.method === 'tools/call') {
      respond(
        this.scenario.callResult ?? {
          content: [{ type: 'text', text: 'ok' }],
          structuredContent: { ok: true },
        },
        this.scenario.callDelayMs
      );
    }
  }

  async close() {
    if (this.closed) {
      return;
    }

    this.closed = true;
    this.onclose?.();
  }
}

function createServerConfig(overrides: Partial<McpServerConfig> = {}): McpServerConfig {
  return {
    id: 'mock-server',
    transport: 'streamable-http',
    url: 'http://127.0.0.1:1234',
    enabled: true,
    connectTimeoutMs: 100,
    requestTimeoutMs: 100,
    shutdownTimeoutMs: 100,
    disabledToolNames: [],
    headers: {},
    ...overrides,
  };
}

describe('Live MCP support', () => {
  it('connects, lists tools, invokes tools, and closes cleanly', async () => {
    const transport = new MockMcpTransport({
      tools: [
        { name: 'echo', title: 'Echo', description: 'Returns input' },
      ],
    });
    const client = new LiveMcpClient(createServerConfig(), {
      transportFactory: () => transport,
    });

    const tools = await client.listTools();
    const result = await client.invokeTool('echo', { value: 'Elyan' });

    expect(transport.started).toBe(true);
    expect(transport.receivedMethods).toContain('initialize');
    expect(tools).toHaveLength(1);
    expect(tools[0]?.id).toBe('mock-server::echo');
    expect(result.isError).toBeUndefined();

    await client.close();
    await client.close();

    expect(transport.closed).toBe(true);
  });

  it('returns an empty tool list cleanly', async () => {
    const transport = new MockMcpTransport({ tools: [] });
    const client = new LiveMcpClient(createServerConfig(), {
      transportFactory: () => transport,
    });

    await expect(client.listTools()).resolves.toEqual([]);
    await client.close();
  });

  it('marks malformed tool lists as malformed responses', async () => {
    const transport = new MockMcpTransport({
      listResult: { tools: [{ name: 123 }] },
    });
    const client = new LiveMcpClient(createServerConfig(), {
      transportFactory: () => transport,
    });

    await expect(client.listTools()).rejects.toBeInstanceOf(McpMalformedResponseError);
    await client.close();
  });

  it('cancels slow requests without hanging', async () => {
    const transport = new MockMcpTransport({
      tools: [{ name: 'slow' }],
      listDelayMs: 100,
    });
    const client = new LiveMcpClient(createServerConfig({ requestTimeoutMs: 500 }), {
      transportFactory: () => transport,
    });
    const controller = new AbortController();

    const promise = client.listTools({ signal: controller.signal, timeoutMs: 500 });
    controller.abort();

    await expect(promise).rejects.toBeInstanceOf(McpCancelledError);
    await client.close();
  });

  it('applies request timeouts to tool calls', async () => {
    const transport = new MockMcpTransport({
      tools: [{ name: 'slow' }],
      callDelayMs: 100,
    });
    const client = new LiveMcpClient(createServerConfig({ requestTimeoutMs: 10 }), {
      transportFactory: () => transport,
    });

    await client.listTools();
    await expect(client.invokeTool('slow', { value: 1 })).rejects.toBeInstanceOf(McpTimeoutError);
    await client.close();
  });

  it('treats unavailable MCP servers as soft failures during catalog refresh', async () => {
    const registry = new McpToolRegistry(
      [createServerConfig()],
      new McpAuditTrail(),
      {
        transportFactory: () => {
          throw new Error('MCP offline');
        },
      }
    );

    await expect(registry.listTools()).resolves.toEqual([]);
    expect(registry.getAuditTrail()[0]?.status).toBe('error');
    await registry.close();
  });

  it('respects disable flags on live tool registry entries', async () => {
    const transport = new MockMcpTransport({
      tools: [{ name: 'skip' }, { name: 'keep' }],
    });
    const registry = new McpToolRegistry(
      [
        createServerConfig({
          disabledToolNames: ['skip'],
        }),
      ],
      new McpAuditTrail(),
      {
        transportFactory: () => transport,
      }
    );

    const tools = await registry.listTools();
    expect(tools.map((tool) => tool.toolName)).toEqual(['keep']);

    await expect(registry.invokeTool('mock-server::skip', {})).rejects.toBeInstanceOf(McpDisabledError);
    await registry.close();
  });

  it('blocks tools through server policy and keeps the hidden surface visible', async () => {
    const transport = new MockMcpTransport({
      tools: [{ name: 'echo', title: 'Echo', description: 'Returns input' }],
    });
    const client = new LiveMcpClient(
      createServerConfig({
        policy: {
          block: {
            tools: ['echo'],
            resources: [],
            resourceTemplates: [],
            prompts: [],
          },
        },
      }),
      {
        transportFactory: () => transport,
      }
    );

    const tools = await client.listTools();

    expect(tools.some((tool) => tool.toolName === 'echo' && tool.enabled === false)).toBe(true);
    await expect(client.invokeTool('echo', { value: 'blocked' })).rejects.toBeInstanceOf(McpBlockedError);

    await client.close();
  });

  it('deduplicates repeated resource and prompt manifests across merged servers', async () => {
    const firstTransport = new MockMcpTransport({
      resources: [
        { uri: 'elyan://workspace/state', name: 'workspace-state', title: 'Workspace state' },
      ],
      resourceTemplates: [
        {
          uriTemplate: 'elyan://workspace/{id}',
          name: 'workspace-template',
          title: 'Workspace template',
        },
      ],
      prompts: [
        { name: 'summary-template', title: 'Summary template' },
      ],
    });
    const secondTransport = new MockMcpTransport({
      resources: [
        { uri: 'elyan://workspace/state', name: 'workspace-state-copy', title: 'Workspace state copy' },
      ],
      resourceTemplates: [
        {
          uriTemplate: 'elyan://workspace/{id}',
          name: 'workspace-template-copy',
          title: 'Workspace template copy',
        },
      ],
      prompts: [
        { name: 'summary-template', title: 'Summary template copy' },
      ],
    });

    const registry = new McpToolRegistry(
      [
        createServerConfig({ id: 'first-server' }),
        createServerConfig({ id: 'second-server' }),
      ],
      new McpAuditTrail(),
      {
        transportFactory: (config) => {
          if (config.id === 'first-server') {
            return firstTransport;
          }

          return secondTransport;
        },
      }
    );

    const resources = await registry.listResources();
    const resourceTemplates = await registry.listResourceTemplates();
    const prompts = await registry.listPrompts();

    expect(resources).toHaveLength(1);
    expect(resources[0]?.uri).toBe('elyan://workspace/state');
    expect(resourceTemplates).toHaveLength(1);
    expect(resourceTemplates[0]?.uriTemplate).toBe('elyan://workspace/{id}');
    expect(prompts).toHaveLength(1);
    expect(prompts[0]?.name).toBe('summary-template');

    await registry.close();
  });

  it('reuses cached server manifests instead of rediscovering the same MCP surface twice', async () => {
    const transport = new MockMcpTransport({
      tools: [{ name: 'echo', title: 'Echo' }],
      resources: [{ uri: 'elyan://workspace/state', name: 'workspace-state' }],
      prompts: [{ name: 'summary-template', title: 'Summary template' }],
    });

    const registry = new McpToolRegistry(
      [createServerConfig()],
      new McpAuditTrail(),
      {
        transportFactory: () => transport,
      }
    );

    await registry.listTools();
    await registry.listTools();
    await registry.listResources();
    await registry.listResources();
    await registry.listPrompts();
    await registry.listPrompts();

    expect(transport.receivedMethods.filter((method) => method === 'tools/list')).toHaveLength(1);
    expect(transport.receivedMethods.filter((method) => method === 'resources/list')).toHaveLength(1);
    expect(transport.receivedMethods.filter((method) => method === 'prompts/list')).toHaveLength(1);

    await registry.close();
  });
});
