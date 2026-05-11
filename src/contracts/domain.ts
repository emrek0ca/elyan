import { z } from "zod";

export const deviceTypeValues = ["mobile", "desktop"] as const;
export const pairSessionStatusValues = ["pending", "claimed", "expired"] as const;
export const runtimeConnectionStatusValues = ["online", "busy", "idle", "offline"] as const;
export const taskStatusValues = [
  "queued",
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
export const aiProviderValues = ["openai", "claude", "ollama", "groq"] as const;

export const deviceTypeSchema = z.enum(deviceTypeValues);
export const pairSessionStatusSchema = z.enum(pairSessionStatusValues);
export const runtimeConnectionStatusSchema = z.enum(runtimeConnectionStatusValues);
export const taskStatusSchema = z.enum(taskStatusValues);
export const artifactKindSchema = z.enum(artifactKindValues);
export const subscriptionStatusSchema = z.enum(subscriptionStatusValues);
export const aiProviderSchema = z.enum(aiProviderValues);

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
export type ArtifactInput = z.infer<typeof artifactInputSchema>;
