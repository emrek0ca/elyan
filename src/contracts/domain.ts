import { z } from "zod";
import { hasRawBinaryUploadHint } from "../lib/derived-data.js";
import {
  elyanAssistantBlockEnvelopeSchema,
  elyanAssistantBlockTypeValues,
  elyanAssistantBlockVisibilityValues,
} from "./assistant-block-schemas.js";

export {
  ELYAN_ASSISTANT_BLOCK_ENVELOPE_VERSION,
  elyanAssistantBlockDataSchemaByType,
  elyanAssistantBlockEnvelopeSchema,
  elyanAssistantBlockEnvelopeSchemaByType,
  elyanLegacyAssistantBlockTypeValues,
  elyanAssistantBlockSourceSchema,
  elyanAssistantBlockSourceValues,
  elyanAssistantBlockTransportV4Schema,
  elyanAssistantBlockTypeValues,
  elyanAssistantBlockVisibilityValues,
  elyanSourceWidgetBlockTypeValues,
} from "./assistant-block-schemas.js";

export const deviceTypeValues = ["mobile", "desktop"] as const;
export const pairSessionStatusValues = [
  "pending",
  "claimed",
  "expired",
] as const;
export const runtimeConnectionStatusValues = [
  "online",
  "busy",
  "idle",
  "offline",
] as const;
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
export const subscriptionStatusValues = [
  "free",
  "trialing",
  "active",
  "past_due",
  "canceled",
] as const;
export const aiProviderValues = ["groq"] as const;
export const userRoleValues = ["user", "admin"] as const;
export const connectionProviderValues = [
  "google",
  "apple",
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
export const integrationAuthTypeValues = [
  "oauth2",
  "api_key",
  "webhook",
  "none",
] as const;
export const integrationConnectionStatusValues = [
  "pending",
  "connected",
  "error",
  "revoked",
] as const;
export const oauthStateStatusValues = [
  "pending",
  "completed",
  "expired",
] as const;
export const mcpTransportValues = [
  "stdio",
  "remote",
  "oauth_remote",
  "streamable_http",
] as const;
export const mcpAuthTypeValues = [
  "none",
  "bearer",
  "oauth2",
  "api_key",
] as const;
export const mcpServerStatusValues = [
  "configured",
  "connected",
  "degraded",
  "revoked",
] as const;
export const auditActorTypeValues = ["user", "runtime", "system"] as const;
export const auditStatusValues = ["success", "failure"] as const;
export const aiInvocationStatusValues = [
  "success",
  "timeout",
  "fallback",
  "error",
] as const;
export const brainScopeValues = ["user", "shared"] as const;
export const datasetSourceValues = [
  "huggingface",
  "task_feedback",
  "manual_curation",
  "document_import",
] as const;
export const datasetFormatValues = [
  "chat_jsonl",
  "instruction_jsonl",
  "preference_jsonl",
  "document_corpus",
] as const;
export const datasetStatusValues = [
  "draft",
  "ready",
  "archived",
  "failed",
] as const;
export const trainingJobKindValues = [
  "sft",
  "lora",
  "dpo",
  "retrieval_index",
  "memory_extraction",
  "memory_consolidation",
  "memory_reconsolidation",
  "memory_index",
] as const;
export const trainingJobStatusValues = [
  "queued",
  "running",
  "completed",
  "failed",
  "canceled",
] as const;
export const modelArtifactStatusValues = [
  "draft",
  "ready",
  "archived",
  "failed",
] as const;
export const knowledgeDocumentStatusValues = [
  "processing",
  "ready",
  "failed",
  "archived",
] as const;
export const knowledgeSourceTypeValues = [
  "manual",
  "task_artifact",
  "external_url",
  "dataset",
  "feedback",
] as const;
export const chatSessionSourceValues = [
  "mobile",
  "desktop",
  "web",
  "email",
  "whatsapp",
] as const;
export const chatSessionStatusValues = ["active", "archived"] as const;
export const chatMessageRoleValues = ["user", "assistant", "system"] as const;
export const chatMessageStatusValues = [
  "queued",
  "running",
  "waiting_approval",
  "completed",
  "failed",
  "canceled",
] as const;
export const sessionGoalStatusValues = [
  "draft",
  "active",
  "paused",
  "done",
  "canceled",
] as const;
export const sessionGoalScheduleHintValues = [
  "on_next_message",
  "daily_08_00",
  "every_15m",
] as const;
export const elyanTaskTraceStatusValues = [
  "running",
  "completed",
  "failed",
  "waiting_approval",
] as const;
export const elyanAssistantActionableKindValues = [
  "approval_needed",
  "choose_device",
  "retry_option",
  "open_history",
  "restore_context",
] as const;
export const elyanTaskTraceStepStatusValues = [
  "pending",
  "running",
  "waiting_approval",
  "completed",
  "failed",
  "skipped",
] as const;
export const elyanTaskTraceStepIdValues = [
  "intent",
  "route",
  "plan",
  "context",
  "tool",
  "verify",
  "response",
] as const;

export const deviceTypeSchema = z.enum(deviceTypeValues);
export const pairSessionStatusSchema = z.enum(pairSessionStatusValues);
export const runtimeConnectionStatusSchema = z.enum(
  runtimeConnectionStatusValues,
);
export const taskStatusSchema = z.enum(taskStatusValues);
export const artifactKindSchema = z.enum(artifactKindValues);
export const subscriptionStatusSchema = z.enum(subscriptionStatusValues);
export const aiProviderSchema = z.enum(aiProviderValues);
export const userRoleSchema = z.enum(userRoleValues);
export const connectionProviderSchema = z.enum(connectionProviderValues);
export const integrationAuthTypeSchema = z.enum(integrationAuthTypeValues);
export const integrationConnectionStatusSchema = z.enum(
  integrationConnectionStatusValues,
);
export const oauthStateStatusSchema = z.enum(oauthStateStatusValues);
export const mcpTransportSchema = z.enum(mcpTransportValues);
export const mcpAuthTypeSchema = z.enum(mcpAuthTypeValues);
export const mcpServerStatusSchema = z.enum(mcpServerStatusValues);
export const auditActorTypeSchema = z.enum(auditActorTypeValues);
export const auditStatusSchema = z.enum(auditStatusValues);
export const aiInvocationStatusSchema = z.enum(aiInvocationStatusValues);
export const brainScopeSchema = z.enum(brainScopeValues);
export const datasetSourceSchema = z.enum(datasetSourceValues);
export const datasetFormatSchema = z.enum(datasetFormatValues);
export const datasetStatusSchema = z.enum(datasetStatusValues);
export const trainingJobKindSchema = z.enum(trainingJobKindValues);
export const trainingJobStatusSchema = z.enum(trainingJobStatusValues);
export const modelArtifactStatusSchema = z.enum(modelArtifactStatusValues);
export const knowledgeDocumentStatusSchema = z.enum(
  knowledgeDocumentStatusValues,
);
export const knowledgeSourceTypeSchema = z.enum(knowledgeSourceTypeValues);
export const chatSessionSourceSchema = z.enum(chatSessionSourceValues);
export const chatSessionStatusSchema = z.enum(chatSessionStatusValues);
export const chatMessageRoleSchema = z.enum(chatMessageRoleValues);
export const chatMessageStatusSchema = z.enum(chatMessageStatusValues);
export const elyanTaskTraceStatusSchema = z.enum(elyanTaskTraceStatusValues);
export const elyanAssistantBlockTypeSchema = z.enum(
  elyanAssistantBlockTypeValues,
);
export const elyanAssistantBlockVisibilitySchema = z.enum(
  elyanAssistantBlockVisibilityValues,
);
export const elyanAssistantActionableKindSchema = z.enum(
  elyanAssistantActionableKindValues,
);
export const elyanTaskTraceStepStatusSchema = z.enum(
  elyanTaskTraceStepStatusValues,
);
export const elyanTaskTraceStepIdSchema = z.string().regex(/^[a-zA-Z0-9_-]{1,80}$/);

export const artifactInputSchema = z
  .object({
    kind: artifactKindSchema,
    name: z.string().min(1).max(255),
    contentType: z.string().min(1).max(255),
    storageKey: z.string().min(1).max(512).optional(),
    textContent: z.string().optional(),
    payload: z.record(z.any()).optional(),
    metadata: z.record(z.any()).optional(),
  })
  .superRefine((input, ctx) => {
    if (hasRawBinaryUploadHint(input.payload)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["payload"],
        message:
          "raw binary upload payload is not accepted; send structured output only",
      });
    }

    if (hasRawBinaryUploadHint(input.metadata)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["metadata"],
        message:
          "raw binary upload payload is not accepted; send structured output only",
      });
    }
  });

