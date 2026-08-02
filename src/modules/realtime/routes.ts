import { randomUUID } from "node:crypto";
import { and, eq, sql } from "drizzle-orm";
import type {
  FastifyInstance,
  FastifyPluginAsync,
  FastifyRequest,
} from "fastify";
import { ZodError } from "zod";
import { z } from "zod";
import type { RawData } from "ws";
import { chatSessions, devices, tasks } from "../../db/schema.js";
import { recordMobileSyncRecoverySignals } from "../../core/understanding/user-understanding-service.js";
import {
  AppError,
  badRequest,
  notFound,
  unauthorized,
} from "../../lib/errors.js";
import { extractBearerToken, getUserAuth } from "../../lib/request-auth.js";
import type { RuntimeAuthTokenPayload } from "../../types/auth.js";
import type { DomainEvent } from "./event-bus.js";
import {
  acknowledgeTaskDispatchLease,
  acknowledgeTaskControl,
  appendTaskArtifacts,
  buildRuntimeTaskDispatchEnvelope,
  issueTaskDispatchLease,
  updateTaskFromRuntime,
} from "../tasks/service.js";
import { runtimeSocketMessageSchema } from "../runtime/schemas.js";
import {
  disconnectRuntime,
  heartbeatRuntime,
  listAssignedRuntimeTasks,
  markRuntimeConnected,
} from "../runtime/service.js";
import {
  getRealtimeReplayAvailability,
  listRealtimeEventsForStream,
  parseRealtimeEventCursor,
} from "./log.js";
import { sanitizePublicTaskEventPayload } from "../tasks/service-helpers.js";

const realtimeStreamQuerySchema = z
  .object({
    taskId: z.string().uuid().optional(),
    deviceId: z.string().uuid().optional(),
    cursor: z.coerce.number().int().positive().optional(),
  })
  .refine((value) => !(value.taskId && value.deviceId), {
    message: "Specify at most one of taskId or deviceId",
    path: ["taskId"],
  });

type RealtimeStreamQuery = z.infer<typeof realtimeStreamQuerySchema>;

export type RealtimeEventEnvelope = DomainEvent & {
  eventId: string | null;
  seq: number | null;
  cursor: string | null;
  aggregateId: string | null;
  type: string;
};

export function shapeRealtimeEventEnvelope(
  event: DomainEvent,
): RealtimeEventEnvelope {
  const seq =
    typeof event.id === "number" && Number.isFinite(event.id) && event.id > 0
      ? Math.floor(event.id)
      : null;
  return {
    ...event,
    payload: sanitizePublicTaskEventPayload(event.payload),
    eventId: seq != null ? String(seq) : null,
    seq,
    cursor: seq != null ? String(seq) : null,
    aggregateId: event.taskId ?? event.deviceId ?? event.userId ?? null,
    type: event.topic,
  };
}

export function shouldDispatchAssignedRuntimeTask(
  task: Awaited<ReturnType<typeof listAssignedRuntimeTasks>>[number],
  connectionId: string,
): boolean {
  if (task.status === "queued" || task.status === "planning") {
    return true;
  }
  if (task.status === "running") {
    return task.runtimeConnectionId !== connectionId;
  }
  return false;
}

const activeRealtimeStreamsByUser = new Map<string, number>();
const SSE_MAX_PENDING_EVENTS = 64;
const SSE_DROPPED_BACKPRESSURE_METRIC_KEY =
  "metrics:sse_dropped_connections_total:reason:backpressure";

export function realtimeStreamChannelForUser(
  userId: string,
  query: RealtimeStreamQuery,
): string {
  return query.taskId
    ? `task:${query.taskId}`
    : query.deviceId
      ? `device:${query.deviceId}`
      : `user:${userId}`;
}

export function activeRealtimeStreamCountForUser(userId: string): number {
  return activeRealtimeStreamsByUser.get(userId) ?? 0;
}

