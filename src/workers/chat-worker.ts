import { buildApp } from "../app/build-app.js";
import { loadEnv } from "../config/env.js";
import { ensureChatGenerationWorkers } from "../modules/brain/chat-generation-queue.js";
import { warmSharedBrainRuntime } from "../modules/brain/runtime.js";

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
