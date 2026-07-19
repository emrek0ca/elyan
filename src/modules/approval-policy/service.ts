import { eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { users } from "../../db/schema.js";
import { unauthorized } from "../../lib/errors.js";
import { createAuditLog } from "../audit/service.js";
import {
  DEFAULT_USER_APPROVAL_MODE,
  normalizeUserApprovalMode,
  type UserApprovalMode,
} from "./policy.js";

export async function getUserApprovalMode(
  app: FastifyInstance,
  userId: string,
): Promise<UserApprovalMode> {
  try {
    const rows = await app.db
      .select({ approvalMode: users.approvalMode })
      .from(users)
      .where(eq(users.id, userId))
      .limit(1);
    return normalizeUserApprovalMode(rows[0]?.approvalMode);
  } catch (error) {
    app.log?.warn?.(
      {
        userId,
        errorCode: error instanceof Error ? error.name : "approval_mode_read_failed",
      },
      "user approval mode could not be read; safe default applied",
    );
    return DEFAULT_USER_APPROVAL_MODE;
  }
}

export async function updateUserApprovalMode(
  app: FastifyInstance,
  input: {
    userId: string;
    mode: UserApprovalMode;
    ipAddress?: string;
    userAgent?: string;
    requestId?: string;
  },
) {
  const previousMode = await getUserApprovalMode(app, input.userId);
  return app.db.transaction(async (tx) => {
    const rows = await tx
      .update(users)
      .set({ approvalMode: input.mode, updatedAt: new Date() })
      .where(eq(users.id, input.userId))
      .returning({ approvalMode: users.approvalMode });

    if (!rows[0]) {
      throw unauthorized("Bilgileri kontrol et.");
    }

    const mode = normalizeUserApprovalMode(rows[0].approvalMode);
    await createAuditLog(app, {
      userId: input.userId,
      actorType: "user",
      actorId: input.userId,
      action: "approval_mode.update",
      resourceType: "user",
      resourceId: input.userId,
      status: "success",
      ipAddress: input.ipAddress,
      userAgent: input.userAgent,
      requestId: input.requestId,
      payload: { previousMode, mode },
    }, tx);
    return mode;
  });
}

export function shapeUserApprovalMode(mode: UserApprovalMode) {
  return {
    mode,
    defaultMode: DEFAULT_USER_APPROVAL_MODE,
    trustedIdempotentWritesEnabled:
      mode === "trusted_idempotent_writes",
    immutableApprovalClasses: [
      "side_effect",
      "non_idempotent",
    ] as const,
  };
}
