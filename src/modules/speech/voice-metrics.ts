/**
 * F4: the numbers that decide whether live voice actually got faster.
 *
 * Without these, "it feels quick now" is a guess — and the sliding-window
 * design has a specific, checkable claim to defend (CANLI-SES-PLANI.md §4):
 *
 *   - first provisional transcript  < 400 ms
 *   - end of sentence → task start  < 800 ms
 *
 * Durations go through `recordStageDuration`, so they land in the same p95
 * table `/internal/perf` already serves. The revision rate is a ratio rather
 * than a duration, so it is counted here and attached to the same endpoint.
 * Only counts and durations are kept — no transcript text, no user ids.
 */

import { getPerfSnapshot, recordStageDuration } from "../../lib/perf-telemetry.js";

/** §4 target: the caption must appear this fast. */
export const FIRST_PARTIAL_TARGET_MS = 400;

/** §4 target: end of sentence → work started. */
export const FINAL_TO_DISPATCH_TARGET_MS = 800;

/**
 * Below this many samples a p95 is noise — one cold Groq call would trip the
 * alarm on the first request after a deploy.
 */
export const MIN_SAMPLES_FOR_ALARM = 20;

export const VOICE_FIRST_PARTIAL_STAGE = "voice.first_partial";
export const VOICE_FINAL_TO_DISPATCH_STAGE = "voice.final_to_dispatch";
export const VOICE_SEGMENT_FINAL_STAGE = "voice.segment_final";

type RevisionCounters = {
  segments: number;
  partials: number;
  /** Partials whose text was later contradicted, not merely extended. */
  rewrites: number;
};

const counters: RevisionCounters = {
  segments: 0,
  partials: 0,
  rewrites: 0,
};

/** Latency from the first audio frame of a segment to its first partial. */
export function recordFirstPartialLatency(durationMs: number): void {
  if (!Number.isFinite(durationMs) || durationMs < 0) return;
  recordStageDuration(VOICE_FIRST_PARTIAL_STAGE, durationMs);
}

/** Latency from a committed segment to the task actually being created. */
export function recordFinalToDispatchLatency(durationMs: number): void {
  if (!Number.isFinite(durationMs) || durationMs < 0) return;
  recordStageDuration(VOICE_FINAL_TO_DISPATCH_STAGE, durationMs);
}

/** How long the segment's audio was, as a load reference for the two above. */
export function recordSegmentDuration(durationMs: number): void {
  if (!Number.isFinite(durationMs) || durationMs < 0) return;
  recordStageDuration(VOICE_SEGMENT_FINAL_STAGE, durationMs);
}

/**
 * A partial that only extends the previous one is the window working as
 * intended. One that rewrites earlier words is what the user sees as the
 * caption "changing its mind", so the two are counted separately.
 */
export function recordPartialEmitted(
  previousText: string,
  nextText: string,
): void {
  counters.partials += 1;
  if (!nextText.startsWith(previousText)) {
    counters.rewrites += 1;
  }
}

export function recordSegmentCommitted(): void {
  counters.segments += 1;
}

export function getVoiceStreamingTelemetry(): {
  segments: number;
  partials: number;
  rewrites: number;
  /** Rewrites per partial. Rising means the window is too short. */
  rewriteRate: number;
  /** Partials per committed segment. */
  partialsPerSegment: number;
} {
  return {
    segments: counters.segments,
    partials: counters.partials,
    rewrites: counters.rewrites,
    rewriteRate:
      counters.partials > 0
        ? Number((counters.rewrites / counters.partials).toFixed(4))
        : 0,
    partialsPerSegment:
      counters.segments > 0
        ? Number((counters.partials / counters.segments).toFixed(2))
        : 0,
  };
}

export type VoiceLatencyTarget = {
  stage: string;
  targetMs: number;
  p95Ms: number;
  count: number;
  /** True only when there is enough data to trust the verdict. */
  breached: boolean;
};

export type VoiceLatencyReport = {
  firstPartial: VoiceLatencyTarget;
  finalToDispatch: VoiceLatencyTarget;
  breached: boolean;
};

function evaluateStage(
  stages: ReturnType<typeof getPerfSnapshot>["stages"],
  stage: string,
  targetMs: number,
): VoiceLatencyTarget {
  const entry = stages[stage];
  const p95Ms = entry?.p95Ms ?? 0;
  const count = entry?.count ?? 0;
  return {
    stage,
    targetMs,
    p95Ms,
    count,
    breached: count >= MIN_SAMPLES_FOR_ALARM && p95Ms > targetMs,
  };
}

/**
 * Compares the live p95s against the two §4 targets.
 *
 * The numbers were already on `/internal/perf`, but a number on a page nobody
 * opens is not a check — this turns them into a verdict, and
 * [maybeWarnOnVoiceLatencyBreach] turns the verdict into a log line.
 */
export function evaluateVoiceLatencyTargets(): VoiceLatencyReport {
  const { stages } = getPerfSnapshot();
  const firstPartial = evaluateStage(
    stages,
    VOICE_FIRST_PARTIAL_STAGE,
    FIRST_PARTIAL_TARGET_MS,
  );
  const finalToDispatch = evaluateStage(
    stages,
    VOICE_FINAL_TO_DISPATCH_STAGE,
    FINAL_TO_DISPATCH_TARGET_MS,
  );
  return {
    firstPartial,
    finalToDispatch,
    breached: firstPartial.breached || finalToDispatch.breached,
  };
}

/** Edge-triggered so a sustained regression logs once, not once per segment. */
let lastBreachSignature = "";

export type VoiceLatencyLogger = (
  payload: Record<string, unknown>,
  message: string,
) => void;

/**
 * Logs when the breach state *changes*. Called on every committed segment; a
 * steady-state breach must not turn the log into the regression.
 */
export function maybeWarnOnVoiceLatencyBreach(
  warn: VoiceLatencyLogger,
  info?: VoiceLatencyLogger,
): VoiceLatencyReport {
  const report = evaluateVoiceLatencyTargets();
  const signature = report.breached
    ? `${report.firstPartial.breached ? "p" : ""}${report.finalToDispatch.breached ? "d" : ""}`
    : "";
  if (signature === lastBreachSignature) return report;

  const previouslyBreached = lastBreachSignature !== "";
  lastBreachSignature = signature;

  if (report.breached) {
    warn(
      {
        metric: "voice_latency_target_breached",
        firstPartialP95Ms: report.firstPartial.p95Ms,
        firstPartialTargetMs: report.firstPartial.targetMs,
        firstPartialBreached: report.firstPartial.breached,
        finalToDispatchP95Ms: report.finalToDispatch.p95Ms,
        finalToDispatchTargetMs: report.finalToDispatch.targetMs,
        finalToDispatchBreached: report.finalToDispatch.breached,
      },
      "live voice latency target breached",
    );
  } else if (previouslyBreached) {
    info?.(
      {
        metric: "voice_latency_target_recovered",
        firstPartialP95Ms: report.firstPartial.p95Ms,
        finalToDispatchP95Ms: report.finalToDispatch.p95Ms,
      },
      "live voice latency back within target",
    );
  }
  return report;
}

export function resetVoiceStreamingTelemetry(): void {
  counters.segments = 0;
  counters.partials = 0;
  counters.rewrites = 0;
  lastBreachSignature = "";
}
