import { z } from "zod";

export const artifactTypeSchema = z.enum([
  "text",
  "table",
  "chart",
  "svg",
  "pdf",
  "document",
  "image_prompt",
]);

export type ArtifactType = z.infer<typeof artifactTypeSchema>;

export const validationIssueSchema = z.object({
  code: z.string().min(1).max(120),
  message: z.string().min(1).max(500),
  path: z.string().min(1).max(240).optional(),
  severity: z.enum(["error", "warning"]),
});

export const validationWarningSchema = validationIssueSchema.omit({
  severity: true,
});

export const validationResultSchema = z.object({
  ok: z.boolean(),
  errors: z.array(validationIssueSchema),
  warnings: z.array(validationWarningSchema).optional(),
});

export type ValidationIssue = z.infer<typeof validationIssueSchema>;
export type ValidationResult = z.infer<typeof validationResultSchema>;

const artifactMetadataSchema = z.object({
  userId: z.string().min(1).optional(),
  sessionId: z.string().min(1).optional(),
  taskId: z.string().min(1).optional(),
  createdAt: z.string().datetime(),
  model: z.string().min(1).max(160).optional(),
  confidence: z.number().min(0).max(1).optional(),
});

export const artifactBlockSchema = z.object({
  type: z.string().min(1).max(80),
}).passthrough();

export const artifactSpecBaseSchema = z.object({
  id: z.string().min(1).max(160),
  type: artifactTypeSchema,
  intent: z.string().min(1).max(240),
  sourceText: z.string().max(20_000).optional(),
  locale: z.string().min(2).max(32).optional(),
  blocks: z.array(artifactBlockSchema).default([]),
  renderOptions: z.record(z.unknown()).optional(),
  validationRules: z.array(z.string().min(1).max(120)).optional(),
  metadata: artifactMetadataSchema.optional(),
});

export const textSpecSchema = artifactSpecBaseSchema.extend({
  type: z.literal("text"),
  purpose: z.enum([
    "email",
    "chat_message",
    "social_post",
    "report",
    "description",
    "summary",
    "caption",
    "custom",
  ]),
  tone: z.enum([
    "formal",
    "friendly",
    "technical",
    "short",
    "persuasive",
    "neutral",
  ]).optional(),
  language: z.string().min(2).max(32),
  audience: z.string().min(1).max(160).optional(),
  blocks: z.array(z.object({
    type: z.enum(["opening", "body", "closing", "cta", "note"]),
    text: z.string().min(1).max(8_000),
  })).min(1).max(16),
});

export const tableColumnSchema = z.object({
  key: z.string().min(1).max(80),
  label: z.string().min(1).max(120),
  dataType: z.enum(["string", "number", "currency", "date", "boolean"]),
  align: z.enum(["left", "center", "right"]).optional(),
  required: z.boolean().default(true),
});

export const tableSpecSchema = artifactSpecBaseSchema.extend({
  type: z.literal("table"),
  title: z.string().min(1).max(160).optional(),
  columns: z.array(tableColumnSchema).min(1).max(24),
  rows: z.array(z.record(z.unknown())).min(1).max(500),
  summary: z.object({
    label: z.string().min(1).max(160),
    values: z.record(z.unknown()),
  }).optional(),
  sort: z.object({
    key: z.string().min(1).max(80),
    direction: z.enum(["asc", "desc"]),
  }).optional(),
});

export const chartSpecSchema = artifactSpecBaseSchema.extend({
  type: z.literal("chart"),
  chartType: z.enum(["bar", "line", "pie", "scatter"]),
  title: z.string().min(1).max(160).optional(),
  description: z.string().min(1).max(400).optional(),
  xKey: z.string().min(1).max(80).optional(),
  yKey: z.string().min(1).max(80).optional(),
  series: z.array(z.object({
    key: z.string().min(1).max(80),
    label: z.string().min(1).max(120),
    valueType: z.enum(["number", "currency", "percentage"]).optional(),
  })).max(8).optional(),
  data: z.array(z.record(z.unknown())).min(1).max(1_500),
});

export const svgElementSchema: z.ZodType<{
  type: "rect" | "circle" | "line" | "path" | "text" | "group" | "polygon" | "polyline";
  children?: Array<z.infer<typeof svgElementSchema>>;
  [key: string]: unknown;
}> = z.lazy(() => z.object({
  type: z.enum(["rect", "circle", "line", "path", "text", "group", "polygon", "polyline"]),
  children: z.array(svgElementSchema).optional(),
}).passthrough());

export const svgSpecSchema = artifactSpecBaseSchema.extend({
  type: z.literal("svg"),
  canvas: z.object({
    width: z.number().int().positive().max(10_000),
    height: z.number().int().positive().max(10_000),
    viewBox: z.string().min(1).max(120),
  }),
  elements: z.array(svgElementSchema).min(1).max(300),
});

export const pdfBlockTypeSchema = z.enum([
  "title",
  "subtitle",
  "paragraph",
  "line_item",
  "table",
  "total",
  "signature",
  "footer",
  "spacer",
  "divider",
]);

