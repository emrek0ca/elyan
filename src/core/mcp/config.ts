import { z } from 'zod';
import { readRuntimeSettingsSync } from '@/core/runtime-settings';
import {
  mcpServerConfigListSchema,
  mcpServerConfigSchema,
  mcpServerManifestSchema,
  type McpServerConfig,
  type McpServerManifest,
} from './types';
import { normalizeMcpServerPolicy } from './policy';

const mcpConfigEnvelopeSchema = z.object({
  servers: mcpServerConfigListSchema.default([]),
});

export function parseMcpConfig(value: string | undefined): McpServerConfig[] {
  if (!value || value.trim().length === 0) {
    return [];
  }

  const parsedJson = JSON.parse(value);
  const normalized = mcpConfigEnvelopeSchema.parse(
    Array.isArray(parsedJson) ? { servers: parsedJson } : parsedJson
  );

  return normalized.servers.map((server) => mcpServerConfigSchema.parse(server));
}

export function normalizeMcpServerManifest(
  server: McpServerConfig,
  overrides?: Partial<Pick<McpServerManifest, 'state' | 'stateReason' | 'lastCheckedAt' | 'lastError' | 'policy'>>
): McpServerManifest {
  return mcpServerManifestSchema.parse({
    id: server.id,
    transport: server.transport,
    endpoint: server.transport === 'streamable-http' ? server.url : undefined,
    enabled: server.enabled,
    connectTimeoutMs: server.connectTimeoutMs,
    requestTimeoutMs: server.requestTimeoutMs,
    shutdownTimeoutMs: server.shutdownTimeoutMs,
    disabledToolNames: server.disabledToolNames,
    state: overrides?.state ?? (server.enabled ? 'configured' : 'disabled'),
    stateReason:
      overrides?.stateReason ??
      (server.enabled ? 'Server configured and awaiting discovery.' : 'Server disabled by configuration.'),
    lastCheckedAt: overrides?.lastCheckedAt,
    lastError: overrides?.lastError,
    policy: overrides?.policy ?? normalizeMcpServerPolicy(server.policy),
  });
}

export function readMcpServerConfigsFromEnv(envValue = process.env.ELYAN_MCP_SERVERS): McpServerConfig[] {
  try {
    return parseMcpConfig(envValue);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'unknown MCP config failure';
    throw new Error(`Invalid ELYAN_MCP_SERVERS: ${message}`);
  }
}

export function readMcpServerConfigs(): McpServerConfig[] {
  const settings = readRuntimeSettingsSync();
  if (settings.mcp.servers.length > 0) {
    return settings.mcp.servers;
  }

  return readMcpServerConfigsFromEnv();
}

export function readDisabledMcpServerIdsFromEnv(envValue = process.env.ELYAN_DISABLED_MCP_SERVERS): Set<string> {
  return new Set(
    (envValue ?? '')
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean)
  );
}

export function readDisabledMcpToolNamesFromEnv(envValue = process.env.ELYAN_DISABLED_MCP_TOOLS): Set<string> {
  return new Set(
    (envValue ?? '')
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean)
  );
}
