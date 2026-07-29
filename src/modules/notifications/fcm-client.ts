import { createSign } from "node:crypto";

/**
 * Minimal FCM HTTP v1 client.
 *
 * Deliberately dependency-free: the whole surface we need is one OAuth2
 * service-account exchange plus one POST. Pulling `firebase-admin` in would
 * add a large transitive tree for that.
 */

const GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";
const FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging";
const TOKEN_SKEW_MS = 60_000;
const REQUEST_TIMEOUT_MS = 10_000;

export type FcmCredentials = {
  projectId: string;
  clientEmail: string;
  privateKey: string;
};

export type FcmSendOutcome =
  | { status: "sent"; name: string }
  | { status: "invalid_token"; reason: string }
  | { status: "failed"; reason: string; retryable: boolean };

export type FcmMessage = {
  token: string;
  title: string;
  body: string;
  /** Flat string map — FCM rejects nested values. */
  data?: Record<string, string>;
  /** Android notification channel; must match the channel the app creates. */
  androidChannelId?: string;
  collapseKey?: string;
  /** Delivered silently (no banner) — used for state sync, not for nudges. */
  silent?: boolean;
};

type CachedToken = { value: string; expiresAtMs: number };

const tokenCache = new Map<string, CachedToken>();

function base64Url(input: Buffer | string): string {
  return Buffer.from(input)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * Env-supplied private keys usually arrive with literal `\n` sequences because
 * dotenv does not interpret escapes inside quoted values.
 */
export function normalizePrivateKey(raw: string): string {
  const unescaped = raw.includes("\\n") ? raw.replace(/\\n/g, "\n") : raw;
  return unescaped.trim();
}

export function readFcmCredentials(config: {
  FCM_PROJECT_ID?: string;
  FCM_CLIENT_EMAIL?: string;
  FCM_PRIVATE_KEY?: string;
}): FcmCredentials | null {
  const projectId = config.FCM_PROJECT_ID?.trim();
  const clientEmail = config.FCM_CLIENT_EMAIL?.trim();
  const privateKeyRaw = config.FCM_PRIVATE_KEY?.trim();
  if (!projectId || !clientEmail || !privateKeyRaw) {
    return null;
  }
  const privateKey = normalizePrivateKey(privateKeyRaw);
  if (!privateKey.includes("BEGIN") || !privateKey.includes("PRIVATE KEY")) {
    return null;
  }
  return { projectId, clientEmail, privateKey };
}

function signServiceAccountAssertion(
  credentials: FcmCredentials,
  nowMs: number,
): string {
  const issuedAt = Math.floor(nowMs / 1000);
  const header = base64Url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const claims = base64Url(
    JSON.stringify({
      iss: credentials.clientEmail,
      scope: FCM_SCOPE,
      aud: GOOGLE_TOKEN_URL,
      iat: issuedAt,
      exp: issuedAt + 3600,
    }),
  );
  const signingInput = `${header}.${claims}`;
  const signer = createSign("RSA-SHA256");
  signer.update(signingInput);
  signer.end();
  const signature = base64Url(signer.sign(credentials.privateKey));
  return `${signingInput}.${signature}`;
}

export async function getFcmAccessToken(
  credentials: FcmCredentials,
  options: { now?: number; fetchImpl?: typeof fetch } = {},
): Promise<string | null> {
  const now = options.now ?? Date.now();
  const cached = tokenCache.get(credentials.clientEmail);
  if (cached && cached.expiresAtMs - TOKEN_SKEW_MS > now) {
    return cached.value;
  }

  const fetchImpl = options.fetchImpl ?? fetch;
  let assertion: string;
  try {
    assertion = signServiceAccountAssertion(credentials, now);
  } catch {
    // A malformed key must not take the caller down; push is best-effort.
    return null;
  }

  const response = await fetchImpl(GOOGLE_TOKEN_URL, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion,
    }).toString(),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  }).catch(() => null);

  if (!response || !response.ok) {
    return null;
  }

  const payload = (await response.json().catch(() => null)) as
    | { access_token?: unknown; expires_in?: unknown }
    | null;
  const accessToken =
    typeof payload?.access_token === "string" ? payload.access_token : null;
  if (!accessToken) {
    return null;
  }
  const expiresInSeconds =
    typeof payload?.expires_in === "number" && payload.expires_in > 0
      ? payload.expires_in
      : 3600;
  tokenCache.set(credentials.clientEmail, {
    value: accessToken,
    expiresAtMs: now + expiresInSeconds * 1000,
  });
  return accessToken;
}

/** Test seam — the module-level cache would otherwise leak between cases. */
export function clearFcmTokenCache(): void {
  tokenCache.clear();
}

export function buildFcmPayload(message: FcmMessage): Record<string, unknown> {
  const data: Record<string, string> = { ...(message.data ?? {}) };
  const payload: Record<string, unknown> = {
    token: message.token,
    data,
    android: {
      priority: message.silent ? "NORMAL" : "HIGH",
      ...(message.collapseKey ? { collapse_key: message.collapseKey } : {}),
      ...(message.silent
        ? {}
        : {
            notification: {
              title: message.title,
              body: message.body,
              ...(message.androidChannelId
                ? { channel_id: message.androidChannelId }
                : {}),
            },
          }),
    },
    apns: {
      headers: {
        "apns-priority": message.silent ? "5" : "10",
        ...(message.collapseKey ? { "apns-collapse-id": message.collapseKey } : {}),
      },
      payload: {
        aps: message.silent
          ? { "content-available": 1 }
          : {
              alert: { title: message.title, body: message.body },
              sound: "default",
              "content-available": 1,
            },
      },
    },
  };
  if (!message.silent) {
    payload.notification = { title: message.title, body: message.body };
  }
  return { message: payload };
}

/**
 * FCM reports a dead registration through these codes; anything else is a
 * transport or quota problem and the token must be kept.
 */
function classifyFcmError(status: number, bodyText: string): FcmSendOutcome {
  const normalized = bodyText.slice(0, 400);
  if (
    status === 404 ||
    /UNREGISTERED|INVALID_ARGUMENT.*registration|registration-token-not-registered/i.test(
      bodyText,
    )
  ) {
    return { status: "invalid_token", reason: normalized || `http_${status}` };
  }
  const retryable = status === 429 || status >= 500;
  return { status: "failed", reason: normalized || `http_${status}`, retryable };
}

export async function sendFcmMessage(
  credentials: FcmCredentials,
  message: FcmMessage,
  options: { fetchImpl?: typeof fetch; now?: number } = {},
): Promise<FcmSendOutcome> {
  const accessToken = await getFcmAccessToken(credentials, options);
  if (!accessToken) {
    return { status: "failed", reason: "oauth_token_unavailable", retryable: true };
  }

  const fetchImpl = options.fetchImpl ?? fetch;
  const response = await fetchImpl(
    `https://fcm.googleapis.com/v1/projects/${encodeURIComponent(credentials.projectId)}/messages:send`,
    {
      method: "POST",
      headers: {
        authorization: `Bearer ${accessToken}`,
        "content-type": "application/json",
      },
      body: JSON.stringify(buildFcmPayload(message)),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    },
  ).catch(() => null);

  if (!response) {
    return { status: "failed", reason: "network_error", retryable: true };
  }

  const bodyText = await response.text().catch(() => "");
  if (!response.ok) {
    return classifyFcmError(response.status, bodyText);
  }

  let name = "";
  try {
    const parsed = JSON.parse(bodyText) as { name?: unknown };
    name = typeof parsed?.name === "string" ? parsed.name : "";
  } catch {
    name = "";
  }
  return { status: "sent", name };
}
