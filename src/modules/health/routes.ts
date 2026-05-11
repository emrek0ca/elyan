import type { FastifyPluginAsync } from "fastify";
import { getReadiness } from "./service.js";

export const healthRoutes: FastifyPluginAsync = async (app) => {
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
    const readiness = await getReadiness(app);
    const payload = {
      status: readiness.ok ? "ok" : "degraded",
      uptimeSeconds: process.uptime(),
      ...readiness,
      timestamp: new Date().toISOString(),
    };

    if (!readiness.ok) {
      return reply.status(503).send(payload);
    }

    return payload;
  });
};
