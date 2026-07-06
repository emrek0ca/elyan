import { buildApp } from "../app/build-app.js";
import { loadEnv } from "../config/env.js";
import { runDocumentWorker } from "../modules/brain/worker.js";

try {
  process.loadEnvFile();
} catch (error) {
  const code =
    typeof error === "object" && error && "code" in error
      ? String((error as { code?: string }).code)
      : "";
  if (code !== "ENOENT") {
    throw error;
  }
}

process.env.ELYAN_MEMORY_WORKER_DISABLED = "true";

const env = loadEnv();
const app = await buildApp(env);
let shuttingDown = false;

async function shutdown(signal: string) {
  if (shuttingDown) return;
  shuttingDown = true;
  app.log.info({ signal }, "document worker shutting down");
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

try {
  await runDocumentWorker(app);
} catch (error) {
  app.log.error(error);
  await app.close();
  process.exit(1);
}
