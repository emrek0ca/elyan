import type { FastifyPluginAsync } from "fastify";
import { getUserAuth } from "../../lib/request-auth.js";
import { getMobileBootstrap } from "./service.js";

export const mobileRoutes: FastifyPluginAsync = async (app) => {
  app.get("/bootstrap", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    return getMobileBootstrap(app, auth.sub);
  });
};
