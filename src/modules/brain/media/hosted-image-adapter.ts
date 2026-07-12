export type HostedImageProviderConfig = {
  provider: "gemini" | "openai";
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
  aspectRatio: "1:1" | "2:3" | "3:2" | "9:16" | "16:9";
  openAiSize: "1024x1024" | "1024x1536" | "1536x1024";
}): HostedImageProviderRequest {
  if (input.config.provider === "gemini") {
    return {
      path: "/interactions",
      headers: {
        "x-goog-api-key": input.config.apiKey,
        "content-type": "application/json",
      },
      body: {
        model: input.config.model,
        input: input.prompt,
        response_format: {
          type: "image",
          mime_type: "image/jpeg",
          aspect_ratio: input.aspectRatio,
          image_size: input.config.imageSize ?? "1K",
        },
      },
      timeoutMs: 60_000,
      defaultMimeType: "image/jpeg",
    };
  }

  return {
    path: "/images/generations",
    headers: {
      Authorization: `Bearer ${input.config.apiKey}`,
      "content-type": "application/json",
    },
    body: {
      model: input.config.model,
      prompt: input.prompt,
      size: input.openAiSize,
      response_format: "b64_json",
      n: 1,
      quality: "medium",
      output_format: "png",
    },
    timeoutMs: 45_000,
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