export const documentBlockTypeValues = [
  "text",
  "table",
  "image",
  "heading",
  "page",
] as const;
export const documentRedactionStateValues = [
  "unredacted",
  "redacted",
  "partial",
  "failed",
] as const;
export const brainResultActionValues = [
  "export_pdf",
  "create_summary_doc",
  "generate_image",
] as const;

export const documentBlockTypeSchema = z.enum(documentBlockTypeValues);
export const documentRedactionStateSchema = z.enum(
  documentRedactionStateValues,
);
export const brainResultActionSchema = z.enum(brainResultActionValues);

const documentBboxSchema = z.tuple([
  z.number(),
  z.number(),
  z.number(),
  z.number(),
]);

export const documentBlockSchema = z.object({
  id: z.string().min(1).max(255),
  type: documentBlockTypeSchema,
  text: z.string().optional(),
  rows: z.array(z.array(z.string())).optional(),
  page: z.number().int().nonnegative().optional(),
  bbox: documentBboxSchema.optional(),
  confidence: z.number().min(0).max(1).optional(),
  sourceHash: z.string().min(1).max(255),
  mimeType: z.string().min(1).max(255).optional(),
  language: z.string().min(1).max(32).optional(),
  redactionState: documentRedactionStateSchema.optional(),
  lineage: z.array(z.string().min(1).max(255)).optional(),
  metadata: z.record(z.any()).optional(),
});