export const pdfBlockSchema = z.object({
  type: pdfBlockTypeSchema,
  text: z.string().max(8_000).optional(),
  label: z.string().max(240).optional(),
  amount: z.number().finite().optional(),
  currency: z.string().max(12).optional(),
  rawAmount: z.string().max(80).optional(),
  source: z.enum(["user", "computed", "normalized"]).optional(),
  placement: z.enum(["body", "footer", "signature"]).optional(),
  columns: z.array(tableColumnSchema).optional(),
  rows: z.array(z.record(z.unknown())).optional(),
}).passthrough();

export const pdfSpecSchema = artifactSpecBaseSchema.extend({
  type: z.literal("pdf"),
  documentType: z.enum([
    "receipt",
    "invoice",
    "quote",
    "report",
    "letter",
    "summary",
    "custom",
  ]),
  title: z.string().min(1).max(200).optional(),
  blocks: z.array(pdfBlockSchema).min(1).max(80),
  page: z.object({
    size: z.literal("A4"),
    margin: z.number().min(12).max(120),
    orientation: z.enum(["portrait", "landscape"]).optional(),
  }),
  footer: z.object({
    text: z.string().min(1).max(500).optional(),
    align: z.enum(["left", "center", "right"]).optional(),
  }).optional(),
});

export const documentSpecSchema = artifactSpecBaseSchema.extend({
  type: z.literal("document"),
  documentType: z.enum(["report", "quote", "contract_draft", "letter", "summary", "custom"]),
  title: z.string().min(1).max(200).optional(),
  language: z.string().min(2).max(32),
  sections: z.array(z.object({
    heading: z.string().min(1).max(200).optional(),
    content: z.string().min(1).max(12_000),
    level: z.number().int().min(1).max(3).optional(),
  })).min(1).max(40),
  exportFormats: z.array(z.enum(["pdf", "docx", "xlsx"])).max(3).optional(),
});

export const imagePromptSpecSchema = artifactSpecBaseSchema.extend({
  type: z.literal("image_prompt"),
  subject: z.string().min(1).max(500),
  style: z.string().min(1).max(240).optional(),
  aspectRatio: z.string().min(1).max(40).optional(),
  constraints: z.array(z.string().min(1).max(300)).max(24),
  negativePrompt: z.array(z.string().min(1).max(200)).max(24).optional(),
  prompt: z.string().min(1).max(4_000),
  character_lock: z.record(z.unknown()).optional(),
});

export const artifactSpecSchema = z.discriminatedUnion("type", [
  textSpecSchema,
  tableSpecSchema,
  chartSpecSchema,
  svgSpecSchema,
  pdfSpecSchema,
  documentSpecSchema,
  imagePromptSpecSchema,
]);

export type ArtifactSpec = z.infer<typeof artifactSpecSchema>;
export type TextSpec = z.infer<typeof textSpecSchema>;
export type TableSpec = z.infer<typeof tableSpecSchema>;
export type ChartSpec = z.infer<typeof chartSpecSchema>;
export type SvgSpec = z.infer<typeof svgSpecSchema>;
export type PdfSpec = z.infer<typeof pdfSpecSchema>;
export type PdfBlock = z.infer<typeof pdfBlockSchema>;
export type DocumentSpec = z.infer<typeof documentSpecSchema>;
export type ImagePromptSpec = z.infer<typeof imagePromptSpecSchema>;

export const artifactOutputSchema = z.object({
  artifactId: z.string().min(1).max(160),
  type: artifactTypeSchema,
  spec: artifactSpecSchema,
  output: z.discriminatedUnion("kind", [
    z.object({ kind: z.literal("text"), content: z.string() }),
    z.object({ kind: z.literal("html"), content: z.string() }),
    z.object({ kind: z.literal("svg"), content: z.string() }),
    z.object({ kind: z.literal("json"), content: z.unknown() }),
    z.object({
      kind: z.literal("file"),
      path: z.string().optional(),
      url: z.string().optional(),
      mimeType: z.string().min(1),
    }),
  ]),
  validation: validationResultSchema,
});

export type ArtifactOutput = z.infer<typeof artifactOutputSchema>;

export type ArtifactIntent = {
  type: ArtifactType | null;
  confidence: number;
  intent: string;
  source: "typed_extractor" | "metadata" | "understanding_envelope";
  requiresDesktopRuntime: boolean;
  privateDataReason?: string;
};

export interface ArtifactRenderer<TSpec extends ArtifactSpec = ArtifactSpec> {
  supports(type: ArtifactType): boolean;
  validate(spec: TSpec): Promise<ValidationResult>;
  render(spec: TSpec): Promise<ArtifactOutput>;
}

export function makeValidationResult(
  issues: ValidationIssue[],
  warnings: Array<Omit<ValidationIssue, "severity">> = [],
): ValidationResult {
  return {
    ok: issues.every((issue) => issue.severity !== "error"),
    errors: issues,
    ...(warnings.length > 0 ? { warnings } : {}),
  };
}
