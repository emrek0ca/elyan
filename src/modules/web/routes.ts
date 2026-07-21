import { createHash, randomUUID } from "node:crypto";
import type { FastifyInstance, FastifyPluginAsync } from "fastify";
import { getUserAuth } from "../../lib/request-auth.js";
import { sendConditionalJson } from "../../lib/http.js";
import { getWebBootstrap } from "./service.js";
import { warmupSharedBrainForUser } from "../brain/inference.js";

export const WEB_WARMUP_DEDUPE_MS = 45_000;
const WEB_WARMUP_LOCK_PREFIX = "web:warmup";

type WebRouteOptions = {
  getBootstrap?: (app: FastifyInstance, userId: string) => Promise<unknown>;
  warmup?: (app: FastifyInstance, userId: string) => Promise<void>;
};

function warmupLockKey(userId: string): string {
  const subjectHash = createHash("sha256").update(userId).digest("hex");
  return `${WEB_WARMUP_LOCK_PREFIX}:${subjectHash}`;
}

export async function claimWebWarmup(
  app: Parameters<typeof warmupSharedBrainForUser>[0],
  userId: string,
): Promise<boolean> {
  const store = app.services?.reliability?.store;
  if (!store) {
    return true;
  }

  try {
    return await store.acquireLock(
      warmupLockKey(userId),
      randomUUID(),
      WEB_WARMUP_DEDUPE_MS,
    );
  } catch {
    app.log.debug(
      { errorClass: "reliability_store_unavailable" },
      "web warmup dedupe unavailable; continuing without dedupe",
    );
    return true;
  }
}

export const webRoutes: FastifyPluginAsync<WebRouteOptions> = async (
  app,
  options,
) => {
  const loadBootstrap = options.getBootstrap ?? getWebBootstrap;
  const runWarmup = options.warmup ?? warmupSharedBrainForUser;

  app.get("/bootstrap", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const payload = await loadBootstrap(app, auth.sub);
    return sendConditionalJson(request, reply, payload);
  });

  app.post("/warmup", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) {
      return;
    }
    const auth = getUserAuth(request);
    const shouldRun = await claimWebWarmup(app, auth.sub);
    if (shouldRun) {
      void Promise.resolve()
        .then(() => runWarmup(app, auth.sub))
        .catch(() => {
          app.log.debug(
            { errorClass: "warmup_failed" },
            "web warmup ping failed (non-fatal)",
          );
        });
    }
    return reply.code(202).send({ queued: shouldRun });
  });
};
