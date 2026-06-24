import { ReliabilityStore } from "./redis.js";

export type NumericMetricSummary = {
  count: number;
  last: number | null;
  average: number | null;
  p50: number | null;
  p95: number | null;
};

type NumericMetricStoreRecord = {
  samples: number[];
};

const DEFAULT_MAX_SAMPLES = 120;
const DEFAULT_TTL_MS = 24 * 60 * 60 * 1_000;

function clampMetricValue(value: number): number | null {
  if (!Number.isFinite(value)) {
    return null;
  }

  return Math.max(0, Math.round(value));
}

function percentile(samples: number[], value: number): number | null {
  if (samples.length === 0) {
    return null;
  }

  const sorted = [...samples].sort((left, right) => left - right);
  const index = Math.min(
    sorted.length - 1,
    Math.max(0, Math.ceil((value / 100) * sorted.length) - 1),
  );
  return sorted[index] ?? null;
}

function parseMetricRecord(raw: string | null): NumericMetricStoreRecord {
  if (!raw) {
    return {
      samples: [],
    };
  }

  try {
    const parsed = JSON.parse(raw) as NumericMetricStoreRecord | null;
    const samples = Array.isArray(parsed?.samples)
      ? parsed.samples
          .map((sample) => clampMetricValue(Number(sample)))
          .filter((sample): sample is number => sample != null)
      : [];
    return {
      samples,
    };
  } catch {
    return {
      samples: [],
    };
  }
}

export async function recordNumericMetricSample(
  store: ReliabilityStore | undefined,
  key: string,
  value: number,
  options: {
    maxSamples?: number;
    ttlMs?: number;
  } = {},
): Promise<void> {
  if (!store) {
    return;
  }

  const normalizedValue = clampMetricValue(value);
  if (normalizedValue == null) {
    return;
  }

  const record = parseMetricRecord(await store.get(key).catch(() => null));
  const samples = [...record.samples, normalizedValue];
  const maxSamples = Math.max(5, options.maxSamples ?? DEFAULT_MAX_SAMPLES);
  const trimmed = samples.slice(-maxSamples);
  await store
    .set(
      key,
      JSON.stringify({
        samples: trimmed,
      } satisfies NumericMetricStoreRecord),
      options.ttlMs ?? DEFAULT_TTL_MS,
    )
    .catch(() => undefined);
}

export async function readNumericMetricSummary(
  store: ReliabilityStore | undefined,
  key: string,
): Promise<NumericMetricSummary> {
  const record = parseMetricRecord((await store?.get(key).catch(() => null)) ?? null);
  const samples = record.samples;
  if (samples.length === 0) {
    return {
      count: 0,
      last: null,
      average: null,
      p50: null,
      p95: null,
    };
  }

  const total = samples.reduce((sum, sample) => sum + sample, 0);
  return {
    count: samples.length,
    last: samples[samples.length - 1] ?? null,
    average: Math.round(total / samples.length),
    p50: percentile(samples, 50),
    p95: percentile(samples, 95),
  };
}
