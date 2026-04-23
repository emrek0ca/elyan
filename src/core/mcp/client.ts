import { z } from 'zod';
import {
  McpCancelledError,
  McpBlockedError,
  McpError,
  McpMalformedResponseError,
  McpTimeoutError,
  McpUnavailableError,
} from './errors';
import { normalizeMcpServerManifest } from './config';
import {
  estimatePayloadSize,
  isMcpItemAllowed,
  normalizeMcpServerPolicy,
} from './policy';
import {
  type McpPromptManifest,
  type McpResourceManifest,
  type McpResourceTemplateManifest,
  type McpServerConfig,
  type McpToolManifest,
} from './types';

type MCPClient = import('@modelcontextprotocol/sdk/client/index.js').Client;
type MCPTransport = import('@modelcontextprotocol/sdk/shared/transport.js').Transport;

const mcpListedToolSchema = z
  .object({
    name: z.string().min(1),
    title: z.string().min(1).optional(),
    description: z.string().optional(),
  })
  .passthrough();

const mcpListToolsResultSchema = z
  .object({
    tools: z.array(mcpListedToolSchema),
  })
  .passthrough();

const mcpListResourceTemplateSchema = z
  .object({
    uriTemplate: z.string().min(1),
    name: z.string().min(1),
    title: z.string().optional(),
    description: z.string().optional(),
    mimeType: z.string().optional(),
  })
  .passthrough();

const mcpListResourceTemplatesResultSchema = z
  .object({
    resourceTemplates: z.array(mcpListResourceTemplateSchema),
  })
  .passthrough();

const mcpListedResourceSchema = z
  .object({
    uri: z.string().min(1),
    name: z.string().min(1),
    title: z.string().optional(),
    description: z.string().optional(),
    mimeType: z.string().optional(),
    size: z.number().nonnegative().optional(),
  })
  .passthrough();

const mcpListResourcesResultSchema = z
  .object({
    resources: z.array(mcpListedResourceSchema),
  })
  .passthrough();

const mcpListedPromptArgumentSchema = z
  .object({
    name: z.string().min(1),
    description: z.string().optional(),
    required: z.boolean().optional(),
  })
  .passthrough();

const mcpListedPromptSchema = z
  .object({
    name: z.string().min(1),
    title: z.string().optional(),
    description: z.string().optional(),
    arguments: z.array(mcpListedPromptArgumentSchema).optional(),
  })
  .passthrough();

const mcpListPromptsResultSchema = z
  .object({
    prompts: z.array(mcpListedPromptSchema),
  })
  .passthrough();

const mcpCallToolResultSchema = z
  .object({
    content: z.array(z.unknown()).default([]),
    structuredContent: z.unknown().optional(),
    isError: z.boolean().optional(),
  })
  .passthrough();

type ConnectOptions = {
  signal?: AbortSignal;
  timeoutMs?: number;
};

type ToolCallOptions = ConnectOptions;

export type McpTransportFactory = (config: McpServerConfig) => Promise<MCPTransport> | MCPTransport;

export type LiveMcpClientOptions = {
  clientFactory?: () => Promise<MCPClient> | MCPClient;
  transportFactory?: McpTransportFactory;
};

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, errorFactory: () => Error, signal?: AbortSignal) {
  return new Promise<T>((resolve, reject) => {
    const timeout = setTimeout(() => {
      reject(errorFactory());
    }, timeoutMs);

    const cleanup = () => {
      clearTimeout(timeout);
      signal?.removeEventListener('abort', onAbort);
    };

    const onAbort = () => {
      cleanup();
      reject(new McpCancelledError('MCP request cancelled'));
    };

    if (signal?.aborted) {
      cleanup();
      reject(errorFactory());
      return;
    }

    signal?.addEventListener('abort', onAbort, { once: true });

    promise
      .then((value) => {
        cleanup();
        resolve(value);
      })
      .catch((error) => {
        cleanup();
        reject(error);
      });
  });
}

function isMalformedResponseError(error: unknown) {
  if (!(error instanceof Error)) {
    return false;
  }

  return /schema|validation|malformed|parse/i.test(error.message);
}

function normalizeEndpoint(config: McpServerConfig) {
  return config.transport === 'streamable-http' ? config.url : undefined;
}

function getPolicy(config: McpServerConfig) {
  return normalizeMcpServerPolicy(config.policy);
}

function createBlockedError(subject: string, reason: string) {
  return new McpBlockedError(`MCP operation blocked: ${subject} (${reason})`);
}

