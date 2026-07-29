/**
 * F2: starting work while the user is still speaking.
 *
 * Every committed segment is examined the moment it lands. If it is already a
 * complete instruction, the task is created right then — the microphone stays
 * open and the user can keep talking. That concurrency is the product promise
 * ("I keep working while you keep talking"); waiting for the mic to close would
 * make live voice just a faster dictation box.
 *
 * The gate is deliberately deterministic. `classifyIntent` is a rule and
 * embedding classifier, not a model call, so per-segment classification costs
 * nothing and cannot itself add latency to the thing it is trying to speed up
 * (CANLI-SES-PLANI.md §3 F2: "no new model call").
 *
 * Fail-closed: anything ambiguous stays conversation. A false dispatch starts
 * real work — files move, mail goes out — off half a sentence the user was
 * still building. A missed dispatch merely costs the round trip that today's
 * turn-based flow already pays.
 *
 * This gate decides *when* to start, never *what is allowed*. Side-effectful
 * work still passes the normal approval gate inside `createTask`; voice does
 * not bypass it (§4 trap 4).
 */

import type { IntentClassification } from "../../core/understanding/types.js";

/** Below this a segment is a fragment, not an instruction. */
export const MIN_DISPATCH_WORDS = 3;

/**
 * The classifier reports 0.55 for a plain chat guess and climbs with each rule
 * that fires. Requiring more than that keeps single-weak-signal matches — the
 * ones most likely to be a half-finished sentence — in conversation.
 */
export const MIN_DISPATCH_CONFIDENCE = 0.62;

/**
 * Turkish sentences put the verb last, so a segment cut mid-clause usually ends
 * on a conjunction or a filler. These are the endings that mean "I am not done
 * talking" — dispatching on them is the mid-sentence cut this whole design is
 * built to avoid.
 */
const TRAILING_CONTINUATION =
  /(?:^|\s)(ve|veya|ama|ancak|çünkü|yani|sonra|ayrıca|ki|de|da|ile|için|gibi|hem|ya|şey|şeyi|bir|bu|şu|o)\s*$/iu;

export type VoiceDispatchDecision =
  | { dispatch: false; reason: string }
  | { dispatch: true; title: string };

export function normalizeSegmentText(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

/** Short, stable title for the task list. */
export function deriveVoiceTaskTitle(text: string, maxLength = 80): string {
  const normalized = normalizeSegmentText(text);
  if (normalized.length <= maxLength) return normalized;
  const clipped = normalized.slice(0, maxLength);
  const lastSpace = clipped.lastIndexOf(" ");
  return `${(lastSpace > 24 ? clipped.slice(0, lastSpace) : clipped).trim()}…`;
}

/**
 * Decide whether a committed segment is a complete, actionable instruction.
 */
export function decideVoiceDispatch(
  text: string,
  classification: Pick<
    IntentClassification,
    | "primaryIntent"
    | "confidence"
    | "requiresToolUse"
    | "requiresLocalRuntime"
    | "requiresLongRunningTask"
  >,
): VoiceDispatchDecision {
  const normalized = normalizeSegmentText(text);
  if (!normalized) {
    return { dispatch: false, reason: "empty_segment" };
  }

  const words = normalized.split(" ").filter(Boolean);
  if (words.length < MIN_DISPATCH_WORDS) {
    return { dispatch: false, reason: "too_short" };
  }

  if (TRAILING_CONTINUATION.test(normalized)) {
    return { dispatch: false, reason: "sentence_incomplete" };
  }

  // A question is a request for an answer, not for work. Answering belongs to
  // the conversation path, which is already streaming.
  if (normalized.endsWith("?")) {
    return { dispatch: false, reason: "question" };
  }

  if (
    classification.primaryIntent === "chat" ||
    classification.primaryIntent === "unknown"
  ) {
    return { dispatch: false, reason: "conversational_intent" };
  }

  // Only work that actually needs the runtime is worth pre-starting. Anything
  // the assistant can just answer stays in the chat stream.
  if (
    !classification.requiresToolUse &&
    !classification.requiresLocalRuntime &&
    !classification.requiresLongRunningTask
  ) {
    return { dispatch: false, reason: "no_tool_use" };
  }

  if (classification.confidence < MIN_DISPATCH_CONFIDENCE) {
    return { dispatch: false, reason: "low_confidence" };
  }

  return { dispatch: true, title: deriveVoiceTaskTitle(normalized) };
}

/** Marks a task as started from live voice rather than the turn-based path. */
export const VOICE_LIVE_CHANNEL = "voice_live";

export function buildVoiceTaskPayload(input: {
  text: string;
  sessionId: string | null;
  segmentId: number;
  locale?: string;
}): Record<string, unknown> {
  return {
    prompt: normalizeSegmentText(input.text),
    source: "voice",
    metadata: {
      channel: VOICE_LIVE_CHANNEL,
      voice: {
        sessionId: input.sessionId,
        segmentId: input.segmentId,
        ...(input.locale ? { locale: input.locale } : {}),
        // The mic was still open when this task was created. Downstream
        // presentation uses this to avoid interrupting the speaker.
        concurrent: true,
      },
    },
  };
}
