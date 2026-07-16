import { z } from "zod";
import {
  brainScopeSchema,
  datasetFormatSchema,
  datasetSourceSchema,
  datasetStatusSchema,
  knowledgeSourceTypeSchema,
  modelArtifactStatusSchema,
  trainingJobKindSchema,
} from "../../contracts/domain.js";
import { hasRawBinaryUploadHint } from "../../lib/derived-data.js";
import { boundedJsonRecordSchema } from "../../lib/json-boundary.js";

const jsonRecordSchema = boundedJsonRecordSchema;
const memoryLifecycleStatusSchema = z.enum([
  "active",
  "contested",
  "superseded",
  "soft_deleted",
  "stale",
]);
const memorySurfaceSchema = z.enum(["all", "facts", "episodes"]);
const brainChatConversationItemSchema = z.object({
  role: z.enum(["system", "user", "assistant"]),
  content: z.string().trim().min(1).max(20_000),
});

function looksLikeDataUri(value: unknown): boolean {
  return (
    typeof value === "string" &&
    /^data:[a-z0-9.+-]+\/[a-z0-9.+-]+;base64,/i.test(value.trim())
  );
}

const knowledgeDocumentChunkObjectSchema = z
  .object({
    text: z.string().trim().min(1).max(8_000).optional(),
    content: z.string().trim().min(1).max(8_000).optional(),
    pageNumber: z.coerce.number().int().min(0).optional(),
    page_number: z.coerce.number().int().min(0).optional(),
    kind: z.string().trim().max(80).optional(),
    metadata: jsonRecordSchema.optional(),
  })
  .passthrough()
  .superRefine((chunk, ctx) => {
    if (!chunk.text && !chunk.content) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["text"],
        message: "chunk text or content is required",
      });
    }

    if (looksLikeDataUri(chunk.text) || looksLikeDataUri(chunk.content)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["text"],
        message:
          "raw binary upload payload is not accepted; send text/chunks only",
      });
    }

    if (hasRawBinaryUploadHint(chunk)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["metadata"],
        message:
          "raw binary upload payload is not accepted; send text/chunks only",
      });
    }
  });

const knowledgeDocumentChunkSchema = z.union([
  z.string().min(1).max(8_000),
  knowledgeDocumentChunkObjectSchema,
]);

export const brainProfileQuerySchema = z.object({});

export const brainChatBodySchema = z.object({
  prompt: z.string().trim().min(1).max(20_000),
  title: z.string().trim().min(1).max(200).optional(),
  conversation: z.array(brainChatConversationItemSchema).max(24).default([]),
});

// Desktop yapılandırılmış planlama isteği (elyan.plan.v2). `prompt` masaüstünün
// structured_planner.planning_prompt() çıktısıdır; büyük olabilir (araç
// kataloğu + bağlam + yanıt şeması tek zarf).
export const desktopPlanBodySchema = z.object({
  contract: z.literal("elyan.plan.v2"),
  prompt: z.string().trim().min(1).max(48_000),
  repair: z.boolean().default(false),
  taskId: z.string().trim().max(120).optional(),
});

export const connectorWriteApprovalParamsSchema = z.object({
  token: z
    .string()
    .regex(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    ),
});

export const connectorWriteApprovalBodySchema = z.object({
  approved: z.boolean(),
});

export const datasetParamsSchema = z.object({
  datasetId: z.string().uuid(),
});

export const createDatasetManifestBodySchema = z.object({
  name: z.string().min(1).max(160),
  source: datasetSourceSchema,
  format: datasetFormatSchema,
  scope: brainScopeSchema.default("user"),
  description: z.string().max(4_000).optional(),
  locator: z.string().max(4_000).optional(),
  languageTags: z.array(z.string().min(2).max(32)).max(16).default([]),
  recordCount: z.coerce.number().int().min(0).default(0),
  tokenEstimate: z.coerce.number().int().min(0).default(0),
  metadata: jsonRecordSchema.default({}),
});

export const updateDatasetManifestBodySchema = z.object({
  name: z.string().min(1).max(160).optional(),
  description: z.string().max(4_000).nullable().optional(),
  locator: z.string().max(4_000).nullable().optional(),
  status: datasetStatusSchema.optional(),
  languageTags: z.array(z.string().min(2).max(32)).max(16).optional(),
  recordCount: z.coerce.number().int().min(0).optional(),
  tokenEstimate: z.coerce.number().int().min(0).optional(),
  metadata: jsonRecordSchema.optional(),
});

export const trainingJobParamsSchema = z.object({
  jobId: z.string().uuid(),
});