export const documentEnvelopeSchema = z.object({
  id: z.string().min(1).max(255).optional(),
  sourceHash: z.string().min(1).max(255),
  mimeType: z.string().min(1).max(255),
  language: z.string().min(1).max(32).optional(),
  page: z.number().int().nonnegative().optional(),
  bbox: documentBboxSchema.optional(),
  confidence: z.number().min(0).max(1).optional(),
  redactionState: documentRedactionStateSchema.optional(),
  lineage: z.array(z.string().min(1).max(255)).optional(),
  blocks: z.array(documentBlockSchema).min(1),
  metadata: z.record(z.any()).optional(),
});

export const brainCitationSchema = z.object({
  blockId: z.string().min(1).max(255),
  page: z.number().int().nonnegative().optional(),
  text: z.string(),
  sourceHash: z.string().min(1).max(255).optional(),
});

export const brainResultSchema = z.object({
  answer: z.string(),
  highlights: z.array(z.string()),
  citations: z.array(brainCitationSchema),
  extractedTables: z.array(z.unknown()).optional(),
  actions: z.array(brainResultActionSchema).optional(),
});
export const elyanTaskTraceStepSchema = z.object({
  id: elyanTaskTraceStepIdSchema,
  label: z.string().min(1).max(120),
  status: elyanTaskTraceStepStatusSchema,
  detail: z.string().max(240).optional(),
  resultSummary: z.string().max(240).optional(),
  capability: z.string().min(1).max(120).optional(),
  tool: z.string().min(1).max(120).optional(),
  verificationStatus: z.enum(["pending", "passed", "repaired", "failed"]).optional(),
  attemptCount: z.number().int().min(1).max(32).optional(),
  approval: z.object({
    token: z.string().min(1).max(512),
    tool: z.string().min(1).max(120),
    title: z.string().min(1).max(180),
    appLabel: z.string().max(120),
    expiresAt: z.number().finite().nullable().optional(),
    lines: z.array(z.object({
      label: z.string().min(1).max(120),
      value: z.string().max(500),
    })).max(8).default([]),
  }).optional(),
  startedAt: z.string().datetime().optional(),
  completedAt: z.string().datetime().optional(),
  durationMs: z.number().finite().nonnegative().optional(),
});
export const elyanTaskTraceBlockSchema = z.object({
  type: z.union([z.literal("dispatch_widget"), z.literal("task_trace")]),
  stableBlockId: z.string().min(1).max(255).optional(),
  visibility: elyanAssistantBlockVisibilitySchema.optional(),
  confidence: z.number().min(0).max(1).optional(),
  priority: z.number().int().min(0).max(3).optional(),
  cacheDigest: z.string().min(1).max(255).optional(),
  renderHints: z.record(z.any()).optional(),
  taskId: z.string().min(1).max(255),
  status: elyanTaskTraceStatusSchema,
  title: z.string().min(1).max(120),
  phase: z.string().min(1).max(80).optional(),
  summary: z.string().min(1).max(180).optional(),
  progressLabel: z.string().min(1).max(80).optional(),
  routeReason: z.string().min(1).max(240).optional(),
  activeStepId: elyanTaskTraceStepIdSchema.optional(),
  verification: z.object({
    status: z.enum(["pending", "passed", "repaired", "failed"]),
  }).passthrough().optional(),
  repairAttempts: z.number().int().min(0).max(32).optional(),
  stopReason: z.string().min(1).max(160).optional(),
  steps: z.array(elyanTaskTraceStepSchema).min(1),
});
const elyanAssistantBlockBaseSchema = z.object({
  stableBlockId: z.string().min(1).max(255).optional(),
  visibility: elyanAssistantBlockVisibilitySchema.optional(),
  confidence: z.number().min(0).max(1).optional(),
  priority: z.number().int().min(0).max(3).optional(),
  cacheDigest: z.string().min(1).max(255).optional(),
  renderHints: z.record(z.any()).optional(),
});
const elyanAssistantInfoItemSchema = z.object({
  label: z.string().min(1).max(120),
  value: z.string().min(1).max(240),
  confidence: z.number().min(0).max(1).optional(),
});
export const elyanAssistantTextBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("text"),
    markdown: z.string().min(1),
  });