export function acquireRealtimeStreamSlot(
  userId: string,
  maxStreams: number,
): () => void {
  const current = activeRealtimeStreamCountForUser(userId);
  if (current >= maxStreams) {
    throw new AppError(
      429,
      "too_many_realtime_streams",
      "Too many realtime streams are already open.",
    );
  }

  activeRealtimeStreamsByUser.set(userId, current + 1);
  let released = false;
  return () => {
    if (released) {
      return;
    }
    released = true;
    const next = activeRealtimeStreamCountForUser(userId) - 1;
    if (next <= 0) {
      activeRealtimeStreamsByUser.delete(userId);
      return;
    }
    activeRealtimeStreamsByUser.set(userId, next);
  };
}

function parseSseEventCursor(
  request: FastifyRequest,
  queryCursor?: number,
): number | null {
  if (
    typeof queryCursor === "number" &&
    Number.isFinite(queryCursor) &&
    queryCursor > 0
  ) {
    return Math.floor(queryCursor);
  }

  const headerCursor = request.headers["last-event-id"];
  if (typeof headerCursor === "string") {
    return parseRealtimeEventCursor(headerCursor);
  }

  return null;
}

function writeSseEvent(
  raw: {
    write: (chunk: string) => boolean;
  },
  input: {
    event: string;
    data: unknown;
    id?: number;
  },
): boolean {
  const lines: string[] = [];
  if (
    typeof input.id === "number" &&
    Number.isFinite(input.id) &&
    input.id > 0
  ) {
    lines.push(`id: ${input.id}`);
  }
  lines.push(`event: ${input.event}`);
  lines.push(`data: ${JSON.stringify(input.data)}`);
  return raw.write(`${lines.join("\n")}\n\n`);
}

/**
 * Backpressure gate: yavaş client'ın soket yazma buffer'ı sınırsız büyürse
 * her açık stream sunucu belleğini rehin alır. Buffer sınırı aşıldığında
 * bağlantıyı KESMEK doğru politika (drop-oldest değil): SSE zaten
 * Last-Event-ID + replay ile kayıpsız devam edebildiği için client yeniden
 * bağlanınca kaldığı yerden alır; olay atlamak ise sözleşmeyi bozar.
 */
export function shouldDropSlowSseClient(
  raw: { writableLength?: number },
  maxBufferedBytes: number,
): boolean {
  const buffered =
    typeof raw.writableLength === "number" ? raw.writableLength : 0;
  return buffered > Math.max(1, maxBufferedBytes);
}

export type SsePendingWriteState = {
  pendingEvents: number;
  maxPendingEvents: number;
  waitingDrain: boolean;
};

export function createSsePendingWriteState(
  maxPendingEvents = SSE_MAX_PENDING_EVENTS,
): SsePendingWriteState {
  return {
    pendingEvents: 0,
    maxPendingEvents,
    waitingDrain: false,
  };
}

export function shouldDropSsePendingWrite(
  state: SsePendingWriteState,
  writeAccepted: boolean,
): boolean {
  if (writeAccepted) {
    state.pendingEvents = 0;
    return false;
  }
  state.pendingEvents += 1;
  return state.pendingEvents > state.maxPendingEvents;
}

function readSessionIdFromSseData(data: unknown): string | null {
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return null;
  }
  const record = data as Record<string, unknown>;
  const direct = record.sessionId;
  if (typeof direct === "string" && direct.trim()) {
    return direct.trim();
  }
  const payload = record.payload;
  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    const nested = (payload as Record<string, unknown>).sessionId;
    if (typeof nested === "string" && nested.trim()) {
      return nested.trim();
    }
  }
  return null;
}

function recordSseDroppedBackpressure(app: FastifyInstance) {
  void app.services?.reliability?.store
    ?.increment?.(SSE_DROPPED_BACKPRESSURE_METRIC_KEY, 86_400_000)
    .catch(() => 0);
  app.log.warn(
    {
      metric: 'sse_dropped_connections_total{reason="backpressure"}',
      reason: "backpressure",
    },
    "sse dropped connection metric recorded",
  );
}

