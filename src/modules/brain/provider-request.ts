import type { ResolvedAttachmentContextVisionImage } from "./attachment-context.js";
import {
  ANALYTICAL_GENERATION_TEMPERATURE,
  isReasoningChannelModel,
} from "./generation-policy.js";
import type { SharedBrainProvider } from "./runtime.js";
import {
  buildTurnEnvelopeSystemInstruction,
  buildTurnEnvelopeResponseFormat,
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
  | { type: "image_url"; image_url: { url: string } };

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
      for (const img of visionImages) {
        blocks.push({
          type: "image_url",
          image_url: { url: `data:${img.mimeType};base64,${img.base64}` },
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

  const outMessages = buildOpenAiMessagesWithVision(messages, visionImages);
  return {
    model,
    messages: outMessages,
    temperature,
    max_tokens: maxTokens,
    stream,
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

function withTurnEnvelopeResponseFormat(
  body: Record<string, unknown>,
  proactiveOpsEnabled: boolean,
): Record<string, unknown> {
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
              content: buildTurnEnvelopeSystemInstruction(proactiveOpsEnabled),
            },
            ...messages,
          ],
        }
      : {}),
    response_format: buildTurnEnvelopeResponseFormat(proactiveOpsEnabled),
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
      ? withTurnEnvelopeResponseFormat(input.body, input.proactiveOpsEnabled === true)
      : input.body,
    turnEnvelopeMode,
  };
}