export const createTrainingJobBodySchema = z.object({
  name: z.string().min(1).max(160),
  kind: trainingJobKindSchema,
  scope: brainScopeSchema.default("user"),
  baseModel: z.string().min(1).max(160),
  datasetManifestId: z.string().uuid().optional(),
  config: jsonRecordSchema.default({}),
});

export const modelArtifactParamsSchema = z.object({
  artifactId: z.string().uuid(),
});

export const createModelArtifactBodySchema = z.object({
  name: z.string().min(1).max(160),
  scope: brainScopeSchema.default("user"),
  trainingJobId: z.string().uuid().optional(),
  provider: z.string().min(1).max(80).default("manual"),
  baseModel: z.string().min(1).max(160),
  adapterKind: z.string().min(1).max(80).default("lora"),
  status: modelArtifactStatusSchema.default("draft"),
  storageUri: z.string().max(4_000).optional(),
  checksum: z.string().min(8).max(128).optional(),
  metadata: jsonRecordSchema.default({}),
});

export const updateModelArtifactBodySchema = z.object({
  status: modelArtifactStatusSchema.optional(),
  storageUri: z.string().max(4_000).nullable().optional(),
  checksum: z.string().min(8).max(128).nullable().optional(),
  metadata: jsonRecordSchema.optional(),
});

export const createKnowledgeDocumentBodySchema = z
  .object({
    title: z.string().min(1).max(200),
    scope: brainScopeSchema.default("user"),
    sourceType: knowledgeSourceTypeSchema,
    sourceUri: z.string().max(4_000).optional(),
    text: z.string().max(200_000).optional(),
    chunks: z.array(knowledgeDocumentChunkSchema).max(256).optional(),
    learningMode: z
      .enum(["retrieval_only", "shared_corpus_train"])
      .default("retrieval_only"),
    languageTags: z.array(z.string().min(2).max(32)).max(16).default([]),
    autoQueueTraining: z.boolean().optional(),
    metadata: jsonRecordSchema.default({}),
  })
  .superRefine((input, ctx) => {
    if (looksLikeDataUri(input.text)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["text"],
        message:
          "raw binary upload payload is not accepted; send text/chunks only",
      });
    }

    if ((input.chunks ?? []).some((chunk) => looksLikeDataUri(chunk))) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["chunks"],
        message:
          "raw binary upload payload is not accepted; send text/chunks only",
      });
    }

    if (!input.text && !input.chunks?.length) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["text"],
        message: "text or chunks is required",
      });
    }

    if (hasRawBinaryUploadHint(input.metadata)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["metadata"],
        message:
          "raw binary upload payload is not accepted; send text/chunks only",
      });
    }

    if (
      hasRawBinaryUploadHint(input.text) ||
      hasRawBinaryUploadHint(input.chunks)
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["text"],
        message:
          "raw binary upload payload is not accepted; send text/chunks only",
      });
    }
  });

export const knowledgeDocumentParamsSchema = z.object({
  documentId: z.string().uuid(),
});

export const searchKnowledgeBodySchema = z.object({
  query: z.string().min(2).max(500),
  limit: z.coerce.number().int().min(1).max(20).default(8),
});

export const brainMemoryParamsSchema = z.object({
  memoryId: z.string().uuid(),
});

export const listBrainMemoryQuerySchema = z.object({
  userId: z.string().uuid().optional(),
  includeSoftDeleted: z.coerce.boolean().default(false),
  limit: z.coerce.number().int().min(1).max(100).default(40),
  surface: memorySurfaceSchema.default("all"),
  lifecycle: z
    .string()
    .trim()
    .optional()
    .transform((value) =>
      value
        ? value
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean)
        : [],
    )
    .pipe(z.array(memoryLifecycleStatusSchema).max(5)),
});

export const mutateBrainMemoryBodySchema = z.object({
  userId: z.string().uuid().optional(),
  reason: z.string().trim().min(1).max(500).optional(),
  supersedesMemoryId: z.string().uuid().optional(),
});

export const updateBrainMemoryBodySchema = z.object({
  userId: z.string().uuid().optional(),
  reason: z.string().trim().min(1).max(500).optional(),
  title: z.string().trim().min(1).max(120).optional(),
  content: z.string().trim().min(1).max(1000),
});

export const reviewInteractionParamsSchema = z.object({
  interactionId: z.string().uuid(),
});

export const listBrainReviewQuerySchema = z.object({
  limit: z.coerce.number().int().min(1).max(100).default(40),
});

export const approveBrainReviewBodySchema = z.object({
  correctedAnswer: z.string().trim().min(1).max(4_000).optional(),
  reason: z.string().trim().min(1).max(500).optional(),
});

export const rejectBrainReviewBodySchema = z.object({
  reason: z.string().trim().min(1).max(500).optional(),
});
