import type { FastifyPluginAsync, FastifyReply } from "fastify";
import { getReadiness } from "./service.js";

export const healthRoutes: FastifyPluginAsync = async (app) => {
  const shapePublicHealthPayload = (readiness: Awaited<ReturnType<typeof getReadiness>>) => ({
    ok: readiness.ok,
    status: readiness.ok ? "ok" : "degraded",
    timestamp: new Date().toISOString(),
    mobile: {
      statusSummary: readiness.mobile.statusSummary,
      safeForExternalClients: readiness.mobile.safeForExternalClients,
    },
    realtime: {
      sseEnabled: readiness.realtime.sseEnabled,
      websocketEnabled: readiness.realtime.websocketEnabled,
      heartbeatSeconds: readiness.realtime.heartbeatSeconds,
    },
    coreSurfaces: readiness.coreSurfaces,
    network: {
      warning: readiness.network.warning,
      externalClientsCanReachAdvertisedBaseUrl:
        readiness.network.externalClientsCanReachAdvertisedBaseUrl,
      advertisedBaseUrl: readiness.network.advertisedBaseUrl,
    },
  });

  const sendReadiness = async (reply: FastifyReply) => {
    const readiness = await getReadiness(app);
    const payload = shapePublicHealthPayload(readiness);

    if (!readiness.ok) {
      reply.header("retry-after", "15");
      return reply.status(503).send(payload);
    }

    return reply.send(payload);
  };

  app.get("/livez", async () => ({
    status: "ok",
    service: "elyan-backend",
    timestamp: new Date().toISOString(),
  }));

  app.get("/readyz", async (request, reply) => {
    const readiness = await getReadiness(app);

    if (!readiness.ok) {
      return reply.status(503).send({
        status: "degraded",
        ...readiness,
      });
    }

    return {
      status: "ok",
      ...readiness,
    };
  });

  app.get("/healthz", async (request, reply) => {
    return sendReadiness(reply);
  });

  app.get("/control-plane/health", async (request, reply) => {
    return sendReadiness(reply);
  });
};
