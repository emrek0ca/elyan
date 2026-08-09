import type { SharedBrainProvider } from "./runtime.js";
import type { SharedBrainWorkload } from "./workloads.js";
import { getChatCompletionPath } from "./provider-request.js";

export const STREAM_MAX_CONTENT_CHARS = 512 * 1024;
export const STREAM_MAX_REASONING_CHARS = 128 * 1024;
export const STREAM_CONTINUATION_DIRECTIVE =
  "Continue from exactly where you stopped, without repeating.";
export const STREAM_CONTINUATION_MAX_HOPS = 2;
const STREAM_CONTINUATION_MIN_TOKENS = 200;

function readTextPart(value: unknown): string {
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return "";
  }
  const record = value as Record<string, unknown>;
  if (record.thought === true || record.reasoning === true) return "";
  const type = typeof record.type === "string" ? record.type.toLowerCase() : "";
  if (type && !["text", "output_text"].includes(type)) return "";
  const text = record.text;
  return typeof text === "string" && text.trim() ? text.trim() : "";
}

function readTextParts(value: unknown): string {
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  if (!Array.isArray(value)) {
    return "";
  }
  return value.map(readTextPart).filter(Boolean).join("\n").trim();
}

function readNativeInteractionText(value: unknown): string {
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  if (Array.isArray(value)) {
    return value.map(readNativeInteractionText).filter(Boolean).join("\n").trim();
  }
  if (!value || typeof value !== "object") {
    return "";
  }
  const record = value as Record<string, unknown>;
  if (record.thought === true || record.type === "thought") {
    return "";
  }
  if (typeof record.output_text === "string" && record.output_text.trim()) {
    return record.output_text.trim();
  }
  if (record.type === "text" && typeof record.text === "string") {
    return record.text.trim();
  }
  for (const key of ["output", "steps", "content", "parts", "interaction"]) {
    const text = readNativeInteractionText(record[key]);
    if (text) return text;
  }
  return "";
}

export function extractResponseText(
  provider: SharedBrainProvider | string,
  payload: unknown,
): string {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return "";
  }

  const record = payload as Record<string, unknown>;
  const nativeText = readNativeInteractionText(payload);
  if (nativeText) {
    return nativeText;
  }
  if (provider === "claude") {
    const text = readTextParts(record.content);
    if (text) {
      return text;
    }
  }

  const choices = record.choices;
  if (Array.isArray(choices)) {
    for (const choice of choices) {
      if (!choice || typeof choice !== "object" || Array.isArray(choice)) {
        continue;
      }
      const message = (choice as Record<string, unknown>).message;
      if (message && typeof message === "object" && !Array.isArray(message)) {
        const content = (message as Record<string, unknown>).content;
        const text = readTextParts(content);
        if (text) {
          return text;
        }
      }
    }
  }

  const response = record.response;
  if (typeof response === "string" && response.trim()) {
    return response.trim();
  }

  const message = record.message;
  if (message && typeof message === "object" && !Array.isArray(message)) {
    const content = (message as Record<string, unknown>).content;
    const text = readTextParts(content);
    if (text) {
      return text;
    }
  }

  const candidates = record.candidates;
  if (Array.isArray(candidates)) {
    for (const candidate of candidates) {
      if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) {
        continue;
      }
      const content = (candidate as Record<string, unknown>).content;
      if (!content || typeof content !== "object" || Array.isArray(content)) {
        continue;
      }
      const text = readTextParts((content as Record<string, unknown>).parts);
      if (text) {
        return text;
      }
    }
  }

  return "";
}

export function extractResponseDelta(payload: unknown): string {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return "";
  }

  const record = payload as Record<string, unknown>;
  const nativeDelta = record.delta;
  if (nativeDelta && typeof nativeDelta === "object" && !Array.isArray(nativeDelta)) {
    const delta = nativeDelta as Record<string, unknown>;
    if (delta.type === "text" && typeof delta.text === "string") {
      return delta.text;
    }
  }
  const response = record.response;
  if (typeof response === "string" && response.length > 0) {
    return response;
  }

  const message = record.message;
  if (message && typeof message === "object" && !Array.isArray(message)) {
    const content = (message as Record<string, unknown>).content;
    if (typeof content === "string" && content.length > 0) {
      return content;
    }
  }

  const choices = record.choices;
  if (Array.isArray(choices)) {
    for (const choice of choices) {
      if (!choice || typeof choice !== "object" || Array.isArray(choice)) {
        continue;
      }
      const delta = (choice as Record<string, unknown>).delta;
      if (delta && typeof delta === "object" && !Array.isArray(delta)) {
        const content = (delta as Record<string, unknown>).content;
        if (typeof content === "string" && content.length > 0) {
          return content;
        }
      }
    }
  }

  return "";
}

