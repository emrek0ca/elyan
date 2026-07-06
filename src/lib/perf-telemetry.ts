import { monitorEventLoopDelay, type IntervalHistogram } from "node:perf_hooks";

/**
 * Sıfır-bağımlılık performans telemetrisi.
 *
 * İki sinyal:
 * 1. Event loop lag — monitorEventLoopDelay (V8 native histogram, ~sıfır
 *    maliyet). Milyon kullanıcıda "donma/kasma"nın tek gerçek göstergesi:
 *    p95 lag yükseliyorsa bir şey event loop'u blokluyor demektir.
 * 2. Stage süreleri — kritik aşamalar (understanding, memory_search,
 *    inference, tool_loop...) için ring-buffer p50/p95/p99. Tahmin değil
 *    ölçümle optimizasyon: hangi aşama yavaşsa o native'e/işçiye taşınır.
 *
 * Kayıt maliyeti: sayı yazma + index artırma (nanosaniye). Yüzdelik hesabı
 * yalnızca snapshot alınırken yapılır.
 */

const RING_SIZE = 512;

type StageRing = {
  values: Float64Array;
  index: number;
  count: number;
};

const stages = new Map<string, StageRing>();
let loopMonitor: IntervalHistogram | null = null;

export function startPerfTelemetry(): void {
  if (loopMonitor) return;
  loopMonitor = monitorEventLoopDelay({ resolution: 20 });
  loopMonitor.enable();
}

export function stopPerfTelemetry(): void {
  loopMonitor?.disable();
  loopMonitor = null;
}

export function recordStageDuration(stage: string, durationMs: number): void {
  if (!Number.isFinite(durationMs) || durationMs < 0) return;
  let ring = stages.get(stage);
  if (!ring) {
    if (stages.size >= 64) return; // sınırsız kardinalite yok
    ring = { values: new Float64Array(RING_SIZE), index: 0, count: 0 };
    stages.set(stage, ring);
  }
  ring.values[ring.index] = durationMs;
  ring.index = (ring.index + 1) % RING_SIZE;
  if (ring.count < RING_SIZE) ring.count += 1;
}

/** Aşama ölçümü için yardımcı: const done = startStage("x"); ...; done(); */
export function startStage(stage: string): () => void {
  const startedAt = performance.now();
  return () => recordStageDuration(stage, performance.now() - startedAt);
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  const index = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1);
  return Number(sorted[Math.max(0, index)].toFixed(2));
}

export type PerfSnapshot = {
  eventLoop: {
    p50Ms: number;
    p95Ms: number;
    p99Ms: number;
    maxMs: number;
  } | null;
  stages: Record<
    string,
    { count: number; p50Ms: number; p95Ms: number; p99Ms: number }
  >;
};

export function getPerfSnapshot(options: { resetLoop?: boolean } = {}): PerfSnapshot {
  const eventLoop = loopMonitor
    ? {
        p50Ms: Number((loopMonitor.percentile(50) / 1e6).toFixed(2)),
        p95Ms: Number((loopMonitor.percentile(95) / 1e6).toFixed(2)),
        p99Ms: Number((loopMonitor.percentile(99) / 1e6).toFixed(2)),
        maxMs: Number((loopMonitor.max / 1e6).toFixed(2)),
      }
    : null;
  if (options.resetLoop) {
    loopMonitor?.reset();
  }
  const stageSnapshot: PerfSnapshot["stages"] = {};
  for (const [name, ring] of stages) {
    const sorted = Array.from(ring.values.subarray(0, ring.count)).sort((a, b) => a - b);
    stageSnapshot[name] = {
      count: ring.count,
      p50Ms: percentile(sorted, 50),
      p95Ms: percentile(sorted, 95),
      p99Ms: percentile(sorted, 99),
    };
  }
  return { eventLoop, stages: stageSnapshot };
}

/** Test izolasyonu. */
export function resetPerfTelemetry(): void {
  stages.clear();
  loopMonitor?.reset();
}
