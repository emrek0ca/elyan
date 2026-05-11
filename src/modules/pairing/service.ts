import { and, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import QRCode from "qrcode";
import { devices, pairSessions } from "../../db/schema.js";
import { createOpaqueCode, createPairingCode, deriveRuntimeDeviceSecret, hashSecret, verifySecret } from "../../lib/auth-crypto.js";
import { conflict, notFound } from "../../lib/errors.js";

function getPairingExpiry(minutes: number): Date {
  return new Date(Date.now() + minutes * 60_000);
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

export async function createPairSession(
  app: FastifyInstance,
  input: { deviceLabel: string; platform: string; runtimeVersion?: string },
) {
  const deviceRows = await app.db
    .insert(devices)
    .values({
      type: "desktop",
      label: input.deviceLabel,
      platform: input.platform,
      runtimeVersion: input.runtimeVersion,
    })
    .returning({
      id: devices.id,
      label: devices.label,
      platform: devices.platform,
      runtimeVersion: devices.runtimeVersion,
    });

  const desktopDevice = deviceRows[0];
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

  return {
    sessionId: pairSession.id,
    desktopDevice,
    status: pairSession.status,
    pairingCode,
    pairingToken,
    expiresAt: pairSession.expiresAt,
    qrPayload: {
      sessionId: pairSession.id,
      pairingCode,
    },
    qrText: `elyan://pair?sessionId=${pairSession.id}&code=${pairingCode}`,
    qrDataUrl: await QRCode.toDataURL(`elyan://pair?sessionId=${pairSession.id}&code=${pairingCode}`, {
      margin: 1,
      width: 320,
    }),
  };
}

export async function getPairSessionStatus(app: FastifyInstance, sessionId: string, pairingToken: string) {
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
    throw notFound("Pair session not found");
  }

  const tokenMatches = await verifySecret(pairingToken, pairSession.pairingTokenHash);

  if (!tokenMatches) {
    throw conflict("Pairing token does not match this session");
  }

  if (pairSession.expiresAt.getTime() <= Date.now()) {
    await expirePairSession(app, pairSession.id);
    throw conflict("Pair session has expired");
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
  const rows = await app.db
    .select({
      id: pairSessions.id,
      desktopDeviceId: pairSessions.desktopDeviceId,
      claimedByUserId: pairSessions.claimedByUserId,
      pairingCode: pairSessions.pairingCode,
      status: pairSessions.status,
      expiresAt: pairSessions.expiresAt,
      currentDeviceUserId: devices.userId,
    })
    .from(pairSessions)
    .innerJoin(devices, eq(devices.id, pairSessions.desktopDeviceId))
    .where(eq(pairSessions.id, input.sessionId))
    .limit(1);

  const pairSession = rows[0];

  if (!pairSession) {
    throw notFound("Pair session not found");
  }

  if (pairSession.expiresAt.getTime() <= Date.now()) {
    await expirePairSession(app, pairSession.id);
    throw conflict("Pair session has expired");
  }

  if (pairSession.pairingCode !== input.pairingCode) {
    throw conflict("Pairing code does not match");
  }

  if (pairSession.currentDeviceUserId && pairSession.currentDeviceUserId !== input.userId) {
    throw conflict("Desktop runtime is already paired with another user");
  }

  const derivedSecret = deriveRuntimeDeviceSecret({
    pairingSecret: app.config.RUNTIME_SECRET_PEPPER,
    pairSessionId: pairSession.id,
    pairingCode: pairSession.pairingCode,
    deviceId: pairSession.desktopDeviceId,
  });

  const deviceSecretHash = await hashSecret(derivedSecret);

  await app.db
    .update(devices)
    .set({
      userId: input.userId,
      deviceKeyHash: deviceSecretHash,
      pairedAt: new Date(),
      updatedAt: new Date(),
    })
    .where(eq(devices.id, pairSession.desktopDeviceId));

  if (input.mobileDevice) {
    await app.db.insert(devices).values({
      userId: input.userId,
      type: "mobile",
      label: input.mobileDevice.label,
      platform: input.mobileDevice.platform,
      appVersion: input.mobileDevice.appVersion,
      pairedAt: new Date(),
      lastSeenAt: new Date(),
    });
  }

  await app.db
    .update(pairSessions)
    .set({
      claimedByUserId: input.userId,
      status: "claimed",
      claimedAt: new Date(),
      updatedAt: new Date(),
    })
    .where(and(eq(pairSessions.id, input.sessionId), eq(pairSessions.desktopDeviceId, pairSession.desktopDeviceId)));

  app.services.eventBus.publish({
    topic: "pairing.claimed",
    userId: input.userId,
    deviceId: pairSession.desktopDeviceId,
    payload: {
      sessionId: pairSession.id,
      status: "claimed",
    },
  });

  return {
    sessionId: pairSession.id,
    desktopDeviceId: pairSession.desktopDeviceId,
    status: "claimed" as const,
  };
}