function ensurePayloadWithinLimit(subject: string, payload: unknown, maxBytes: number) {
  const size = estimatePayloadSize(payload);
  if (size > maxBytes) {
    throw createBlockedError(subject, `payload exceeds ${maxBytes} bytes`);
  }
}

async function createDefaultTransport(config: McpServerConfig): Promise<MCPTransport> {
  if (config.transport === 'stdio') {
    const { StdioClientTransport } = await import('@modelcontextprotocol/sdk/client/stdio.js');
    return new StdioClientTransport({
      command: config.command,
      args: config.args,
      cwd: config.cwd,
      env: config.env,
    });
  }

  const { StreamableHTTPClientTransport } = await import('@modelcontextprotocol/sdk/client/streamableHttp.js');
  return new StreamableHTTPClientTransport(new URL(config.url), {
    requestInit: {
      headers: config.headers,
    },
  });
}

async function createDefaultClient(): Promise<MCPClient> {
  const { Client } = await import('@modelcontextprotocol/sdk/client/index.js');
  return new Client({ name: 'Elyan MCP Bridge', version: '1.0.0' });
}

export class LiveMcpClient {
  private client?: MCPClient;
  private transport?: MCPTransport;
  private connected = false;
  private closed = false;

  constructor(
    public readonly config: McpServerConfig,
    private readonly options?: LiveMcpClientOptions
  ) {}

  get serverManifest() {
    return normalizeMcpServerManifest(this.config);
  }

  get isClosed() {
    return this.closed;
  }

  async connect(options?: ConnectOptions) {
    if (this.closed) {
      throw new McpError(`MCP client already closed: ${this.config.id}`);
    }

    if (this.connected) {
      return;
    }

    const connectTimeoutMs = options?.timeoutMs ?? this.config.connectTimeoutMs;
    const transport = await withTimeout(
      Promise.resolve(this.options?.transportFactory?.(this.config) ?? createDefaultTransport(this.config)),
      connectTimeoutMs,
      () => new McpTimeoutError(`MCP connect timed out: ${this.config.id}`),
      options?.signal
    );

    const client = await (this.options?.clientFactory?.() ?? createDefaultClient());

    try {
      await withTimeout(
        client.connect(transport),
        connectTimeoutMs,
        () => new McpTimeoutError(`MCP initialize timed out: ${this.config.id}`),
        options?.signal
      );
      this.client = client;
      this.transport = transport;
      this.connected = true;
    } catch (error) {
      await transport.close().catch(() => undefined);
      throw error instanceof Error ? error : new McpUnavailableError(`Unable to connect to MCP server: ${this.config.id}`);
    }
  }

  async listTools(options?: ToolCallOptions): Promise<McpToolManifest[]> {
    await this.connect(options);

    if (!this.client) {
      throw new McpUnavailableError(`MCP client unavailable: ${this.config.id}`);
    }

    const result = await withTimeout(
      this.client.listTools({}, {
        signal: options?.signal,
      }),
      options?.timeoutMs ?? this.config.requestTimeoutMs,
      () => new McpTimeoutError(`MCP listTools timed out: ${this.config.id}`),
      options?.signal
    ).catch((error) => {
      if (isMalformedResponseError(error)) {
        throw new McpMalformedResponseError(`Malformed MCP tool list from ${this.config.id}`);
      }

      throw error instanceof Error ? error : new McpUnavailableError(`Unable to list MCP tools: ${this.config.id}`);
    });

    const parsed = mcpListToolsResultSchema.safeParse(result);
    if (!parsed.success) {
      throw new McpMalformedResponseError(`Malformed MCP tool list from ${this.config.id}`);
    }

    const policy = getPolicy(this.config);
    return parsed.data.tools
      .filter((tool) => !this.config.disabledToolNames.includes(tool.name))
      .map((tool) => ({
        id: `${this.config.id}::${tool.name}`,
        toolName: tool.name,
        title: tool.title ?? tool.name,
        description: tool.description ?? `MCP tool from ${this.config.id}`,
        library: 'mcp',
        timeoutMs: this.config.requestTimeoutMs,
        enabled:
          !this.config.disabledToolNames.includes(tool.name) &&
          isMcpItemAllowed('tool', tool.name, policy),
        source: {
          kind: 'mcp',
          serverId: this.config.id,
          transport: this.config.transport,
          endpoint: this.config.transport === 'streamable-http' ? this.config.url : undefined,
        },
      }));
  }

