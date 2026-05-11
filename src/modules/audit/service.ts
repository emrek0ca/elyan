import type { FastifyInstance } from "fastify";
import { auditLogs } from "../../db/schema.js";
import type { AuditActorType, AuditStatus } from "../../contracts/domain.js";

export async function createAuditLog(
  app: FastifyInstance,
  input: {
    userId?: string | null;
    actorType: AuditActorType;
    actorId?: string | null;
    action: string;
    resourceType: string;
    resourceId?: string | null;
    status: AuditStatus;
    ipAddress?: string;
    userAgent?: string;
    payload?: Record<string, unknown>;
  },
): Promise<void> {
  await app.db.insert(auditLogs).values({
    userId: input.userId ?? null,
    actorType: input.actorType,
    actorId: input.actorId ?? null,
    action: input.action,
    resourceType: input.resourceType,
    resourceId: input.resourceId ?? null,
    status: input.status,
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    payload: input.payload ?? {},
  });
}
