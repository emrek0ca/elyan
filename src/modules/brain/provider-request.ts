import type { ResolvedAttachmentContextVisionImage } from "./attachment-context.js";
import {
  ANALYTICAL_GENERATION_TEMPERATURE,
  isReasoningChannelModel,
} from "./generation-policy.js";
import type { SharedBrainProvider } from "./runtime.js";
import {
  buildTurnEnvelopeSystemInstruction,
  buildTurnEnvelopeResponseFormat,
  TURN_ENVELOPE_COMPACT_SCHEMA_INSTRUCTION,
} from "./turn-envelope.js";

export type SharedBrainConversationMessage = {
  role: "system" | "user" | "assistant";
  content: string;
};

export type SharedBrainRequestAttempt = {
  path: string;
  body: Record<string, unknown>;
  turnEnvelopeMode?: boolean;
  forceNonStreaming?: boolean;
};

type OpenAiContentBlock =
  | { type: "text"; text: string }
  | { type: "image_url"; image_url: { url: string; detail?: "low" | "high" | "auto" } };

function compactText(value: string): string {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

export function getChatCompletionPath(provider: SharedBrainProvider): string {
  if (provider === "ollama") {
    return "/api/chat";
  }
  if (provider === "claude") {
    return "/messages";
  }
  return "/chat/completions";
}

function buildAnthropicRequestBody(
  model: string,
  messages: SharedBrainConversationMessage[],
  maxTokens: number,
) {
  const system = messages
    .filter((message) => message.role === "system")
    .map((message) => compactText(message.content))
    .filter(Boolean)
    .join("\n\n");

  return {
    model,
    max_tokens: maxTokens,
    temperature: 0.25,
    ...(system ? { system } : {}),
    messages: messages
      .filter((message) => message.role !== "system")
      .map((message) => ({
        role: message.role === "assistant" ? "assistant" : "user",
        content: [
          {
            type: "text",
            text: message.content,
          },
        ],
      })),
  };
}

function buildOpenAiMessagesWithVision(
  provider: SharedBrainProvider,
  messages: SharedBrainConversationMessage[],
  visionImages: ResolvedAttachmentContextVisionImage[],
): unknown[] {
  if (visionImages.length === 0) {
    return messages as unknown[];
  }
  const result: unknown[] = [];
  for (let i = 0; i < messages.length; i += 1) {
    const msg = messages[i];
    if (i === messages.length - 1 && msg.role === "user") {
      const textContent =
        typeof msg.content === "string"
          ? msg.content
          : String(msg.content ?? "");
      const blocks: OpenAiContentBlock[] = [
        { type: "text", text: textContent },
      ];
      for (const img of visionImages.slice(0, 5)) {
        blocks.push({
          type: "image_url",
          image_url: {
            url: `data:${img.mimeType};base64,${img.base64}`,
            ...(provider === "gemini" && img.detail ? { detail: img.detail } : {}),
          },
        });
      }
      result.push({ ...msg, content: blocks });
    } else {
      result.push(msg);
    }
  }
  return result;
}

export function buildRequestBody(
  provider: SharedBrainProvider,
  model: string,
  messages: SharedBrainConversationMessage[],
  maxTokens: number,
  keepAlive?: string,
  stream = false,
  visionImages: ResolvedAttachmentContextVisionImage[] = [],
  reasoningPolicy: "hidden" | "visible" = "hidden",
  reasoningEffort: "low" | "medium" | "high" = "low",
  temperature: number = ANALYTICAL_GENERATION_TEMPERATURE,
  responseSchema?: Record<string, unknown>,
) {
  if (provider === "ollama") {
    return {
      model,
      messages,
      stream,
      ...(keepAlive ? { keep_alive: keepAlive } : {}),
      options: {
        temperature,
        num_predict: maxTokens,
      },
    };
  }

  if (provider === "claude") {
    return buildAnthropicRequestBody(model, messages, maxTokens);
  }

  const outMessages = buildOpenAiMessagesWithVision(provider, messages, visionImages);
  return {
    model,
    messages: outMessages,
    temperature,
    max_tokens: maxTokens,
    stream,
    ...(responseSchema && ["gemini", "groq", "openai", "openrouter"].includes(provider)
      ? {
          response_format: {
            type: "json_schema",
            json_schema: {
              name: "elyan_structured_output",
              strict: true,
              schema: responseSchema,
            },
          },
        }
      : {}),
    ...(isReasoningChannelModel(model)
      ? {
          reasoning_format: reasoningPolicy === "visible" ? "parsed" : "hidden",
          reasoning_effort:
            reasoningEffort === "high" && maxTokens < 1500
              ? "medium"
              : reasoningEffort,
        }
      : {}),
  };
}

export function buildGenerateRequestBody(
  model: string,
  prompt: string,
  maxTokens: number,
  keepAlive?: string,
  stream = false,
  temperature: number = ANALYTICAL_GENERATION_TEMPERATURE,
) {
  return {
    model,
    prompt,
    stream,
    ...(keepAlive ? { keep_alive: keepAlive } : {}),
    options: {
      temperature,
      num_predict: maxTokens,
    },
  };
}

function supportsTurnEnvelopeResponseFormat(
  provider: SharedBrainProvider,
  path: string,
): boolean {
  return (
    path === getChatCompletionPath(provider) &&
    (provider === "groq" || provider === "openai" || provider === "openrouter")
  );
}

/**
 * Groq'ta `json_schema` yalnız yapılandırılmış çıktı destekleyen modellerde
 * çalışır; qwen gibi modeller isteği 400 "does not support response format
 * json_schema" ile reddeder (canlıda tüm sağlayıcı zincirini düşürüyordu).
 * Desteklemeyen modeller `json_object` moduna düşer — şema anayasası prompt'a
 * taşınır, otoriter doğrulama zaten Zod parser'dadır.
 */
function modelSupportsJsonSchemaFormat(
  provider: SharedBrainProvider,
  model: unknown,
): boolean {
  if (provider !== "groq") return true;
  const name = String(model ?? "").toLowerCase();
  return name.includes("gpt-oss") || name.startsWith("moonshotai/kimi-k2");
}

function withTurnEnvelopeResponseFormat(
  provider: SharedBrainProvider,
  body: Record<string, unknown>,
  proactiveOpsEnabled: boolean,
): Record<string, unknown> {
  const jsonSchemaSupported = modelSupportsJsonSchemaFormat(
    provider,
    body.model,
  );
  const systemInstruction = jsonSchemaSupported
    ? buildTurnEnvelopeSystemInstruction(proactiveOpsEnabled)
    : `${buildTurnEnvelopeSystemInstruction(proactiveOpsEnabled)} ${TURN_ENVELOPE_COMPACT_SCHEMA_INSTRUCTION}`;
  const messages = Array.isArray(body.messages)
    ? (body.messages as SharedBrainConversationMessage[])
    : null;
  return {
    ...body,
    ...(messages
      ? {
          messages: [
            {
              role: "system",
              content: systemInstruction,
            },
            ...messages,
          ],
        }
      : {}),
    response_format: jsonSchemaSupported
      ? buildTurnEnvelopeResponseFormat(proactiveOpsEnabled)
      : { type: "json_object" },
  };
}

export function buildSharedBrainRequestAttempt(input: {
  provider: SharedBrainProvider;
  path: string;
  body: Record<string, unknown>;
  turnEnvelopeEnabled: boolean;
  proactiveOpsEnabled?: boolean;
}): SharedBrainRequestAttempt {
  const turnEnvelopeMode =
    input.turnEnvelopeEnabled &&
    supportsTurnEnvelopeResponseFormat(input.provider, input.path);
  return {
    path: input.path,
    body: turnEnvelopeMode
      ? withTurnEnvelopeResponseFormat(
          input.provider,
          input.body,
          input.proactiveOpsEnabled === true,
        )
      : input.body,
    turnEnvelopeMode,
  };
}
