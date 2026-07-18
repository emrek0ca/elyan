import { z } from "zod";
import { stripVisionProviderAttribution } from "./vision-provider-privacy.js";

const boxSchema = z.object({
  x: z.number().min(0).max(1),
  y: z.number().min(0).max(1),
  w: z.number().min(0).max(1),
  h: z.number().min(0).max(1),
});

export const visionBlockV2Schema = z.object({
  id: z.string().trim().min(1).max(160),
  type: z.literal("vision"),
  version: z.literal(2),
  render: z
    .object({
      widget: z.literal("vision_summary").optional(),
      title: z.string().trim().max(120).optional(),
      status: z.enum(["ready", "low_confidence", "unreadable", "error"]).optional(),
    })
    .passthrough(),
  source: z.object({
    kind: z.string().trim().max(40),
    privacy: z.literal("local_extracted_only"),
    image_sent_to_server: z.literal(false),
    platform: z.enum(["ios", "android", "unknown"]),
    engine: z.enum(["apple_vision", "mlkit", "native_ocr"]),
  }),
  input_kind: z.object({
    value: z.string().trim().max(80),
    confidence: z.number().min(0).max(1),
  }),
  quality: z
    .object({
      blur: z.number().min(0).max(1).optional(),
      brightness: z.number().min(0).max(1).optional(),
      contrast: z.number().min(0).max(1).optional(),
      resolution: z
        .object({
          width: z.number().int().nonnegative(),
          height: z.number().int().nonnegative(),
        })
        .optional(),
      rotation: z.number().optional(),
      is_readable: z.boolean(),
      warnings: z.array(z.string().trim().max(80)).max(12).default([]),
    })
    .passthrough(),
  text: z
    .object({
      full_text: z.string().max(8_000).default(""),
      blocks: z
        .array(
          z
            .object({
              text: z.string().max(1_000),
              confidence: z.number().min(0).max(1),
              box: boxSchema,
              role: z.string().trim().max(40).optional(),
            })
            .passthrough(),
        )
        .max(100)
        .default([]),
      reading_order: z.string().trim().max(40).optional(),
    })
    .passthrough(),
  scene: z
    .object({
      labels: z
        .array(
          z
            .object({
              name: z.string().trim().max(120),
              confidence: z.number().min(0).max(1),
              source: z.string().trim().max(40).optional(),
            })
            .passthrough(),
        )
        .max(20)
        .default([]),
      objects: z
        .array(
          z
            .object({
              label: z.string().trim().max(120),
              confidence: z.number().min(0).max(1),
              box: boxSchema,
              source: z.string().trim().max(40).optional(),
            })
            .passthrough(),
        )
        .max(24)
        .default([]),
    })
    .passthrough(),
  documents: z
    .object({
      detected: z.boolean().default(false),
      pages: z
        .array(
          z
            .object({
              page: z.number().int().positive(),
              confidence: z.number().min(0).max(1),
              box: boxSchema,
            })
            .passthrough(),
        )
        .max(8)
        .default([]),
    })
    .passthrough(),
  barcodes: z
    .array(
      z
        .object({
          format: z.string().trim().max(80),
          value: z.string().trim().max(600),
          confidence: z.number().min(0).max(1),
          box: boxSchema,
        })
        .passthrough(),
    )
    .max(20)
    .default([]),
  task_hints: z.array(z.string().trim().max(80)).max(12).default([]),
  summary_for_llm: z.string().max(2_000).default(""),
  confidence: z
    .object({
      overall: z.number().min(0).max(1),
      ocr: z.number().min(0).max(1),
      scene: z.number().min(0).max(1),
      document: z.number().min(0).max(1),
    })
    .passthrough(),
  debug: z
    .object({
      latency_ms: z.number().nonnegative().optional(),
      engine_version: z.string().max(120).optional(),
      warnings: z.array(z.string().trim().max(100)).max(20).optional(),
    })
    .passthrough()
    .optional(),
});

export type VisionBlockV2 = z.infer<typeof visionBlockV2Schema>;

export type VisionEvidenceBucket = {
  certain: string[];
  probable: string[];
  lowConfidence: string[];
  qualityWarnings: string[];
  missing: string[];
  taskHints: string[];
  inputKind: string;
};

