import type { FastifyInstance } from "fastify";
import type { ArtifactInput } from "../../contracts/domain.js";
import { tryAcquireLoadSheddingPermit } from "../../lib/reliability/load-shedding.js";

type HostedImageArtifactInput = {
  prompt: string;
  responseText: string;
  metadata?: Record<string, unknown>;
};

export type HostedImageArtifactResult = {
  artifact: ArtifactInput;
  binaryBody: Uint8Array;
  mimeType: string;
  model: string;
  previewText: string;
  revisedPrompt: string | null;
};

const CREATIVE_IMAGE_REQUEST_PATTERNS = [
  /\b(görsel|gorsel|resim|image|afiş|afis|poster|banner|kapak|thumbnail|illüstrasyon|illustration|mockup|cover)\b.*\b(üret|uret|oluştur|olustur|hazırla|hazirla|tasarla|design|generate|create)\b/i,
  /\b(üret|uret|oluştur|olustur|hazırla|hazirla|tasarla|design|generate|create)\b.*\b(görsel|gorsel|resim|image|afiş|afis|poster|banner|kapak|thumbnail|illüstrasyon|illustration|mockup|cover)\b/i,
  /\b(afiş|afis|poster|banner|kapak|thumbnail)\b/i,
];

const NON_CREATIVE_EXPORT_PATTERNS = [
  /\b(png|jpg|jpeg|webp)\b.*\b(ver|çevir|cevir|dönüştür|donustur|kaydet)\b/i,
  /\b(ver|çevir|cevir|dönüştür|donustur|kaydet)\b.*\b(png|jpg|jpeg|webp)\b/i,
];

function compactText(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readArray(record: Record<string, unknown> | null, key: string): unknown[] {
  const value = record?.[key];
  return Array.isArray(value) ? value : [];
}

function readString(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function shouldGenerateHostedImage(prompt: string): boolean {
  const normalized = compactText(prompt).toLowerCase();
  if (!normalized) {
    return false;
  }
  if (NON_CREATIVE_EXPORT_PATTERNS.some((pattern) => pattern.test(normalized))) {
    return false;
  }
  return CREATIVE_IMAGE_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized));
}

