import { readFile } from "node:fs/promises";
import http2 from "node:http2";
import { and, eq, isNotNull } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { importPKCS8, SignJWT } from "jose";
import type { AppEnv } from "../../config/env.js";
import { devices } from "../../db/schema.js";
import { serviceUnavailable } from "../../lib/errors.js";
import type { DomainEvent, EventBus } from "../realtime/event-bus.js";

type MobilePushDeviceRow = {
  id: string;
  platform: string;
  label: string;
  clientMetadata: unknown;
};

export type MobilePushDeliveryResult = {
  attempted: number;
  delivered: number;
  skipped: number;
  failed: number;
  reasons: string[];
};

type ApplePushEnvironment = "sandbox" | "production";

function readString(value: unknown): string {
  return String(value ?? "").trim();
}

function readRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function sanitizePushProvider(value: unknown): string {
  return readString(value).toLowerCase();
}

function normalizePlatform(value: unknown): string {
  return readString(value).toLowerCase();
}

function splitLines(value: string): string[] {
  return value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function safeEventTopic(topic: string): string {
  return readString(topic).slice(0, 80);
}

function safeText(value: unknown, fallback: string): string {
  const text = readString(value);
  return text || fallback;
}

export function buildMobileNativePushReadiness(
  env: Pick<
    AppEnv,
    | "APPLE_TEAM_ID"
    | "APPLE_APP_BUNDLE_ID"
    | "APNS_KEY_ID"
    | "APNS_PRIVATE_KEY"
    | "APNS_PRIVATE_KEY_PATH"
    | "APNS_ENVIRONMENT"
  >,
) {
  const teamId = readString(env.APPLE_TEAM_ID);
  const bundleId = readString(env.APPLE_APP_BUNDLE_ID);
  const keyId = readString(env.APNS_KEY_ID);
  const privateKey = readString(env.APNS_PRIVATE_KEY);
  const privateKeyPath = readString(env.APNS_PRIVATE_KEY_PATH);
  const privateKeyConfigured = Boolean(privateKey || privateKeyPath);

  const missingEnv = [
    !teamId ? "APPLE_TEAM_ID" : null,
    !bundleId ? "APPLE_APP_BUNDLE_ID" : null,
    !keyId ? "APNS_KEY_ID" : null,
    !privateKeyConfigured ? "APNS_PRIVATE_KEY_OR_PATH" : null,
  ].filter((value): value is string => Boolean(value));

  const ready = missingEnv.length === 0;

  return {
    ready,
    status: ready ? ("ready" as const) : ("degraded" as const),
    environment: env.APNS_ENVIRONMENT,
    teamId,
    bundleId,
    keyIdConfigured: Boolean(keyId),
    privateKeyConfigured,
    topic: bundleId,
    missingEnv,
  };
}

export function buildAppleAppSiteAssociationPayload(
  env: Pick<AppEnv, "APPLE_TEAM_ID" | "APPLE_APP_BUNDLE_ID">,
) {
  const teamId = readString(env.APPLE_TEAM_ID);
  const bundleId = readString(env.APPLE_APP_BUNDLE_ID);
  const appId = teamId && bundleId ? `${teamId}.${bundleId}` : "";

  return {
    applinks: {
      apps: [],
      details: appId
        ? [
            {
              appID: appId,
              paths: ["*"],
            },
          ]
        : [],
    },
  };
}

export function buildAndroidAssetLinksPayload(
  env: Pick<AppEnv, "ANDROID_APP_LINK_PACKAGE_NAME" | "ANDROID_SHA256_CERT_FINGERPRINTS">,
) {
  const packageName = readString(env.ANDROID_APP_LINK_PACKAGE_NAME) || "com.elyan.elyanMobile";
  const fingerprints = splitLines(readString(env.ANDROID_SHA256_CERT_FINGERPRINTS));

  if (!packageName || fingerprints.length === 0) {
    return [] as Array<Record<string, unknown>>;
  }

  return [
    {
      relation: ["delegate_permission/common.handle_all_urls"],
      target: {
        namespace: "android_app",
        package_name: packageName,
        sha256_cert_fingerprints: fingerprints,
      },
    },
  ];
}

function buildPushMessage(event: DomainEvent): { title: string; body: string; silent: boolean } | null {
  const topic = safeEventTopic(event.topic);
  const payload = readRecord(event.payload);
  const task = readRecord(payload.task);
  const session = readRecord(payload.session);
  const title = safeText(task.title ?? session.title ?? payload.title, "Elyan");

  if (topic === "chat.message.created") {
    return {
      title: "Elyan",
      body: title !== "Elyan" ? `${title} için yeni yanıt hazır.` : "Yeni sohbet yanıtı hazır.",
      silent: false,
    };
  }

  if (topic === "chat.session.created") {
    return {
      title: "Elyan",
      body: title !== "Elyan" ? `${title} oluşturuldu.` : "Yeni sohbet oluşturuldu.",
      silent: false,
    };
  }

  if (topic === "chat.session.updated") {
    return {
      title: "Elyan",
      body: title !== "Elyan" ? `${title} güncellendi.` : "Sohbet güncellendi.",
      silent: false,
    };
  }

  if (topic === "task.created") {
    return {
      title: "Elyan",
      body: title !== "Elyan" ? `${title} oluşturuldu.` : "Yeni görev oluşturuldu.",
      silent: false,
    };
  }

  if (topic === "task.updated") {
    const status = readString(task.status ?? payload.status).toLowerCase();
    const label = title !== "Elyan" ? title : "Görev";
    const body =
      status === "completed"
        ? `${label} tamamlandı.`
        : status === "waiting_approval"
          ? `${label} onay bekliyor.`
          : status === "failed"
            ? `${label} başarısız oldu.`
            : `${label} güncellendi.`;
    return {
      title: "Elyan",
      body,
      silent: false,
    };
  }

  if (topic === "pair.session.claimed" || topic === "pair.session.activated") {
    return {
      title: "Elyan",
      body: "Desktop eşleştirmesi hazır.",
      silent: true,
    };
  }

  return null;
}

class ApplePushClient {
  private cachedPrivateKeySource = "";
  private cachedPrivateKeyPem = "";
  private cachedSigningKey: Awaited<ReturnType<typeof importPKCS8>> | null = null;
  private cachedJwt = "";
  private cachedJwtExpiresAt = 0;

  public constructor(private readonly env: AppEnv) {}

  public readiness() {
    return buildMobileNativePushReadiness(this.env);
  }

  private async resolvePrivateKeyPem(): Promise<string> {
    const keyValue = readString(this.env.APNS_PRIVATE_KEY);
    if (keyValue) {
      const normalized = keyValue.replace(/\\n/g, "\n");
      if (this.cachedPrivateKeySource === `inline:${normalized}` && this.cachedPrivateKeyPem) {
        return this.cachedPrivateKeyPem;
      }
      this.cachedPrivateKeySource = `inline:${normalized}`;
      this.cachedPrivateKeyPem = normalized;
      return normalized;
    }

    const keyPath = readString(this.env.APNS_PRIVATE_KEY_PATH);
    if (!keyPath) {
      return "";
    }

    if (this.cachedPrivateKeySource === `path:${keyPath}` && this.cachedPrivateKeyPem) {
      return this.cachedPrivateKeyPem;
    }

    const pem = await readFile(keyPath, "utf8");
    this.cachedPrivateKeySource = `path:${keyPath}`;
    this.cachedPrivateKeyPem = pem;
    return pem;
  }

  private async resolveSigningKey() {
    const pem = await this.resolvePrivateKeyPem();
    if (!pem) {
      return null;
    }
    if (this.cachedSigningKey) {
      return this.cachedSigningKey;
    }
    this.cachedSigningKey = await importPKCS8(pem, "ES256");
    return this.cachedSigningKey;
  }

  private async resolveAuthorizationJwt(): Promise<string> {
    const now = Date.now();
    if (this.cachedJwt && this.cachedJwtExpiresAt - now > 60_000) {
      return this.cachedJwt;
    }

    const teamId = readString(this.env.APPLE_TEAM_ID);
    const keyId = readString(this.env.APNS_KEY_ID);
    const signingKey = await this.resolveSigningKey();
    if (!teamId || !keyId || !signingKey) {
      throw serviceUnavailable("apns_config_missing");
    }

    const jwt = await new SignJWT({})
      .setProtectedHeader({ alg: "ES256", kid: keyId })
      .setIssuer(teamId)
      .setIssuedAt()
      .setExpirationTime("55m")
      .sign(signingKey);

    this.cachedJwt = jwt;
    this.cachedJwtExpiresAt = now + 55 * 60_000;
    return jwt;
  }

  public async sendNotification(input: {
    deviceToken: string;
    title: string;
    body: string;
    badge?: number;
    silent?: boolean;
    collapseId?: string;
    extra?: Record<string, unknown>;
  }): Promise<{
    ok: boolean;
    statusCode: number | null;
    reason: string | null;
    apnsId: string | null;
    errorCode: string | null;
  }> {
    const readiness = this.readiness();
    if (!readiness.ready) {
      return {
        ok: false,
        statusCode: null,
        reason: "apns_config_missing",
        apnsId: null,
        errorCode: "apns_config_missing",
      };
    }

    const deviceToken = readString(input.deviceToken);
    if (!deviceToken) {
      return {
        ok: false,
        statusCode: null,
        reason: "apns_device_token_missing",
        apnsId: null,
        errorCode: "apns_device_token_missing",
      };
    }

    const topic = readiness.topic;
    const jwt = await this.resolveAuthorizationJwt();
    const host = this.env.APNS_ENVIRONMENT === "production" ? "api.push.apple.com" : "api.sandbox.push.apple.com";
    const payload = {
      aps: input.silent
        ? { "content-available": 1 }
        : {
            alert: {
              title: input.title,
              body: input.body,
            },
            sound: "default",
            badge: input.badge,
          },
      elyan: input.extra ?? {},
    };

    return await new Promise((resolve) => {
      const client = http2.connect(`https://${host}`);
      let statusCode: number | null = null;
      let apnsId: string | null = null;
      let responseBody = "";
      let settled = false;
      const finish = (result: {
        ok: boolean;
        statusCode: number | null;
        reason: string | null;
        apnsId: string | null;
        errorCode: string | null;
      }) => {
        if (settled) {
          return;
        }
        settled = true;
        client.close();
        resolve(result);
      };

      client.on("error", () => {
        finish({
          ok: false,
          statusCode: null,
          reason: "apns_unreachable",
          apnsId: null,
          errorCode: "apns_unreachable",
        });
      });

      const request = client.request({
        ":method": "POST",
        ":path": `/3/device/${encodeURIComponent(deviceToken)}`,
        authorization: `bearer ${jwt}`,
        "apns-topic": topic,
        "apns-push-type": input.silent ? "background" : "alert",
        "apns-priority": input.silent ? "5" : "10",
        "apns-expiration": "0",
        ...(input.collapseId ? { "apns-collapse-id": input.collapseId.slice(0, 64) } : {}),
      });

      request.setEncoding("utf8");
      request.on("response", (headers) => {
        const headerStatus = headers[":status"];
        statusCode = typeof headerStatus === "number" ? headerStatus : null;
        const headerApnsId = headers["apns-id"];
        apnsId = typeof headerApnsId === "string" ? headerApnsId : null;
      });
      request.on("data", (chunk) => {
        responseBody += chunk;
      });
      request.on("error", () => {
        finish({
          ok: false,
          statusCode: statusCode ?? null,
          reason: "apns_unreachable",
          apnsId,
          errorCode: "apns_unreachable",
        });
      });
      request.on("end", () => {
        if ((statusCode ?? 0) >= 200 && (statusCode ?? 0) < 300) {
          finish({
            ok: true,
            statusCode,
            reason: null,
            apnsId,
            errorCode: null,
          });
          return;
        }

        let reason = responseBody.trim() || "apns_request_failed";
        try {
          const parsed = JSON.parse(responseBody) as { reason?: string };
          if (parsed && typeof parsed.reason === "string" && parsed.reason.trim()) {
            reason = parsed.reason.trim();
          }
        } catch {
          // ignore parse failures; the raw body is not surfaced
        }

        finish({
          ok: false,
          statusCode,
          reason,
          apnsId,
          errorCode: mapApnsErrorCode(reason),
        });
      });

      request.end(JSON.stringify(payload));
    });
  }
}

function mapApnsErrorCode(reason: string): string {
  const normalized = readString(reason).toLowerCase();
  switch (normalized) {
    case "baddevicetoken":
      return "apns_bad_device_token";
    case "unregistered":
      return "apns_unregistered";
    case "payloadtoolarge":
      return "apns_payload_too_large";
    case "toomanyrequests":
      return "apns_rate_limited";
    case "topicdisallowed":
      return "apns_topic_disallowed";
    case "badcertificateenvironment":
      return "apns_bad_certificate_environment";
    case "badpath":
      return "apns_bad_path";
    case "methodnotallowed":
      return "apns_method_not_allowed";
    case "serviceunavailable":
      return "apns_service_unavailable";
    case "internalservererror":
      return "apns_internal_error";
    case "badtoken":
      return "apns_bad_token";
    default:
      return "apns_request_failed";
  }
}

export class MobilePushDispatcher {
  private unsubscribe: (() => void) | null = null;

  public constructor(
    private readonly app: FastifyInstance,
    private readonly client: ApplePushClient = new ApplePushClient(app.config),
  ) {}

  public start(eventBus: EventBus): void {
    if (this.unsubscribe) {
      return;
    }

    this.unsubscribe = eventBus.subscribe("event", (event: DomainEvent) => {
      void this.handleDomainEvent(event).catch((error) => {
        this.app.log.warn(
          {
            error: error instanceof Error ? error.message : String(error),
            topic: event.topic,
          },
          "mobile push dispatch failed",
        );
      });
    });
  }

  public close(): void {
    this.unsubscribe?.();
    this.unsubscribe = null;
  }

  public status() {
    const readiness = this.client.readiness();
    return {
      provider: "apns",
      ...readiness,
    };
  }

  public async handleDomainEvent(event: DomainEvent): Promise<MobilePushDeliveryResult> {
    const message = buildPushMessage(event);
    if (!message || !event.userId) {
      return {
        attempted: 0,
        delivered: 0,
        skipped: 0,
        failed: 0,
        reasons: message ? ["missing_user"] : ["unhandled_topic"],
      };
    }

    const rows = await this.app.db
      .select({
        id: devices.id,
        platform: devices.platform,
        label: devices.label,
        clientMetadata: devices.clientMetadata,
      })
      .from(devices)
      .where(
        and(
          eq(devices.userId, event.userId),
          eq(devices.type, "mobile"),
          eq(devices.isActive, true),
          isNotNull(devices.clientMetadata),
        ),
      );

    let attempted = 0;
    let delivered = 0;
    let skipped = 0;
    let failed = 0;
    const reasons = new Set<string>();

    for (const row of rows as MobilePushDeviceRow[]) {
      const metadata = readRecord(row.clientMetadata);
      const pushToken = readString(metadata.pushToken);
      const pushProvider = sanitizePushProvider(metadata.pushProvider) || "apns";
      const platform = normalizePlatform(row.platform);
      if (!pushToken) {
        skipped += 1;
        reasons.add("missing_push_token");
        continue;
      }
      if (pushProvider !== "apns") {
        skipped += 1;
        reasons.add("unsupported_push_provider");
        continue;
      }
      if (platform && !platform.includes("ios") && platform !== "iphoneos" && platform !== "ipados") {
        skipped += 1;
        reasons.add("unsupported_platform");
        continue;
      }

      attempted += 1;
      const result = await this.client.sendNotification({
        deviceToken: pushToken,
        title: message.title,
        body: message.body,
        silent: message.silent,
        extra: {
          topic: event.topic,
          userId: event.userId,
          deviceId: event.deviceId ?? null,
          taskId: event.taskId ?? null,
          sourceDeviceId: row.id,
        },
      });

      if (result.ok) {
        delivered += 1;
        continue;
      }

      failed += 1;
      if (result.errorCode) {
        reasons.add(result.errorCode);
      }
      if (result.reason) {
        reasons.add(result.reason);
      }
    }

    return {
      attempted,
      delivered,
      skipped,
      failed,
      reasons: [...reasons],
    };
  }
}

export function createMobilePushDispatcher(app: FastifyInstance) {
  return new MobilePushDispatcher(app);
}

