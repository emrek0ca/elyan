import { buildApp } from "../app/build-app.js";
import { loadEnv } from "../config/env.js";
import { ensureChatGenerationWorkers } from "../modules/brain/chat-generation-queue.js";
import { warmSharedBrainRuntime } from "../modules/brain/runtime.js";
import { primeSemanticComputeWorker } from "../modules/brain/semantic-compute-client.js";

try {
  process.loadEnvFile();
} catch (error) {
  const code =
    typeof error === "object" && error && "code" in error
      ? String((error as { code?: string }).code)
      : "";
  if (code !== "ENOENT") throw error;
}

process.env.ELYAN_MEMORY_WORKER_DISABLED = "true";
process.env.ELYAN_PROACTIVE_ENGINE_ENABLED = "false";

const env = loadEnv();
const app = await buildApp(env);
// The API process warms its own runtime, but this worker has a separate
// process-local cache. Start warmup immediately, while the queue becomes
// available in parallel; a provider probe must never leave accepted chat jobs
// invisible behind a worker that has not published readiness yet.
void warmSharedBrainRuntime(app).catch((error) => {
  app.log.warn({ error }, "chat worker brain runtime warmup unavailable");
});
// e5 modeli imaja gömülü ama ONNX oturumu ilk `embed` isteğinde kuruluyordu:
// o maliyeti ilk KULLANICI turu ödüyor, çağıranın bütçesini aşıyor ve arka
// arkaya 5 timeout semantik katmanı 60 sn cooldown'a sokuyordu. Canlıda saatte
// 15 timeout ölçüldü — semantik kararlar çoğunlukla hash yedeğinde koşuyordu.
// Maliyeti açılışta ödüyoruz; başarısız olursa davranış eskisiyle aynı.
void primeSemanticComputeWorker({
  modelName: app.config.ELYAN_RAG_SEMANTIC_RERANK_MODEL,
  logger: app.log,
})
  .then((warmed) => {
    app.log.info({ warmed }, "semantic compute model warmup finished");
  })
  .catch((error) => {
    app.log.warn({ error }, "semantic compute model warmup unavailable");
  });
await ensureChatGenerationWorkers(app);
app.log.info("chat generation worker ready");

let shuttingDown = false;
async function shutdown(signal: string) {
  if (shuttingDown) return;
  shuttingDown = true;
  app.log.info({ signal }, "chat generation worker shutting down");
  try {
    await app.close();
  } finally {
    process.exit(0);
  }
}

process.once("SIGINT", () => {
  void shutdown("SIGINT");
});
process.once("SIGTERM", () => {
  void shutdown("SIGTERM");
});
