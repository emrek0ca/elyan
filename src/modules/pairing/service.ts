import { and, eq, inArray, lte } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import QRCode from "qrcode";
import { devices, pairSessions, tasks } from "../../db/schema.js";
import { createOpaqueCode, createPairingCode, deriveRuntimeDeviceSecret, hashSecret, verifySecret } from "../../lib/auth-crypto.js";
import { AppError, conflict, notFound } from "../../lib/errors.js";
import { assertDesktopPairingAllowed } from "../billing/service.js";
import { RUNTIME_CONNECTION_STALE_AFTER_MS } from "../devices/service.js";
import { invalidateBrainProfileCache } from "../brain/profile-cache.js";
import { getSharedBrainTargetDeviceId } from "../devices/service.js";
import { activeTaskStatuses, resequenceDeviceQueue } from "../tasks/queue.js";
import { deriveTaskDeliveryState, extractTaskRouteDecision } from "../tasks/service-helpers.js";

function getPairingExpiry(minutes: number): Date {
  return new Date(Date.now() + minutes * 60_000);
}

function buildPairingQrText(sessionId: string, pairingCode: string): string {
  return `elyan://pair?sessionId=${sessionId}&pairingCode=${pairingCode}`;
}

function buildPairingManualCode(sessionId: string, pairingCode: string): string {
  return `${sessionId}|${pairingCode}`;
}

