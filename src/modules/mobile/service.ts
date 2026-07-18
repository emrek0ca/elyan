import { and, desc, eq, gte, isNull, lte, or, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import {
  chatSessions,
  devices,
  learningEvents,
  tasks,
  users,
  worldSignals,
} from "../../db/schema.js";
import { AppError } from "../../lib/errors.js";
import {
  getBillingSummary,
  shapePublicUsageSnapshot,
} from "../billing/service.js";
import { shapeSubscriptionTruth } from "../billing/subscription-truth.js";
import { getBrainProfile, shapePublicBrainProfile } from "../brain/service.js";
import { listUserDevices, pruneStaleDevices } from "../devices/service.js";
import { getTrialQuotaPolicy } from "../quota/service.js";
import type { UploadWorldSignalsBody } from "./schemas.js";
import {
  deriveLearningSignalsFromWorldSignals,
  toDerivedSignalInput,
} from "../../core/understanding/world-signal-derived.js";
import { filterLearningSignals } from "../../core/understanding/personalization-policy.js";
import {
  sanitizeInboundContextRecord,
  sanitizeInboundContextText,
} from "../../lib/context-text-sanitizer.js";
import { getWorldSignalTtlHours } from "../../core/understanding/context-packets.js";

const MAX_WORLD_SIGNAL_PAYLOAD_BYTES = 24 * 1024;
const MAX_WORLD_SIGNAL_FUTURE_SKEW_MS = 5 * 60_000;
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
const BLOCKED_KEY_FRAGMENT_PATTERNS = [
  /(?:^|raw)(?:image|audio|video|file|binary|bytes|payload|sample|content)/u,
  /(?:image|audio|video|file|binary|bytes|payload|sample|content)(?:raw|base64|bytes|blob|data)$/u,
  /(?:access|auth|bearer|refresh|session|id)?token$/u,
  /(?:password|passwd|secret|credential|privatekey)$/u,
  /(?:stacktrace|debugpayload|providerresponse|reasoningtrace)$/u,
];
const DATA_URI_PATTERN = /^data:(?:image|audio|video|application)\/[a-z0-9.+-]+;base64,/iu;
const BASE64_LIKE_PATTERN = /^[A-Za-z0-9+/]{512,}={0,2}$/u;

function normalizeKey(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

function isBlockedWorldSignalKey(normalizedKey: string): boolean {
  return (
    BLOCKED_SECRET_KEYS.has(normalizedKey) ||
    BLOCKED_BINARY_KEYS.has(normalizedKey) ||
    BLOCKED_PRECISE_LOCATION_KEYS.has(normalizedKey) ||
    BLOCKED_HEALTH_KEYS.has(normalizedKey) ||
    BLOCKED_CALENDAR_KEYS.has(normalizedKey) ||
    BLOCKED_DEBUG_KEYS.has(normalizedKey) ||
    BLOCKED_KEY_FRAGMENT_PATTERNS.some((pattern) => pattern.test(normalizedKey))
  );
}

function looksLikeLocalPath(value: string) {
  return (
    value.startsWith("/") ||
    value.startsWith("file://") ||
    value.startsWith("~/") ||
    /^[A-Za-z]:\\/.test(value)
  );
}

function looksLikeRawEncodedPayload(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed) {
    return false;
  }
  if (DATA_URI_PATTERN.test(trimmed)) {
    return true;
  }
  const compact = trimmed.replace(/\s+/g, "");
  return compact.length > 768 && BASE64_LIKE_PATTERN.test(compact);
}

function assertWorldSignalValueSafe(value: unknown, key = ""): void {
  if (value == null) {
    return;
  }
  if (typeof value === "string") {
    if (looksLikeLocalPath(value.trim())) {
      throw new AppError(
        422,
        "local_path_blocked",
        "Local file paths cannot be uploaded.",
      );
    }
    if (looksLikeRawEncodedPayload(value)) {
      throw new AppError(
        422,
        "raw_payload_blocked",
        "Raw private content cannot be uploaded.",
      );
    }
    return;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return;
  }
  if (Array.isArray(value)) {
    if (value.length > 16) {
      throw new AppError(
        413,
        "payload_too_large",
        "World signal list payload is too large.",
      );
    }
    for (const item of value) {
      assertWorldSignalValueSafe(item, key);
    }
    return;
  }
  if (typeof value === "object") {
    for (const [entryKey, entryValue] of Object.entries(value)) {
      const normalizedKey = normalizeKey(entryKey);
      if (isBlockedWorldSignalKey(normalizedKey)) {
        if (BLOCKED_SECRET_KEYS.has(normalizedKey)) {
          throw new AppError(
            422,
            "secret_blocked",
            "Secrets cannot be uploaded.",
          );
        }
        if (BLOCKED_PRECISE_LOCATION_KEYS.has(normalizedKey)) {
          throw new AppError(
            422,
            "precise_location_blocked",
            "Precise coordinates cannot be uploaded.",
          );
        }
        if (BLOCKED_HEALTH_KEYS.has(normalizedKey)) {
          throw new AppError(
            422,
            "raw_health_blocked",
            "Raw health values cannot be uploaded.",
          );
        }
        if (BLOCKED_CALENDAR_KEYS.has(normalizedKey)) {
          throw new AppError(
            422,
            "raw_calendar_blocked",
            "Raw calendar fields cannot be uploaded.",
          );
        }
        if (BLOCKED_DEBUG_KEYS.has(normalizedKey)) {
          throw new AppError(
            422,
            "debug_payload_blocked",
            "Debug or reasoning payloads cannot be uploaded.",
          );
        }
        throw new AppError(
          422,
          "raw_payload_blocked",
          "Raw private content cannot be uploaded.",
        );
      }
      assertWorldSignalValueSafe(entryValue, normalizedKey);
    }
  }
}

function sanitizeStoredWorldSignalRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? sanitizeInboundContextRecord(value as Record<string, unknown>, {
        maxDepth: 2,
        maxStringLength: 160,
      })
    : {};
}

