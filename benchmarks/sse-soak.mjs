#!/usr/bin/env node
/**
 * SSE soak/smoke testi — /v1/realtime/stream yayınına N eşzamanlı sahte
 * client bağlar; time-to-first-event (ready), heartbeat sayısı ve bağlantı
 * hatalarını ölçer, p50/p95/p99 raporlar ve client tarafı bellek eğrisini
 * örnekler.
 *
 * Kullanım:
 *   ELYAN_BASE_URL=http://127.0.0.1:4000 \
 *   ELYAN_TOKENS=token1,token2,...   # 1..N access token (round-robin)
 *   CLIENTS=500 DURATION_SECONDS=60 RAMP_MS=10 \
 *   node benchmarks/sse-soak.mjs
 *
 * Notlar:
 * - Sunucu tarafında SSE_MAX_STREAMS_PER_USER (varsayılan 4) uygulanır;
 *   500 client için en az ceil(500/4)=125 farklı kullanıcı token'ı gerekir.
 *   Daha az token verilirse script bunu raporlar (429 too_many_realtime_streams).
 * - Sunucu bellek eğrisi için sunucu host'unda `pm2 monit` veya
 *   `watch -n1 'ps -o rss= -p <pid>'` ile eş zamanlı izleyin; bu script
 *   client süreci belleğini örnekler (sızıntı burada da görünür çünkü açık
 *   soket başına buffer tutulur).
 * - Deploy edilmiş ortama karşı koşmayın; yerel/staging hedefleyin.
 */

const BASE_URL = process.env.ELYAN_BASE_URL ?? "http://127.0.0.1:4000";
const TOKENS = String(process.env.ELYAN_TOKENS ?? "")
  .split(",")
  .map((token) => token.trim())
  .filter(Boolean);
const CLIENTS = Number(process.env.CLIENTS ?? 500);
const DURATION_SECONDS = Number(process.env.DURATION_SECONDS ?? 60);
const RAMP_MS = Number(process.env.RAMP_MS ?? 10);

if (TOKENS.length === 0) {
  console.error("ELYAN_TOKENS gerekli (virgülle ayrılmış en az 1 access token).");
  process.exit(1);
}

const stats = {
  connected: 0,
  ready: 0,
  heartbeats: 0,
  events: 0,
  errors: [],
  rejected429: 0,
  closedEarly: 0,
  firstEventMs: [],
};

const memorySamples = [];
const controllers = [];

function percentile(sorted, p) {
  if (sorted.length === 0) return null;
  const index = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1);
  return sorted[Math.max(0, index)];
}

async function runClient(clientIndex) {
  const token = TOKENS[clientIndex % TOKENS.length];
  const controller = new AbortController();
  controllers.push(controller);
  const startedAt = Date.now();
  let sawFirstEvent = false;

  try {
    const response = await fetch(`${BASE_URL}/v1/realtime/stream`, {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "text/event-stream",
      },
      signal: controller.signal,
    });

    if (response.status === 429) {
      stats.rejected429 += 1;
      return;
    }
    if (!response.ok || !response.body) {
      stats.errors.push(`http_${response.status}`);
      return;
    }

    stats.connected += 1;
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        stats.closedEarly += 1;
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = boundary + 2 <= buffer.length ? buffer.slice(boundary + 2) : "";
        if (!frame.trim()) continue;
        stats.events += 1;
        if (!sawFirstEvent) {
          sawFirstEvent = true;
          stats.ready += 1;
          stats.firstEventMs.push(Date.now() - startedAt);
        }
        if (frame.includes("event: heartbeat")) {
          stats.heartbeats += 1;
        }
      }
      // Frame sınırına gelmeyen kuyruk büyümesin
      if (buffer.length > 256 * 1024) {
        buffer = buffer.slice(-64 * 1024);
      }
    }
  } catch (error) {
    if (error?.name !== "AbortError") {
      stats.errors.push(String(error?.message ?? error).slice(0, 80));
    }
  }
}

async function main() {
  console.log(
    `SSE soak: ${CLIENTS} client → ${BASE_URL} (${DURATION_SECONDS}s, ramp ${RAMP_MS}ms, ${TOKENS.length} token)`,
  );

  const memoryTimer = setInterval(() => {
    const usage = process.memoryUsage();
    memorySamples.push({
      atSeconds: memorySamples.length,
      rssMb: Math.round(usage.rss / 1024 / 1024),
      heapMb: Math.round(usage.heapUsed / 1024 / 1024),
      connected: stats.connected,
      events: stats.events,
    });
  }, 1_000);

  const clients = [];
  for (let index = 0; index < CLIENTS; index += 1) {
    clients.push(runClient(index));
    if (RAMP_MS > 0) {
      await new Promise((resolve) => setTimeout(resolve, RAMP_MS));
    }
  }

  await new Promise((resolve) => setTimeout(resolve, DURATION_SECONDS * 1_000));
  for (const controller of controllers) {
    controller.abort();
  }
  clearInterval(memoryTimer);
  await Promise.allSettled(clients);

  const sortedFirstEvent = [...stats.firstEventMs].sort((a, b) => a - b);
  const errorCounts = stats.errors.reduce((acc, key) => {
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});

  const report = {
    target: BASE_URL,
    clients: CLIENTS,
    durationSeconds: DURATION_SECONDS,
    connected: stats.connected,
    receivedFirstEvent: stats.ready,
    rejected429: stats.rejected429,
    closedEarly: stats.closedEarly,
    totalEvents: stats.events,
    heartbeats: stats.heartbeats,
    firstEventLatencyMs: {
      p50: percentile(sortedFirstEvent, 50),
      p95: percentile(sortedFirstEvent, 95),
      p99: percentile(sortedFirstEvent, 99),
      max: sortedFirstEvent[sortedFirstEvent.length - 1] ?? null,
    },
    errors: errorCounts,
    clientMemoryCurve: memorySamples.filter(
      (_, index) => index % 5 === 0 || index === memorySamples.length - 1,
    ),
  };

  console.log(JSON.stringify(report, null, 2));

  const failed = stats.connected === 0 || stats.ready === 0;
  process.exit(failed ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
