import { z } from 'zod';
import {
  McpCancelledError,
  McpDisabledError,
  McpError,
  McpTimeoutError,
  McpUnavailableError,
} from './errors';
import { LiveMcpClient, type LiveMcpClientOptions } from './client';
import { normalizeMcpServerManifest } from './config';
import { buildLiveMcpToolCatalog } from './catalog';
import {
  type McpPromptManifest,
  type McpResourceManifest,
  type McpResourceTemplateManifest,
  type McpServerConfig,
  type McpServerManifest,
  type McpToolManifest,
} from './types';
import { McpAuditTrail, type McpAuditEntry } from './audit';

const toolIdSeparator = '::';

export type McpToolResolution = {
  serverId: string;
  toolName: string;
};

export type McpToolRegistryOptions = {
  transportFactory?: LiveMcpClientOptions['transportFactory'];
  clientFactory?: LiveMcpClientOptions['clientFactory'];
};

export type McpLookupOptions = {
  serverId?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
};

type ServerListOptions = {
  signal?: AbortSignal;
  timeoutMs?: number;
  softFail?: boolean;
};

type ServerManifestCache<T> = Map<string, T[]>;

const resolvedToolIdSchema = z
  .string()
  .min(1)
  .refine((value) => value.includes(toolIdSeparator), 'tool id must include server id and tool name');

function splitToolId(toolId: string): McpToolResolution {
  const [serverId, ...rest] = toolId.split(toolIdSeparator);
  const toolName = rest.join(toolIdSeparator);

  if (!serverId || !toolName) {
    throw new McpError(`Malformed MCP tool id: ${toolId}`);
  }

  return {
    serverId,
    toolName,
  };
}

function describeError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return 'unknown MCP failure';
}

function dedupeByKey<T>(items: T[], keySelector: (item: T) => string): T[] {
  const seen = new Set<string>();
  const deduped: T[] = [];

  for (const item of items) {
    const key = keySelector(item);
    if (seen.has(key)) {
      continue;
    }

    seen.add(key);
    deduped.push(item);
  }

  return deduped;
}

function mapAuditStatus(error: unknown): McpAuditEntry['status'] {
  if (error instanceof McpDisabledError) {
    return 'disabled';
  }

  if (error instanceof McpTimeoutError) {
    return 'timeout';
  }

  if (error instanceof McpUnavailableError) {
    return 'unavailable';
  }

  return 'error';
}

function shouldSoftFailDiscovery(error: unknown, softFail = true) {
  if (error instanceof McpDisabledError) {
    return true;
  }

  if (error instanceof McpCancelledError || error instanceof McpTimeoutError) {
    return false;
  }

  return softFail;
}

export class McpToolRegistry {
  private readonly clients = new Map<string, LiveMcpClient>();
  private readonly toolCache: ServerManifestCache<McpToolManifest> = new Map();
  private readonly resourceCache: ServerManifestCache<McpResourceManifest> = new Map();
  private readonly resourceTemplateCache: ServerManifestCache<McpResourceTemplateManifest> = new Map();
  private readonly promptCache: ServerManifestCache<McpPromptManifest> = new Map();

  constructor(
    private readonly servers: McpServerConfig[],
    private readonly auditTrail = new McpAuditTrail(),
    private readonly options?: McpToolRegistryOptions
  ) {}

  listServers(): McpServerManifest[] {
    return this.servers.map((server) => normalizeMcpServerManifest(server));
  }

  getAuditTrail(): McpAuditEntry[] {
    return this.auditTrail.list();
  }

  getEnabledServers(): McpServerConfig[] {
    return this.servers.filter((server) => server.enabled);
  }

  private getClient(serverId: string) {
    const server = this.servers.find((entry) => entry.id === serverId);
    if (!server) {
      throw new McpError(`MCP server not found: ${serverId}`);
    }

    let client = this.clients.get(serverId);
    if (!client) {
      client = new LiveMcpClient(server, this.options);
      this.clients.set(serverId, client);
    }

    return client;
  }

