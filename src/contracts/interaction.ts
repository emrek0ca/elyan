import { z } from "zod";

export const interactionKindValues = [
  "clarification",
  "permission",
  "approval",
] as const;

export const interactionActionValues = [
  "answer",
  "approve",
  "reject",
] as const;

const interactionBaseShape = {
  contract: z.literal("elyan.interaction.v1"),
  id: z.string().min(1).max(255),
  taskId: z.string().min(1).max(255),
  taskRunId: z.string().min(1).max(255),
  revision: z.number().int().positive().max(1_000_000),
  question: z.string().min(1).max(1_000).optional(),
  summary: z.string().min(1).max(1_000).optional(),
  expiresAt: z.string().datetime(),
  resolution: z.record(z.string(), z.unknown()).nullable(),
} as const;

const clarificationInteractionSchema = z.object({
  ...interactionBaseShape,
  kind: z.literal("clarification"),
  availableActions: z.tuple([z.literal("answer")]),
}).passthrough();

const permissionInteractionSchema = z.object({
  ...interactionBaseShape,
  kind: z.literal("permission"),
  availableActions: z.tuple([z.literal("approve"), z.literal("reject")]),
}).passthrough();

const approvalInteractionSchema = z.object({
  ...interactionBaseShape,
  kind: z.literal("approval"),
  availableActions: z.tuple([z.literal("approve"), z.literal("reject")]),
}).passthrough();

/**
 * Kullanıcıdan beklenen tek, eklemeli etkileşim zarfı.
 *
 * `waiting_approval` yalnızca taşıma durumudur; hangi UI/yanıtın mümkün
 * olduğunu bu zarf belirler. Eski approval alanları ayrı tutulur ve geriye
 * dönük istemciler için korunur.
 */
export const interactionEnvelopeSchema = z.union([
  clarificationInteractionSchema,
  permissionInteractionSchema,
  approvalInteractionSchema,
]);

export type InteractionEnvelope = z.infer<typeof interactionEnvelopeSchema>;