function joinUrl(baseUrl: string, path: string): string {
  const normalizedBase = baseUrl.replace(/\/+$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${normalizedBase}${normalizedPath}`.replace(/\/v1\/v1\//g, "/v1/");
}

function inferImageSize(prompt: string): "1024x1024" | "1024x1536" | "1536x1024" {
  const normalized = compactText(prompt).toLowerCase();
  if (/\b(afiş|afis|poster|flyer)\b/i.test(normalized)) {
    return "1024x1536";
  }
  if (/\b(banner|kapak|cover|thumbnail|hero)\b/i.test(normalized)) {
    return "1536x1024";
  }
  return "1024x1024";
}

function inferAttachmentSummary(metadata: Record<string, unknown> | undefined): string | null {
  const record = readRecord(metadata);
  if (!record) {
    return null;
  }

  const attachments = readArray(record, "attachments")
    .map((item) => readRecord(item))
    .filter((item): item is Record<string, unknown> => item != null);

  for (const attachment of attachments) {
    const deepContext = readRecord(attachment.deepContext);
    const fastPreview = readRecord(attachment.fastPreview);
    const deepAnalysis = readRecord(deepContext?.document_analysis);
    const summary =
      readString(fastPreview, "summary") ??
      readString(deepAnalysis, "summary") ??
      readString(attachment, "summary") ??
      readString(readRecord(attachment.document_analysis), "summary");
    if (summary) {
      return summary;
    }
  }

  return (
    readString(readRecord(record.document_analysis), "summary") ??
    readString(readRecord(record.documentAnalysis), "summary")
  );
}

function buildHostedImagePrompt(input: HostedImageArtifactInput): string {
  const attachmentSummary = inferAttachmentSummary(input.metadata);
  const sections = [
    "Create one polished production-ready image for a mobile user.",
    `User request: ${compactText(input.prompt)}`,
    attachmentSummary ? `Attachment summary: ${attachmentSummary}` : null,
    compactText(input.responseText)
      ? `Approved content brief: ${compactText(input.responseText)}`
      : null,
    "Use clean typography and coherent layout. Do not add watermarks or UI chrome unless the request explicitly needs it.",
  ];
  return sections.filter((value): value is string => Boolean(value)).join("\n\n");
}

function buildArtifactName(prompt: string, mimeType: string): string {
  const normalizedPrompt = compactText(prompt).toLowerCase();
  const extension = mimeType === "image/jpeg" ? "jpg" : mimeType === "image/webp" ? "webp" : "png";
  if (/\b(afiş|afis|poster)\b/i.test(normalizedPrompt)) {
    return `elyan-poster.${extension}`;
  }
  if (/\b(banner|thumbnail|kapak|cover)\b/i.test(normalizedPrompt)) {
    return `elyan-visual.${extension}`;
  }
  return `elyan-image.${extension}`;
}

export async function maybeGenerateHostedImageArtifact(
  app: FastifyInstance,
  input: HostedImageArtifactInput,
): Promise<HostedImageArtifactResult | null> {
  if (!shouldGenerateHostedImage(input.prompt)) {
    return null;
  }

  const apiKey = String(app.config.OPENAI_API_KEY ?? "").trim();
  if (!apiKey) {
    return null;
  }

  // Load shedding: görsel üretimi opsiyonel ve pahalı bir dış çağrı (45s'e
  // kadar). Sunucu doygunken permit yoksa üretim atlanır; metin cevabı akmaya
  // devam eder.
  const imagePermit = await tryAcquireLoadSheddingPermit(app, {
    namespace: "hosted_image_generation",
    maxConcurrent: 4,
    ttlMs: 60_000,
    salt: input.prompt.slice(0, 64),
  }).catch(() => null);
  if (!imagePermit) {
    app.log.warn("hosted image generation shed due to load");
    return null;
  }

  try {
    return await generateHostedImageArtifactWithPermit(app, input, apiKey);
  } finally {
    await imagePermit.release().catch(() => undefined);
  }
}

async function generateHostedImageArtifactWithPermit(
  app: FastifyInstance,
  input: HostedImageArtifactInput,
  apiKey: string,
): Promise<HostedImageArtifactResult | null> {
  const baseUrl = String(app.config.OPENAI_BASE_URL ?? "https://api.openai.com/v1").trim();
  const model = "gpt-image-1";
  const size = inferImageSize(input.prompt);
  const mimeType = "image/png";

  try {
    const response = await fetch(joinUrl(baseUrl, "/images/generations"), {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model,
        prompt: buildHostedImagePrompt(input),
        size,
        quality: "medium",
        output_format: "png",
      }),
      signal: AbortSignal.timeout(45_000),
    });

    if (!response.ok) {
      app.log.warn(
        {
          statusCode: response.status,
        },
        "hosted image generation request failed",
      );
      return null;
    }

    const payload = (await response.json()) as {
      data?: Array<{
        b64_json?: string;
        revised_prompt?: string;
      }>;
    };
    const image = payload.data?.[0];
    const base64 = compactText(image?.b64_json);
    if (!base64) {
      return null;
    }

    const revisedPrompt = compactText(image?.revised_prompt) || null;
    const previewText = compactText(input.responseText) || "Görsel hazır.";
    return {
      artifact: {
        kind: "file",
        name: buildArtifactName(input.prompt, mimeType),
        contentType: mimeType,
        textContent: previewText,
        payload: {
          previewText,
          mimeType,
          revisedPrompt: revisedPrompt ?? undefined,
          source: "openai_image_generation",
          model,
        },
        metadata: {
          sourceType: "task_artifact",
          contentFamily: "image",
          viewerHint: "image",
          provider: "openai",
          model,
          mimeType,
        },
      },
      binaryBody: Buffer.from(base64, "base64"),
      mimeType,
      model,
      previewText,
      revisedPrompt,
    };
  } catch (error) {
    app.log.warn({ err: error }, "hosted image generation failed");
    return null;
  }
}