  private readCache<T>(cache: ServerManifestCache<T>, serverId: string) {
    const cached = cache.get(serverId);
    return cached ? [...cached] : undefined;
  }

  private writeCache<T>(cache: ServerManifestCache<T>, serverId: string, entries: T[]) {
    cache.set(serverId, [...entries]);
    return [...entries];
  }

  private async listFromServer<T>(
    server: McpServerConfig,
    cache: ServerManifestCache<T>,
    read: (client: LiveMcpClient, options: { signal?: AbortSignal; timeoutMs?: number }) => Promise<T[]>,
    options?: ServerListOptions
  ) {
    const cached = this.readCache(cache, server.id);
    if (cached) {
      return cached;
    }

    const startedAt = new Date();

    try {
      const client = this.getClient(server.id);
      const entries = await read(client, {
        signal: options?.signal,
        timeoutMs: options?.timeoutMs ?? server.requestTimeoutMs,
      });

      const cachedEntries = this.writeCache(cache, server.id, entries);
      this.auditTrail.record({
        serverId: server.id,
        status: 'success',
        startedAt: startedAt.toISOString(),
        finishedAt: new Date().toISOString(),
        durationMs: new Date().getTime() - startedAt.getTime(),
      });

      return cachedEntries;
    } catch (error) {
      const finishedAt = new Date();
      this.auditTrail.record({
        serverId: server.id,
        status: mapAuditStatus(error),
        startedAt: startedAt.toISOString(),
        finishedAt: finishedAt.toISOString(),
        durationMs: finishedAt.getTime() - startedAt.getTime(),
        errorMessage: describeError(error),
      });

      if (shouldSoftFailDiscovery(error, options?.softFail ?? true)) {
        return [];
      }

      throw error instanceof Error ? error : new McpUnavailableError(`Unable to read MCP server: ${server.id}`);
    }
  }

  private async listAcrossEnabledServers<T>(
    cache: ServerManifestCache<T>,
    read: (client: LiveMcpClient, options: { signal?: AbortSignal; timeoutMs?: number }) => Promise<T[]>,
    options?: ServerListOptions
  ) {
    const enabledServers = this.getEnabledServers();
    if (enabledServers.length === 0) {
      return [] as T[];
    }

    const manifests: T[] = [];

    for (const server of enabledServers) {
      const entries = await this.listFromServer(server, cache, read, {
        ...options,
        softFail: options?.softFail ?? true,
      });
      manifests.push(...entries);
    }

    return manifests;
  }

  private getEnabledServer(serverId?: string) {
    if (serverId) {
      const server = this.servers.find((entry) => entry.id === serverId);
      if (!server) {
        throw new McpError(`MCP server not found: ${serverId}`);
      }

      if (!server.enabled) {
        throw new McpDisabledError(`MCP server disabled: ${serverId}`);
      }

      return server;
    }

    return this.getEnabledServers()[0];
  }

  async listTools(options?: { signal?: AbortSignal; timeoutMs?: number }): Promise<McpToolManifest[]> {
    const manifests = await this.listAcrossEnabledServers(
      this.toolCache,
      (client, requestOptions) => client.listTools(requestOptions),
      options
    );

    return buildLiveMcpToolCatalog(manifests);
  }

  async listResources(options?: { signal?: AbortSignal; timeoutMs?: number }): Promise<McpResourceManifest[]> {
    const manifests = await this.listAcrossEnabledServers(
      this.resourceCache,
      (client, requestOptions) => client.listResources(requestOptions),
      options
    );

    return dedupeByKey(manifests, (resource) => resource.uri);
  }

  async listResourceTemplates(options?: { signal?: AbortSignal; timeoutMs?: number }): Promise<McpResourceTemplateManifest[]> {
    const manifests = await this.listAcrossEnabledServers(
      this.resourceTemplateCache,
      (client, requestOptions) => client.listResourceTemplates(requestOptions),
      options
    );

    return dedupeByKey(manifests, (template) => template.uriTemplate);
  }

