import { and, eq, isNotNull, isNull, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { devices } from "../../db/schema.js";
import { isUndefinedColumnError } from "../devices/service.js";
import { ApplePushClient } from "../mobile/push.js";
import {
  type FcmCredentials,
  readFcmCredentials,
  sendFcmMessage,
} from "./fcm-client.js";

/**
 * Addressed push for Elyan-initiated messages.
 *
 * This sits next to the existing event-bus dispatcher in `modules/mobile/push`
 * rather than replacing it — they answer different questions. That one reacts
 * to domain events ("a task finished"); this one is called directly when Elyan
 * decides to speak, and needs to reach *every* platform rather than only iOS.
 *
 * Transport is chosen per device, matching what the client registered:
 *   - iOS/macOS → APNs directly, through the same `ApplePushClient`.
 *   - everything else → FCM HTTP v1.
 *
 * Two invariants:
 *
 * 1. **Push is a notification, never a copy of the content.** The body carries
 *    a short preview and the ids needed to open the right screen; the message
 *    itself stays in the database behind auth. World signals, connector data
 *    and anything else sensitive must not transit Apple/Google infrastructure
 *    or land on a lock screen.
 * 2. **Failing to notify is never fatal.** The message is already persisted
 *    and streamed; a dead token or missing credential downgrades the outcome,
 *    it does not throw.
 */

export const PUSH_TITLE_MAX = 60;
export const PUSH_BODY_MAX = 160;
const DATA_VALUE_MAX = 200;
const MAX_TARGETS_PER_SEND = 8;

export type PushTransport = "apns" | "fcm";

export type PushTarget = {
  deviceId: string;
  token: string;
  transport: PushTransport;
};

export type PushSendResult = {
  status: "sent" | "skipped" | "no_target" | "failed";
  reason?: string;
  delivered: number;
  invalidated: number;
  attempted: number;
};

export type PushRequest = {
  userId: string;
  /** Notification channel/category, e.g. `proactive.follow_up`. */
  kind: string;
  title: string;
  body: string;
  /** Ids only. Values are stringified and truncated; never put content here. */
  data?: Record<string, string | number | null | undefined>;
  /** A newer push with the same key replaces the older one on the device. */
  collapseKey?: string;
  silent?: boolean;
};

function truncate(value: string, max: number): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= max) return normalized;
  return `${normalized.slice(0, max - 1).trimEnd()}…`;
}

export function sanitizePushData(
  input: PushRequest["data"],
  kind: string,
): Record<string, string> {
  const out: Record<string, string> = { kind: truncate(kind, 40) };
  for (const [key, value] of Object.entries(input ?? {})) {
    if (value == null) continue;
    const stringified = typeof value === "string" ? value : String(value);
    const trimmed = stringified.trim();
    if (!trimmed) continue;
    out[key.slice(0, 40)] = truncate(trimmed, DATA_VALUE_MAX);
  }
  return out;
}

/**
 * Which transport a device row implies. The registered provider is
 * authoritative when present, because it describes the token we actually
 * hold; platform is only the fallback for older rows.
 */
export function resolvePushTransport(input: {
  provider?: string | null;
  platform?: string | null;
}): PushTransport {
  const provider = String(input.provider ?? "").trim().toLowerCase();
  if (provider === "apns") return "apns";
  if (provider === "fcm") return "fcm";
  const platform = String(input.platform ?? "").trim().toLowerCase();
  return platform.includes("ios") || platform.includes("mac") ? "apns" : "fcm";
}

export function resolveFcmCredentials(
  app: FastifyInstance,
): FcmCredentials | null {
  if (app.config?.ELYAN_PUSH_ENABLED === false) {
    return null;
  }
  return readFcmCredentials(app.config ?? {});
}

/**
 * Devices that can receive a push right now. Falls back to the legacy
 * `client_metadata.pushToken` location when the 0048 migration has not been
 * applied yet, so a lagging schema degrades to "still works" rather than
 * "throws on every proactive fire".
 */
export async function listPushTargets(
  app: FastifyInstance,
  userId: string,
): Promise<PushTarget[]> {
  try {
    const rows = await app.db
      .select({
        deviceId: devices.id,
        token: devices.pushToken,
        provider: devices.pushProvider,
        platform: devices.platform,
      })
      .from(devices)
      .where(
        and(
          eq(devices.userId, userId),
          eq(devices.isActive, true),
          isNotNull(devices.pushToken),
          isNull(devices.pushInvalidatedAt),
        ),
      )
      .limit(MAX_TARGETS_PER_SEND);
    return rows
      .filter((row) => Boolean(row.token))
      .map((row) => ({
        deviceId: row.deviceId,
        token: row.token as string,
        transport: resolvePushTransport(row),
      }));
  } catch (error) {
    if (!isUndefinedColumnError(error)) {
      throw error;
    }
    app.log?.warn?.(
      "devices.push_token migration missing; falling back to client_metadata",
    );
    const legacy = await app.db
      .select({
        deviceId: devices.id,
        token: sql<string | null>`${devices.clientMetadata} ->> 'pushToken'`,
        provider: sql<string | null>`${devices.clientMetadata} ->> 'pushProvider'`,
        platform: devices.platform,
      })
      .from(devices)
      .where(and(eq(devices.userId, userId), eq(devices.isActive, true)))
      .limit(MAX_TARGETS_PER_SEND);
    return legacy
      .filter((row) => Boolean(row.token))
      .map((row) => ({
        deviceId: row.deviceId,
        token: row.token as string,
        transport: resolvePushTransport(row),
      }));
  }
}

