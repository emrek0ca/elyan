import { z } from "zod/v4";

// `domain.ts` uses the repository's zod/v3 compatibility import while this
// transport schema intentionally uses zod/v4. Keep the wire shape identical
// without nesting a schema instance from the other runtime.
const interactionEnvelopeCompatBaseShape = {
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

const interactionEnvelopeCompatSchema = z.union([
  z.object({
    ...interactionEnvelopeCompatBaseShape,
    kind: z.literal("clarification"),
    availableActions: z.tuple([z.literal("answer")]),
  }).passthrough(),
  z.object({
    ...interactionEnvelopeCompatBaseShape,
    kind: z.literal("permission"),
    availableActions: z.tuple([z.literal("approve"), z.literal("reject")]),
  }).passthrough(),
  z.object({
    ...interactionEnvelopeCompatBaseShape,
    kind: z.literal("approval"),
    availableActions: z.tuple([z.literal("approve"), z.literal("reject")]),
  }).passthrough(),
]);

/**
 * Canonical per-block envelope version. This is intentionally independent of
 * the existing `elyan_blocks.v2` transport contract, which remains unchanged.
 */
export const ELYAN_ASSISTANT_BLOCK_ENVELOPE_VERSION = 1 as const;

/** Source-typed widgets. Keep this ordered list as the only routing inventory. */
export const elyanSourceWidgetBlockTypeValues = [
  "mail_list",
  "mail_detail",
  "calendar_agenda",
  "drive_files",
  "notion_page",
  "github_activity",
  "slack_messages",
] as const;

/**
 * Types already persisted before source widgets gained the canonical envelope.
 * `connector_result` stays here only so stored messages remain readable.
 */
export const elyanLegacyAssistantBlockTypeValues = [
  "text",
  "summary",
  "next_steps",
  "status",
  "security_decision",
  "task_trace",
  "attachment_context",
  "context_signal",
  "web_search",
  "code",
  "table",
  "chart",
  "math_surface_3d",
  "math",
  "svg",
  "file",
  "artifact",
  "actionable",
  "block_group",
  "memory_echo",
  "proactive_touch",
  "document_block",
  "attachment_ack",
  "image_analysis",
  "vision",
  "goal_progress",
  "desktop_suggestion",
  "document_block_skeleton",
  "pdf_generate",
  "pdf_viewer",
  "terminal",
  "automation",
  "reasoning_trace",
  "capability_unavailable",
  "clarification",
  "connector_result",
] as const;

/**
 * Canonical blocks introduced with the typed envelope that are not source
 * widgets. `tool_call` surfaces the agent's tool activity (which tool, how
 * long, what it found) as a first-class, user-visible block.
 */
export const elyanCanonicalBlockTypeValues = ["tool_call", "dispatch_widget"] as const;

/**
 * Legacy type names that map onto a canonical type on read. `task_trace`
 * became `dispatch_widget`: the block only ships when a dispatch is live, and
 * the widget renders the whole run, not just a trace.
 */
export const elyanAssistantBlockTypeAliases: Record<string, ElyanAssistantBlockTypeValue> = {
  task_trace: "dispatch_widget",
};

export function canonicalAssistantBlockType(type: string): string {
  return elyanAssistantBlockTypeAliases[type] ?? type;
}

export function isDispatchWidgetType(type: unknown): boolean {
  return type === "dispatch_widget" || type === "task_trace";
}

/** Complete canonical type inventory used by new envelopes. */
export const elyanAssistantBlockTypeValues = [
  ...elyanLegacyAssistantBlockTypeValues,
  ...elyanSourceWidgetBlockTypeValues,
  ...elyanCanonicalBlockTypeValues,
] as const;

export const elyanAssistantBlockVisibilityValues = [
  "user_visible",
  "assistant_internal_by_default",
] as const;

export const elyanAssistantBlockSourceValues = [
  "elyan",
  "runtime",
  "web",
  "document",
  "user_attachment",
  "legacy",
  "gmail",
  "calendar",
  "drive",
  "notion",
  "github",
  "slack",
  "linear",
  "connector",
  "mcp",
] as const;

export const elyanAssistantBlockTypeV4Schema = z.enum(
  elyanAssistantBlockTypeValues,
);
export const elyanAssistantBlockVisibilityV4Schema = z.enum(
  elyanAssistantBlockVisibilityValues,
);
export const elyanAssistantBlockSourceSchema = z.enum(
  elyanAssistantBlockSourceValues,
);

export type ElyanAssistantBlockTypeValue =
  (typeof elyanAssistantBlockTypeValues)[number];

const safeErrorSchema = z.strictObject({
  code: z.string().min(1).max(80),
  message: z.string().min(1).max(240),
});

const renderHintsSchema = z.record(z.string(), z.unknown());
const stringRecordSchema = z.record(z.string(), z.unknown());

const linkOpenActionSchema = z.strictObject({
  kind: z.literal("link.open"),
  url: z.string().min(1).max(2_000),
});
const mailOpenActionSchema = z.strictObject({
  kind: z.literal("mail.open"),
  messageId: z.string().min(1).max(255),
  threadId: z.string().min(1).max(255),
});
const calendarMenuActionSchema = z.strictObject({
  kind: z.literal("calendar.menu"),
  eventId: z.string().min(1).max(255),
  url: z.string().min(1).max(2_000).optional(),
});

const textDataSchema = z.looseObject({ markdown: z.string().min(1) });
const summaryDataSchema = z.looseObject({
  title: z.string().min(1).max(120).optional(),
  summary: z.string().min(1).max(400),
});
const nextStepsDataSchema = z.looseObject({
  title: z.string().min(1).max(120).optional(),
  items: z.array(z.string().min(1).max(240)).min(1).max(6),
});
const statusDataSchema = z.looseObject({
  status: z.enum([
    "running",
    "waiting_approval",
    "needs_desktop",
    "completed",
    "failed",
    "retrying",
    "degraded",
  ]),
  title: z.string().min(1).max(120),
  detail: z.string().min(1).max(240).optional(),
});
const securityDecisionDataSchema = z.looseObject({
  request_type: z.string().min(1).max(120),
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
const taskTraceDataSchema = z.looseObject({
  taskId: z.string().min(1).max(255),
  status: z.enum(["running", "completed", "failed", "waiting_approval"]),
  title: z.string().min(1).max(120),
  phase: z.string().min(1).max(80).optional(),
  summary: z.string().min(1).max(180).optional(),
  activeStepId: z.string().min(1).max(80).optional(),
  // AÇIK ONAY ALANI. `looseObject` olduğu için yazılmayan bir alan doğrulamadan
  // geçer ama YAYIMLANAN şemada görünmez; istemci tarafı o zaman alanı
  // türetmeye kalkar. Canlı sonuç (2026-08-21): mobil onay ihtiyacını adım
  // durumlarından türetiyordu, sunucu hiçbir adımı öyle işaretlemiyordu,
  // kullanıcıya onay düğmesi HİÇ çıkmadı. Türetme sözleşme değildir.
  needsApproval: z.boolean().optional(),
  interaction: interactionEnvelopeCompatSchema.optional(),
  verification: z.object({
    status: z.enum(["pending", "passed", "repaired", "failed"]),
    summary: z.string().min(1).max(240).optional(),
  }).passthrough().optional(),
  artifacts: z.array(z.object({
    id: z.string().min(1).max(255).optional(),
    title: z.string().min(1).max(180),
    kind: z.string().min(1).max(80).optional(),
    path: z.string().min(1).max(1_000).optional(),
    url: z.string().min(1).max(2_000).optional(),
  })).max(12).optional(),
  error: z.object({
    code: z.string().min(1).max(120),
    message: z.string().min(1).max(500),
    retryable: z.boolean(),
  }).optional(),
  availableActions: z.array(z.enum(["approve", "reject", "answer", "retry"])).max(4).optional(),
  updatedAt: z.string().datetime().optional(),
  steps: z.array(stringRecordSchema).min(1),
});
const infoCardDataSchema = z.looseObject({
  title: z.string().min(1).max(120),
  items: z
    .array(
      z.looseObject({
        label: z.string().min(1).max(120),
        value: z.string().min(1).max(240),
        confidence: z.number().min(0).max(1).optional(),
      }),
    )
    .min(1)
    .max(8),
});
const webSearchDataSchema = z.looseObject({
  query: z.string().min(1).max(320),
  queries: z.array(z.string().min(1).max(320)).min(1).max(4),
  confidence: z.enum(["high", "medium", "low"]),
  retrievedAt: z.string().max(120).optional(),
  results: z
    .array(
      z.looseObject({
        title: z.string().min(1).max(240),
        url: z.string().min(1).max(512),
        snippet: z.string().max(400).optional(),
        sourceHost: z.string().max(120).optional(),
        verificationState: z.enum(["verified", "partial", "unverified"]),
      }),
    )
    .min(1)
    .max(8),
});
const codeDataSchema = z.looseObject({
  code: z.string().min(1).max(24_000),
  language: z.string().min(1).max(40).optional(),
  filename: z.string().min(1).max(180).optional(),
  title: z.string().min(1).max(120).optional(),
  collapsed: z.boolean().optional(),
});
const tableDataSchema = z.looseObject({
  title: z.string().min(1).max(120).optional(),
  summary: z.string().min(1).max(240).optional(),
  columns: z.array(z.string().min(1).max(120)).min(1).max(12),
  rows: z
    .array(z.array(z.string().max(240)).min(1).max(12))
    .min(1)
    .max(80),
  caption: z.string().min(1).max(240).optional(),
});
const chartDataSchema = z.looseObject({
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
  labels: z.array(z.string().min(1).max(120)).max(240).optional(),
  values: z.array(z.number()).max(240).optional(),
  points: z.array(stringRecordSchema).max(1_500).optional(),
  data: z.array(z.unknown()).max(1_500).optional(),
  series: z.array(stringRecordSchema).max(8).optional(),
  expression: z.string().min(1).max(2_000).optional(),
  variables: z.array(z.string().min(1).max(24)).max(12).optional(),
  range: stringRecordSchema.optional(),
  fixed: z.record(z.string(), z.number()).optional(),
  xLabel: z.string().min(1).max(120).optional(),
  yLabel: z.string().min(1).max(120).optional(),
  // `unit`, `interactions` ve `theme` sözleşmenin görünür yüzeyidir: istemci
  // ekseni birimle etiketler, bildirilen etkileşimleri açar ve temayı uygular.
  // Şemada tanımlı OLMADIKLARI sürece mobil parite testi bunları "bilinmeyen
  // alan" sayıyor, bu da backend'in ürettiğini istemcinin yok saymasına yol
  // açıyordu.
  unit: z.string().min(1).max(40).optional(),
  renderer: z.string().min(1).max(40).optional(),
  interactions: z
    .array(
      z.enum([
        "tooltip",
        "trackball",
        "zoom",
        "pan",
        "type_switch",
        "fullscreen",
        "share",
      ]),
    )
    .max(8)
    .optional(),
  theme: z.enum(["system", "presentation", "report", "minimal"]).optional(),
  caption: z.string().min(1).max(240).optional(),
});
const mathSurface3dDataSchema = z.looseObject({
  title: z.string().min(1).max(120).optional(),
  expression: z.string().min(1).max(240).optional(),
  variables: z.array(z.string().min(1).max(24)).max(4).optional(),
  range: stringRecordSchema.optional(),
  resolution: z.number().int().min(10).max(120).optional(),
  zLabel: z.string().min(1).max(160).optional(),
  colorBy: z.enum(["z", "gradientMagnitude"]).optional(),
  mode: z.enum(["surface"]).optional(),
  interactive: z.boolean().optional(),
  caption: z.string().min(1).max(240).optional(),
});
const mathDataSchema = z.looseObject({
  title: z.string().min(1).max(120).optional(),
  content: z.string().min(1).max(8_000),
  latex: z.string().min(1).max(8_000).optional(),
  displayMode: z.boolean().optional(),
  result: z.string().min(1).max(240).optional(),
  explanation: z.string().min(1).max(480).optional(),
  steps: z.array(z.union([z.string(), stringRecordSchema])).max(8).optional(),
});
const svgDataSchema = z.looseObject({
  title: z.string().min(1).max(120).optional(),
  caption: z.string().min(1).max(240).optional(),
  svg: z.string().min(1).max(80_000).optional(),
  markup: z.string().min(1).max(80_000).optional(),
  url: z.string().min(1).max(2_000).optional(),
  viewBox: z.string().min(1).max(80).optional(),
});
const fileDataSchema = z.looseObject({
  fileName: z.string().min(1).max(180),
  mimeType: z.string().min(1).max(120).optional(),
  sizeBytes: z.number().int().nonnegative().optional(),
  documentId: z.string().min(1).max(255).optional(),
  preview: z.string().min(1).max(400).optional(),
});
const artifactDataSchema = z.looseObject({
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
  viewerHint: z.string().min(1).max(80).optional(),
  contentFamily: z.string().min(1).max(80).optional(),
  loadStrategy: z.string().min(1).max(80).optional(),
  mime: z.string().min(1).max(120).optional(),
  summary: z.string().min(1).max(400).optional(),
  payload: stringRecordSchema.optional(),
  metadata: stringRecordSchema.optional(),
});
const actionableDataSchema = z.looseObject({
  kind: z.enum([
    "approval_needed",
    "choose_device",
    "retry_option",
    "open_history",
    "restore_context",
  ]),
  title: z.string().min(1).max(120),
  detail: z.string().min(1).max(240).optional(),
});
const blockGroupDataSchema = z.looseObject({
  title: z.string().min(1).max(120).optional(),
  children: z.array(stringRecordSchema).min(1).max(12),
});
const documentDataSchema = z.looseObject({
  title: z.string().min(1).max(200).optional(),
  sections: z
    .array(
      z.looseObject({
        heading: z.string().min(1).max(200).optional(),
        content: z.string().min(1).max(8_000),
        level: z.number().int().min(1).max(3).optional(),
        role: z.enum(["title", "summary", "body", "table", "appendix"]).optional(),
      }),
    )
    .min(1)
    .max(40),
  format: z.enum(["report", "letter", "outline", "notes"]).optional(),
  wordCount: z.number().int().nonnegative().optional(),
  summary: z.string().min(1).max(300).optional(),
});
const attachmentAckDataSchema = z.looseObject({
  summary: z.string().min(1).max(400),
  attachmentCount: z.number().int().nonnegative(),
  pageCount: z.number().int().nonnegative().optional(),
  chunkCount: z.number().int().nonnegative().optional(),
  hasTable: z.boolean().optional(),
  hasImage: z.boolean().optional(),
});
const imageAnalysisDataSchema = z.looseObject({
  description: z.string().min(1).max(2_000),
  detectedText: z.string().max(2_000).optional(),
  tags: z.array(z.string().min(1).max(60)).max(12).optional(),
  confidence: z.number().min(0).max(1).optional(),
  language: z.string().max(20).optional(),
});
const goalProgressDataSchema = z.looseObject({
  goalId: z.string().min(1).max(120),
  step: z.number().int().min(0).max(10_000),
  ofSteps: z.number().int().min(1).max(10_000),
  advancedTo: z.string().min(1).max(400),
  blocker: z.string().min(1).max(400).nullable(),
  done: z.boolean(),
});
const connectorResultDataSchema = z.looseObject({
  provider: z.enum([
    "gmail",
    "drive",
    "calendar",
    "notion",
    "github",
    "slack",
    "linear",
    "mcp",
    "connector",
  ]),
  tool: z.string().min(1).max(160),
  title: z.string().min(1).max(160),
  kind: z.string().min(1).max(80).optional(),
  summary: z.string().min(1).max(240).optional(),
  items: z.array(stringRecordSchema).min(1).max(80),
});

// A single tool/capability invocation in an agent turn. Telemetry the registry
// already records (duration, ok/error, attempts) becomes a visible surface:
// which tool ran, how long it took, and what it found.
const toolCallEntrySchema = z.strictObject({
  callId: z.string().min(1).max(255),
  toolName: z.string().min(1).max(160),
  label: z.string().min(1).max(200).optional(),
  provider: z
    .enum([
      "gmail",
      "drive",
      "calendar",
      "notion",
      "github",
      "slack",
      "linear",
      "mcp",
      "connector",
      "runtime",
      "web",
    ])
    .optional(),
  status: z.enum(["running", "ok", "error"]),
  durationMs: z.number().int().nonnegative().max(3_600_000).optional(),
  resultSummary: z.string().min(1).max(400).optional(),
  attempts: z.number().int().min(1).max(20).optional(),
  error: safeErrorSchema.optional(),
});
const toolCallDataSchema = z.looseObject({
  title: z.string().min(1).max(160).optional(),
  calls: z.array(toolCallEntrySchema).min(1).max(40),
});

// Passthrough-era types keep their payload extensible while the transport
// envelope becomes stable and code-generated.
const extensibleDataSchema = z.record(z.string(), z.unknown());

const mailListItemSchema = z.strictObject({
  messageId: z.string().min(1).max(255),
  threadId: z.string().min(1).max(255),
  senderName: z.string().min(1).max(240),
  senderAddress: z.string().min(1).max(320).optional(),
  subject: z.string().min(1).max(500),
  preview: z.string().max(1_000),
  receivedAt: z.string().min(1).max(120),
  isUnread: z.boolean(),
  avatarUrl: z.string().min(1).max(2_000).optional(),
  labels: z.array(z.string().min(1).max(120)).max(24).optional(),
  action: mailOpenActionSchema,
});
const mailListContextSchema = {
  title: z.string().min(1).max(160).optional(),
  query: z.string().min(1).max(500).optional(),
  nextPageToken: z.string().min(1).max(1_000).optional(),
};
const mailListDataSchema = z.discriminatedUnion("state", [
  z.strictObject({
    state: z.literal("loading"),
    ...mailListContextSchema,
    items: z.array(mailListItemSchema).max(0),
  }),
  z.strictObject({
    state: z.literal("ready"),
    ...mailListContextSchema,
    items: z.array(mailListItemSchema).min(1).max(80),
  }),
  z.strictObject({
    state: z.literal("empty"),
    ...mailListContextSchema,
    items: z.array(mailListItemSchema).max(0),
  }),
  z.strictObject({
    state: z.literal("error"),
    ...mailListContextSchema,
    items: z.array(mailListItemSchema).max(0),
    error: safeErrorSchema,
  }),
]);

const mailAttachmentSchema = z.strictObject({
  attachmentId: z.string().min(1).max(255),
  name: z.string().min(1).max(500),
  mimeType: z.string().min(1).max(240).optional(),
  sizeBytes: z.number().int().nonnegative().optional(),
  downloadUrl: z.string().min(1).max(2_000).optional(),
  action: linkOpenActionSchema.optional(),
});
const mailDetailDataSchema = z.discriminatedUnion("state", [
  z.strictObject({ state: z.literal("loading") }),
  z.strictObject({
    state: z.literal("ready"),
    messageId: z.string().min(1).max(255),
    threadId: z.string().min(1).max(255),
    senderName: z.string().min(1).max(240),
    senderAddress: z.string().min(1).max(320).optional(),
    recipients: z.array(z.string().min(1).max(320)).max(100),
    subject: z.string().min(1).max(500),
    receivedAt: z.string().min(1).max(120),
    bodyRichText: z.string().min(1).max(200_000),
    bodyFormat: z.enum(["markdown", "plain_text"]),
    attachments: z.array(mailAttachmentSchema).max(40),
    action: linkOpenActionSchema.optional(),
  }),
  z.strictObject({ state: z.literal("empty") }),
  z.strictObject({ state: z.literal("error"), error: safeErrorSchema }),
]);

const calendarEventSchema = z.strictObject({
  eventId: z.string().min(1).max(255),
  title: z.string().min(1).max(500),
  startAt: z.string().min(1).max(120),
  endAt: z.string().min(1).max(120),
  allDay: z.boolean(),
  location: z.string().max(500).optional(),
  calendarName: z.string().max(240).optional(),
  hasConflict: z.boolean(),
  url: z.string().min(1).max(2_000).optional(),
  action: calendarMenuActionSchema,
});
const agendaContextSchema = {
  date: z.string().min(1).max(32),
  timeZone: z.string().min(1).max(120),
};
const calendarAgendaDataSchema = z.discriminatedUnion("state", [
  z.strictObject({
    state: z.literal("loading"),
    ...agendaContextSchema,
    events: z.array(calendarEventSchema).max(0),
  }),
  z.strictObject({
    state: z.literal("ready"),
    ...agendaContextSchema,
    events: z.array(calendarEventSchema).min(1).max(160),
  }),
  z.strictObject({
    state: z.literal("empty"),
    ...agendaContextSchema,
    events: z.array(calendarEventSchema).max(0),
  }),
  z.strictObject({
    state: z.literal("error"),
    ...agendaContextSchema,
    events: z.array(calendarEventSchema).max(0),
    error: safeErrorSchema,
  }),
]);

const driveFileSchema = z.strictObject({
  fileId: z.string().min(1).max(255),
  name: z.string().min(1).max(500),
  mimeType: z.string().min(1).max(255),
  kind: z.string().min(1).max(120).optional(),
  sizeBytes: z.number().int().nonnegative().optional(),
  modifiedAt: z.string().min(1).max(120).optional(),
  ownerName: z.string().min(1).max(240).optional(),
  url: z.string().min(1).max(2_000).optional(),
  action: linkOpenActionSchema,
});
const driveContextSchema = {
  title: z.string().min(1).max(160).optional(),
  query: z.string().min(1).max(500).optional(),
  availableTypes: z.array(z.string().min(1).max(120)).max(40).optional(),
};
const driveFilesDataSchema = z.discriminatedUnion("state", [
  z.strictObject({
    state: z.literal("loading"),
    ...driveContextSchema,
    files: z.array(driveFileSchema).max(0),
  }),
  z.strictObject({
    state: z.literal("ready"),
    ...driveContextSchema,
    files: z.array(driveFileSchema).min(1).max(160),
  }),
  z.strictObject({
    state: z.literal("empty"),
    ...driveContextSchema,
    files: z.array(driveFileSchema).max(0),
  }),
  z.strictObject({
    state: z.literal("error"),
    ...driveContextSchema,
    files: z.array(driveFileSchema).max(0),
    error: safeErrorSchema,
  }),
]);

const notionSummaryBlockSchema = z.strictObject({
  kind: z.string().min(1).max(80),
  text: z.string().min(1).max(4_000),
});
const notionPageDataSchema = z.discriminatedUnion("state", [
  z.strictObject({ state: z.literal("loading") }),
  z.strictObject({
    state: z.literal("ready"),
    pageId: z.string().min(1).max(255),
    title: z.string().min(1).max(500),
    breadcrumb: z.array(z.string().min(1).max(255)).max(16),
    summaryBlocks: z.array(notionSummaryBlockSchema).min(1).max(80),
    url: z.string().min(1).max(2_000).optional(),
    lastEditedAt: z.string().min(1).max(120).optional(),
    action: linkOpenActionSchema,
  }),
  z.strictObject({ state: z.literal("empty") }),
  z.strictObject({ state: z.literal("error"), error: safeErrorSchema }),
]);

const githubActivityItemSchema = z.strictObject({
  activityId: z.string().min(1).max(255),
  kind: z.enum(["pull_request", "issue"]),
  number: z.number().int().positive(),
  title: z.string().min(1).max(500),
  repository: z.string().min(1).max(300),
  status: z.enum(["open", "closed", "merged", "draft"]),
  author: z.string().min(1).max(240).optional(),
  updatedAt: z.string().min(1).max(120).optional(),
  url: z.string().min(1).max(2_000).optional(),
  action: linkOpenActionSchema,
});
const titledListContextSchema = {
  title: z.string().min(1).max(160).optional(),
};
const githubActivityDataSchema = z.discriminatedUnion("state", [
  z.strictObject({
    state: z.literal("loading"),
    ...titledListContextSchema,
    items: z.array(githubActivityItemSchema).max(0),
  }),
  z.strictObject({
    state: z.literal("ready"),
    ...titledListContextSchema,
    items: z.array(githubActivityItemSchema).min(1).max(160),
  }),
  z.strictObject({
    state: z.literal("empty"),
    ...titledListContextSchema,
    items: z.array(githubActivityItemSchema).max(0),
  }),
  z.strictObject({
    state: z.literal("error"),
    ...titledListContextSchema,
    items: z.array(githubActivityItemSchema).max(0),
    error: safeErrorSchema,
  }),
]);

const slackMessageSchema = z.strictObject({
  messageId: z.string().min(1).max(255),
  channelId: z.string().min(1).max(255),
  channelName: z.string().min(1).max(240),
  authorName: z.string().min(1).max(240),
  text: z.string().min(1).max(20_000),
  timestamp: z.string().min(1).max(120),
  threadTs: z.string().min(1).max(120).optional(),
  avatarUrl: z.string().min(1).max(2_000).optional(),
  permalink: z.string().min(1).max(2_000).optional(),
  action: linkOpenActionSchema,
});
const slackMessagesDataSchema = z.discriminatedUnion("state", [
  z.strictObject({
    state: z.literal("loading"),
    ...titledListContextSchema,
    messages: z.array(slackMessageSchema).max(0),
  }),
  z.strictObject({
    state: z.literal("ready"),
    ...titledListContextSchema,
    messages: z.array(slackMessageSchema).min(1).max(160),
  }),
  z.strictObject({
    state: z.literal("empty"),
    ...titledListContextSchema,
    messages: z.array(slackMessageSchema).max(0),
  }),
  z.strictObject({
    state: z.literal("error"),
    ...titledListContextSchema,
    messages: z.array(slackMessageSchema).max(0),
    error: safeErrorSchema,
  }),
]);

export const elyanAssistantBlockDataSchemaByType = {
  text: textDataSchema,
  summary: summaryDataSchema,
  next_steps: nextStepsDataSchema,
  status: statusDataSchema,
  security_decision: securityDecisionDataSchema,
  task_trace: taskTraceDataSchema,
  dispatch_widget: taskTraceDataSchema,
  attachment_context: infoCardDataSchema,
  context_signal: infoCardDataSchema,
  web_search: webSearchDataSchema,
  code: codeDataSchema,
  table: tableDataSchema,
  chart: chartDataSchema,
  math_surface_3d: mathSurface3dDataSchema,
  math: mathDataSchema,
  svg: svgDataSchema,
  file: fileDataSchema,
  artifact: artifactDataSchema,
  actionable: actionableDataSchema,
  block_group: blockGroupDataSchema,
  memory_echo: extensibleDataSchema,
  proactive_touch: extensibleDataSchema,
  document_block: documentDataSchema,
  attachment_ack: attachmentAckDataSchema,
  image_analysis: imageAnalysisDataSchema,
  vision: extensibleDataSchema,
  goal_progress: goalProgressDataSchema,
  desktop_suggestion: extensibleDataSchema,
  document_block_skeleton: extensibleDataSchema,
  pdf_generate: extensibleDataSchema,
  pdf_viewer: extensibleDataSchema,
  terminal: extensibleDataSchema,
  automation: extensibleDataSchema,
  reasoning_trace: extensibleDataSchema,
  capability_unavailable: extensibleDataSchema,
  clarification: extensibleDataSchema,
  connector_result: connectorResultDataSchema,
  mail_list: mailListDataSchema,
  mail_detail: mailDetailDataSchema,
  calendar_agenda: calendarAgendaDataSchema,
  drive_files: driveFilesDataSchema,
  notion_page: notionPageDataSchema,
  github_activity: githubActivityDataSchema,
  slack_messages: slackMessagesDataSchema,
  tool_call: toolCallDataSchema,
} satisfies Record<ElyanAssistantBlockTypeValue, z.ZodType>;

const sourceSchemaByType: Partial<
  Record<ElyanAssistantBlockTypeValue, z.ZodType>
> = {
  mail_list: z.literal("gmail"),
  mail_detail: z.literal("gmail"),
  calendar_agenda: z.literal("calendar"),
  drive_files: z.literal("drive"),
  notion_page: z.literal("notion"),
  github_activity: z.literal("github"),
  slack_messages: z.literal("slack"),
};

function buildEnvelopeSchema(type: ElyanAssistantBlockTypeValue) {
  // Keep top-level legacy payload keys readable during the additive migration.
  // New consumers use `data`; old `elyan_blocks.v2` clients keep their fields.
  return z.looseObject({
    type: z.literal(type),
    version: z.literal(ELYAN_ASSISTANT_BLOCK_ENVELOPE_VERSION),
    blockId: z.string().min(1).max(255),
    source: sourceSchemaByType[type] ?? elyanAssistantBlockSourceSchema,
    visibility: elyanAssistantBlockVisibilityV4Schema,
    renderHints: renderHintsSchema,
    data: elyanAssistantBlockDataSchemaByType[type],
    stableBlockId: z.string().min(1).max(255).optional(),
    confidence: z.number().min(0).max(1).optional(),
    priority: z.number().int().min(0).max(3).optional(),
    cacheDigest: z.string().min(1).max(255).optional(),
    isRenderable: z.boolean().optional(),
  });
}

export const elyanAssistantBlockEnvelopeSchemaByType = Object.fromEntries(
  elyanAssistantBlockTypeValues.map((type) => [type, buildEnvelopeSchema(type)]),
) as unknown as Record<ElyanAssistantBlockTypeValue, z.ZodType>;

const canonicalEnvelopeSchemas = Object.values(
  elyanAssistantBlockEnvelopeSchemaByType,
) as [z.ZodType, z.ZodType, ...z.ZodType[]];

export const elyanAssistantBlockEnvelopeSchema = z.union(
  canonicalEnvelopeSchemas,
);

/**
 * Read-only compatibility branch for already persisted `elyan_blocks.v2`
 * messages. Canonical envelope markers deliberately reject this branch so a
 * partially assembled new envelope cannot bypass required-field validation.
 */
export const elyanAssistantLegacyTopLevelBlockSchema = z
  .looseObject({
    type: z.enum(elyanLegacyAssistantBlockTypeValues),
    stableBlockId: z.string().min(1).max(255).optional(),
    visibility: elyanAssistantBlockVisibilityV4Schema.optional(),
    cacheDigest: z.string().min(1).max(255).optional(),
    renderHints: renderHintsSchema.optional(),
  })
  .refine(
    (value) =>
      !("version" in value) && !("blockId" in value) && !("data" in value),
    { message: "Canonical block envelopes must include every required field" },
  );

export const elyanAssistantBlockTransportV4Schema = z.union([
  elyanAssistantBlockEnvelopeSchema,
  elyanAssistantLegacyTopLevelBlockSchema,
]);

export type ElyanAssistantBlockEnvelope = z.infer<
  typeof elyanAssistantBlockEnvelopeSchema
>;