  async listResources(options?: ToolCallOptions): Promise<McpResourceManifest[]> {
    await this.connect(options);

    if (!this.client) {
      throw new McpUnavailableError(`MCP client unavailable: ${this.config.id}`);
    }

    const result = await withTimeout(
      this.client.listResources({}, {
        signal: options?.signal,
      }),
      options?.timeoutMs ?? this.config.requestTimeoutMs,
      () => new McpTimeoutError(`MCP listResources timed out: ${this.config.id}`),
      options?.signal
    ).catch((error) => {
      if (isMalformedResponseError(error)) {
        throw new McpMalformedResponseError(`Malformed MCP resource list from ${this.config.id}`);
      }

      throw error instanceof Error ? error : new McpUnavailableError(`Unable to list MCP resources: ${this.config.id}`);
    });

    const parsed = mcpListResourcesResultSchema.safeParse(result);
    if (!parsed.success) {
      throw new McpMalformedResponseError(`Malformed MCP resource list from ${this.config.id}`);
    }

    const policy = getPolicy(this.config);
    return parsed.data.resources.map((resource) => ({
      uri: resource.uri,
      name: resource.name,
      title: resource.title,
      description: resource.description,
      mimeType: resource.mimeType,
      size: resource.size,
      enabled: isMcpItemAllowed('resource', resource.uri, policy),
      source: {
        kind: 'mcp',
        serverId: this.config.id,
        transport: this.config.transport,
        endpoint: normalizeEndpoint(this.config),
      },
    }));
  }

  async listResourceTemplates(options?: ToolCallOptions): Promise<McpResourceTemplateManifest[]> {
    await this.connect(options);

    if (!this.client) {
      throw new McpUnavailableError(`MCP client unavailable: ${this.config.id}`);
    }

    const result = await withTimeout(
      this.client.listResourceTemplates({}, {
        signal: options?.signal,
      }),
      options?.timeoutMs ?? this.config.requestTimeoutMs,
      () => new McpTimeoutError(`MCP listResourceTemplates timed out: ${this.config.id}`),
      options?.signal
    ).catch((error) => {
      if (isMalformedResponseError(error)) {
        throw new McpMalformedResponseError(`Malformed MCP resource template list from ${this.config.id}`);
      }

      throw error instanceof Error
        ? error
        : new McpUnavailableError(`Unable to list MCP resource templates: ${this.config.id}`);
    });

    const parsed = mcpListResourceTemplatesResultSchema.safeParse(result);
    if (!parsed.success) {
      throw new McpMalformedResponseError(`Malformed MCP resource template list from ${this.config.id}`);
    }

    const policy = getPolicy(this.config);
    return parsed.data.resourceTemplates.map((resourceTemplate) => ({
      uriTemplate: resourceTemplate.uriTemplate,
      name: resourceTemplate.name,
      title: resourceTemplate.title ?? resourceTemplate.name,
      description: resourceTemplate.description,
      mimeType: resourceTemplate.mimeType,
      enabled: isMcpItemAllowed('resourceTemplate', resourceTemplate.uriTemplate, policy),
      source: {
        kind: 'mcp',
        serverId: this.config.id,
        transport: this.config.transport,
        endpoint: normalizeEndpoint(this.config),
      },
    }));
  }

  async listPrompts(options?: ToolCallOptions): Promise<McpPromptManifest[]> {
    await this.connect(options);

    if (!this.client) {
      throw new McpUnavailableError(`MCP client unavailable: ${this.config.id}`);
    }

    const result = await withTimeout(
      this.client.listPrompts({}, {
        signal: options?.signal,
      }),
      options?.timeoutMs ?? this.config.requestTimeoutMs,
      () => new McpTimeoutError(`MCP listPrompts timed out: ${this.config.id}`),
      options?.signal
    ).catch((error) => {
      if (isMalformedResponseError(error)) {
        throw new McpMalformedResponseError(`Malformed MCP prompt list from ${this.config.id}`);
      }

      throw error instanceof Error ? error : new McpUnavailableError(`Unable to list MCP prompts: ${this.config.id}`);
    });

    const parsed = mcpListPromptsResultSchema.safeParse(result);
    if (!parsed.success) {
      throw new McpMalformedResponseError(`Malformed MCP prompt list from ${this.config.id}`);
    }

    const policy = getPolicy(this.config);
    return parsed.data.prompts.map((prompt) => ({
      name: prompt.name,
      title: prompt.title,
      description: prompt.description,
      arguments: prompt.arguments ?? [],
      enabled: isMcpItemAllowed('prompt', prompt.name, policy),
      source: {
        kind: 'mcp',
        serverId: this.config.id,
        transport: this.config.transport,
        endpoint: normalizeEndpoint(this.config),
      },
    }));
  }