export const elyanAssistantSummaryBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("summary"),
    title: z.string().min(1).max(120).optional(),
    summary: z.string().min(1).max(400),
  });
export const elyanAssistantNextStepsBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("next_steps"),
    title: z.string().min(1).max(120).optional(),
    items: z.array(z.string().min(1).max(240)).min(1).max(6),
  });
export const elyanAssistantStatusBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("status"),
    status: z
      .enum([
        "running",
        "waiting_approval",
        "needs_desktop",
        "completed",
        "failed",
        "retrying",
        "degraded",
      ])
      .default("running"),
    title: z.string().min(1).max(120),
    detail: z.string().min(1).max(240).optional(),
  });
export const elyanAssistantSecurityDecisionBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("security_decision"),
    request_type: z.enum([
      "secret_extraction_attempt",
      "system_prompt_extraction_attempt",
      "internal_endpoint_request",
      "database_credential_request",
      "payment_action_request",
      "destructive_action_request",
      "external_send_request",
    ]),
    is_sensitive: z.boolean(),
    should_refuse: z.boolean(),
    blocked_fields: z.array(z.string().min(1).max(120)).max(16),
    reason: z.string().min(1).max(500),
    safe_alternative: z.string().min(1).max(500),
    leaked_secret: z.literal(false),
    invented_internal_info: z.literal(false),
    requires_verified_admin_channel: z.boolean(),
    risk: z.enum(["low", "medium", "high", "critical"]),
  });
export const elyanAssistantInfoCardBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.enum(["attachment_context", "context_signal"]),
    title: z.string().min(1).max(120),
    items: z.array(elyanAssistantInfoItemSchema).min(1).max(8),
  });
export const elyanAssistantCodeBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("code"),
    code: z.string().min(1).max(24_000),
    language: z.string().min(1).max(40).optional(),
    filename: z.string().min(1).max(180).optional(),
    title: z.string().min(1).max(120).optional(),
    collapsed: z.boolean().optional(),
  });
export const elyanAssistantTableBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("table"),
    title: z.string().min(1).max(120).optional(),
    summary: z.string().min(1).max(240).optional(),
    columns: z.array(z.string().min(1).max(120)).min(1).max(12),
    rows: z
      .array(z.array(z.string().max(240)).min(1).max(12))
      .min(1)
      .max(80),
    previewRows: z
      .array(z.array(z.string().max(240)).min(1).max(12))
      .max(20)
      .optional(),
    totalRowCount: z.number().int().positive().optional(),
    caption: z.string().min(1).max(240).optional(),
    highlightRules: z.array(z.record(z.any())).max(12).optional(),
    density: z.enum(["compact", "comfortable", "spacious"]).optional(),
    style: z.record(z.any()).optional(),
    interactions: z.array(z.enum(["sort", "copy", "share", "fullscreen"])).max(8).optional(),
  });
const elyanAssistantChartSeriesSchema = z.object({
  name: z.string().min(1).max(120).optional(),
  labels: z.array(z.string().min(1).max(120)).min(1).max(240).optional(),
  values: z.array(z.number()).min(1).max(240).optional(),
  points: z.array(z.record(z.any())).min(1).max(1_500).optional(),
  data: z.array(z.any()).min(1).max(1_500).optional(),
});
export const elyanAssistantChartBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("chart"),
    title: z.string().min(1).max(120).optional(),
    chartType: z.enum([
      "bar",
      "line",
      "pie",
      "area",
      "scatter",
      "geometry",
      "function",
      "surface3d",
      "mesh",
      "heatmap",
    ]),
    labels: z.array(z.string().min(1).max(120)).min(1).max(240).optional(),
    values: z.array(z.number()).min(1).max(240).optional(),
    points: z.array(z.record(z.any())).min(1).max(1_500).optional(),
    data: z.array(z.any()).min(1).max(1_500).optional(),
    series: z.array(elyanAssistantChartSeriesSchema).min(1).max(8).optional(),
    expression: z.string().min(1).max(2_000).optional(),
    variables: z.array(z.string().min(1).max(24)).max(12).optional(),
    range: z.record(z.any()).optional(),
    fixed: z.record(z.number()).optional(),
    xLabel: z.string().min(1).max(120).optional(),
    yLabel: z.string().min(1).max(120).optional(),
    unit: z.string().min(1).max(40).optional(),
    renderer: z.string().min(1).max(40).optional(),
    caption: z.string().min(1).max(240).optional(),
    interactions: z
      .array(z.enum(["tooltip", "trackball", "zoom", "pan", "type_switch", "fullscreen", "share"]))
      .max(8)
      .optional(),
    theme: z.enum(["system", "presentation", "report", "minimal"]).optional(),
    style: z.record(z.any()).optional(),
  });