/**
 * A token the provider rejected as dead. Kept (not nulled) with a timestamp so
 * re-registration from the same install can clear it, and so "never had push"
 * stays distinguishable from "push broke".
 */
export async function markPushTokenInvalid(
  app: FastifyInstance,
  deviceId: string,
  now = new Date(),
): Promise<void> {
  try {
    await app.db
      .update(devices)
      .set({ pushInvalidatedAt: now, updatedAt: now })
      .where(eq(devices.id, deviceId));
  } catch (error) {
    if (!isUndefinedColumnError(error)) {
      throw error;
    }
  }
}

/** APNs status codes that mean the token is gone for good. */
const APNS_DEAD_TOKEN_CODES = new Set([
  "apns_bad_token",
  "apns_unregistered",
  "apns_device_token_missing",
]);

type DeliveryOutcome =
  | { kind: "sent" }
  | { kind: "invalid_token"; reason: string }
  | { kind: "failed"; reason: string };

async function deliverToTarget(
  target: PushTarget,
  message: {
    title: string;
    body: string;
    data: Record<string, string>;
    collapseKey?: string;
    silent?: boolean;
  },
  transports: { apple: ApplePushClient | null; fcm: FcmCredentials | null },
): Promise<DeliveryOutcome> {
  if (target.transport === "apns") {
    if (!transports.apple) {
      return { kind: "failed", reason: "apns_not_configured" };
    }
    const result = await transports.apple.sendNotification({
      deviceToken: target.token,
      title: message.title,
      body: message.body,
      silent: message.silent,
      collapseId: message.collapseKey,
      extra: message.data,
    });
    if (result.ok) return { kind: "sent" };
    const code = result.errorCode ?? result.reason ?? "apns_request_failed";
    return APNS_DEAD_TOKEN_CODES.has(code)
      ? { kind: "invalid_token", reason: code }
      : { kind: "failed", reason: code };
  }

  if (!transports.fcm) {
    return { kind: "failed", reason: "fcm_not_configured" };
  }
  const outcome = await sendFcmMessage(transports.fcm, {
    token: target.token,
    title: message.title,
    body: message.body,
    data: message.data,
    androidChannelId: "elyan_proactive",
    collapseKey: message.collapseKey,
    silent: message.silent,
  });
  if (outcome.status === "sent") return { kind: "sent" };
  return outcome.status === "invalid_token"
    ? { kind: "invalid_token", reason: outcome.reason }
    : { kind: "failed", reason: outcome.reason };
}

export async function sendUserPush(
  app: FastifyInstance,
  request: PushRequest,
): Promise<PushSendResult> {
  const empty: PushSendResult = {
    status: "skipped",
    delivered: 0,
    invalidated: 0,
    attempted: 0,
  };

  if (app.config?.ELYAN_PUSH_ENABLED === false) {
    return { ...empty, reason: "push_disabled" };
  }

  const title = truncate(request.title, PUSH_TITLE_MAX);
  const body = truncate(request.body, PUSH_BODY_MAX);
  if (!title && !body) {
    return { ...empty, reason: "empty_notification" };
  }

  let targets: PushTarget[];
  try {
    targets = await listPushTargets(app, request.userId);
  } catch (error) {
    app.log?.error?.({ error }, "push target lookup failed");
    return { ...empty, status: "failed", reason: "target_lookup_failed" };
  }

  if (targets.length === 0) {
    return { ...empty, status: "no_target", reason: "no_push_target" };
  }

  const appleClient = targets.some((target) => target.transport === "apns")
    ? new ApplePushClient(app.config)
    : null;
  const fcmCredentials = targets.some((target) => target.transport === "fcm")
    ? resolveFcmCredentials(app)
    : null;
  if (!appleClient && !fcmCredentials) {
    return { ...empty, reason: "push_not_configured" };
  }

  const data = sanitizePushData(request.data, request.kind);
  const message = {
    title,
    body,
    data,
    collapseKey: request.collapseKey,
    silent: request.silent,
  };

  let delivered = 0;
  let invalidated = 0;
  let lastFailure: string | undefined;

  for (const target of targets) {
    const outcome = await deliverToTarget(target, message, {
      apple: appleClient,
      fcm: fcmCredentials,
    }).catch((error): DeliveryOutcome => {
      app.log?.debug?.({ error, deviceId: target.deviceId }, "push send threw");
      return { kind: "failed", reason: "sender_threw" };
    });

    if (outcome.kind === "sent") {
      delivered += 1;
      continue;
    }
    if (outcome.kind === "invalid_token") {
      invalidated += 1;
      await markPushTokenInvalid(app, target.deviceId).catch(() => undefined);
      continue;
    }
    lastFailure = outcome.reason;
    app.log?.warn?.(
      {
        deviceId: target.deviceId,
        transport: target.transport,
        reason: outcome.reason,
      },
      "push delivery failed",
    );
  }

  if (delivered > 0) {
    return { status: "sent", delivered, invalidated, attempted: targets.length };
  }

  return {
    status: "failed",
    reason: lastFailure ?? (invalidated > 0 ? "all_tokens_invalid" : "delivery_failed"),
    delivered,
    invalidated,
    attempted: targets.length,
  };
}