/**
 * Pulls the reasoning chunk emitted by gpt-oss/o1-style models on their
 * separate "thinking" channel.
 */
export function extractResponseReasoning(payload: unknown): string {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return "";
  }

  const record = payload as Record<string, unknown>;
  const message = record.message;
  if (message && typeof message === "object" && !Array.isArray(message)) {
    const reasoning = (message as Record<string, unknown>).reasoning;
    if (typeof reasoning === "string" && reasoning.length > 0) {
      return reasoning;
    }
  }

  const choices = record.choices;
  if (Array.isArray(choices)) {
    for (const choice of choices) {
      if (!choice || typeof choice !== "object" || Array.isArray(choice)) {
        continue;
      }
      const delta = (choice as Record<string, unknown>).delta;
      if (delta && typeof delta === "object" && !Array.isArray(delta)) {
        const chunk = delta as Record<string, unknown>;
        const reasoning = chunk.reasoning;
        if (typeof reasoning === "string" && reasoning.length > 0) {
          return reasoning;
        }
        const reasoningContent = chunk.reasoning_content;
        if (typeof reasoningContent === "string" && reasoningContent.length > 0) {
          return reasoningContent;
        }
      }
    }
  }

  return "";
}

export function shouldStreamReasoning(
  workload: SharedBrainWorkload | undefined,
): boolean {
  if (!workload) {
    return false;
  }
  return (
    workload === "planning" ||
    workload === "document_generate" ||
    workload === "mobile_chat_balanced" ||
    workload === "mobile_chat_deep_refine" ||
    workload === "document_analysis" ||
    workload === "vision_reasoning" ||
    workload === "image_analyze"
  );
}

export function supportsNativeStreamingAttempt(
  provider: SharedBrainProvider,
  path: string,
): boolean {
  if (provider === "claude") {
    return false;
  }
  if (provider === "ollama") {
    return path === "/api/generate" || path === getChatCompletionPath(provider);
  }
  if (provider === "gemini") {
    return (
      path.startsWith("/interactions") ||
      path === getChatCompletionPath(provider)
    );
  }
  return (
    provider === "groq" ||
    provider === "openai" ||
    provider === "openrouter" ||
    provider === "vllm" ||
    provider === "llamacpp"
  );
}

export function extractResponseFinishReason(payload: unknown): string | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }

  const record = payload as Record<string, unknown>;
  const nativeStatus =
    typeof record.status === "string"
      ? record.status
      : record.interaction &&
          typeof record.interaction === "object" &&
          !Array.isArray(record.interaction) &&
          typeof (record.interaction as Record<string, unknown>).status === "string"
        ? (record.interaction as Record<string, unknown>).status
        : null;
  if (typeof nativeStatus === "string" && nativeStatus.trim()) {
    const normalized = nativeStatus.trim().toLowerCase();
    if (["completed", "succeeded", "success"].includes(normalized)) return "stop";
    if (["failed", "error", "cancelled", "canceled"].includes(normalized)) return "error";
  }
  for (const key of ["finish_reason", "finishReason", "done_reason"]) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim().toLowerCase();
    }
  }

  const choices = record.choices;
  if (Array.isArray(choices)) {
    for (const choice of choices) {
      if (!choice || typeof choice !== "object" || Array.isArray(choice)) {
        continue;
      }
      const value = (choice as Record<string, unknown>).finish_reason;
      if (typeof value === "string" && value.trim()) {
        return value.trim().toLowerCase();
      }
    }
  }

  return null;
}

export function shouldAttemptStreamContinuation(input: {
  finishReason: string | null;
  text: string;
}): boolean {
  const reason = input.finishReason?.toLowerCase();
  if (reason !== "length" && reason !== "max_tokens") {
    return false;
  }

  const text = input.text.trimEnd();
  if (!text) {
    return false;
  }

  return !/[.!?…]$/.test(text);
}

export function resolveStreamContinuationTokenBudget(input: {
  maxTokens: number;
  usedContinuationTokens: number;
}): number {
  const remaining = Math.max(0, input.maxTokens - input.usedContinuationTokens);
  if (remaining < STREAM_CONTINUATION_MIN_TOKENS) {
    return 0;
  }
  return Math.min(
    remaining,
    Math.max(STREAM_CONTINUATION_MIN_TOKENS, Math.floor(input.maxTokens / 2)),
  );
}

export function stripRepeatedContinuationPrefix(
  previous: string,
  next: string,
): string {
  const normalizedNext = String(next ?? "");
  if (!previous || !normalizedNext) {
    return normalizedNext;
  }

  const maxOverlap = Math.min(previous.length, normalizedNext.length, 1_000);
  for (let size = maxOverlap; size >= 12; size -= 1) {
    if (previous.endsWith(normalizedNext.slice(0, size))) {
      return normalizedNext.slice(size);
    }
  }
  return normalizedNext;
}
