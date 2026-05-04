import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { z } from 'zod';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { CapabilityAuditTrail, buildCapabilityDirectorySnapshot } from '@/core/capabilities';
import { LiveMcpClient, McpTimeoutError, McpToolRegistry } from '@/core/mcp';
import type { McpServerConfig } from '@/core/mcp';

const authToken = 'elyan-production-token';

function sleep(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

function createValidatedMcpServer() {
  const server = new McpServer({
    name: 'elyan-production-mcp',
    version: '1.0.0',
  });

  server.registerTool(
    'echo',
    {
      title: 'Echo',
      description: 'Echoes the provided message',
      inputSchema: {
        message: z.string(),
      },
    },
    async ({ message }) => ({
      content: [{ type: 'text', text: message }],
      structuredContent: { echoed: message },
    })
  );

  server.registerTool(
    'slow',
    {
      title: 'Slow Echo',
      description: 'Deliberately slow tool for timeout validation',
      inputSchema: {
        message: z.string(),
        delayMs: z.number().int().min(1).max(1000).default(150),
      },
    },
    async ({ message, delayMs }) => {
      await sleep(delayMs);
      return {
        content: [{ type: 'text', text: message }],
        structuredContent: { echoed: message, delayMs },
      };
    }
  );

  server.registerResource(
    'knowledge-base',
    'elyan://knowledge/base',
    {
      title: 'Knowledge Base',
      description: 'A read-only knowledge resource',
      mimeType: 'text/plain',
    },
    async () => ({
      contents: [
        {
          uri: 'elyan://knowledge/base',
          text: 'Elyan local-first knowledge surface',
        },
      ],
    })
  );

  server.registerPrompt(
    'summary-template',
    {
      title: 'Summary Template',
      description: 'A simple prompt template',
      argsSchema: {
        topic: z.string().describe('Topic to summarize'),
      },
    },
    async ({ topic }) => ({
      messages: [
        {
          role: 'user',
          content: {
            type: 'text',
            text: `Summarize ${topic} for a local-first Elyan user.`,
          },
        },
      ],
    })
  );

  return server;
}

function createServerConfig(baseUrl: string, token: string, id: string, delayMs = 0): McpServerConfig {
  return {
    id,
    transport: 'streamable-http',
    url: `${baseUrl}/mcp${delayMs > 0 ? `?delayMs=${delayMs}` : ''}`,
    headers: {
      Authorization: `Bearer ${token}`,
    },
    enabled: true,
    connectTimeoutMs: 2_000,
    requestTimeoutMs: 2_000,
    shutdownTimeoutMs: 500,
    disabledToolNames: [],
  };
}

describe('Production MCP validation', () => {
  let server: ReturnType<typeof createServer>;
  let baseUrl = '';

  beforeAll(async () => {
    server = createServer(async (req: IncomingMessage, res: ServerResponse) => {
      const url = new URL(req.url ?? '/mcp', 'http://127.0.0.1');

      if (url.pathname !== '/mcp') {
        res.writeHead(404, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'not_found' }));
        return;
      }

      const authHeader = req.headers.authorization;
      const authorization = Array.isArray(authHeader) ? authHeader[0] : authHeader;
      if (authorization !== `Bearer ${authToken}`) {
        res.writeHead(401, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'unauthorized' }));
        return;
      }

      const delayMs = Number(url.searchParams.get('delayMs') ?? '0');
      if (Number.isFinite(delayMs) && delayMs > 0) {
        await sleep(delayMs);
      }

      const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
      const mcpServer = createValidatedMcpServer();

      try {
        await mcpServer.connect(transport);
        await transport.handleRequest(req, res);
      } finally {
        await transport.close().catch(() => undefined);
        await mcpServer.close().catch(() => undefined);
      }
    });

    await new Promise<void>((resolve) => {
      server.listen(0, '127.0.0.1', () => resolve());
    });

    const address = server.address();
    if (!address || typeof address === 'string') {
      throw new Error('Failed to start MCP production validation server');
    }

    baseUrl = `http://127.0.0.1:${address.port}`;
  });

  afterAll(async () => {
    server.closeIdleConnections?.();
    server.closeAllConnections?.();

    await new Promise<void>((resolve, reject) => {
      server.close((error) => {
        if (error) {
          reject(error);
          return;
        }

        resolve();
      });
    });
  });

  it('connects to a real streamable-http MCP server, lists tools, invokes tools, and closes cleanly', async () => {
    const client = new LiveMcpClient(createServerConfig(baseUrl, authToken, 'remote-mcp'));

    const tools = await client.listTools();
    const resources = await client.listResources();
    const prompts = await client.listPrompts();
    const resourceResult = await client.readResource('elyan://knowledge/base');
    const promptResult = await client.getPrompt('summary-template', { topic: 'MCP catalogs' });
    const result = await client.invokeTool('echo', { message: 'Elyan' });

    expect(tools.map((tool) => tool.toolName)).toContain('echo');
    expect(resources.map((resource) => resource.uri)).toContain('elyan://knowledge/base');
    expect(prompts.map((prompt) => prompt.name)).toContain('summary-template');
    expect(resourceResult.contents[0]).toMatchObject({
      uri: 'elyan://knowledge/base',
      text: expect.stringContaining('local-first'),
    });
    expect(promptResult.messages[0]?.content).toMatchObject({
      type: 'text',
      text: expect.stringContaining('Summarize MCP catalogs'),
    });
    expect(result.structuredContent).toMatchObject({ echoed: 'Elyan' });

    await client.close();
    expect(client.isClosed).toBe(true);
  });

  it('rejects invalid auth clearly and lets the registry soft-fail without breaking reachable tools', async () => {
    const deniedClient = new LiveMcpClient(createServerConfig(baseUrl, 'wrong-token', 'remote-mcp-denied'));

    await expect(deniedClient.listTools()).rejects.toThrow(/401|unauthorized/i);
    await deniedClient.close();

    const registry = new McpToolRegistry(
      [
        createServerConfig(baseUrl, authToken, 'remote-mcp-good'),
        createServerConfig(baseUrl, 'wrong-token', 'remote-mcp-denied'),
      ],
      new CapabilityAuditTrail()
    );

    const tools = await registry.listTools();
    const toolNames = tools.map((tool) => tool.toolName);

    expect(toolNames).toContain('echo');
    expect(registry.getAuditTrail().some((entry) => entry.serverId === 'remote-mcp-good' && entry.status === 'success')).toBe(true);
    expect(registry.getAuditTrail().some((entry) => entry.serverId === 'remote-mcp-denied' && entry.status === 'error')).toBe(true);

    const resources = await registry.listResources();
    const prompts = await registry.listPrompts();
    expect(resources.map((resource) => resource.uri)).toContain('elyan://knowledge/base');
    expect(prompts.map((prompt) => prompt.name)).toContain('summary-template');

    await expect(registry.invokeTool('remote-mcp-good::echo', { message: 'Elyan' })).resolves.toMatchObject({
      structuredContent: { echoed: 'Elyan' },
    });

    await registry.close();
  });

  it('times out slow discovery and slow invokes in the real transport path', async () => {
    const slowDiscoveryClient = new LiveMcpClient(createServerConfig(baseUrl, authToken, 'remote-mcp-slow-discovery', 120));

    await expect(slowDiscoveryClient.listTools({ timeoutMs: 20 })).rejects.toBeInstanceOf(McpTimeoutError);
    await slowDiscoveryClient.close();

    const slowInvokeClient = new LiveMcpClient(createServerConfig(baseUrl, authToken, 'remote-mcp-slow-invoke'));

    await slowInvokeClient.listTools();
    await expect(slowInvokeClient.invokeTool('slow', { message: 'slow', delayMs: 120 }, { timeoutMs: 20 })).rejects.toBeInstanceOf(
      McpTimeoutError
    );
    await slowInvokeClient.close();
  });

  it('builds a unified capability directory from local and live MCP surfaces', async () => {
    const previous = process.env.ELYAN_MCP_SERVERS;
    process.env.ELYAN_MCP_SERVERS = JSON.stringify({
      servers: [createServerConfig(baseUrl, authToken, 'remote-mcp-directory')],
    });

    try {
      const snapshot = await buildCapabilityDirectorySnapshot(true);

      expect(snapshot.local.capabilities.some((capability) => capability.id === 'tool_bridge')).toBe(true);
      expect(snapshot.local.bridgeTools.some((tool) => tool.id === 'math_exact')).toBe(true);
      expect(snapshot.mcp.mcpServers.some((server) => server.id === 'remote-mcp-directory')).toBe(true);
      expect(snapshot.mcp.mcpServers.some((server) => server.state === 'reachable')).toBe(true);
      expect(snapshot.mcp.mcpTools.some((tool) => tool.toolName === 'echo')).toBe(true);
      expect(snapshot.mcp.mcpResources.some((resource) => resource.uri === 'elyan://knowledge/base')).toBe(true);
      expect(snapshot.mcp.mcpPrompts.some((prompt) => prompt.name === 'summary-template')).toBe(true);
      expect(snapshot.summary.mcpReachableServerCount).toBeGreaterThan(0);
      expect(snapshot.summary.mcpToolCount).toBeGreaterThan(0);
      expect(snapshot.summary.mcpPromptCount).toBeGreaterThan(0);
    } finally {
      process.env.ELYAN_MCP_SERVERS = previous;
    }
  });
});
