import { buildApp } from "../app/build-app.js";
import { loadEnv } from "../config/env.js";
import { runTrainingWorker } from "../modules/brain/worker.js";

try {
  process.loadEnvFile();
} catch (error) {
  const code = typeof error === "object" && error && "code" in error ? String((error as { code?: string }).code) : "";

  if (code !== "ENOENT") {
    throw error;
  }
}

const env = loadEnv();
const app = await buildApp(env);

if (process.env.NODE_TRAINING_WORKER_ENABLED === "false") {
  app.log.info("node training worker disabled; ml-worker owns training job execution");
  await app.close();
  process.exit(0);
}

let shuttingDown = false;

async function shutdown(signal: string) {
  if (shuttingDown) {
    return;
  }

  shuttingDown = true;
  app.log.info({ signal }, "training worker shutting down");

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
  await runTrainingWorker(app);
} catch (error) {
  app.log.error(error);
  await app.close();
  process.exit(1);
}