export function assertSafeWorldSignalPayload(body: UploadWorldSignalsBody) {
  const payloadBytes = Buffer.byteLength(JSON.stringify(body), "utf8");
  if (payloadBytes > MAX_WORLD_SIGNAL_PAYLOAD_BYTES) {
    throw new AppError(
      413,
      "payload_too_large",
      "World signal payload exceeds the size limit.",
    );
  }

  for (const signal of body.signals) {
    const rawDataUploaded =
      signal.privacy.rawDataUploaded === undefined
        ? false
        : Boolean(signal.privacy.rawDataUploaded);
    if (rawDataUploaded) {
      throw new AppError(
        422,
        "raw_payload_blocked",
        "Raw world data cannot be uploaded.",
      );
    }
    if (
      signal.privacy.rawFileUploaded === true ||
      signal.privacy.rawImageUploaded === true ||
      signal.privacy.rawAudioUploaded === true
    ) {
      throw new AppError(
        422,
        "raw_payload_blocked",
        "Raw world data cannot be uploaded.",
      );
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
  pruneStaleDevices(app, userId).catch(() => undefined);
  const [userRows, devices, pendingCounts, billing, brain] = await Promise.all([
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
    throw new AppError(
      403,
      "device_revoked",
      "Mobile device scope is not valid for this user.",
    );
  }

  const scopedSession =
    input.body.sessionId == null
      ? null
      : await resolveOwnedChatSession(app, input.userId, input.body.sessionId);
  if (input.body.sessionId != null && !scopedSession) {
    throw new AppError(
      403,
      "session_scope_invalid",
      "World signal session scope is not valid for this user.",
    );
  }
  const scopedSessionId = scopedSession?.id ?? null;

  // Resolve device/session ownership before validating observation details so
  // an unauthorized scope always fails closed at the authorization boundary.
  const ingestNow = new Date();
  for (const signal of input.body.signals) {
    const observedAt = new Date(signal.createdAt);
    if (
      !Number.isFinite(observedAt.getTime()) ||
      observedAt.getTime() - ingestNow.getTime() > MAX_WORLD_SIGNAL_FUTURE_SKEW_MS
    ) {
      throw new AppError(
        422,
        "invalid_signal_time",
        "World signal observation time is not valid.",
      );
    }
  }

  const payloadBytes = Buffer.byteLength(JSON.stringify(input.body), "utf8");
  // GÜVENLİK ÇEKİRDEĞİ: summary + string fact değerleri buradan sonra memory
  // fact'lerine, context packet'lerine ve SİSTEM PROMPT'una akar. Tek arınma
  // noktası burasıdır — prompt-injection kalıpları, rol etiketleri, model
  // kontrol tokenleri ve zero-width karakterler girişte etkisizleştirilir;
  // downstream her zaman temiz metinle çalışır.
  const sanitizedSignals = [
    ...new Map(
      input.body.signals.map((signal) => [
        signal.signalId,
        {
          ...signal,
          summary: sanitizeInboundContextText(signal.summary, 480).text,
          facts: sanitizeInboundContextRecord(signal.facts),
          privacy: sanitizeInboundContextRecord(signal.privacy),
          renderHints: signal.renderHints
            ? sanitizeInboundContextRecord(signal.renderHints)
            : undefined,
          createdAt: new Date(signal.createdAt),
        },
      ]),
    ).values(),
  ];

  const insertedSignals = await app.db
    .insert(worldSignals)
    .values(
      sanitizedSignals.map((signal) => ({
        userId: input.userId,
        deviceId: ownedDevice.id,
        sessionId: scopedSessionId,
        clientRequestId: input.body.clientRequestId,
        signalId: signal.signalId,
        source: signal.source,
        kind: signal.kind,
        summary: signal.summary,
        confidenceBps: Math.max(
          0,
          Math.min(1000, Math.round(signal.confidence * 1000)),
        ),
        facts: signal.facts,
        privacy: signal.privacy,
        renderHints: signal.renderHints ?? {},
        visibility: signal.visibility ?? "assistant_internal_by_default",
        createdAt: signal.createdAt,
      })),
    )
    .onConflictDoNothing({
      target: [worldSignals.userId, worldSignals.signalId],
    })
    .returning({ signalId: worldSignals.signalId });
  const insertedSignalIds = new Set(insertedSignals.map((row) => row.signalId));
  const newlyStoredSignals = sanitizedSignals.filter((signal) =>
    insertedSignalIds.has(signal.signalId),
  );

  const derivedLearningSignals = filterLearningSignals(
    deriveLearningSignalsFromWorldSignals(
      newlyStoredSignals.map((signal) =>
        toDerivedSignalInput({
          signalId: signal.signalId,
          kind: signal.kind,
          summary: signal.summary,
          confidence: signal.confidence,
          facts: signal.facts,
          privacy: signal.privacy,
          createdAt: signal.createdAt,
        }),
      ),
    ),
  );
  const observedAtBySignalId = new Map(
    newlyStoredSignals.map((signal) => [signal.signalId, signal.createdAt]),
  );
  const liveDerivedLearningSignals = derivedLearningSignals.filter((signal) => {
    const signalId = String(signal.metadata?.signalId ?? "");
    const observedAt = observedAtBySignalId.get(signalId);
    if (!observedAt || !signal.ttlDays) return true;
    return observedAt.getTime() + signal.ttlDays * 86_400_000 > ingestNow.getTime();
  });

  if (liveDerivedLearningSignals.length > 0) {
    await app.db.insert(learningEvents).values(
      liveDerivedLearningSignals.map((signal) => {
        const signalId = String(signal.metadata?.signalId ?? "");
        const observedAt = observedAtBySignalId.get(signalId) ?? ingestNow;
        return {
          userId: input.userId,
          accountId: input.userId,
          taskId: scopedSessionId ? null : null,
          type: signal.type,
          key: signal.key,
          value: signal.value,
          confidence: Math.round(signal.confidence * 100),
          scope: signal.scope,
          source: signal.source,
          privacyLevel: "safe",
          metadata: {
            ...signal.metadata,
            clientRequestId: input.body.clientRequestId,
            sessionId: scopedSessionId,
            trainingEligible: false,
          },
          expiresAt: signal.ttlDays
            ? new Date(observedAt.getTime() + signal.ttlDays * 86_400_000)
            : null,
        };
      }),
    );
  }

  if (insertedSignalIds.size > 0) {
    const cacheStore = app.services?.reliability?.store;
    await Promise.all([
      cacheStore?.del(`understanding:world:${input.userId}`),
      cacheStore?.del(`understanding:world:${input.userId}:global`),
      ...(scopedSessionId
        ? [cacheStore?.del(`understanding:world:${input.userId}:${scopedSessionId}`)]
        : []),
    ]).catch(() => undefined);
  }

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
    storedCount: insertedSignalIds.size,
    dedupedCount: input.body.signals.length - insertedSignalIds.size,
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
    includeUnscopedSession?: boolean;
    limit?: number;
    maxAgeHours?: number;
  },
) {
  const now = new Date();
  const maxAgeHours = input.maxAgeHours ?? 24;
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
        input.sessionId
          ? input.includeUnscopedSession
            ? or(
                isNull(worldSignals.sessionId),
                eq(worldSignals.sessionId, input.sessionId),
              )
            : eq(worldSignals.sessionId, input.sessionId)
          : undefined,
        gte(
          worldSignals.createdAt,
          new Date(now.getTime() - 1000 * 60 * 60 * maxAgeHours),
        ),
        lte(
          worldSignals.createdAt,
          new Date(now.getTime() + MAX_WORLD_SIGNAL_FUTURE_SKEW_MS),
        ),
      ),
    )
    .orderBy(desc(worldSignals.createdAt))
    .limit(input.limit ?? 20);

  return rows
    .filter((row) => {
      const ttlHours = Math.min(maxAgeHours, getWorldSignalTtlHours(row.kind));
      const ageHours = Math.max(0, now.getTime() - row.createdAt.getTime()) / 3_600_000;
      return Number.isFinite(ageHours) && ageHours <= ttlHours;
    })
    .map((row) => ({
      signalId: row.signalId,
      source: row.source,
      kind: row.kind,
      summary: sanitizeInboundContextText(row.summary, 480).text,
      confidence: row.confidenceBps / 1000,
      facts: sanitizeStoredWorldSignalRecord(row.facts),
      privacy: sanitizeStoredWorldSignalRecord(row.privacy),
      renderHints: sanitizeStoredWorldSignalRecord(row.renderHints),
      visibility: row.visibility,
      createdAt: row.createdAt,
    }));
}
