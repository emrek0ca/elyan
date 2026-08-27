import { z } from "zod";

export const INTERACTION_CONTRACT = "elyan.interaction.v1";

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

export type InteractionKind = (typeof interactionKindValues)[number];
export type InteractionAction = (typeof interactionActionValues)[number];

/**
 * Bir etkileşim türünün kullanıcıya sunduğu eylem yüzeyi.
 *
 * Bu tek yer otoritedir: istemci kart tipini `waiting_approval` durumundan
 * ÇIKARMAZ, buradaki `availableActions` listesini okur.
 */
export function interactionActionsForKind(
  kind: InteractionKind,
): readonly InteractionAction[] {
  return kind === "clarification"
    ? (["answer"] as const)
    : (["approve", "reject"] as const);
}

const clarificationAliases = new Set([
  "clarification",
  "clarify",
  "question",
  "ask",
]);

const approvalAliases = new Set([
  "approval",
  "desktop_plan",
  "plan_approval",
  "plan",
]);

/**
 * Serbest biçimli `kind` alanını kanonik etkileşim türüne indirger.
 *
 * Masaüstü tarihsel olarak `kind` alanına yetenek adı ("email_send") yazar;
 * bu bir izin sorusudur, netleştirme değil. Tanınmayan her değer bu yüzden
 * `permission`'a düşer — en dar eylem yüzeyi değil, en doğru olanı.
 */
export function normalizeInteractionKind(value: unknown): InteractionKind {
  const raw = typeof value === "string" ? value.trim().toLowerCase() : "";
  if (clarificationAliases.has(raw)) return "clarification";
  if (approvalAliases.has(raw)) return "approval";
  return "permission";
}

export const interactionResolutionSchema = z
  .object({
    approved: z.boolean().nullable().optional(),
    state: z.string().max(64).optional(),
    action: z.enum(interactionActionValues).optional(),
    answer: z.string().max(4_000).optional(),
    resolvedAt: z.string().optional(),
    revision: z.number().int().positive().max(1_000_000).optional(),
  })
  .passthrough();

const interactionBaseShape = {
  contract: z.literal(INTERACTION_CONTRACT),
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

/**
 * Zarfın TEK üretim noktası: eylem yüzeyi türden türetilir, elle yazılmaz.
 */
export function buildInteractionEnvelope(input: {
  id: string;
  taskId: string;
  taskRunId: string;
  kind: InteractionKind;
  revision: number;
  expiresAt: string;
  question?: string;
  summary?: string;
  resolution?: Record<string, unknown> | null;
  extra?: Record<string, unknown>;
}): InteractionEnvelope {
  const question = (input.question ?? "").trim().slice(0, 1_000);
  const summary = (input.summary ?? "").trim().slice(0, 1_000);
  return interactionEnvelopeSchema.parse({
    ...(input.extra ?? {}),
    contract: INTERACTION_CONTRACT,
    id: input.id.slice(0, 255),
    taskId: input.taskId.slice(0, 255),
    taskRunId: input.taskRunId.slice(0, 255),
    kind: input.kind,
    revision: Math.max(1, Math.floor(input.revision)),
    availableActions: [...interactionActionsForKind(input.kind)],
    ...(question ? { question } : {}),
    ...(summary ? { summary } : {}),
    expiresAt: input.expiresAt,
    resolution: input.resolution ?? null,
  });
}

/**
 * Bir eylem, verilen etkileşim türünde gerçekten mümkün mü?
 *
 * Netleştirmeye "approve" gelmesi bir onay değildir; cevabın kendisi eksiktir.
 */
export function isInteractionActionAllowed(
  kind: InteractionKind,
  action: InteractionAction,
): boolean {
  return interactionActionsForKind(kind).includes(action);
}
