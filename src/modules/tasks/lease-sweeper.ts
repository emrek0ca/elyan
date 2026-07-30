import { and, eq, inArray, isNull, lt, or, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { runtimeConnections, tasks } from "../../db/schema.js";
import { RUNTIME_CONNECTION_STALE_AFTER_MS } from "../devices/service.js";
import { reconcileStaleRuntimeTasks } from "./service.js";
import {
  TASK_APPROVAL_TTL_MS,
  TASK_QUEUE_TTL_MS,
  TASK_RETENTION_MS,
} from "./service-lifecycle.js";

const DEFAULT_SWEEP_INTERVAL_MS = 30_000;
const STALE_RUNTIME_TASK_AFTER_MS = 120_000;
/** Saklama temizliği süpürücü kadar sık koşmaz; saatte bir yeterli. */
const RETENTION_PURGE_INTERVAL_MS = 60 * 60_000;
/** Tek turda silinecek azami kayıt: uzun kilitler yerine kısa turlar. */
const RETENTION_PURGE_BATCH = 500;

/** Terminal (bitmiş) görev durumları — yalnız bunlar silinebilir. */
const TERMINAL_TASK_STATUSES = ["completed", "failed", "canceled"] as const;

/**
 * Saklama süresi dolmuş bitmiş görevleri KALICI olarak siler.
 *
 * Bağımlı satırlar şemadaki `cascade` / `set null` kurallarıyla birlikte
 * temizlenir; ayrıca elle silme gerekmez. Aktif görevler (queued, planning,
 * running, waiting_approval) yaşına bakılmaksızın korunur.
 */
async function purgeExpiredTasks(app: FastifyInstance, now: Date): Promise<number> {
  const cutoff = new Date(now.getTime() - TASK_RETENTION_MS);
  const doomed = await app.db
    .select({ id: tasks.id })
    .from(tasks)
    .where(
      and(
        inArray(tasks.status, [...TERMINAL_TASK_STATUSES]),
        lt(tasks.updatedAt, cutoff),
      ),
    )
    .limit(RETENTION_PURGE_BATCH);
  if (doomed.length === 0) return 0;
  await app.db.delete(tasks).where(
    inArray(
      tasks.id,
      doomed.map((row) => row.id),
    ),
  );
  return doomed.length;
}

type LeaseSweeperState = {
  timer: NodeJS.Timeout;
  running: boolean;
  stopped: boolean;
  lastRetentionPurgeAt: number;
};

const activeSweeps = new WeakMap<FastifyInstance, LeaseSweeperState>();

async function collectStaleRuntimeTaskScopes(app: FastifyInstance, now: Date) {
  const cutoff = new Date(now.getTime() - STALE_RUNTIME_TASK_AFTER_MS);
  const runtimeCutoff = new Date(now.getTime() - RUNTIME_CONNECTION_STALE_AFTER_MS);
  const approvalCutoff = new Date(now.getTime() - TASK_APPROVAL_TTL_MS);
  const queueCutoff = new Date(now.getTime() - TASK_QUEUE_TTL_MS);
  return app.db
    .select({
      userId: tasks.userId,
      targetDeviceId: tasks.targetDeviceId,
    })
    .from(tasks)
    .leftJoin(runtimeConnections, eq(tasks.runtimeConnectionId, runtimeConnections.id))
    .where(
      and(
        or(
          and(
            eq(tasks.status, "planning"),
            or(
              lt(tasks.dispatchLeaseExpiresAt, now),
              and(isNull(tasks.dispatchLeaseExpiresAt), lt(tasks.updatedAt, cutoff)),
            ),
          ),
          and(
            eq(tasks.status, "running"),
            lt(tasks.updatedAt, cutoff),
            or(
              isNull(tasks.runtimeConnectionId),
              isNull(runtimeConnections.id),
              sql`${runtimeConnections.disconnectedAt} is not null`,
              eq(runtimeConnections.status, "offline"),
              lt(runtimeConnections.lastHeartbeatAt, runtimeCutoff),
            ),
          ),
          // ONAY BEKLEYEN GÖREVLER DE SÜPÜRÜLÜR.
          //
          // Bu dal eksikti: `reconcileStaleRuntimeTasks` süresi dolmuş onayı
          // `approval_expired` ile kapatmayı zaten biliyordu, ama süpürücü
          // `waiting_approval` görevlerini hiç TOPLAMIYORDU. Uzlaştırma yalnız
          // kullanıcı başka bir istek attığında tetiklendiği için, onaya
          // dokunulmayan bir görev sonsuza kadar asılı kalıyordu — mobilde
          // "sıkışmış onay" olarak görünen şey buydu.
          //
          // Cihaz bağlantısı şart değil: onay kullanıcıyı bekler, masaüstünü
          // değil. Bağlantı koşulu buraya konursa çevrimiçi bir masaüstünde
          // bekleyen onay yine hiç süpürülmez.
          and(
            eq(tasks.status, "waiting_approval"),
            lt(tasks.updatedAt, approvalCutoff),
          ),
          // Teslim edilemeden kuyrukta kalan görevler (bkz. TASK_QUEUE_TTL_MS).
          and(eq(tasks.status, "queued"), lt(tasks.updatedAt, queueCutoff)),
        ),
      ),
    )
    .groupBy(tasks.userId, tasks.targetDeviceId);
}

export function startTaskLeaseSweeper(app: FastifyInstance): () => void {
  const existing = activeSweeps.get(app);
  if (existing) {
    return () => {
      if (existing.stopped) {
        return;
      }
      existing.stopped = true;
      clearInterval(existing.timer);
      activeSweeps.delete(app);
    };
  }

  const state: LeaseSweeperState = {
    timer: setInterval(() => {
      void runSweep();
    }, DEFAULT_SWEEP_INTERVAL_MS),
    running: false,
    stopped: false,
    lastRetentionPurgeAt: 0,
  };

  state.timer.unref?.();
  activeSweeps.set(app, state);

  void runSweep();

  async function runSweep() {
    if (state.stopped || state.running) {
      return;
    }

    state.running = true;
    const now = new Date();
    try {
      await app.services.blobs.pruneExpiredMediaInputs(now, 100);
      const scopes = await collectStaleRuntimeTaskScopes(app, now);
      for (const scope of scopes) {
        if (state.stopped) {
          return;
        }

        await reconcileStaleRuntimeTasks(app, {
          userId: scope.userId,
          targetDeviceId: scope.targetDeviceId ?? undefined,
          limit: 50,
          now,
        });
      }
      if (
        !state.stopped &&
        now.getTime() - state.lastRetentionPurgeAt >= RETENTION_PURGE_INTERVAL_MS
      ) {
        state.lastRetentionPurgeAt = now.getTime();
        const purged = await purgeExpiredTasks(app, now);
        if (purged > 0) {
          app.log.info(
            { purged, retentionDays: TASK_RETENTION_MS / (24 * 60 * 60_000) },
            "expired tasks purged",
          );
        }
      }
    } catch (error) {
      app.log.warn(
        {
          error,
        },
        "task lease sweeper failed",
      );
    } finally {
      state.running = false;
    }
  }

  return () => {
    if (state.stopped) {
      return;
    }
    state.stopped = true;
    clearInterval(state.timer);
    activeSweeps.delete(app);
  };
}
