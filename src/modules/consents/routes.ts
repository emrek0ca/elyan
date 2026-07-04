import type { FastifyPluginAsync } from "fastify";
import { getUserAuth } from "../../lib/request-auth.js";
import {
  CONSENT_VERSIONS,
  getConsentStatus,
  grantConsentBodySchema,
  revokeConsentBodySchema,
  setUserConsent,
} from "./service.js";

export const consentRoutes: FastifyPluginAsync = async (app) => {
  app.get("/status", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;
    const auth = getUserAuth(request);
    return getConsentStatus(app, auth.sub);
  });

  app.post("/grant", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;
    const auth = getUserAuth(request);
    const body = grantConsentBodySchema.parse(request.body);
    return setUserConsent(app, {
      userId: auth.sub,
      consentType: body.consentType,
      consentVersion: body.consentVersion,
      granted: body.granted,
      source: "mobile",
    });
  });

  app.post("/revoke", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;
    const auth = getUserAuth(request);
    const body = revokeConsentBodySchema.parse(request.body);
    return setUserConsent(app, {
      userId: auth.sub,
      consentType: body.consentType,
      consentVersion: CONSENT_VERSIONS[body.consentType],
      granted: false,
      source: "mobile",
    });
  });
};