const elyanMathSurfaceRangeAxisSchema = z
  .tuple([z.number(), z.number()])
  .refine(([min, max]) => Number.isFinite(min) && Number.isFinite(max) && min < max, {
    message: "surface range axis must be finite and ascending",
  });
export const elyanAssistantMathSurface3DBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("math_surface_3d"),
    title: z.string().min(1).max(120).optional(),
    expression: z.string().min(1).max(240).optional(),
    variables: z.tuple([z.literal("x"), z.literal("y")]).optional(),
    range: z
      .object({
        x: elyanMathSurfaceRangeAxisSchema,
        y: elyanMathSurfaceRangeAxisSchema,
      })
      .optional(),
    resolution: z.number().int().min(10).max(120).optional(),
    zLabel: z.string().min(1).max(160).optional(),
    colorBy: z.enum(["z", "gradientMagnitude"]).optional(),
    mode: z.enum(["surface"]).optional(),
    interactive: z.boolean().optional(),
    cacheKey: z.string().min(1).max(128).optional(),
    renderer: z.enum(["plotly_local_webview"]).optional(),
    caption: z.string().min(1).max(240).optional(),
    error: z
      .object({
        code: z.string().min(1).max(80),
        message: z.string().min(1).max(240),
      })
      .optional(),
  });
export const elyanAssistantMathBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("math"),
    title: z.string().min(1).max(120).optional(),
    content: z.string().min(1).max(8_000),
    latex: z.string().min(1).max(8_000).optional(),
    displayMode: z.boolean().optional(),
    format: z.enum(["latex", "tex", "plain"]).optional(),
    result: z.string().min(1).max(240).optional(),
    explanation: z.string().min(1).max(480).optional(),
    steps: z
      .array(
        z.union([
          z.string().min(1).max(2_000),
          z.object({
            label: z.string().min(1).max(80).optional(),
            content: z.string().min(1).max(2_000),
            note: z.string().min(1).max(240).optional(),
          }),
        ]),
      )
      .max(8)
      .optional(),
  });
export const elyanAssistantSvgBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("svg"),
    title: z.string().min(1).max(120).optional(),
    caption: z.string().min(1).max(240).optional(),
    svg: z.string().min(1).max(80_000).optional(),
    markup: z.string().min(1).max(80_000).optional(),
    url: z.string().min(1).max(2_000).optional(),
    viewBox: z.string().min(1).max(80).optional(),
    exportFormats: z.array(z.enum(["svg", "png", "pdf"])).max(3).optional(),
    style: z.record(z.any()).optional(),
  });
export const elyanAssistantFileBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("file"),
    fileName: z.string().min(1).max(180),
    mimeType: z.string().min(1).max(120).optional(),
    sizeBytes: z.number().int().nonnegative().optional(),
    documentId: z.string().min(1).max(255).optional(),
    preview: z.string().min(1).max(400).optional(),
  });
export const elyanAssistantArtifactBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("artifact"),
    artifactType: z.string().min(1).max(80).optional(),
    artifactId: z.string().min(1).max(255).optional(),
    title: z.string().min(1).max(180).optional(),
    url: z.string().min(1).max(2_000).optional(),
    downloadUrl: z.string().min(1).max(2_000).optional(),
    sourceArtifactId: z.string().min(1).max(255).optional(),
    intrinsicSize: z
      .object({
        width: z.number().positive(),
        height: z.number().positive(),
      })
      .optional(),
    viewBox: z.string().min(1).max(80).optional(),
    mime: z.string().min(1).max(120).optional(),
    viewerHint: z.string().min(1).max(80).optional(),
    contentFamily: z.string().min(1).max(80).optional(),
    summary: z.string().min(1).max(400).optional(),
    preview: z.string().min(1).max(400).optional(),
    loadStrategy: z.string().min(1).max(80).optional(),
    payload: z.record(z.any()).optional(),
    metadata: z.record(z.any()).optional(),
  });
export const elyanAssistantActionableBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("actionable"),
    kind: elyanAssistantActionableKindSchema,
    title: z.string().min(1).max(120),
    detail: z.string().min(1).max(240).optional(),
  });
