import { desc, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { aiProviderInvocations } from "../../db/schema.js";
import { readNumericMetricSummary } from "../../lib/reliability/sample-metrics.js";

const SESSION_MESSAGES_LATENCY_KEY = "metrics:chat:sessions:messages:latency_ms";
const SESSION_MESSAGES_BYTES_KEY = "metrics:chat:sessions:messages:payload_bytes";
const BRAIN_LATENCY_SAMPLE_SIZE = 50;

export type BrainLatencySummary = {
  lastChatLatencyMs: number | null;
  lastStreamingFirstDeltaMs: number | null;
  recentBrainTimeoutCount: number;
  lastBrainResponseAt: string | null;
  completionLatencyP50Ms: number | null;
  completionLatencyP95Ms: number | null;
  firstDeltaP50Ms: number | null;
  firstDeltaP95Ms: number | null;
  attachmentCacheHitRate: number | null;
  recentResponseBytesAverage: number | null;
  sessionPageLatencyP50Ms: number | null;
  sessionPageLatencyP95Ms: number | null;
  sessionPageBytesP50: number | null;
  sessionPageBytesP95: number | null;
};

function readNumberMetadata(metadata: unknown, key: string): number | null {
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return null;
  }
  const value = (metadata as Record<string, unknown>)[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readBooleanMetadata(metadata: unknown, keys: string[]): boolean | null {
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return null;
  }

  const record = metadata as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "boolean") {
      return value;
    }
  }

  return null;
}

function percentile(samples: number[], value: number): number | null {
  if (samples.length === 0) {
    return null;
  }

  const sorted = [...samples].sort((left, right) => left - right);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil((value / 100) * sorted.length) - 1));
  const sample = sorted[index];
  return Number.isFinite(sample) ? Math.round(sample) : null;
}

function average(samples: number[]): number | null {
  if (samples.length === 0) {
    return null;
  }

  const total = samples.reduce((sum, sample) => sum + sample, 0);
  return Math.round(total / samples.length);
}

export async function getBrainLatencySummary(app: FastifyInstance): Promise<BrainLatencySummary> {
  const rows = await app.db
    .select({
      status: aiProviderInvocations.status,
      latencyMs: aiProviderInvocations.latencyMs,
      metadata: aiProviderInvocations.metadata,
      createdAt: aiProviderInvocations.createdAt,
    })
    .from(aiProviderInvocations)
    .where(eq(aiProviderInvocations.route, "shared_brain"))
    .orderBy(desc(aiProviderInvocations.createdAt))
    .limit(BRAIN_LATENCY_SAMPLE_SIZE);

  const latest = rows.find((row) => row.status === "success" || row.status === "fallback") ?? rows[0];
  const successfulRows = rows.filter((row) => row.status === "success" || row.status === "fallback");
  const completionSamples = successfulRows
    .map((row) => readNumberMetadata(row.metadata, "completionLatencyMs") ?? row.latencyMs)
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  const firstDeltaSamples = successfulRows
    .map((row) => readNumberMetadata(row.metadata, "firstDeltaMs"))
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  const responseBytesSamples = successfulRows
    .map((row) => readNumberMetadata(row.metadata, "responseBytes"))
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  const attachmentCacheSignals = successfulRows
    .map((row) => readBooleanMetadata(row.metadata, ["attachmentCacheHit", "cacheHit"]))
    .filter((value): value is boolean => typeof value === "boolean");
  const sessionLatency = await readNumericMetricSummary(app.services?.reliability?.store, SESSION_MESSAGES_LATENCY_KEY);
  const sessionBytes = await readNumericMetricSummary(app.services?.reliability?.store, SESSION_MESSAGES_BYTES_KEY);

  return {
    lastChatLatencyMs: latest?.latencyMs ?? null,
    lastStreamingFirstDeltaMs: latest ? readNumberMetadata(latest.metadata, "firstDeltaMs") : null,
    recentBrainTimeoutCount: rows.filter((row) =>
      JSON.stringify(row.metadata ?? {}).toLowerCase().includes("timeout"),
    ).length,
    lastBrainResponseAt: latest?.createdAt ? latest.createdAt.toISOString() : null,
    completionLatencyP50Ms: percentile(completionSamples, 50),
    completionLatencyP95Ms: percentile(completionSamples, 95),
    firstDeltaP50Ms: percentile(firstDeltaSamples, 50),
    firstDeltaP95Ms: percentile(firstDeltaSamples, 95),
    attachmentCacheHitRate:
      attachmentCacheSignals.length > 0
        ? Number((attachmentCacheSignals.filter(Boolean).length / attachmentCacheSignals.length).toFixed(3))
        : null,
    recentResponseBytesAverage: average(responseBytesSamples),
    sessionPageLatencyP50Ms: sessionLatency?.p50 ?? null,
    sessionPageLatencyP95Ms: sessionLatency?.p95 ?? null,
    sessionPageBytesP50: sessionBytes?.p50 ?? null,
    sessionPageBytesP95: sessionBytes?.p95 ?? null,
  };
}
