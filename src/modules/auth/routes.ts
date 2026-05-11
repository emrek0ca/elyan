import type { FastifyPluginAsync } from "fastify";
import { getRequestContext } from "../../lib/http.js";
import { getUserAuth } from "../../lib/request-auth.js";
import { loginBodySchema, refreshBodySchema, registerBodySchema } from "./schemas.js";
import { getCurrentUserProfile, loginUser, refreshUserSession, registerUser, revokeUserSession } from "./service.js";

export const authRoutes: FastifyPluginAsync = async (app) => {
  app.post("/register", async (request) => {
    const body = registerBodySchema.parse(request.body);
    return registerUser(app, body, getRequestContext(request));
  });

  app.post("/login", async (request) => {
    const body = loginBodySchema.parse(request.body);
    return loginUser(app, body, getRequestContext(request));
  });

  app.post("/refresh", async (request) => {
    const body = refreshBodySchema.parse(request.body);
    return refreshUserSession(app, body.refreshToken, getRequestContext(request));
  });

  app.post("/logout", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    await revokeUserSession(app, auth.sessionId);

    return {
      ok: true,
    };
  });

  app.get("/me", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    return getCurrentUserProfile(app, auth.sub);
  });
};