const elyanWebSearchResultSchema = z.object({
  title: z.string().min(1).max(240),
  url: z.string().min(1).max(512),
  snippet: z.string().max(400).optional(),
  sourceHost: z.string().max(120).optional(),
  verificationState: z.enum(["verified", "partial", "unverified"]),
});
export const elyanAssistantWebSearchBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("web_search"),
    query: z.string().min(1).max(320),
    queries: z.array(z.string().min(1).max(320)).min(1).max(4),
    confidence: z.enum(["high", "medium", "low"]),
    retrievedAt: z.string().datetime().optional(),
    results: z.array(elyanWebSearchResultSchema).min(1).max(8),
  });
export const elyanAssistantBlockGroupBlockSchema: z.ZodType<any> =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("block_group"),
    title: z.string().min(1).max(120).optional(),
    children: z
      .array(z.lazy(() => elyanAssistantBlockSchema))
      .min(1)
      .max(12),
  });

/* ── document_block: AI-generated multi-section document ─────────────── */
const elyanDocumentSectionSchema = z.object({
  heading: z.string().min(1).max(200).optional(),
  content: z.string().min(1).max(8_000),
  level: z.number().int().min(1).max(3).optional(),
  role: z.enum(["title", "summary", "body", "table", "appendix"]).optional(),
});
export const elyanAssistantDocumentBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("document_block"),
    title: z.string().min(1).max(200).optional(),
    sections: z.array(elyanDocumentSectionSchema).min(1).max(40),
    format: z.enum(["report", "letter", "outline", "notes"]).optional(),
    wordCount: z.number().int().nonnegative().optional(),
    summary: z.string().min(1).max(300).optional(),
    exportFormats: z.array(z.enum(["pdf", "docx", "xlsx"])).max(3).optional(),
    design: z
      .object({
        theme: z.enum(["system", "report", "editorial", "minimal"]).optional(),
        density: z.enum(["compact", "comfortable", "spacious"]).optional(),
        pageSize: z.enum(["A4", "Letter"]).optional(),
      })
      .passthrough()
      .optional(),
  });

/* ── attachment_ack: what the backend received/processed ─────────────── */
export const elyanAssistantAttachmentAckBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("attachment_ack"),
    summary: z.string().min(1).max(400),
    attachmentCount: z.number().int().nonnegative(),
    pageCount: z.number().int().nonnegative().optional(),
    chunkCount: z.number().int().nonnegative().optional(),
    hasTable: z.boolean().optional(),
    hasImage: z.boolean().optional(),
  });

/* ── image_analysis: structured result of image + OCR processing ─────── */
export const elyanAssistantImageAnalysisBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("image_analysis"),
    description: z.string().min(1).max(2_000),
    detectedText: z.string().max(2_000).optional(),
    tags: z.array(z.string().min(1).max(60)).max(12).optional(),
    confidence: z.number().min(0).max(1).optional(),
    language: z.string().max(20).optional(),
  });

export const elyanAssistantGoalProgressBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("goal_progress"),
    goalId: z.string().min(1).max(120),
    step: z.number().int().min(0).max(10_000),
    ofSteps: z.number().int().min(1).max(10_000),
    advancedTo: z.string().min(1).max(400),
    blocker: z.string().min(1).max(400).nullable(),
    done: z.boolean(),
  });

const elyanConnectorProviderSchema = z.enum([
  "gmail",
  "drive",
  "calendar",
  "notion",
  "github",
  "slack",
  "linear",
  "mcp",
  "connector",
]);
const elyanConnectorResultItemSchema = z
  .object({
    title: z.string().min(1).max(240),
    subtitle: z.string().min(1).max(240).optional(),
    detail: z.string().min(1).max(400).optional(),
    timestamp: z.string().min(1).max(120).optional(),
    url: z.string().min(1).max(2_000).optional(),
    kind: z.string().min(1).max(80).optional(),
    status: z.string().min(1).max(80).optional(),
    metadata: z.record(z.any()).optional(),
  })
  .passthrough();
export const elyanAssistantConnectorResultBlockSchema =
  elyanAssistantBlockBaseSchema.extend({
    type: z.literal("connector_result"),
    provider: elyanConnectorProviderSchema,
    tool: z.string().min(1).max(160),
    title: z.string().min(1).max(160),
    kind: z.string().min(1).max(80).optional(),
    summary: z.string().min(1).max(240).optional(),
    items: z.array(elyanConnectorResultItemSchema).min(1).max(80),
    columns: z.array(z.string().min(1).max(120)).min(1).max(8).optional(),
    rows: z.array(z.array(z.string().max(240)).min(1).max(8)).min(1).max(80).optional(),
    nextAction: z
      .object({
        kind: z.enum(["reauth", "open", "retry"]).optional(),
        label: z.string().min(1).max(80).optional(),
        url: z.string().min(1).max(2_000).optional(),
      })
      .optional(),
  });