async function markChatSessionReconnectPending(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId: string | null;
  },
) {
  if (!input.sessionId) {
    return;
  }
  const now = new Date();
  await app.db
    .update(chatSessions)
    .set({
      metadata: sql`coalesce(${chatSessions.metadata}, '{}'::jsonb) || ${JSON.stringify(
        {
          realtimeDeliveryState: "reconnect-pending",
          realtimeReconnectPendingAt: now.toISOString(),
        },
      )}::jsonb`,
      updatedAt: now,
    })
    .where(
      and(
        eq(chatSessions.id, input.sessionId),
        eq(chatSessions.userId, input.userId),
      ),
    )
    .catch(() => undefined);
}

export const realtimeRoutes: FastifyPluginAsync = async (app) => {
  app.get("/stream", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const query = realtimeStreamQuerySchema.parse(request.query ?? {});

    if (query.taskId) {
      const ownedTask = await app.db
        .select({ id: tasks.id })
        .from(tasks)
        .where(and(eq(tasks.id, query.taskId), eq(tasks.userId, auth.sub)))
        .limit(1);

      if (!ownedTask[0]) {
        throw notFound("Task stream not found");
      }
    }

    if (query.deviceId) {
      const ownedDevice = await app.db
        .select({ id: devices.id })
        .from(devices)
        .where(
          and(eq(devices.id, query.deviceId), eq(devices.userId, auth.sub)),
        )
        .limit(1);

      if (!ownedDevice[0]) {
        throw notFound("Device stream not found");
      }
    }

    const channel = realtimeStreamChannelForUser(auth.sub, query);
    const cursor = parseSseEventCursor(request, query.cursor);
    const releaseStreamSlot = acquireRealtimeStreamSlot(
      auth.sub,
      app.config.SSE_MAX_STREAMS_PER_USER,
    );

    reply.hijack();
    reply.raw.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    });
    reply.raw.flushHeaders?.();
    reply.raw.write("retry: 3000\n\n");
    let replayCompleted = false;
    let lastSentEventId = cursor ?? 0;
    let closed = false;
    let heartbeat: NodeJS.Timeout | undefined;
    let unsubscribe: () => void = () => undefined;
    const bufferedEvents: DomainEvent[] = [];
    const pendingWriteState = createSsePendingWriteState();
    let lastChatSessionId: string | null = null;

    const closeStream = () => {
      if (closed) {
        return;
      }
      closed = true;
      if (heartbeat) {
        clearInterval(heartbeat);
      }
      unsubscribe();
      releaseStreamSlot();
      if (!reply.raw.destroyed) {
        reply.raw.end();
      }
    };

    const writeOrClose = (input: {
      event: string;
      data: unknown;
      id?: number;
    }) => {
      if (closed) {
        return false;
      }
      // Yavaş client: yazma buffer'ı sınırı aştıysa bağlantıyı kes; client
      // Last-Event-ID ile yeniden bağlanıp replay'den devam eder.
      if (
        shouldDropSlowSseClient(reply.raw, app.config.SSE_MAX_BUFFERED_BYTES)
      ) {
        recordSseDroppedBackpressure(app);
        void markChatSessionReconnectPending(app, {
          userId: auth.sub,
          sessionId: lastChatSessionId,
        });
        app.log.warn(
          { channel, bufferedBytes: reply.raw.writableLength },
          "sse client too slow; dropping connection (resume via replay)",
        );
        closeStream();
        return false;
      }
      lastChatSessionId =
        readSessionIdFromSseData(input.data) ?? lastChatSessionId;
      const writable = writeSseEvent(reply.raw, input);
      if (!writable && !pendingWriteState.waitingDrain) {
        pendingWriteState.waitingDrain = true;
        reply.raw.once?.("drain", () => {
          pendingWriteState.pendingEvents = 0;
          pendingWriteState.waitingDrain = false;
        });
      }
      if (shouldDropSsePendingWrite(pendingWriteState, writable)) {
        recordSseDroppedBackpressure(app);
        void markChatSessionReconnectPending(app, {
          userId: auth.sub,
          sessionId: lastChatSessionId,
        });
        app.log.warn(
          {
            channel,
            pendingEvents: pendingWriteState.pendingEvents,
          },
          "sse client pending queue exceeded; dropping connection (resume via replay)",
        );
        closeStream();
        return false;
      }
      if (!writable && reply.raw.destroyed) {
        closeStream();
        return false;
      }
      return true;
    };

    request.raw.on("close", closeStream);

    if (
      !writeOrClose({
        event: "ready",
        data: {
          channel,
          cursor,
          replaySupported: true,
          realtimeReady: true,
          resumeCursorTtlSeconds:
            app.config.REALTIME_EVENT_RETENTION_HOURS * 60 * 60,
          sessionHydrationMode: "realtime_then_authoritative_refresh",
          degradedReason: null,
          timestamp: new Date().toISOString(),
        },
      })
    ) {
      return;
    }

    unsubscribe = app.services.eventBus.subscribe(channel, (event) => {
      if (closed) {
        return;
      }
      if (!replayCompleted) {
        lastChatSessionId =
          readSessionIdFromSseData(event.payload) ?? lastChatSessionId;
        if (bufferedEvents.length >= SSE_MAX_PENDING_EVENTS) {
          recordSseDroppedBackpressure(app);
          void markChatSessionReconnectPending(app, {
            userId: auth.sub,
            sessionId: lastChatSessionId,
          });
          app.log.warn(
            {
              channel,
              bufferedEvents: bufferedEvents.length,
            },
            "sse replay buffer exceeded; dropping connection (resume via replay)",
          );
          closeStream();
          return;
        }
        bufferedEvents.push(event);
        return;
      }

      writeOrClose({
        event: event.topic,
        id: typeof event.id === "number" ? event.id : undefined,
        data: shapeRealtimeEventEnvelope(event),
      });
      if (
        typeof event.id === "number" &&
        Number.isFinite(event.id) &&
        event.id > lastSentEventId
      ) {
        lastSentEventId = event.id;
      }
    });

    try {
      const replayAvailability = await getRealtimeReplayAvailability(app, {
        scope: {
          userId: query.taskId || query.deviceId ? undefined : auth.sub,
          deviceId: query.deviceId,
          taskId: query.taskId,
        },
      });
      if (
        cursor != null &&
        replayAvailability.earliestAvailableEventId != null &&
        cursor < replayAvailability.earliestAvailableEventId - 1
      ) {
        void recordMobileSyncRecoverySignals(app, {
          userId: auth.sub,
          cursorProvided: true,
          outcome: "resync_required",
        });
        writeOrClose({
          event: "resync_required",
          data: {
            reason: "cursor_expired",
            cursor,
            earliestAvailableEventId:
              replayAvailability.earliestAvailableEventId,
            latestAvailableEventId: replayAvailability.latestAvailableEventId,
          },
        });
      }

      const replayEvents = await listRealtimeEventsForStream(app, {
        scope: {
          userId: query.taskId || query.deviceId ? undefined : auth.sub,
          deviceId: query.deviceId,
          taskId: query.taskId,
        },
        afterEventId: cursor ?? undefined,
        limit: app.config.SSE_REPLAY_LIMIT,
      });

      for (const event of replayEvents) {
        if (
          !writeOrClose({
            event: event.topic,
            id: event.id,
            data: shapeRealtimeEventEnvelope(event),
          })
        ) {
          return;
        }
        lastSentEventId = event.id;
      }

      // Connect-race recovery: chat stream event'leri volatile — client bu
      // bağlantı kurulmadan ÖNCE stream'lenmeye başlamış bir cevabın delta /
      // completed'ını kaçırmış olabilir (ilk mesaj senaryosu: uygulama açılır
      // açılmaz yazınca SSE auth+replay penceresinde cevap akar). Event bus
      // kanal başına son snapshot'ları kısa TTL ile tutuyor; burada teslim
      // ediyoruz. delta payload'ı kümülatif otoriter snapshot taşıdığı ve
      // mobil bunu idempotent uyguladığı için duplicate zararsızdır.
      const missedSnapshots =
        app.services.eventBus.recentVolatileSnapshots(channel);
      for (const event of missedSnapshots) {
        if (
          !writeOrClose({
            event: event.topic,
            data: shapeRealtimeEventEnvelope(event),
          })
        ) {
          return;
        }
      }

      if (cursor != null) {
        void recordMobileSyncRecoverySignals(app, {
          userId: auth.sub,
          cursorProvided: true,
          outcome: "recovered",
        });
      }

      // KRİTİK: volatile chat event'lerinin (message.delta / message.completed
      // — publishVolatile ile yayınlanır) `id`'si YOKTUR. Eski drain filtresi
      // `typeof event.id === "number"` bu event'lerin hepsini sessizce
      // düşürüyordu: replay penceresi sırasında stream'lenen bir cevabın tüm
      // delta'ları VE completed'ı kayboluyordu — "ilk mesajda cevap hiç
      // gelmiyor" şikayetinin kök nedeni. Id'li (persisted) event'ler dedup +
      // sıra ile, id'siz (volatile) event'ler geliş sırasıyla geçer.
      while (!closed && bufferedEvents.length > 0) {
        const pending = bufferedEvents.splice(0);
        const persisted = pending
          .filter(
            (event): event is DomainEvent & { id: number } =>
              typeof event.id === "number" && event.id > lastSentEventId,
          )
          .sort((a, b) => a.id - b.id);
        const volatile = pending.filter(
          (event) => typeof event.id !== "number",
        );

        for (const event of persisted) {
          if (
            !writeOrClose({
              event: event.topic,
              id: event.id,
              data: shapeRealtimeEventEnvelope(event),
            })
          ) {
            return;
          }
          lastSentEventId = event.id;
        }
        for (const event of volatile) {
          if (
            !writeOrClose({
              event: event.topic,
              data: shapeRealtimeEventEnvelope(event),
            })
          ) {
            return;
          }
        }
      }

      replayCompleted = true;

      while (!closed && bufferedEvents.length > 0) {
        const pending = bufferedEvents.splice(0);
        const persisted = pending
          .filter(
            (event): event is DomainEvent & { id: number } =>
              typeof event.id === "number" && event.id > lastSentEventId,
          )
          .sort((a, b) => a.id - b.id);
        const volatile = pending.filter(
          (event) => typeof event.id !== "number",
        );

        for (const event of persisted) {
          if (
            !writeOrClose({
              event: event.topic,
              id: event.id,
              data: shapeRealtimeEventEnvelope(event),
            })
          ) {
            return;
          }
          lastSentEventId = event.id;
        }
        for (const event of volatile) {
          if (
            !writeOrClose({
              event: event.topic,
              data: shapeRealtimeEventEnvelope(event),
            })
          ) {
            return;
          }
        }
      }

      heartbeat = setInterval(() => {
        writeOrClose({
          event: "heartbeat",
          data: {
            event: "heartbeat",
            timestamp: new Date().toISOString(),
          },
        });
      }, app.config.SSE_HEARTBEAT_MS);
    } catch (error) {
      app.log.warn(
        {
          error,
          channel,
        },
        "realtime stream replay failed",
      );
      closeStream();
    }
  });

  app.get("/runtime", { websocket: true }, async (socket, request) => {
    let attachedDeviceId: string | null = null;
    try {
      const token = extractBearerToken(request);
      const payload = (await app.jwt.verify(token)) as RuntimeAuthTokenPayload;

      if (payload.kind !== "runtime") {
        throw unauthorized("Runtime token required");
      }

      const socketSessionId = randomUUID();
      app.services.realtimeHub.attachRuntime({
        socket,
        userId: payload.sub,
        deviceId: payload.deviceId,
      });
      attachedDeviceId = payload.deviceId;
      await app.services.realtimeHub
        .registerRuntimePresence(payload.deviceId)
        .catch((error) => {
          app.log.warn(
            { error, deviceId: payload.deviceId },
            "runtime distributed presence could not be registered",
          );
        });
      await markRuntimeConnected(app, payload, socketSessionId);

      const queuedTasks = await listAssignedRuntimeTasks(app, payload);

      for (const task of queuedTasks) {
        if (!shouldDispatchAssignedRuntimeTask(task, payload.connectionId)) {
          continue;
        }

        const leaseResult = await issueTaskDispatchLease(app, {
          taskId: task.id,
          runtimeConnectionId: payload.connectionId,
        });

        if (!leaseResult || !leaseResult.lease) {
          continue;
        }

        socket.send(
          JSON.stringify(
            buildRuntimeTaskDispatchEnvelope(
              leaseResult.task,
              leaseResult.lease,
            ),
          ),
        );
      }

      socket.on("message", async (raw: RawData) => {
        try {
          const parsed = runtimeSocketMessageSchema.parse(
            JSON.parse(raw.toString()),
          );

          if (parsed.type === "heartbeat") {
            await heartbeatRuntime(app, payload, parsed);
            await app.services.realtimeHub
              .touchRuntimePresence(payload.deviceId)
              .catch((error) => {
                app.log.warn(
                  { error, deviceId: payload.deviceId },
                  "runtime distributed presence could not be renewed",
                );
                return false;
              });
            return;
          }

          if (parsed.type === "task.ack") {
            await acknowledgeTaskDispatchLease(app, payload, {
              taskId: parsed.taskId,
              leaseId: parsed.leaseId,
              state: parsed.state,
              acceptedAt: parsed.acceptedAt,
              missingCapabilities: parsed.missingCapabilities,
              blockedReason: parsed.blockedReason,
              consumedContractFields: parsed.consumedContractFields,
            });
            return;
          }

          if (parsed.type === "task.update") {
            await updateTaskFromRuntime(
              app,
              payload,
              parsed.taskId,
              parsed.body,
            );
            return;
          }

          if (parsed.type === "task.artifacts") {
            await appendTaskArtifacts(
              app,
              payload,
              parsed.taskId,
              parsed.artifacts,
            );
            return;
          }

          if (parsed.type === "task.control.ack") {
            await acknowledgeTaskControl(app, payload, {
              taskId: parsed.taskId,
              commandId: parsed.commandId,
              state: parsed.state,
              message: parsed.message,
            });
          }
        } catch (error) {
          if (error instanceof AppError && error.statusCode === 401) {
            socket.close(4401, "Runtime session is stale or replaced");
            return;
          }
          const message =
            error instanceof ZodError
              ? "Invalid runtime socket message"
              : error instanceof Error
                ? error.message
                : "Unknown runtime socket error";

          socket.send(
            JSON.stringify({
              type: "error",
              message,
            }),
          );
        }
      });

      socket.on("close", async () => {
        app.services.realtimeHub.detachRuntime(payload.deviceId, socket);
        if (!app.services.realtimeHub.isRuntimeConnected(payload.deviceId)) {
          await app.services.realtimeHub
            .releaseRuntimePresence(payload.deviceId)
            .catch(() => undefined);
        }

        try {
          await disconnectRuntime(app, payload, { closeSocket: false });
        } catch {
          // The database row may have been removed during account/device
          // teardown. Emit a conservative refresh signal only in that case.
          await app.services.eventBus
            .publishVolatile({
              topic: "device.status_changed",
              userId: payload.sub,
              deviceId: payload.deviceId,
              payload: {
                deviceId: payload.deviceId,
                isOnline: false,
                reason: "ws_closed",
              },
            })
            .catch(() => undefined);
        }
      });
    } catch (error) {
      if (attachedDeviceId) {
        app.services.realtimeHub.detachRuntime(attachedDeviceId, socket);
        if (!app.services.realtimeHub.isRuntimeConnected(attachedDeviceId)) {
          await app.services.realtimeHub
            .releaseRuntimePresence(attachedDeviceId)
            .catch(() => undefined);
        }
      }
      const message =
        error instanceof Error
          ? error.message
          : "Runtime websocket authentication failed";
      socket.close(4401, message);
    }
  });

  app.get("/runtime-token-check", async (request) => {
    const token = extractBearerToken(request);
    const payload = (await app.jwt.verify(token)) as RuntimeAuthTokenPayload;

    if (payload.kind !== "runtime") {
      throw badRequest("Runtime token required");
    }

    return {
      ok: true,
      deviceId: payload.deviceId,
      userId: payload.sub,
      connectionId: payload.connectionId,
    };
  });
};
