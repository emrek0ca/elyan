import { and, asc, eq, gt, lt, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { realtimeEvents } from "../../db/schema.js";
import type { PersistedDomainEvent } from "./event-bus.js";

export type RealtimeStreamScope = {
  userId?: string;
  deviceId?: string;
  taskId?: string;
};

function hasScopeConditions(scope: RealtimeStreamScope): boolean {
  return Boolean(scope.userId || scope.deviceId || scope.taskId);
}

export function parseRealtimeEventCursor(value: unknown): number | null {
  if (typeof value === "number" && Number.isInteger(value) && value > 0) {
    return value;
  }

  if (typeof value !== "string") {
    return null;
  }

  const normalized = value.trim();
  if (!normalized) {
    return null;
  }

  const parsed = Number(normalized);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    return null;
  }

  return parsed;
}

export async function listRealtimeEventsForStream(
  app: FastifyInstance,
  input: {
    scope: RealtimeStreamScope;
    afterEventId?: number;
    limit?: number;
  },
): Promise<PersistedDomainEvent[]> {
  if (!hasScopeConditions(input.scope)) {
    return [];
  }

  const conditions = [];
  if (input.scope.userId) {
    conditions.push(eq(realtimeEvents.userId, input.scope.userId));
  }
  if (input.scope.deviceId) {
    conditions.push(eq(realtimeEvents.deviceId, input.scope.deviceId));
  }
  if (input.scope.taskId) {
    conditions.push(eq(realtimeEvents.taskId, input.scope.taskId));
  }
  if (typeof input.afterEventId === "number" && Number.isFinite(input.afterEventId) && input.afterEventId > 0) {
    conditions.push(gt(realtimeEvents.id, Math.floor(input.afterEventId)));
  }

  const rows = await app.db
    .select({
      id: realtimeEvents.id,
      topic: realtimeEvents.topic,
      userId: realtimeEvents.userId,
      deviceId: realtimeEvents.deviceId,
      taskId: realtimeEvents.taskId,
      payload: realtimeEvents.payload,
      payloadBlobId: realtimeEvents.payloadBlobId,
      createdAt: realtimeEvents.createdAt,
    })
    .from(realtimeEvents)
    .where(and(...conditions))
    .orderBy(asc(realtimeEvents.id))
    .limit(input.limit ?? 500);

  return Promise.all(
    rows.map(async (row) => ({
      id: row.id,
      topic: row.topic,
      userId: row.userId ?? undefined,
      deviceId: row.deviceId ?? undefined,
      taskId: row.taskId ?? undefined,
      payload:
        row.payloadBlobId && app.services?.blobs
          ? row.userId
            ? ((await app.services.blobs?.hydrateJsonForOwner({
                blobId: row.payloadBlobId,
                userId: row.userId,
                ownerType: "realtime_event",
                ownerId: String(row.id),
              })) ?? row.payload)
            : ((await app.services.blobs?.hydrateJson(row.payloadBlobId)) ?? row.payload)
          : row.payload,
      createdAt: row.createdAt.toISOString(),
    })),
  );
}

export async function getRealtimeReplayAvailability(
  app: FastifyInstance,
  input: {
    scope: RealtimeStreamScope;
  },
): Promise<{
    earliestAvailableEventId: number | null;
    latestAvailableEventId: number | null;
  }> {
  if (!hasScopeConditions(input.scope)) {
    return {
      earliestAvailableEventId: null,
      latestAvailableEventId: null,
    };
  }

  const conditions = [];
  if (input.scope.userId) {
    conditions.push(eq(realtimeEvents.userId, input.scope.userId));
  }
  if (input.scope.deviceId) {
    conditions.push(eq(realtimeEvents.deviceId, input.scope.deviceId));
  }
  if (input.scope.taskId) {
    conditions.push(eq(realtimeEvents.taskId, input.scope.taskId));
  }

  const rows = await app.db
    .select({
      earliestAvailableEventId: sql<number | null>`min(${realtimeEvents.id})`,
      latestAvailableEventId: sql<number | null>`max(${realtimeEvents.id})`,
    })
    .from(realtimeEvents)
    .where(and(...conditions));

  return {
    earliestAvailableEventId:
      rows[0]?.earliestAvailableEventId == null
        ? null
        : Number(rows[0].earliestAvailableEventId),
    latestAvailableEventId:
      rows[0]?.latestAvailableEventId == null
        ? null
        : Number(rows[0].latestAvailableEventId),
  };
}

export async function pruneRealtimeEvents(
  app: FastifyInstance,
  input: {
    retentionHours: number;
    now?: Date;
  },
): Promise<number> {
  const retentionHours = Math.max(1, Math.floor(input.retentionHours));
  const now = input.now ?? new Date();
  const cutoff = new Date(now.getTime() - retentionHours * 60 * 60 * 1000);
  const rows = await app.db
    .delete(realtimeEvents)
    .where(lt(realtimeEvents.createdAt, cutoff))
    .returning({
      id: realtimeEvents.id,
    });
  return rows.length;
}

export function startRealtimeEventRetentionPruner(app: FastifyInstance): () => void {
  const prune = async () => {
    try {
      const deleted = await pruneRealtimeEvents(app, {
        retentionHours: app.config.REALTIME_EVENT_RETENTION_HOURS,
      });
      if (deleted > 0) {
        app.log.info({ deleted }, "pruned expired realtime events");
      }
    } catch (error) {
      app.log.warn({ error }, "failed to prune expired realtime events");
    }
  };

  void prune();
  const interval = setInterval(prune, 60 * 60 * 1000);
  interval.unref?.();
  return () => clearInterval(interval);
}