export const elyanAssistantPassthroughBlockSchema = elyanAssistantBlockBaseSchema
  .extend({
    type: z.enum([
      "vision",
      "desktop_suggestion",
      "document_block_skeleton",
      "pdf_generate",
      "pdf_viewer",
      "terminal",
      "automation",
      // reasoning_trace BİLEREK yok: ham düşünce zinciri kalıcı bloklara
      // geçmez (normalizeAssistantMessageBlocks düşürme testi bunu korur);
      // mobil reasoning widget'ı ayrı stream kanalından beslenir.
      "capability_unavailable",
      "clarification",
      "memory_echo",
      "proactive_touch",
    ]),
  })
  .passthrough();

const elyanAssistantCanonicalEnvelopeCompatSchema = z.custom<
  Record<string, unknown>
>((value) => elyanAssistantBlockEnvelopeSchema.safeParse(value).success);

export const elyanAssistantBlockSchema: z.ZodType<any> = z.union([
  elyanAssistantCanonicalEnvelopeCompatSchema,
  elyanAssistantTextBlockSchema,
  elyanAssistantSummaryBlockSchema,
  elyanAssistantNextStepsBlockSchema,
  elyanAssistantStatusBlockSchema,
  elyanAssistantSecurityDecisionBlockSchema,
  elyanTaskTraceBlockSchema,
  elyanAssistantInfoCardBlockSchema,
  elyanAssistantWebSearchBlockSchema,
  elyanAssistantCodeBlockSchema,
  elyanAssistantTableBlockSchema,
  elyanAssistantChartBlockSchema,
  elyanAssistantMathSurface3DBlockSchema,
  elyanAssistantMathBlockSchema,
  elyanAssistantSvgBlockSchema,
  elyanAssistantFileBlockSchema,
  elyanAssistantArtifactBlockSchema,
  elyanAssistantActionableBlockSchema,
  elyanAssistantBlockGroupBlockSchema,
  elyanAssistantDocumentBlockSchema,
  elyanAssistantAttachmentAckBlockSchema,
  elyanAssistantImageAnalysisBlockSchema,
  elyanAssistantGoalProgressBlockSchema,
  elyanAssistantConnectorResultBlockSchema,
  elyanAssistantPassthroughBlockSchema,
]);

export type DeviceType = z.infer<typeof deviceTypeSchema>;
export type PairSessionStatus = z.infer<typeof pairSessionStatusSchema>;
export type RuntimeConnectionStatus = z.infer<
  typeof runtimeConnectionStatusSchema
>;
export type TaskStatus = z.infer<typeof taskStatusSchema>;
export type ArtifactKind = z.infer<typeof artifactKindSchema>;
export type SubscriptionStatus = z.infer<typeof subscriptionStatusSchema>;
export type AiProvider = z.infer<typeof aiProviderSchema>;
export type UserRole = z.infer<typeof userRoleSchema>;
export type ConnectionProvider = z.infer<typeof connectionProviderSchema>;
export type IntegrationAuthType = z.infer<typeof integrationAuthTypeSchema>;
export type IntegrationConnectionStatus = z.infer<
  typeof integrationConnectionStatusSchema
>;
export type OauthStateStatus = z.infer<typeof oauthStateStatusSchema>;
export type McpTransport = z.infer<typeof mcpTransportSchema>;
export type McpAuthType = z.infer<typeof mcpAuthTypeSchema>;
export type McpServerStatus = z.infer<typeof mcpServerStatusSchema>;
export type AuditActorType = z.infer<typeof auditActorTypeSchema>;
export type AuditStatus = z.infer<typeof auditStatusSchema>;
export type AiInvocationStatus = z.infer<typeof aiInvocationStatusSchema>;
export type BrainScope = z.infer<typeof brainScopeSchema>;
export type DatasetSource = z.infer<typeof datasetSourceSchema>;
export type DatasetFormat = z.infer<typeof datasetFormatSchema>;
export type DatasetStatus = z.infer<typeof datasetStatusSchema>;
export type TrainingJobKind = z.infer<typeof trainingJobKindSchema>;
export type TrainingJobStatus = z.infer<typeof trainingJobStatusSchema>;
export type ModelArtifactStatus = z.infer<typeof modelArtifactStatusSchema>;
export type KnowledgeDocumentStatus = z.infer<
  typeof knowledgeDocumentStatusSchema
