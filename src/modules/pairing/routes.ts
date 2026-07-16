import type { FastifyPluginAsync } from "fastify";
import { badRequest } from "../../lib/errors.js";
import { getHeaderString } from "../../lib/http.js";
import { getUserAuth } from "../../lib/request-auth.js";
import {
  claimPairSessionBodySchema,
  claimPairSessionByCodeBodySchema,
  createPairSessionBodySchema,
  pairSessionParamsSchema,
} from "./schemas.js";
import { claimPairSession, claimPairSessionByCode, createPairSession, getPairSessionStatus } from "./service.js";

export const pairingRoutes: FastifyPluginAsync = async (app) => {
  app.post("/sessions", async (request, reply) => {
    // Desktop CLI oturum açmadan QR eşleştirme başlatabilir (anonim oturum).
    // Sahiplik claim anında doğrulanır; Authorization varsa yine kabul edilir.
    let userId: string | null = null;
    if (getHeaderString(request.headers.authorization)) {
      await app.authenticateUser(request, reply);

      if (reply.sent) {
        return;
      }

      userId = getUserAuth(request).sub;
    }

    const body = createPairSessionBodySchema.parse(request.body);
    return createPairSession(app, {
      userId,
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

  // Kısa kodla eşleştirme (QR'sız): mobil yalnızca desktop'taki kısa kodu
  // gönderir; session UUID'sine gerek yoktur (kod globally unique).
  app.post("/sessions/claim-by-code", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const body = claimPairSessionByCodeBodySchema.parse(request.body);
    const auth = getUserAuth(request);

    return claimPairSessionByCode(app, {
      userId: auth.sub,
      pairingCode: body.pairingCode,
      mobileDevice: body.mobileDevice,
    });
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
