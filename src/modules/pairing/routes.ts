import type { FastifyPluginAsync } from "fastify";
import { badRequest } from "../../lib/errors.js";
import { getHeaderString } from "../../lib/http.js";
import { getUserAuth } from "../../lib/request-auth.js";
import { claimPairSessionBodySchema, createPairSessionBodySchema, pairSessionParamsSchema } from "./schemas.js";
import { claimPairSession, createPairSession, getPairSessionStatus } from "./service.js";

export const pairingRoutes: FastifyPluginAsync = async (app) => {
  app.post("/sessions", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const body = createPairSessionBodySchema.parse(request.body);
    const auth = getUserAuth(request);
    return createPairSession(app, {
      userId: auth.sub,
      ...body,
    });
  });

  app.get("/sessions/:sessionId", async (request) => {
    const params = pairSessionParamsSchema.parse(request.params);
    const pairingToken = getHeaderString(request.headers["x-pairing-token"]);

    if (!pairingToken) {
      throw badRequest("x-pairing-token header is required");
    }

    return getPairSessionStatus(app, params.sessionId, pairingToken);
  });

  app.post("/sessions/:sessionId/claim", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = pairSessionParamsSchema.parse(request.params);
    const body = claimPairSessionBodySchema.parse(request.body);
    const auth = getUserAuth(request);

    return claimPairSession(app, {
      sessionId: params.sessionId,
      userId: auth.sub,
      pairingCode: body.pairingCode,
      mobileDevice: body.mobileDevice,
    });
  });
};