function normalizePairingCode(value: string): string {
  return value.toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function retargetPairingRequiredPayload(payload: unknown): Record<string, unknown> | null {
  const root = readRecord(payload);
  const metadata = readRecord(root?.metadata);
  const routeDecision = readRecord(metadata?.routeDecision) ?? readRecord(metadata?.routingDecision);
  if (!root || !metadata || !routeDecision || routeDecision.route !== "pairing_required") {
    return null;
  }

  return {
    ...root,
    metadata: {
      ...metadata,
      blocked: false,
      recoveredFrom: "pairing_required",
      routeDecision: {
        ...routeDecision,
        route: "desktop_runtime",
        reason: "Desktop pairing completed; queued task is now assigned to the paired runtime.",
        userFacingMessage: "Görev masaüstüne bağlandı ve çalıştırılmaya hazır.",
        failClosedReason: null,
      },
    },
  };
}

async function retargetPairingRequiredTasksToDesktop(
  app: FastifyInstance,
  input: {
    userId: string;
    desktopDeviceId: string;
  },
) {
  const sharedBrainDeviceId = await getSharedBrainTargetDeviceId(app);
  if (!sharedBrainDeviceId) {
    return 0;
  }

  const rows = await app.db
    .select({
      id: tasks.id,
      userId: tasks.userId,
      targetDeviceId: tasks.targetDeviceId,
      title: tasks.title,
      status: tasks.status,
      payload: tasks.payload,
      queuePosition: tasks.queuePosition,
      dispatchAttemptCount: tasks.dispatchAttemptCount,
      runtimeConnectionId: tasks.runtimeConnectionId,
      dispatchLeaseId: tasks.dispatchLeaseId,
      dispatchLeaseIssuedAt: tasks.dispatchLeaseIssuedAt,
      dispatchLeaseExpiresAt: tasks.dispatchLeaseExpiresAt,
      dispatchAckAt: tasks.dispatchAckAt,
      requestedCapabilities: tasks.requestedCapabilities,
      result: tasks.result,
      summary: tasks.summary,
      error: tasks.error,
      approvalRequest: tasks.approvalRequest,
      createdAt: tasks.createdAt,
      startedAt: tasks.startedAt,
      completedAt: tasks.completedAt,
      canceledAt: tasks.canceledAt,
      updatedAt: tasks.updatedAt,
    })
    .from(tasks)
    .where(
      and(
        eq(tasks.userId, input.userId),
        eq(tasks.targetDeviceId, sharedBrainDeviceId),
        inArray(tasks.status, activeTaskStatuses),
      ),
    )
    .limit(50);

  let retargetedCount = 0;
  for (const task of rows) {
    const nextPayload = retargetPairingRequiredPayload(task.payload);
    if (!nextPayload) {
      continue;
    }

    const updatedRows = await app.db
      .update(tasks)
      .set({
        targetDeviceId: input.desktopDeviceId,
        payload: nextPayload,
        summary: null,
        updatedAt: new Date(),
      })
      .where(eq(tasks.id, task.id))
      .returning({
        id: tasks.id,
        userId: tasks.userId,
        targetDeviceId: tasks.targetDeviceId,
        status: tasks.status,
        payload: tasks.payload,
        queuePosition: tasks.queuePosition,
        dispatchAttemptCount: tasks.dispatchAttemptCount,
        runtimeConnectionId: tasks.runtimeConnectionId,
        dispatchLeaseId: tasks.dispatchLeaseId,
        dispatchLeaseIssuedAt: tasks.dispatchLeaseIssuedAt,
        dispatchLeaseExpiresAt: tasks.dispatchLeaseExpiresAt,
        dispatchAckAt: tasks.dispatchAckAt,
        summary: tasks.summary,
        updatedAt: tasks.updatedAt,
      });
    const updated = updatedRows[0];
    if (!updated) {
      continue;
    }

    retargetedCount += 1;
    await app.services.eventBus.publish({
      topic: "task.updated",
      userId: updated.userId,
      deviceId: updated.targetDeviceId,
      taskId: updated.id,
      payload: {
        id: updated.id,
        taskId: updated.id,
        targetDeviceId: updated.targetDeviceId,
        status: updated.status,
        queuePosition: updated.queuePosition,
        runtimeConnectionId: updated.runtimeConnectionId,
        dispatchLeaseId: updated.dispatchLeaseId,
        dispatchLeaseExpiresAt: updated.dispatchLeaseExpiresAt,
        dispatchAckAt: updated.dispatchAckAt,
        deliveryAttemptCount: updated.dispatchAttemptCount ?? 0,
        lastAckAt: updated.dispatchAckAt ?? null,
        lastDispatchAttemptAt: updated.dispatchLeaseIssuedAt ?? updated.dispatchAckAt ?? null,
        deliveryState: deriveTaskDeliveryState(updated),
        routeDecision: extractTaskRouteDecision(updated.payload),
        summary: updated.summary,
        updatedAt: updated.updatedAt.toISOString(),
      },
    });
  }

  if (retargetedCount > 0) {
    await resequenceDeviceQueue(app, sharedBrainDeviceId);
    await resequenceDeviceQueue(app, input.desktopDeviceId);
  }

  return retargetedCount;
}

async function expirePairSession(app: FastifyInstance, sessionId: string): Promise<void> {
  await app.db
    .update(pairSessions)
    .set({
      status: "expired",
      updatedAt: new Date(),
    })
    .where(eq(pairSessions.id, sessionId));
}

async function expireExpiredPendingPairSessions(app: FastifyInstance): Promise<void> {
  await app.db
    .update(pairSessions)
    .set({
      status: "expired",
      updatedAt: new Date(),
    })
    .where(and(eq(pairSessions.status, "pending"), lte(pairSessions.expiresAt, new Date())));
}

async function expirePendingPairSessionsForDesktop(app: FastifyInstance, desktopDeviceId: string): Promise<void> {
  await app.db
    .update(pairSessions)
    .set({
      status: "expired",
      updatedAt: new Date(),
    })
    .where(and(eq(pairSessions.desktopDeviceId, desktopDeviceId), eq(pairSessions.status, "pending")));
}

type DesktopPairingDeviceRow = {
  id: string;
  userId: string | null;
  externalDeviceId: string | null;
  label: string;
  platform: string;
  runtimeVersion: string | null;
};

async function upsertDesktopPairingDevice(
  app: FastifyInstance,
  input: {
    userId: string | null;
    deviceLabel: string;
    platform: string;
    runtimeVersion?: string;
    externalDeviceId?: string;
  },
): Promise<DesktopPairingDeviceRow> {
  const normalizedExternalDeviceId = String(input.externalDeviceId ?? "").trim();
  const now = new Date();

  if (!normalizedExternalDeviceId) {
    const insertedRows = await app.db
      .insert(devices)
      .values({
        userId: input.userId,
        type: "desktop",
        label: input.deviceLabel,
        platform: input.platform,
        runtimeVersion: input.runtimeVersion,
        isActive: true,
        updatedAt: now,
      })
      .returning({
        id: devices.id,
        userId: devices.userId,
        externalDeviceId: devices.externalDeviceId,
        label: devices.label,
        platform: devices.platform,
        runtimeVersion: devices.runtimeVersion,
      });
    return insertedRows[0]!;
  }

  const existingRows = await app.db
    .select({
      id: devices.id,
      userId: devices.userId,
      externalDeviceId: devices.externalDeviceId,
      label: devices.label,
      platform: devices.platform,
      runtimeVersion: devices.runtimeVersion,
      isActive: devices.isActive,
      lastSeenAt: devices.lastSeenAt,
    })
    .from(devices)
    .where(and(eq(devices.type, "desktop"), eq(devices.externalDeviceId, normalizedExternalDeviceId)))
    .limit(8);

  // Anonim (girişsiz) masaüstü mevcut cihaz kaydını sahibini değiştirmeden
  // yeniden kullanabilir — kullanıcı eşleşmesi claim anında doğrulanır.
  //
  // SAHİPLİK DEVRİ: aynı fiziksel makine başka bir hesaba kayıtlıysa bu
  // ESKİDEN kalıcı bir kilitti — kullanıcı kendi bilgisayarını hiçbir şekilde
  // geri alamıyordu ("başka kullanıcı bağlı" der ama masaüstünde bağlantı
  // görünmez). Eşleştirme zaten masaüstünde gösterilen kodu gerektiriyor,
  // yani makineye fiziksel erişimin kanıtı var.
  //
  // Devir yalnız eski kayıt GERÇEKTEN kopuksa yapılır: pasif ya da
  // heartbeat'i bayat. Başka bir kullanıcının O AN bağlı makinesi asla
  // devralınamaz — o durumda çakışma korunur.
  const conflictingRows = input.userId
    ? existingRows.filter((row) => row.userId && row.userId !== input.userId)
    : [];
  const liveConflict = conflictingRows.find((row) => {
    if (!row.isActive) return false;
    const lastSeen = row.lastSeenAt?.getTime() ?? 0;
    return Date.now() - lastSeen <= RUNTIME_CONNECTION_STALE_AFTER_MS;
  });
  if (liveConflict) {
    throw conflict("Desktop runtime is already paired with another user");
  }
  if (conflictingRows.length > 0) {
    // Bayat kayıtları serbest bırak: sahipsiz kalırlar ve aşağıdaki
    // yeniden-kullanım yolu bu makineyi mevcut kullanıcıya bağlar.
    await app.db
      .update(devices)
      .set({ isActive: false, userId: null, updatedAt: new Date() })
      .where(inArray(devices.id, conflictingRows.map((row) => row.id)));
    app.log.warn(
      { externalDeviceId: normalizedExternalDeviceId, released: conflictingRows.length },
      "stale desktop ownership released for re-pairing",
    );
    conflictingRows.forEach((row) => {
      const index = existingRows.findIndex((candidate) => candidate.id === row.id);
      if (index >= 0) existingRows[index] = { ...existingRows[index]!, userId: null };
    });
  }

  const reusableRow = input.userId
    ? (existingRows.find((row) => row.userId === input.userId) ?? existingRows.find((row) => row.userId == null))
    : existingRows[0];
  if (reusableRow) {
    const updatedRows = await app.db
      .update(devices)
      .set({
        userId: input.userId ?? reusableRow.userId,
        label: input.deviceLabel,
        platform: input.platform,
        runtimeVersion: input.runtimeVersion,
        isActive: true,
        updatedAt: now,
      })
      .where(eq(devices.id, reusableRow.id))
      .returning({
        id: devices.id,
        userId: devices.userId,
        externalDeviceId: devices.externalDeviceId,
        label: devices.label,
        platform: devices.platform,
        runtimeVersion: devices.runtimeVersion,
      });
    return updatedRows[0]!;
  }

  const insertedRows = await app.db
    .insert(devices)
    .values({
      userId: input.userId,
      type: "desktop",
      externalDeviceId: normalizedExternalDeviceId,
      label: input.deviceLabel,
      platform: input.platform,
      runtimeVersion: input.runtimeVersion,
      isActive: true,
      updatedAt: now,
    })
    .returning({
      id: devices.id,
      userId: devices.userId,
      externalDeviceId: devices.externalDeviceId,
      label: devices.label,
      platform: devices.platform,
      runtimeVersion: devices.runtimeVersion,
    });
  return insertedRows[0]!;
}

export async function createPairSession(
  app: FastifyInstance,
  input: {
    userId: string | null;
    deviceLabel: string;
    platform: string;
    runtimeVersion?: string;
    externalDeviceId?: string;
  },
) {
  await expireExpiredPendingPairSessions(app);
  if (input.userId) {
    // Anonim oturumda fatura/limit denetimi claim anında yapılır.
    await assertDesktopPairingAllowed(app, input.userId);
  }
  const desktopDevice = await upsertDesktopPairingDevice(app, input);
  await expirePendingPairSessionsForDesktop(app, desktopDevice.id);
  const pairingToken = createOpaqueCode(24);
  const pairingCode = createPairingCode();
  const pairingTokenHash = await hashSecret(pairingToken);
  const expiresAt = getPairingExpiry(app.config.PAIRING_TTL_MINUTES);

  const pairRows = await app.db
    .insert(pairSessions)
    .values({
      desktopDeviceId: desktopDevice.id,
      pairingCode,
      pairingTokenHash,
      expiresAt,
    })
    .returning({
      id: pairSessions.id,
      desktopDeviceId: pairSessions.desktopDeviceId,
      expiresAt: pairSessions.expiresAt,
      status: pairSessions.status,
    });

  const pairSession = pairRows[0];

  if (input.userId) {
    invalidateBrainProfileCache(app, input.userId);
  }

  return {
    sessionId: pairSession.id,
    desktopDevice,
    status: pairSession.status,
    pairingCode,
    manualEntryCode: buildPairingManualCode(pairSession.id, pairingCode),
    pairingToken,
    expiresAt: pairSession.expiresAt,
    qrPayload: {
      schemaVersion: 1,
      sessionId: pairSession.id,
      pairingCode,
      manualEntryCode: buildPairingManualCode(pairSession.id, pairingCode),
    },
    qrText: buildPairingQrText(pairSession.id, pairingCode),
    qrDataUrl: await QRCode.toDataURL(buildPairingQrText(pairSession.id, pairingCode), {
      margin: 1,
      width: 320,
    }),
  };
}

export async function getPairSessionStatus(app: FastifyInstance, sessionId: string, pairingToken: string) {
  await expireExpiredPendingPairSessions(app);
  const rows = await app.db
    .select({
      id: pairSessions.id,
      desktopDeviceId: pairSessions.desktopDeviceId,
      claimedByUserId: pairSessions.claimedByUserId,
      pairingCode: pairSessions.pairingCode,
      pairingTokenHash: pairSessions.pairingTokenHash,
      status: pairSessions.status,
      expiresAt: pairSessions.expiresAt,
      claimedAt: pairSessions.claimedAt,
    })
    .from(pairSessions)
    .where(eq(pairSessions.id, sessionId))
    .limit(1);

  const pairSession = rows[0];

  if (!pairSession) {
    throw new AppError(404, "pairing_pending", "Pair session not found");
  }

  const tokenMatches = await verifySecret(pairingToken, pairSession.pairingTokenHash);

  if (!tokenMatches) {
    throw new AppError(
      409,
      "pairing_invalid_token",
      "Pairing token does not match this session",
    );
  }

  if (pairSession.status === "expired") {
    throw new AppError(409, "pairing_expired", "Pair session has expired");
  }

  if (pairSession.status !== "claimed" && pairSession.expiresAt.getTime() <= Date.now()) {
    await expirePairSession(app, pairSession.id);
    throw new AppError(409, "pairing_expired", "Pair session has expired");
  }

  const runtimeAuth =
    pairSession.status === "claimed" && pairSession.claimedByUserId
      ? {
          deviceId: pairSession.desktopDeviceId,
          deviceSecret: deriveRuntimeDeviceSecret({
            pairingSecret: app.config.RUNTIME_SECRET_PEPPER,
            pairSessionId: pairSession.id,
            pairingCode: pairSession.pairingCode,
            deviceId: pairSession.desktopDeviceId,
          }),
        }
      : null;

  return {
    sessionId: pairSession.id,
    desktopDeviceId: pairSession.desktopDeviceId,
    claimedByUserId: pairSession.claimedByUserId,
    status: pairSession.status,
    claimedAt: pairSession.claimedAt,
    expiresAt: pairSession.expiresAt,
    runtimeAuth,
  };
}

export async function claimPairSession(
  app: FastifyInstance,
  input: {
    sessionId: string;
    userId: string;
    pairingCode: string;
      mobileDevice?: {
        label: string;
        platform: string;
        appVersion?: string;
      };
  },
) {
  await expireExpiredPendingPairSessions(app);
  const rows = await app.db
    .select({
      id: pairSessions.id,
      desktopDeviceId: pairSessions.desktopDeviceId,
      claimedByUserId: pairSessions.claimedByUserId,
      pairingCode: pairSessions.pairingCode,
      status: pairSessions.status,
      expiresAt: pairSessions.expiresAt,
      currentDeviceUserId: devices.userId,
      currentDeviceActive: devices.isActive,
      currentDeviceLastSeenAt: devices.lastSeenAt,
    })
    .from(pairSessions)
    .innerJoin(devices, eq(devices.id, pairSessions.desktopDeviceId))
    .where(eq(pairSessions.id, input.sessionId))
    .limit(1);

  const pairSession = rows[0];

  if (!pairSession) {
    throw new AppError(404, "pairing_pending", "Pair session not found");
  }

  if (pairSession.status === "claimed") {
    if (pairSession.claimedByUserId === input.userId) {
      return {
        sessionId: pairSession.id,
        desktopDeviceId: pairSession.desktopDeviceId,
        status: "claimed" as const,
        retargetedTaskCount: 0,
      };
    }

    throw new AppError(409, "pairing_pending", "Pair session is already claimed");
  }

  if (pairSession.status === "expired" || pairSession.expiresAt.getTime() <= Date.now()) {
    await expirePairSession(app, pairSession.id);
    throw new AppError(409, "pairing_expired", "Pair session has expired");
  }

  await assertDesktopPairingAllowed(app, input.userId, pairSession.desktopDeviceId);

  if (normalizePairingCode(pairSession.pairingCode) !== normalizePairingCode(input.pairingCode)) {
    throw new AppError(409, "pairing_invalid_code", "Pairing code does not match");
  }

  // SAHİPLİK DEVRİ — claim yolu.
  //
  // Kayıt yolunda (`registerDesktopDevice`) aynı kural zaten var; burası
  // ATLANMIŞTI ve kullanıcının canlıda gördüğü hata tam olarak buradan
  // geliyordu: mobilde kodu girince "Desktop runtime is already paired with
  // another user". Yani makine sahipsiz kalsa bile kod girme adımı yine
  // reddediyordu.
  //
  // Devir yalnız eski kayıt GERÇEKTEN kopuksa yapılır: pasif ya da
  // heartbeat'i bayat. Başka birinin O AN bağlı makinesi devralınamaz.
  // Eşleştirme kodu masaüstünde gösteriliyor, yani makineye fiziksel erişim
  // zaten kanıtlanmış durumda.
  if (pairSession.currentDeviceUserId && pairSession.currentDeviceUserId !== input.userId) {
    const lastSeen = pairSession.currentDeviceLastSeenAt?.getTime() ?? 0;
    const liveElsewhere =
      pairSession.currentDeviceActive === true &&
      Date.now() - lastSeen <= RUNTIME_CONNECTION_STALE_AFTER_MS;
    if (liveElsewhere) {
      throw new AppError(
        409,
        "runtime_unreachable",
        "Desktop runtime is already paired with another user",
      );
    }
    await app.db
      .update(devices)
      .set({ userId: null, isActive: false, updatedAt: new Date() })
      .where(eq(devices.id, pairSession.desktopDeviceId));
    app.log.warn(
      { deviceId: pairSession.desktopDeviceId },
      "stale desktop ownership released during claim",
    );
  }

  const derivedSecret = deriveRuntimeDeviceSecret({
    pairingSecret: app.config.RUNTIME_SECRET_PEPPER,
    pairSessionId: pairSession.id,
    pairingCode: pairSession.pairingCode,
    deviceId: pairSession.desktopDeviceId,
  });

  const deviceSecretHash = await hashSecret(derivedSecret);

  await app.db.transaction(async (tx) => {
    await tx
      .update(devices)
      .set({
        userId: input.userId,
        deviceKeyHash: deviceSecretHash,
        pairedAt: new Date(),
        updatedAt: new Date(),
      })
      .where(eq(devices.id, pairSession.desktopDeviceId));

    // Mobile inventory is owned by /v1/devices/mobile/register because pairing
    // claims do not carry the stable externalDeviceId used for deduplication.
    await tx
      .update(pairSessions)
      .set({
        claimedByUserId: input.userId,
        status: "claimed",
        claimedAt: new Date(),
        updatedAt: new Date(),
      })
      .where(and(eq(pairSessions.id, input.sessionId), eq(pairSessions.desktopDeviceId, pairSession.desktopDeviceId)));
  });

  const retargetedTaskCount = await retargetPairingRequiredTasksToDesktop(app, {
    userId: input.userId,
    desktopDeviceId: pairSession.desktopDeviceId,
  });

  await app.services.eventBus.publish({
    topic: "pairing.claimed",
    userId: input.userId,
    deviceId: pairSession.desktopDeviceId,
    payload: {
      sessionId: pairSession.id,
      desktopDeviceId: pairSession.desktopDeviceId,
      status: "claimed",
      retargetedTaskCount,
    },
  });

  invalidateBrainProfileCache(app, input.userId);
  return {
    sessionId: pairSession.id,
    desktopDeviceId: pairSession.desktopDeviceId,
    status: "claimed" as const,
    retargetedTaskCount,
  };
}

/**
 * Kısa kodla eşleştirme (QR'sız). `pairingCode` DB'de globally UNIQUE olduğu
 * için mobil yalnızca desktop'ta gösterilen kısa kodu girer; session UUID'sine
 * gerek yoktur. Kod → session çözülür, ardından tüm doğrulamalar (süre, sahiplik,
 * kod eşleşmesi, plan limiti) `claimPairSession` içinde aynen uygulanır.
 */
export async function claimPairSessionByCode(
  app: FastifyInstance,
  input: {
    userId: string;
    pairingCode: string;
    mobileDevice?: {
      label: string;
      platform: string;
      appVersion?: string;
    };
  },
) {
  const normalizedCode = normalizePairingCode(input.pairingCode);
  if (normalizedCode.length === 0) {
    throw new AppError(409, "pairing_invalid_code", "Pairing code does not match");
  }

  const rows = await app.db
    .select({ id: pairSessions.id })
    .from(pairSessions)
    .where(eq(pairSessions.pairingCode, normalizedCode))
    .limit(1);

  const pairSession = rows[0];
  if (!pairSession) {
    throw new AppError(404, "pairing_pending", "Pair session not found");
  }

  return claimPairSession(app, {
    sessionId: pairSession.id,
    userId: input.userId,
    pairingCode: normalizedCode,
    mobileDevice: input.mobileDevice,
  });
}
