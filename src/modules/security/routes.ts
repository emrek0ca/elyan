import { desc, eq } from "drizzle-orm";
import type { FastifyPluginAsync } from "fastify";
import { auditLogs } from "../../db/schema.js";
import { getUserAuth } from "../../lib/request-auth.js";
import { auditLogQuerySchema } from "./schemas.js";

export const securityRoutes: FastifyPluginAsync = async (app) => {
  app.get("/audit-logs", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const query = auditLogQuerySchema.parse(request.query);

    return {
      auditLogs: await app.db
        .select()
        .from(auditLogs)
        .where(eq(auditLogs.userId, auth.sub))
        .orderBy(desc(auditLogs.createdAt))
        .limit(query.limit),
    };
  });
};