  async listPrompts(options?: { signal?: AbortSignal; timeoutMs?: number }): Promise<McpPromptManifest[]> {
    const manifests = await this.listAcrossEnabledServers(
      this.promptCache,
      (client, requestOptions) => client.listPrompts(requestOptions),
      options
    );

    return dedupeByKey(manifests, (prompt) => prompt.name);
  }

  async readResource(
    resourceUri: string,
    options?: McpLookupOptions
  ): Promise<Awaited<ReturnType<LiveMcpClient['readResource']>>> {
    const server =
      options?.serverId !== undefined
        ? this.getEnabledServer(options.serverId)
        : await this.findServerWithResource(resourceUri, options);

    if (!server) {
      throw new McpUnavailableError(`MCP resource not found: ${resourceUri}`);
    }

    const startedAt = new Date();

    try {
      const client = this.getClient(server.id);
      const result = await client.readResource(resourceUri, {
        signal: options?.signal,
        timeoutMs: options?.timeoutMs ?? server.requestTimeoutMs,
      });

      this.auditTrail.record({
        serverId: server.id,
        toolId: resourceUri,
        toolName: resourceUri,
        status: 'success',
        startedAt: startedAt.toISOString(),
        finishedAt: new Date().toISOString(),
        durationMs: new Date().getTime() - startedAt.getTime(),
      });

      return result;
    } catch (error) {
      const finishedAt = new Date();
      this.auditTrail.record({
        serverId: server.id,
        toolId: resourceUri,
        toolName: resourceUri,
        status: mapAuditStatus(error),
        startedAt: startedAt.toISOString(),
        finishedAt: finishedAt.toISOString(),
        durationMs: finishedAt.getTime() - startedAt.getTime(),
        errorMessage: describeError(error),
      });

      throw error instanceof Error ? error : new McpUnavailableError(`Unable to read MCP resource: ${resourceUri}`);
    }
  }

  async getPrompt(
    promptName: string,
    args?: Record<string, string>,
    options?: McpLookupOptions
  ) {
    const server =
      options?.serverId !== undefined
        ? this.getEnabledServer(options.serverId)
        : await this.findServerWithPrompt(promptName, options);

    if (!server) {
      throw new McpUnavailableError(`MCP prompt not found: ${promptName}`);
    }

    const startedAt = new Date();

    try {
      const client = this.getClient(server.id);
      const result = await client.getPrompt(promptName, args, {
        signal: options?.signal,
        timeoutMs: options?.timeoutMs ?? server.requestTimeoutMs,
      });

      this.auditTrail.record({
        serverId: server.id,
        toolId: promptName,
        toolName: promptName,
        status: 'success',
        startedAt: startedAt.toISOString(),
        finishedAt: new Date().toISOString(),
        durationMs: new Date().getTime() - startedAt.getTime(),
      });

      return result;
    } catch (error) {
      const finishedAt = new Date();
      this.auditTrail.record({
        serverId: server.id,
        toolId: promptName,
        toolName: promptName,
        status: mapAuditStatus(error),
        startedAt: startedAt.toISOString(),
        finishedAt: finishedAt.toISOString(),
        durationMs: finishedAt.getTime() - startedAt.getTime(),
        errorMessage: describeError(error),
      });

      throw error instanceof Error ? error : new McpUnavailableError(`Unable to get MCP prompt: ${promptName}`);
    }
  }

  private async findServerWithResource(resourceUri: string, options?: McpLookupOptions) {
    const enabledServers = this.getEnabledServers();

    for (const server of enabledServers) {
      const cachedResources = this.readCache(this.resourceCache, server.id);
      if (cachedResources?.some((resource) => resource.uri === resourceUri)) {
        return server;
      }
    }

    for (const server of enabledServers) {
      if (this.resourceCache.has(server.id)) {
        continue;
      }

      const resources = await this.listFromServer(
        server,
        this.resourceCache,
        (client, requestOptions) => client.listResources(requestOptions),
        {
          signal: options?.signal,
          timeoutMs: options?.timeoutMs,
          softFail: true,
        }
      );

      if (resources.some((resource) => resource.uri === resourceUri)) {
        return server;
      }
    }

    return undefined;
  }

