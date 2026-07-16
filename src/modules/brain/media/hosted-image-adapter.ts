export type HostedImageProviderConfig = {
  provider: "gemini";
  apiKey: string;
  baseUrl: string;
  model: string;
  source: string;
  imageSize?: "1K" | "2K" | "4K";
};

export type HostedImageProviderRequest = {
  path: string;
  headers: Record<string, string>;
  body: Record<string, unknown>;
  timeoutMs: number;
  defaultMimeType: "image/jpeg" | "image/png";
};

export function buildHostedImageProviderRequest(input: {
  config: HostedImageProviderConfig;
  prompt: string;
  aspectRatio?:
    | "1:1"
    | "2:3"
    | "3:2"
    | "3:4"
    | "4:3"
    | "4:5"
    | "5:4"
    | "9:16"
    | "16:9"
    | "21:9";
  sourceImages?: Array<{ base64Data: string; mimeType: "image/jpeg" | "image/png" | "image/webp" }>;
}): HostedImageProviderRequest {
  const sourceImages = input.sourceImages ?? [];
  const editing = sourceImages.length > 0;
  const premiumEditing =
    editing && /\bpro\b/i.test(input.config.model);
  const responseFormat: Record<string, string> = {
    type: "image",
    mime_type: "image/png",
    image_size: input.config.imageSize ?? "2K",
  };
  if (input.aspectRatio) responseFormat.aspect_ratio = input.aspectRatio;
  return {
    path: "/interactions",
    headers: {
      "x-goog-api-key": input.config.apiKey,
      "content-type": "application/json",
    },
    body: {
      model: input.config.model,
      store: false,
      input: sourceImages.length > 0
        ? [
            { type: "text", text: input.prompt },
            ...sourceImages.map((image) => ({
              type: "image",
              data: image.base64Data,
              mime_type: image.mimeType,
            })),
          ]
        : input.prompt,
      system_instruction: sourceImages.length > 0
        ? [
            "Treat the first supplied image as the primary canvas to edit, not as inspiration for a new recreation.",
            "Treat any additional images only as ordered identity, character, product, style, or object references.",
            "Apply only the user's requested visual delta.",
            "Preserve every unmentioned face, identity, body, product geometry, logo, text, object, crop, camera angle, lighting, texture, color, transparency, and composition detail.",
            "Do not add, remove, beautify, restyle, retouch, or rewrite anything unless the user explicitly requested it.",
          ].join(" ")
        : "Follow the user's visual request precisely. Do not add unrequested text, logos, watermarks, or objects.",
      ...(premiumEditing
        ? { generation_config: { thinking_level: "high" } }
        : {}),
      response_format: responseFormat,
    },
    timeoutMs: 150_000,
    defaultMimeType: "image/png",
  };
}

export function extractHostedGeneratedImage(payload: unknown): {
  base64: string | null;
  mimeType: string | null;
  revisedPrompt: string | null;
} {
  const visited = new Set<unknown>();
  let base64: string | null = null;
  let detectedMimeType: string | null = null;
  let revisedPrompt: string | null = null;

  const asRecord = (value: unknown): Record<string, unknown> | null =>
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null;
  const imageMimeType = (record: Record<string, unknown> | null): string | null => {
    const value =
      typeof record?.mime_type === "string"
        ? record.mime_type
        : typeof record?.mimeType === "string"
          ? record.mimeType
          : null;
    return value?.startsWith("image/") ? value : null;
  };

  const visit = (value: unknown, parentKey = "") => {
    if (!value || typeof value !== "object" || visited.has(value)) return;
    visited.add(value);
    if (Array.isArray(value)) {
      for (const item of value) visit(item, parentKey);
      return;
    }

    const record = value as Record<string, unknown>;
    if (!base64 && typeof record.b64_json === "string" && record.b64_json.trim()) {
      base64 = record.b64_json.trim();
    }
    const outputImage = asRecord(record.output_image);
    const inlineData = asRecord(record.inline_data) ?? asRecord(record.inlineData);
    for (const candidate of [outputImage, inlineData]) {
      if (!base64 && typeof candidate?.data === "string" && candidate.data.trim()) {
        base64 = candidate.data.trim();
      }
      detectedMimeType ??= imageMimeType(candidate);
    }

    const recordMimeType = imageMimeType(record);
    detectedMimeType ??= recordMimeType;
    if (
      !base64 &&
      typeof record.data === "string" &&
      record.data.trim() &&
      (parentKey.toLowerCase().includes("image") || Boolean(recordMimeType))
    ) {
      base64 = record.data.trim();
    }
    if (!revisedPrompt && typeof record.revised_prompt === "string" && record.revised_prompt.trim()) {
      revisedPrompt = record.revised_prompt.trim();
    }
    if (!revisedPrompt && typeof record.text === "string" && record.text.trim()) {
      revisedPrompt = record.text.trim();
    }
    for (const [key, nested] of Object.entries(record)) visit(nested, key);
  };

  visit(payload);
  return { base64, mimeType: detectedMimeType, revisedPrompt };
}