  async readResource(uri: string, options?: ToolCallOptions) {
    await this.connect(options);

    if (!this.client) {
      throw new McpUnavailableError(`MCP client unavailable: ${this.config.id}`);
    }

    const policy = getPolicy(this.config);
    if (!isMcpItemAllowed('resource', uri, policy)) {
      throw createBlockedError(`resource ${this.config.id}::${uri}`, 'blocked by server policy');
    }

    const result = await withTimeout(
      this.client.readResource({ uri }, {
        signal: options?.signal,
      }),
      options?.timeoutMs ?? this.config.requestTimeoutMs,
      () => new McpTimeoutError(`MCP readResource timed out: ${this.config.id}::${uri}`),
      options?.signal
    ).catch((error) => {
      if (isMalformedResponseError(error)) {
        throw new McpMalformedResponseError(`Malformed MCP resource read from ${this.config.id}::${uri}`);
      }

      throw error instanceof Error ? error : new McpUnavailableError(`Unable to read MCP resource: ${this.config.id}::${uri}`);
    });

    ensurePayloadWithinLimit(`resource result ${this.config.id}::${uri}`, result, policy.maxResponseBytes);

    return result;
  }

  async getPrompt(name: string, args?: Record<string, string>, options?: ToolCallOptions) {
    await this.connect(options);

    if (!this.client) {
      throw new McpUnavailableError(`MCP client unavailable: ${this.config.id}`);
    }

    const policy = getPolicy(this.config);
    if (!isMcpItemAllowed('prompt', name, policy)) {
      throw createBlockedError(`prompt ${this.config.id}::${name}`, 'blocked by server policy');
    }

    const result = await withTimeout(
      this.client.getPrompt({ name, arguments: args }, {
        signal: options?.signal,
      }),
      options?.timeoutMs ?? this.config.requestTimeoutMs,
      () => new McpTimeoutError(`MCP getPrompt timed out: ${this.config.id}::${name}`),
      options?.signal
    ).catch((error) => {
      if (isMalformedResponseError(error)) {
        throw new McpMalformedResponseError(`Malformed MCP prompt result from ${this.config.id}::${name}`);
      }

      throw error instanceof Error ? error : new McpUnavailableError(`Unable to get MCP prompt: ${this.config.id}::${name}`);
    });

    ensurePayloadWithinLimit(`prompt result ${this.config.id}::${name}`, result, policy.maxResponseBytes);

    return result;
  }

  async invokeTool(toolName: string, input: unknown, options?: ToolCallOptions) {
    await this.connect(options);

    if (!this.client) {
      throw new McpUnavailableError(`MCP client unavailable: ${this.config.id}`);
    }

    const policy = getPolicy(this.config);
    if (!isMcpItemAllowed('tool', toolName, policy)) {
      throw createBlockedError(`tool ${this.config.id}::${toolName}`, 'blocked by server policy');
    }

    ensurePayloadWithinLimit(`tool ${this.config.id}::${toolName}`, input, policy.maxRequestBytes);

    try {
      const result = await withTimeout(
        this.client.callTool(
          {
            name: toolName,
            arguments: input as Record<string, unknown>,
          },
          undefined,
          {
            signal: options?.signal,
          }
        ),
        options?.timeoutMs ?? this.config.requestTimeoutMs,
        () => new McpTimeoutError(`MCP tool call timed out: ${this.config.id}::${toolName}`),
        options?.signal
      );

      const parsed = mcpCallToolResultSchema.safeParse(result);
      if (!parsed.success) {
        throw new McpMalformedResponseError(`Malformed MCP tool result from ${this.config.id}::${toolName}`);
      }

      ensurePayloadWithinLimit(`tool result ${this.config.id}::${toolName}`, parsed.data, policy.maxResponseBytes);

      return parsed.data;
    } catch (error) {
      if (isMalformedResponseError(error)) {
        throw new McpMalformedResponseError(`Malformed MCP tool result from ${this.config.id}::${toolName}`);
      }

      throw error instanceof Error ? error : new McpUnavailableError(`Unable to invoke MCP tool: ${this.config.id}::${toolName}`);
    }
  }

  async close() {
    if (this.closed) {
      return;
    }

    this.closed = true;
    this.connected = false;

    try {
      if (this.client) {
        await this.client.close();
      } else if (this.transport) {
        await this.transport.close();
      }
    } finally {
      this.client = undefined;
      this.transport = undefined;
    }
  }
}
