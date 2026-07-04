import type { SharedBrainProvider } from "./runtime.js";
import {
  STREAM_MAX_CONTENT_CHARS,
  STREAM_MAX_REASONING_CHARS,
} from "./provider-response.js";

export type SharedBrainInferenceDelta = {
  delta: string;
  content: string;
  provider: SharedBrainProvider;
  model: string;
  firstDeltaMs: number;
  /** Incremental reasoning text emitted by reasoning-channel models (gpt-oss). */
  reasoningDelta?: string;
  /** Full reasoning text accumulated so far. */
  reasoningContent?: string;
};

export function commonPrefixLength(a: string, b: string): number {
  const max = Math.min(a.length, b.length);
  let i = 0;
  while (i < max && a[i] === b[i]) {
    i++;
  }
  return i;
}

export function createDeltaPublisherCore(input: {
  startedAt: number;
  provider: SharedBrainProvider;
  model: string;
  onDelta?: (delta: SharedBrainInferenceDelta) => void | Promise<void>;
  computeVisibleText: (full: string) => string;
  looksLikeReasoningDumpOpening: (text: string) => boolean;
}) {
  let firstDeltaMs: number | null = null;
  let lastPublishedContent = "";
  let lastObservedContent = "";
  let lastVisibleContent = "";
  let pendingContent = "";
  let lastFlushAt = input.startedAt;
  let emittedFirstChunk = false;

  const DUMP_GATE_MIN_CHARS = 24;
  const DUMP_GATE_RELEASE_CHARS = 64;
  let holdingFirstWindow = true;
  let suppressedAsReasoningDump = false;

  function evaluateFirstWindow(force: boolean): "hold" | "suppress" | "release" {
    const opening = lastVisibleContent.trimStart();
    if (!force && opening.length < DUMP_GATE_MIN_CHARS) {
      return "hold";
    }
    if (input.looksLikeReasoningDumpOpening(opening)) {
      return "suppress";
    }
    if (
      force ||
      opening.length >= DUMP_GATE_RELEASE_CHARS ||
      /[.!?…\n]/.test(opening)
    ) {
      return "release";
    }
    return "hold";
  }

  let lastReasoningContent = "";
  let lastReasoningFlushAt = input.startedAt;

  function normalizeDelta(value: string): string {
    return value.replace(/\r\n/g, "\n");
  }

  function shouldFlushPending(buffer: string, force: boolean): boolean {
    if (force) {
      return buffer.length > 0;
    }
    if (!emittedFirstChunk) {
      return buffer.length > 0;
    }
    if (buffer.length >= 32) {
      return true;
    }
    if (/[.!?…]\s*$/.test(buffer)) {
      return true;
    }
    if (/\n{2,}$/.test(buffer)) {
      return true;
    }
    return buffer.length >= 12 && Date.now() - lastFlushAt >= 24;
  }

  return {
    get firstDeltaMs() {
      return firstDeltaMs;
    },
    get suppressedAsReasoningDump() {
      return suppressedAsReasoningDump;
    },
    get hasPublished() {
      return lastPublishedContent.length > 0;
    },
    async publishReplacement(text: string) {
      if (!input.onDelta) {
        return;
      }
      const replacement = normalizeDelta(String(text ?? "")).trim();
      if (!replacement || lastPublishedContent.length > 0) {
        return;
      }
      suppressedAsReasoningDump = false;
      holdingFirstWindow = false;
      pendingContent = "";
      lastPublishedContent = replacement;
      emittedFirstChunk = true;
      firstDeltaMs ??= Math.max(0, Date.now() - input.startedAt);
      lastFlushAt = Date.now();
      await input.onDelta({
        delta: replacement,
        content: replacement,
        provider: input.provider,
        model: input.model,
        firstDeltaMs,
      });
    },
    async publish(
      _delta: string,
      content: string,
      options: { force?: boolean } = {},
    ) {
      if (!input.onDelta) {
        return;
      }
      if (lastPublishedContent.length >= STREAM_MAX_CONTENT_CHARS) {
        return;
      }

      const normalizedContent = normalizeDelta(
        content.length > STREAM_MAX_CONTENT_CHARS
          ? content.slice(0, STREAM_MAX_CONTENT_CHARS)
          : content,
      );

      if (!normalizedContent.trim() && !options.force) {
        return;
      }

      if (normalizedContent !== lastObservedContent) {
        lastObservedContent = normalizedContent;
        const visibleContent = input.computeVisibleText(normalizedContent);
        if (visibleContent !== lastVisibleContent) {
          const appended = visibleContent.startsWith(lastVisibleContent)
            ? visibleContent.slice(lastVisibleContent.length)
            : visibleContent.slice(
                commonPrefixLength(visibleContent, lastVisibleContent),
              );
          lastVisibleContent = visibleContent;
          pendingContent += appended;
        }
      }

      if (suppressedAsReasoningDump) {
        pendingContent = "";
        return;
      }
      if (holdingFirstWindow) {
        const verdict = evaluateFirstWindow(options.force === true);
        if (verdict === "hold") {
          return;
        }
        if (verdict === "suppress") {
          suppressedAsReasoningDump = true;
          pendingContent = "";
          return;
        }
        holdingFirstWindow = false;
      }

      if (!shouldFlushPending(pendingContent, options.force === true)) {
        return;
      }

      const flushedDelta = pendingContent;
      pendingContent = "";
      lastPublishedContent += flushedDelta;
      emittedFirstChunk = true;
      firstDeltaMs ??= Math.max(0, Date.now() - input.startedAt);
      lastFlushAt = Date.now();

      await input.onDelta({
        delta: flushedDelta,
        content: lastPublishedContent,
        provider: input.provider,
        model: input.model,
        firstDeltaMs,
      });
    },
    async publishReasoning(
      fullReasoning: string,
      options: { force?: boolean } = {},
    ) {
      if (!input.onDelta) return;
      if (lastReasoningContent.length >= STREAM_MAX_REASONING_CHARS) return;
      const normalized = normalizeDelta(
        fullReasoning.length > STREAM_MAX_REASONING_CHARS
          ? fullReasoning.slice(0, STREAM_MAX_REASONING_CHARS)
          : fullReasoning,
      );
      if (normalized === lastReasoningContent) return;

      const grew = normalized.length - lastReasoningContent.length;
      if (
        !options.force &&
        grew < 60 &&
        Date.now() - lastReasoningFlushAt < 80
      ) {
        return;
      }
      const reasoningDelta = normalized.startsWith(lastReasoningContent)
        ? normalized.slice(lastReasoningContent.length)
        : normalized;
      lastReasoningContent = normalized;
      lastReasoningFlushAt = Date.now();
      firstDeltaMs ??= Math.max(0, Date.now() - input.startedAt);

      await input.onDelta({
        delta: "",
        content: lastPublishedContent,
        provider: input.provider,
        model: input.model,
        firstDeltaMs,
        reasoningDelta,
        reasoningContent: lastReasoningContent,
      });
    },
  };
}
