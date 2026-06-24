import type { FastifyPluginAsync } from "fastify";
import { AppError } from "../../lib/errors.js";
import { sendConditionalJson } from "../../lib/http.js";
import { assertRequestBudget } from "../../lib/reliability/request-budget.js";
import { getUserAuth } from "../../lib/request-auth.js";
import { uploadWorldSignalsBodySchema } from "./schemas.js";
import { getMobileBootstrap, ingestWorldSignals } from "./service.js";

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