>;
export type KnowledgeSourceType = z.infer<typeof knowledgeSourceTypeSchema>;
export type ChatSessionSource = z.infer<typeof chatSessionSourceSchema>;
export type ChatSessionStatus = z.infer<typeof chatSessionStatusSchema>;
export type ChatMessageRole = z.infer<typeof chatMessageRoleSchema>;
export type ChatMessageStatus = z.infer<typeof chatMessageStatusSchema>;
export type SessionGoalStatus = (typeof sessionGoalStatusValues)[number];
export type SessionGoalScheduleHint = (typeof sessionGoalScheduleHintValues)[number];
export type ElyanTaskTraceStatus = z.infer<typeof elyanTaskTraceStatusSchema>;
export type ElyanAssistantBlockType = z.infer<
  typeof elyanAssistantBlockTypeSchema
>;
export type ElyanAssistantBlockVisibility = z.infer<
  typeof elyanAssistantBlockVisibilitySchema
>;
export type ElyanAssistantActionableKind = z.infer<
  typeof elyanAssistantActionableKindSchema
>;
export type ElyanTaskTraceStepStatus = z.infer<
  typeof elyanTaskTraceStepStatusSchema
>;
export type ElyanTaskTraceStepId = z.infer<typeof elyanTaskTraceStepIdSchema>;
export type ArtifactInput = z.infer<typeof artifactInputSchema>;
export type DocumentBlockType = z.infer<typeof documentBlockTypeSchema>;
export type DocumentRedactionState = z.infer<
  typeof documentRedactionStateSchema
>;
export type BrainResultAction = z.infer<typeof brainResultActionSchema>;
export type DocumentBlock = z.infer<typeof documentBlockSchema>;
export type DocumentEnvelope = z.infer<typeof documentEnvelopeSchema>;
export type BrainCitation = z.infer<typeof brainCitationSchema>;
export type BrainResult = z.infer<typeof brainResultSchema>;
export type ElyanTaskTraceStep = z.infer<typeof elyanTaskTraceStepSchema>;
export type ElyanTaskTraceBlock = z.infer<typeof elyanTaskTraceBlockSchema>;
export type ElyanAssistantTextBlock = z.infer<
  typeof elyanAssistantTextBlockSchema
>;
export type ElyanAssistantSummaryBlock = z.infer<
  typeof elyanAssistantSummaryBlockSchema
>;
export type ElyanAssistantNextStepsBlock = z.infer<
  typeof elyanAssistantNextStepsBlockSchema
>;
export type ElyanAssistantStatusBlock = z.infer<
  typeof elyanAssistantStatusBlockSchema
>;
export type ElyanAssistantInfoCardBlock = z.infer<
  typeof elyanAssistantInfoCardBlockSchema
>;
export type ElyanAssistantCodeBlock = z.infer<
  typeof elyanAssistantCodeBlockSchema
>;
export type ElyanAssistantTableBlock = z.infer<
  typeof elyanAssistantTableBlockSchema
>;
export type ElyanAssistantChartBlock = z.infer<
  typeof elyanAssistantChartBlockSchema
>;
export type ElyanAssistantMathSurface3DBlock = z.infer<
  typeof elyanAssistantMathSurface3DBlockSchema
>;
export type ElyanAssistantMathBlock = z.infer<
  typeof elyanAssistantMathBlockSchema
>;
export type ElyanAssistantSvgBlock = z.infer<
  typeof elyanAssistantSvgBlockSchema
>;
export type ElyanAssistantFileBlock = z.infer<
  typeof elyanAssistantFileBlockSchema
>;
export type ElyanAssistantArtifactBlock = z.infer<
  typeof elyanAssistantArtifactBlockSchema
>;
export type ElyanAssistantActionableBlock = z.infer<
  typeof elyanAssistantActionableBlockSchema
>;
export type ElyanAssistantBlockGroupBlock = z.infer<
  typeof elyanAssistantBlockGroupBlockSchema
>;
export type ElyanAssistantWebSearchBlock = z.infer<
  typeof elyanAssistantWebSearchBlockSchema
>;
export type ElyanAssistantDocumentBlock = z.infer<
  typeof elyanAssistantDocumentBlockSchema
>;
export type ElyanAssistantAttachmentAckBlock = z.infer<
  typeof elyanAssistantAttachmentAckBlockSchema
>;
export type ElyanAssistantImageAnalysisBlock = z.infer<
  typeof elyanAssistantImageAnalysisBlockSchema
>;
export type ElyanAssistantGoalProgressBlock = z.infer<
  typeof elyanAssistantGoalProgressBlockSchema
>;
export type ElyanAssistantConnectorResultBlock = z.infer<
  typeof elyanAssistantConnectorResultBlockSchema
>;
export type ElyanAssistantSecurityDecisionBlock = z.infer<
  typeof elyanAssistantSecurityDecisionBlockSchema
>;
export type ElyanAssistantBlock = z.infer<typeof elyanAssistantBlockSchema>;
