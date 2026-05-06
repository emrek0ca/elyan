import { z } from 'zod';

export const mcpTransportKindSchema = z.enum(['stdio', 'streamable-http']);
export const mcpServerStateSchema = z.enum(['unconfigured', 'configured', 'reachable', 'degraded', 'blocked', 'disabled']);

const mcpSurfacePolicyScopeSchema = z.object({
  tools: z.array(z.string().min(1)).default([]),
  resources: z.array(z.string().min(1)).default([]),
  resourceTemplates: z.array(z.string().min(1)).default([]),
  prompts: z.array(z.string().min(1)).default([]),
});

export const mcpServerPolicySchema = z.object({
  allow: mcpSurfacePolicyScopeSchema.optional(),
  block: mcpSurfacePolicyScopeSchema.optional(),
  maxRequestBytes: z.number().int().min(128).max(1_048_576).default(64_000),
  maxResponseBytes: z.number().int().min(128).max(1_048_576).default(128_000),
  redactionKeys: z.array(z.string().min(1)).default(['token', 'secret', 'password', 'authorization']),
  redactionPatterns: z.array(z.string().min(1)).default([]),
});

const mcpCommonServerConfigSchema = z.object({
  id: z.string().min(1),
  enabled: z.boolean().default(true),
  connectTimeoutMs: z.number().int().min(100).max(30_000).default(5_000),
  requestTimeoutMs: z.number().int().min(100).max(60_000).default(10_000),
  shutdownTimeoutMs: z.number().int().min(100).max(10_000).default(2_000),
  disabledToolNames: z.array(z.string().min(1)).default([]),
  policy: mcpServerPolicySchema.optional(),
});

export const mcpStdioServerConfigSchema = mcpCommonServerConfigSchema.extend({
  transport: z.literal('stdio'),
  command: z.string().min(1),
  args: z.array(z.string()).default([]),
  cwd: z.string().optional(),
  env: z.record(z.string(), z.string()).default({}),
});

export const mcpStreamableHttpServerConfigSchema = mcpCommonServerConfigSchema.extend({
  transport: z.literal('streamable-http'),
  url: z.string().url(),
  headers: z.record(z.string(), z.string()).default({}),
});

export const mcpServerConfigSchema = z.discriminatedUnion('transport', [
  mcpStdioServerConfigSchema,
  mcpStreamableHttpServerConfigSchema,
]);

export const mcpServerConfigListSchema = z.array(mcpServerConfigSchema);

export const mcpToolSourceSchema = z.object({
  kind: z.literal('mcp'),
  serverId: z.string().min(1),
  transport: mcpTransportKindSchema,
  endpoint: z.string().optional(),
});

export const mcpResourceSourceSchema = z.object({
  kind: z.literal('mcp'),
  serverId: z.string().min(1),
  transport: mcpTransportKindSchema,
  endpoint: z.string().optional(),
});

export const mcpPromptSourceSchema = z.object({
  kind: z.literal('mcp'),
  serverId: z.string().min(1),
  transport: mcpTransportKindSchema,
  endpoint: z.string().optional(),
});

export const localToolSourceSchema = z.object({
  kind: z.literal('local'),
  scope: z.enum(['capability', 'bridge']),
});

export const toolSourceSchema = z.union([localToolSourceSchema, mcpToolSourceSchema]);

export const toolManifestSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  description: z.string().min(1),
  library: z.string().min(1),
  timeoutMs: z.number().int().positive(),
  enabled: z.boolean(),
  source: toolSourceSchema,
});

export const mcpServerManifestSchema = z.object({
  id: z.string().min(1),
  transport: mcpTransportKindSchema,
  endpoint: z.string().optional(),
  enabled: z.boolean(),
  connectTimeoutMs: z.number().int().positive(),
  requestTimeoutMs: z.number().int().positive(),
  shutdownTimeoutMs: z.number().int().positive(),
  disabledToolNames: z.array(z.string()),
  state: mcpServerStateSchema.optional(),
  stateReason: z.string().optional(),
  lastCheckedAt: z.string().optional(),
  lastError: z.string().optional(),
  policy: mcpServerPolicySchema.optional(),
});

export const mcpToolManifestSchema = toolManifestSchema.extend({
  source: mcpToolSourceSchema,
  toolName: z.string().min(1),
});

export const mcpResourceManifestSchema = z.object({
  uri: z.string().min(1),
  name: z.string().min(1),
  title: z.string().min(1).optional(),
  description: z.string().optional(),
  mimeType: z.string().optional(),
  size: z.number().nonnegative().optional(),
  enabled: z.boolean(),
  source: mcpResourceSourceSchema,
});

export const mcpResourceTemplateManifestSchema = z.object({
  uriTemplate: z.string().min(1),
  name: z.string().min(1),
  title: z.string().min(1).optional(),
  description: z.string().optional(),
  mimeType: z.string().optional(),
  enabled: z.boolean(),
  source: mcpResourceSourceSchema,
});

export const mcpPromptArgumentManifestSchema = z.object({
  name: z.string().min(1),
  description: z.string().optional(),
  required: z.boolean().optional(),
});

export const mcpPromptManifestSchema = z.object({
  name: z.string().min(1),
  title: z.string().min(1).optional(),
  description: z.string().optional(),
  arguments: z.array(mcpPromptArgumentManifestSchema).default([]),
  enabled: z.boolean(),
  source: mcpPromptSourceSchema,
});

export type McpServerConfig = z.output<typeof mcpServerConfigSchema>;
export type McpServerManifest = z.output<typeof mcpServerManifestSchema>;
export type McpServerPolicy = z.output<typeof mcpServerPolicySchema>;
export type McpServerState = z.output<typeof mcpServerStateSchema>;
export type McpToolManifest = z.output<typeof mcpToolManifestSchema>;
export type McpResourceManifest = z.output<typeof mcpResourceManifestSchema>;
export type McpResourceTemplateManifest = z.output<typeof mcpResourceTemplateManifestSchema>;
export type McpPromptArgumentManifest = z.output<typeof mcpPromptArgumentManifestSchema>;
export type McpPromptManifest = z.output<typeof mcpPromptManifestSchema>;
export type ToolManifest = z.output<typeof toolManifestSchema>;
export type ToolSource = z.output<typeof toolSourceSchema>;
