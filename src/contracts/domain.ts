import { z } from "zod";

export const deviceTypeValues = ["mobile", "desktop"] as const;
export const pairSessionStatusValues = ["pending", "claimed", "expired"] as const;
export const runtimeConnectionStatusValues = ["online", "busy", "idle", "offline"] as const;
export const taskStatusValues = [
  "queued",
  "planning",
  "running",
  "waiting_approval",
  "completed",
  "failed",
  "canceled",
] as const;
export const artifactKindValues = [
  "markdown",
  "file",
  "summary",
  "screenshot",
  "structured_output",
] as const;
export const subscriptionStatusValues = ["free", "trialing", "active", "past_due", "canceled"] as const;
export const aiProviderValues = ["openai", "claude", "ollama", "groq", "openrouter"] as const;
export const userRoleValues = ["user", "admin"] as const;
export const connectionProviderValues = [
  "google",
  "notion",
  "slack",
  "discord",
  "github",
  "linear",
  "telegram",
  "dropbox",
  "trello",
  "jira",
  "clickup",
  "webhooks",
  "custom_api",
  "openai",
  "claude",
  "groq",
  "ollama",
  "openrouter",
] as const;
export const integrationAuthTypeValues = ["oauth2", "api_key", "webhook", "none"] as const;
export const integrationConnectionStatusValues = ["pending", "connected", "error", "revoked"] as const;
export const oauthStateStatusValues = ["pending", "completed", "expired"] as const;
export const mcpTransportValues = ["stdio", "remote", "oauth_remote", "streamable_http"] as const;
export const mcpAuthTypeValues = ["none", "bearer", "oauth2", "api_key"] as const;
export const mcpServerStatusValues = ["configured", "connected", "degraded", "revoked"] as const;
export const auditActorTypeValues = ["user", "runtime", "system"] as const;
export const auditStatusValues = ["success", "failure"] as const;
export const aiInvocationStatusValues = ["success", "timeout", "fallback", "error"] as const;

export const deviceTypeSchema = z.enum(deviceTypeValues);
export const pairSessionStatusSchema = z.enum(pairSessionStatusValues);
export const runtimeConnectionStatusSchema = z.enum(runtimeConnectionStatusValues);
export const taskStatusSchema = z.enum(taskStatusValues);
export const artifactKindSchema = z.enum(artifactKindValues);
export const subscriptionStatusSchema = z.enum(subscriptionStatusValues);
export const aiProviderSchema = z.enum(aiProviderValues);
export const userRoleSchema = z.enum(userRoleValues);
export const connectionProviderSchema = z.enum(connectionProviderValues);
export const integrationAuthTypeSchema = z.enum(integrationAuthTypeValues);
export const integrationConnectionStatusSchema = z.enum(integrationConnectionStatusValues);
export const oauthStateStatusSchema = z.enum(oauthStateStatusValues);
export const mcpTransportSchema = z.enum(mcpTransportValues);
export const mcpAuthTypeSchema = z.enum(mcpAuthTypeValues);
export const mcpServerStatusSchema = z.enum(mcpServerStatusValues);
export const auditActorTypeSchema = z.enum(auditActorTypeValues);
export const auditStatusSchema = z.enum(auditStatusValues);
export const aiInvocationStatusSchema = z.enum(aiInvocationStatusValues);

export const artifactInputSchema = z.object({
  kind: artifactKindSchema,
  name: z.string().min(1).max(255),
  contentType: z.string().min(1).max(255),
  storageKey: z.string().min(1).max(512).optional(),
  textContent: z.string().optional(),
  payload: z.record(z.any()).optional(),
  metadata: z.record(z.any()).optional(),
});

export type DeviceType = z.infer<typeof deviceTypeSchema>;
export type PairSessionStatus = z.infer<typeof pairSessionStatusSchema>;
export type RuntimeConnectionStatus = z.infer<typeof runtimeConnectionStatusSchema>;
export type TaskStatus = z.infer<typeof taskStatusSchema>;
export type ArtifactKind = z.infer<typeof artifactKindSchema>;
export type SubscriptionStatus = z.infer<typeof subscriptionStatusSchema>;
export type AiProvider = z.infer<typeof aiProviderSchema>;
export type UserRole = z.infer<typeof userRoleSchema>;
export type ConnectionProvider = z.infer<typeof connectionProviderSchema>;
export type IntegrationAuthType = z.infer<typeof integrationAuthTypeSchema>;
export type IntegrationConnectionStatus = z.infer<typeof integrationConnectionStatusSchema>;
export type OauthStateStatus = z.infer<typeof oauthStateStatusSchema>;
export type McpTransport = z.infer<typeof mcpTransportSchema>;
export type McpAuthType = z.infer<typeof mcpAuthTypeSchema>;
export type McpServerStatus = z.infer<typeof mcpServerStatusSchema>;
export type AuditActorType = z.infer<typeof auditActorTypeSchema>;
export type AuditStatus = z.infer<typeof auditStatusSchema>;
export type AiInvocationStatus = z.infer<typeof aiInvocationStatusSchema>;
export type ArtifactInput = z.infer<typeof artifactInputSchema>;
