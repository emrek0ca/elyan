import type { FastifyPluginAsync } from "fastify";
import { AppError } from "../../lib/errors.js";
import { getRequestContext, sendConditionalJson } from "../../lib/http.js";
import { assertRequestBudget } from "../../lib/reliability/request-budget.js";
import { getUserAuth } from "../../lib/request-auth.js";
import {
  updateApprovalModeBodySchema,
  uploadWorldSignalsBodySchema,
} from "./schemas.js";
import { getMobileBootstrap, ingestWorldSignals } from "./service.js";
import { warmupSharedBrainForUser } from "../brain/inference.js";
import {
  getUserApprovalMode,
  shapeUserApprovalMode,
  updateUserApprovalMode,
} from "../approval-policy/service.js";

// Per-user warmup dedupe. A user that opens the app, sees the splash, and
// starts typing does that within a few seconds — we don't want every screen
// refresh to fire a fresh warmup and hammer Groq. 45 s covers the "auth
// restore → compose first message" window without keeping the model
// artificially hot.
const RECENT_WARMUPS = new Map<string, number>();
const WARMUP_DEDUPE_MS = 45_000;

function markWarmup(userId: string): boolean {
  const now = Date.now();
  const previous = RECENT_WARMUPS.get(userId);
  if (previous && now - previous < WARMUP_DEDUPE_MS) {
    return false;
  }
  RECENT_WARMUPS.set(userId, now);
  // Best-effort GC: keep the map small even for busy servers.
  if (RECENT_WARMUPS.size > 2_000) {
    for (const [key, when] of RECENT_WARMUPS) {
      if (now - when > WARMUP_DEDUPE_MS) RECENT_WARMUPS.delete(key);
    }
  }
  return true;
}

export const mobileRoutes: FastifyPluginAsync = async (app) => {
  app.get("/bootstrap", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const payload = await getMobileBootstrap(app, auth.sub);
    return sendConditionalJson(request, reply, payload);
  });

  app.get("/approval-mode", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;

    const auth = getUserAuth(request);
    const mode = await getUserApprovalMode(app, auth.sub);
    return shapeUserApprovalMode(mode);
  });

  app.patch("/approval-mode", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;

    const auth = getUserAuth(request);
    const body = updateApprovalModeBodySchema.parse(request.body);
    const context = getRequestContext(request);
    const mode = await updateUserApprovalMode(app, {
      userId: auth.sub,
      mode: body.mode,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
      requestId: context.requestId,
    });
    return shapeUserApprovalMode(mode);
  });

  // Nudge the shared brain so the user's first real turn doesn't pay the
  // cold-start on Groq. The mobile client fires this right after auth
  // restores, in parallel with `/bootstrap`, so by the time the user taps
  // Send the model is warm.
  //
  // Fire-and-forget: we resolve 202 immediately and run the tiny generation
  // detached. No quota, no logging, no memory writes.
  app.post("/warmup", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) {
      return;
    }
    const auth = getUserAuth(request);
    const shouldRun = markWarmup(auth.sub);
    if (shouldRun) {
      // Detached: don't await; the response returns while Groq boots.
      Promise.resolve()
        .then(() => warmupSharedBrainForUser(app, auth.sub))
        .catch((error: unknown) => {
          app.log.debug(
            { error, userId: auth.sub },
            "mobile warmup ping failed (non-fatal)",
          );
        });
    }
    reply.code(202);
    return { queued: shouldRun };
  });

  app.post("/world-signals", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    await assertRequestBudget(app, {
      scope: "mobile_world_signals",
      identity: auth.sub,
      max: 30,
      windowMs: app.config.REQUEST_BUDGET_WINDOW_MS,
    });

    const body = uploadWorldSignalsBodySchema.parse(request.body);
    if (body.userId && body.userId !== auth.sub) {
      throw new AppError(
        403,
        "user_mismatch",
        "World signal user scope does not match the authenticated user.",
      );
    }

    return ingestWorldSignals(app, {
      userId: auth.sub,
      externalDeviceId: body.deviceId,
      body,
    });
  });
};
