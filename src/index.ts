import { buildApp } from "./app/build-app.js";
import { getBaseUrlReachability, loadEnv } from "./config/env.js";
import { ensureElyanServerBrainBootstrap } from "./modules/brain/bootstrap.js";
import { maybeStartSemanticV2Backfill } from "./modules/brain/retrieval.js";
import { warmSharedBrainRuntime } from "./modules/brain/runtime.js";

try {
  process.loadEnvFile();
} catch (error) {
  const code = typeof error === "object" && error && "code" in error ? String(error.code) : "";

  if (code !== "ENOENT") {
    throw error;
  }
}

const env = loadEnv();
const reachability = getBaseUrlReachability(env);

if (reachability.warning) {
  const message = `[elyan-backend] ${reachability.warning} Set APP_BASE_URL to the host machine LAN IP or a public HTTPS origin. Current value: ${reachability.advertisedBaseUrl}`;

  if (env.NODE_ENV === "production") {
    throw new Error(message);
  }

  console.warn(message);
}

const app = await buildApp(env);

// The API process owns the one bounded semantic warm/backfill job. Keeping it
// out of buildApp prevents every queue worker from loading a duplicate model
// merely because they share the application factory.
maybeStartSemanticV2Backfill(app);

try {
  const bootstrap = await ensureElyanServerBrainBootstrap(app);
  app.log.info(
    {
      sharedBrainDeviceId: bootstrap.sharedBrainDevice.id,
      trainingJobId: bootstrap.trainingJob?.id ?? null,
      seeded: bootstrap.seeded,
    },
    "elyan server brain bootstrap ready",
  );
} catch (error) {
  app.log.warn(
    {
      error,
    },
    "elyan server brain bootstrap failed",
  );
}

try {
  const runtime = await warmSharedBrainRuntime(app);
  app.log.info(
    {
      provider: runtime.provider,
      ready: runtime.ready,
      checkedAt: runtime.checkedAt.toISOString(),
    },
    "elyan server brain runtime warmed",
  );
} catch (error) {
  app.log.warn(
    {
      error,
    },
    "elyan server brain runtime warmup failed",
  );
}

try {
  await app.listen({
    host: env.HOST,
    port: env.PORT,
  });
} catch (error) {
  app.log.error(error);
  process.exit(1);
}