export function parseVisionBlockV2(value: unknown): VisionBlockV2 | null {
  const parsed = visionBlockV2Schema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

export function interpretVisionBlock(block: VisionBlockV2): VisionEvidenceBucket {
  const certain: string[] = [];
  const probable: string[] = [];
  const lowConfidence: string[] = [];
  const missing: string[] = [];
  const qualityWarnings = [...block.quality.warnings];

  if (!block.quality.is_readable) {
    qualityWarnings.push("image_unreadable_or_low_quality");
  }

  if (block.text.full_text.trim()) {
    if (block.confidence.ocr >= 0.68) {
      certain.push(`OCR text: ${bounded(block.text.full_text, 700)}`);
    } else if (block.confidence.ocr >= 0.35) {
      lowConfidence.push(`Low-confidence OCR text: ${bounded(block.text.full_text, 450)}`);
    } else {
      missing.push("OCR text is not reliable");
    }
  } else {
    missing.push("No readable OCR text");
  }

  const strongObjects = block.scene.objects.filter((item) => item.confidence >= 0.72);
  const weakObjects = block.scene.objects.filter((item) => item.confidence >= 0.4 && item.confidence < 0.72);
  if (strongObjects.length > 0) {
    certain.push(`Detected objects: ${strongObjects.slice(0, 6).map((item) => item.label).join(", ")}`);
  }
  if (weakObjects.length > 0) {
    probable.push(`Possible objects: ${weakObjects.slice(0, 6).map((item) => item.label).join(", ")}`);
  }

  const strongLabels = block.scene.labels.filter((item) => item.confidence >= 0.72);
  const weakLabels = block.scene.labels.filter((item) => item.confidence >= 0.4 && item.confidence < 0.72);
  if (strongLabels.length > 0) {
    probable.push(`Scene labels: ${strongLabels.slice(0, 6).map((item) => item.name).join(", ")}`);
  }
  if (weakLabels.length > 0) {
    lowConfidence.push(`Weak scene labels: ${weakLabels.slice(0, 6).map((item) => item.name).join(", ")}`);
  }

  if (block.barcodes.length > 0) {
    certain.push(
      `Barcode/QR values: ${block.barcodes
        .slice(0, 4)
        .map((item) => `${item.format}:${bounded(item.value, 120)}`)
        .join(", ")}`,
    );
  }

  if (block.documents.detected) {
    const page = block.documents.pages[0];
    probable.push(`Document/rectangle detected${page ? ` (confidence ${page.confidence.toFixed(2)})` : ""}`);
  }

  if (block.confidence.overall < 0.45) {
    lowConfidence.push("Overall vision confidence is low");
  }

  return {
    certain,
    probable,
    lowConfidence,
    qualityWarnings: [...new Set(qualityWarnings)],
    missing,
    taskHints: block.task_hints,
    inputKind: block.input_kind.value,
  };
}

export function formatVisionEvidencePrompt(blocks: VisionBlockV2[]): string | null {
  if (blocks.length === 0) {
    return null;
  }
  const lines = [
    "VISION EVIDENCE (local-first):",
    "- The server does NOT have the image. It only has device-extracted VisionBlock v2 data.",
    "- Treat OCR, scene labels, objects, barcode values, document rectangles, quality and confidence separately.",
    "- If confidence is low or quality is poor, say that clearly and ask for a clearer image or more context. Do not invent visual facts.",
  ];
  blocks.slice(0, 4).forEach((block, index) => {
    const evidence = interpretVisionBlock(block);
    lines.push(
      `VisionBlock ${index + 1}: input_kind=${evidence.inputKind} overall=${block.confidence.overall.toFixed(2)} ocr=${block.confidence.ocr.toFixed(2)} status=${block.render.status ?? "ready"}`,
    );
    if (block.summary_for_llm.trim()) {
      lines.push(`Summary: ${bounded(block.summary_for_llm, 700)}`);
    }
    if (evidence.qualityWarnings.length > 0) {
      lines.push(`Quality warnings: ${evidence.qualityWarnings.join(", ")}`);
    }
    if (evidence.certain.length > 0) {
      lines.push(`Certain evidence: ${evidence.certain.join(" | ")}`);
    }
    if (evidence.probable.length > 0) {
      lines.push(`Probable evidence: ${evidence.probable.join(" | ")}`);
    }
    if (evidence.lowConfidence.length > 0) {
      lines.push(`Low-confidence signals: ${evidence.lowConfidence.join(" | ")}`);
    }
    if (evidence.missing.length > 0) {
      lines.push(`Missing/weak data: ${evidence.missing.join(" | ")}`);
    }
    if (evidence.taskHints.length > 0) {
      lines.push(`Task hints: ${evidence.taskHints.join(", ")}`);
    }
  });
  return lines.join("\n");
}

function bounded(value: string, maxChars: number): string {
  const compact = stripVisionProviderAttribution(value).replace(/\s+/g, " ").trim();
  if (compact.length <= maxChars) {
    return compact;
  }
  return `${compact.slice(0, maxChars - 1).trimEnd()}…`;
}
