import { and, desc, eq, gte, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { chatSessions, devices, tasks, users, worldSignals } from "../../db/schema.js";
import { AppError } from "../../lib/errors.js";
import { getBillingSummary, shapePublicUsageSnapshot } from "../billing/service.js";
import { shapeSubscriptionTruth } from "../billing/subscription-truth.js";
import { getBrainProfile, shapePublicBrainProfile } from "../brain/service.js";
import { listUserDevices } from "../devices/service.js";
import { getTrialQuotaPolicy } from "../quota/service.js";
import type { UploadWorldSignalsBody } from "./schemas.js";

const MAX_WORLD_SIGNAL_PAYLOAD_BYTES = 24 * 1024;
const BLOCKED_SECRET_KEYS = new Set([
  "accesstoken",
  "authorization",
  "bearertoken",
  "idtoken",
  "refreshtoken",
  "sessiontoken",
  "token",
]);
const BLOCKED_PRECISE_LOCATION_KEYS = new Set([
  "coordinate",
  "coordinates",
  "lat",
  "latitude",
  "lng",
  "lon",
  "long",
  "longitude",
]);
const BLOCKED_CALENDAR_KEYS = new Set([
  "attendee",
  "attendees",
  "body",
  "calendarbody",
  "calendardescription",
  "description",
  "eventbody",
  "eventdescription",
  "eventtitle",
  "invitee",
  "invitees",
  "meetinglink",
  "notes",
  "title",
]);
const BLOCKED_HEALTH_KEYS = new Set([
  "activeenergyburnedkcal",
  "caloriesburned",
  "healthdatapoint",
  "healthdatapoints",
  "heartrate",
  "heartratebpm",
  "rawsample",
  "rawsamples",
  "sleepduration",
  "sleephours",
  "sleepminutes",
  "stepcount",
  "steps",
  "workoutdistance",
  "workouttype",
]);
const BLOCKED_BINARY_KEYS = new Set([
  "arraybuffer",
  "audio",
  "audiofile",
  "audiobase64",
  "base64",
  "base64data",
  "binary",
  "blob",
  "bloburl",
  "buffer",
  "bytes",
  "datauri",
  "dataurl",
  "documentbytes",
  "file",
  "filebytes",
  "filepath",
  "fileuri",
  "image",
  "imagebase64",
  "imagebytes",
  "localpath",
  "path",
  "previewimage",
  "rawaudio",
  "rawbinary",
  "rawbytes",
  "rawfile",
  "rawfilepath",
  "video",
  "videofile",
]);
const BLOCKED_DEBUG_KEYS = new Set([
  "debug",
  "debugblob",
  "debugpayload",
  "providerdebug",
  "providerresponse",
  "rawproviderresponse",
  "reasoning",
  "reasoningtrace",
  "stacktrace",
  "trace",
]);

function normalizeKey(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
}

function looksLikeLocalPath(value: string) {
  return (
    value.startsWith("/") ||
    value.startsWith("file://") ||
    value.startsWith("~/") ||
    /^[A-Za-z]:\\/.test(value)
  );
}

function assertWorldSignalValueSafe(value: unknown, key = ""): void {
  if (value == null) {
    return;
  }
  if (typeof value === "string") {
    if (looksLikeLocalPath(value.trim())) {
      throw new AppError(422, "local_path_blocked", "Local file paths cannot be uploaded.");
    }
    return;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return;
  }
  if (Array.isArray(value)) {
    if (value.length > 16) {
      throw new AppError(413, "payload_too_large", "World signal list payload is too large.");
    }
    for (const item of value) {
      assertWorldSignalValueSafe(item, key);
    }
    return;
  }
  if (typeof value === "object") {
    for (const [entryKey, entryValue] of Object.entries(value)) {
      const normalizedKey = normalizeKey(entryKey);
      if (BLOCKED_SECRET_KEYS.has(normalizedKey)) {
        throw new AppError(422, "secret_blocked", "Secrets cannot be uploaded.");
      }
      if (BLOCKED_BINARY_KEYS.has(normalizedKey)) {
        throw new AppError(422, "raw_payload_blocked", "Raw private content cannot be uploaded.");
      }
      if (BLOCKED_PRECISE_LOCATION_KEYS.has(normalizedKey)) {
        throw new AppError(422, "precise_location_blocked", "Precise coordinates cannot be uploaded.");
      }
      if (BLOCKED_HEALTH_KEYS.has(normalizedKey)) {
        throw new AppError(422, "raw_health_blocked", "Raw health values cannot be uploaded.");
      }
      if (BLOCKED_CALENDAR_KEYS.has(normalizedKey)) {
        throw new AppError(422, "raw_calendar_blocked", "Raw calendar fields cannot be uploaded.");
      }
      if (BLOCKED_DEBUG_KEYS.has(normalizedKey)) {
        throw new AppError(422, "debug_payload_blocked", "Debug or reasoning payloads cannot be uploaded.");
      }
      assertWorldSignalValueSafe(entryValue, normalizedKey);
    }
  }
}

export function assertSafeWorldSignalPayload(body: UploadWorldSignalsBody) {
  const payloadBytes = Buffer.byteLength(JSON.stringify(body), "utf8");
  if (payloadBytes > MAX_WORLD_SIGNAL_PAYLOAD_BYTES) {
    throw new AppError(413, "payload_too_large", "World signal payload exceeds the size limit.");
  }

  for (const signal of body.signals) {
    const rawDataUploaded =
      signal.privacy.rawDataUploaded === undefined
        ? false
        : Boolean(signal.privacy.rawDataUploaded);
    if (rawDataUploaded) {
      throw new AppError(422, "raw_payload_blocked", "Raw world data cannot be uploaded.");
    }
    if (
      signal.privacy.rawFileUploaded === true ||
      signal.privacy.rawImageUploaded === true ||
      signal.privacy.rawAudioUploaded === true
    ) {
      throw new AppError(422, "raw_payload_blocked", "Raw world data cannot be uploaded.");
    }
    assertWorldSignalValueSafe(signal.summary, "summary");
    assertWorldSignalValueSafe(signal.facts, "facts");
    assertWorldSignalValueSafe(signal.privacy, "privacy");
    if (signal.renderHints) {
      assertWorldSignalValueSafe(signal.renderHints, "renderHints");
    }
  }
}

export function buildWorldSignalLogContext(input: {
  accepted: boolean;
  reasonCode: string;
  userId: string;
  deviceId: string;
  payloadBytes: number;
  signals: Array<{ kind: string; createdAt: string }>;
}) {
  return {
    accepted: input.accepted,
    reasonCode: input.reasonCode,
    userId: input.userId,
    deviceId: input.deviceId,
    payloadBytes: input.payloadBytes,
    signalCount: input.signals.length,
    kinds: input.signals.map((signal) => signal.kind),
    createdAt: input.signals[0]?.createdAt ?? null,
  };
}

export async function getMobileBootstrap(app: FastifyInstance, userId: string) {
  const [
    userRows,
    devices,
    pendingCounts,
    billing,
    brain,
  ] = await Promise.all([
    app.db
      .select({
        id: users.id,
        email: users.email,
        displayName: users.displayName,
        role: users.role,
        createdAt: users.createdAt,
      })
      .from(users)
      .where(eq(users.id, userId))
      .limit(1),
    listUserDevices(app, userId),
    app.db
      .select({
        pendingApprovals: sql<number>`count(*) filter (where ${tasks.status} = 'waiting_approval')`,
        activeTasks: sql<number>`count(*) filter (where ${tasks.status} in ('queued', 'planning', 'running', 'waiting_approval'))`,
      })
      .from(tasks)
      .where(eq(tasks.userId, userId)),
    getBillingSummary(app, userId),
    getBrainProfile(app, userId),
  ]);

  return {
    user: userRows[0] ?? null,
    billingState: billing.billingState,
    quota: getTrialQuotaPolicy(),
    subscription: shapeSubscriptionTruth({
      planCode: billing.subscription.planCode,
      status: billing.subscription.status,
      aiCreditsMonthly: billing.entitlements.aiCreditsMonthly,
      taskLimitMonthly: billing.entitlements.taskLimitMonthly,
      brainProfile: billing.subscription.brainProfile,
      periodEndsAt: billing.subscription.periodEndsAt,
      trialEndsAt: billing.subscription.trialEndsAt,
      creditBalance: billing.usage.creditBalance,
      tokenBalance: billing.usage.tokenBalance,
      creditGrantedThisPeriod: billing.usage.creditGrantedThisPeriod,
      tokensGrantedThisPeriod: billing.usage.tokensGrantedThisPeriod,
      creditPeriodEndsAt: billing.usage.creditPeriodEndsAt,
      tokenPeriodEndsAt: billing.usage.tokenPeriodEndsAt,
      billingProvider: billing.subscription.billingProvider,
      subscriptionSource: billing.usage.subscriptionSource,
      manageSubscriptionHint: billing.usage.manageSubscriptionHint,
      creditStatus: billing.usage.creditStatus,
      tokenStatus: billing.usage.tokenStatus,
      trialOffer: billing.subscription.trialOffer,
    }),
    usage: shapePublicUsageSnapshot({
      usage: billing.usage,
      subscription: billing.subscription,
    }),
    brain: shapeMobileBootstrapBrain(brain),
    devices,
    recentTasks: [],
    historyFeed: [],
    summary: {
      pendingApprovals: Number(pendingCounts[0]?.pendingApprovals ?? 0),
      activeTasks: Number(pendingCounts[0]?.activeTasks ?? 0),
      connectedDesktops: devices.filter(
        (device) => device.type === "desktop" && device.runtime.isConnected,
      ).length,
    },
  };
}

export function shapeMobileBootstrapBrain(
  brain: Parameters<typeof shapePublicBrainProfile>[0],
) {
  const publicBrain = shapePublicBrainProfile(brain);

  return {
    ...publicBrain,
    memoryAwareChatReady: brain.metacognition.memoryAwareChatReady,
  };
}

async function resolveOwnedMobileDevice(
  app: FastifyInstance,
  userId: string,
  externalDeviceId: string,
) {
  const rows = await app.db
    .select({
      id: devices.id,
      isActive: devices.isActive,
    })
    .from(devices)
    .where(
      and(
        eq(devices.userId, userId),
        eq(devices.type, "mobile"),
        eq(devices.externalDeviceId, externalDeviceId),
      ),
    )
    .limit(1);
  return rows[0] ?? null;
}

async function resolveOwnedChatSession(
  app: FastifyInstance,
  userId: string,
  sessionId: string,
) {
  const rows = await app.db
    .select({ id: chatSessions.id })
    .from(chatSessions)
    .where(and(eq(chatSessions.userId, userId), eq(chatSessions.id, sessionId)))
    .limit(1);
  return rows[0] ?? null;
}

export async function ingestWorldSignals(
  app: FastifyInstance,
  input: {
    userId: string;
    externalDeviceId: string;
    body: UploadWorldSignalsBody;
  },
) {
  assertSafeWorldSignalPayload(input.body);

  const ownedDevice = await resolveOwnedMobileDevice(
    app,
    input.userId,
    input.externalDeviceId,
  );
  if (!ownedDevice || !ownedDevice.isActive) {
    throw new AppError(403, "device_revoked", "Mobile device scope is not valid for this user.");
  }

  const scopedSessionId =
    input.body.sessionId == null
      ? null
      : (await resolveOwnedChatSession(app, input.userId, input.body.sessionId))
          ?.id ?? null;
  if (input.body.sessionId && scopedSessionId == null) {
    throw new AppError(403, "session_mismatch", "Chat session scope is not valid for this user.");
  }

  const payloadBytes = Buffer.byteLength(JSON.stringify(input.body), "utf8");
  await app.db
    .insert(worldSignals)
    .values(
      input.body.signals.map((signal) => ({
        userId: input.userId,
        deviceId: ownedDevice.id,
        sessionId: scopedSessionId,
        clientRequestId: input.body.clientRequestId,
        signalId: signal.signalId,
        source: signal.source,
        kind: signal.kind,
        summary: signal.summary,
        confidenceBps: Math.max(0, Math.min(1000, Math.round(signal.confidence * 1000))),
        facts: signal.facts,
        privacy: signal.privacy,
        renderHints: signal.renderHints ?? {},
        visibility: signal.visibility ?? "assistant_internal_by_default",
        createdAt: new Date(signal.createdAt),
      })),
    )
    .onConflictDoNothing({
      target: [worldSignals.userId, worldSignals.signalId],
    });

  app.log.info(
    buildWorldSignalLogContext({
      accepted: true,
      reasonCode: "accepted",
      userId: input.userId,
      deviceId: ownedDevice.id,
      payloadBytes,
      signals: input.body.signals.map((signal) => ({
        kind: signal.kind,
        createdAt: signal.createdAt,
      })),
    }),
    "mobile world signal upload accepted",
  );

  return {
    ok: true,
    acceptedCount: input.body.signals.length,
    deviceId: ownedDevice.id,
    sessionId: scopedSessionId,
  };
}

export async function listFreshWorldSignals(
  app: FastifyInstance,
  input: {
    userId: string;
    deviceId?: string;
    sessionId?: string | null;
    limit?: number;
    maxAgeHours?: number;
  },
) {
  const rows = await app.db
    .select({
      signalId: worldSignals.signalId,
      source: worldSignals.source,
      kind: worldSignals.kind,
      summary: worldSignals.summary,
      confidenceBps: worldSignals.confidenceBps,
      facts: worldSignals.facts,
      privacy: worldSignals.privacy,
      renderHints: worldSignals.renderHints,
      visibility: worldSignals.visibility,
      createdAt: worldSignals.createdAt,
    })
    .from(worldSignals)
    .where(
      and(
        eq(worldSignals.userId, input.userId),
        input.deviceId ? eq(worldSignals.deviceId, input.deviceId) : undefined,
        input.sessionId ? eq(worldSignals.sessionId, input.sessionId) : undefined,
        gte(
          worldSignals.createdAt,
          new Date(Date.now() - 1000 * 60 * 60 * (input.maxAgeHours ?? 24)),
        ),
      ),
    )
    .orderBy(desc(worldSignals.createdAt))
    .limit(input.limit ?? 20);

  return rows.map((row) => ({
    signalId: row.signalId,
    source: row.source,
    kind: row.kind,
    summary: row.summary,
    confidence: row.confidenceBps / 1000,
    facts: row.facts,
    privacy: row.privacy,
    renderHints: row.renderHints,
    visibility: row.visibility,
    createdAt: row.createdAt,
  }));
}