  private async findServerWithPrompt(promptName: string, options?: McpLookupOptions) {
    const enabledServers = this.getEnabledServers();

    for (const server of enabledServers) {
      const cachedPrompts = this.readCache(this.promptCache, server.id);
      if (cachedPrompts?.some((prompt) => prompt.name === promptName)) {
        return server;
      }
    }

    for (const server of enabledServers) {
      if (this.promptCache.has(server.id)) {
        continue;
      }

      const prompts = await this.listFromServer(
        server,
        this.promptCache,
        (client, requestOptions) => client.listPrompts(requestOptions),
        {
          signal: options?.signal,
          timeoutMs: options?.timeoutMs,
          softFail: true,
        }
      );

      if (prompts.some((prompt) => prompt.name === promptName)) {
        return server;
      }
    }

    return undefined;
  }

  resolveTool(toolId: string): McpToolResolution {
    const parsed = resolvedToolIdSchema.safeParse(toolId);
    if (!parsed.success) {
      throw new McpError(`Malformed MCP tool id: ${toolId}`);
    }
    return splitToolId(toolId);
  }

  async invokeTool(
    toolId: string,
    input: unknown,
    options?: { signal?: AbortSignal; timeoutMs?: number }
  ): Promise<unknown> {
    const { serverId, toolName } = this.resolveTool(toolId);
    const server = this.servers.find((entry) => entry.id === serverId);

    if (!server) {
      throw new McpError(`MCP server not found: ${serverId}`);
    }

    if (!server.enabled) {
      const startedAt = new Date();
      const finishedAt = new Date();
      this.auditTrail.record({
        serverId,
        toolId,
        toolName,
        status: 'disabled',
        startedAt: startedAt.toISOString(),
        finishedAt: finishedAt.toISOString(),
        durationMs: 0,
        errorMessage: 'disabled by registry configuration',
      });
      throw new McpDisabledError(`MCP tool disabled: ${toolId}`);
    }

    if (server.disabledToolNames.includes(toolName)) {
      const startedAt = new Date();
      const finishedAt = new Date();
      this.auditTrail.record({
        serverId,
        toolId,
        toolName,
        status: 'disabled',
        startedAt: startedAt.toISOString(),
        finishedAt: finishedAt.toISOString(),
        durationMs: 0,
        errorMessage: 'disabled by server configuration',
      });
      throw new McpDisabledError(`MCP tool disabled: ${toolId}`);
    }

    const startedAt = new Date();

    try {
      const client = this.getClient(serverId);
      const result = await client.invokeTool(toolName, input, {
        signal: options?.signal,
        timeoutMs: options?.timeoutMs ?? server.requestTimeoutMs,
      });

      const finishedAt = new Date();
      this.auditTrail.record({
        serverId,
        toolId,
        toolName,
        status: 'success',
        startedAt: startedAt.toISOString(),
        finishedAt: finishedAt.toISOString(),
        durationMs: finishedAt.getTime() - startedAt.getTime(),
      });

      return result;
    } catch (error) {
      const finishedAt = new Date();
      this.auditTrail.record({
        serverId,
        toolId,
        toolName,
        status: mapAuditStatus(error),
        startedAt: startedAt.toISOString(),
        finishedAt: finishedAt.toISOString(),
        durationMs: finishedAt.getTime() - startedAt.getTime(),
        errorMessage: describeError(error),
      });

      if (error instanceof Error) {
        throw error;
      }

      throw new McpUnavailableError(`Unable to invoke MCP tool: ${toolId}`);
    }
  }

  async close() {
    const clients = [...this.clients.values()];
    this.clients.clear();
    this.toolCache.clear();
    this.resourceCache.clear();
    this.resourceTemplateCache.clear();
    this.promptCache.clear();

    await Promise.allSettled(clients.map((client) => client.close()));
  }
}
