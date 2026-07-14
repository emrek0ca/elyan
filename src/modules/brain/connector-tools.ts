import type { FastifyInstance } from "fastify";
import { getConnectorAccessToken } from "../integrations/service.js";

/**
 * Server-side connector tools. They let the shared brain read a mobile-only
 * user's connected Google integrations (Gmail/Calendar/Drive) directly through
 * Google REST, using the already-stored OAuth token, without a paired desktop.
 *
 * All tools here are strictly read-only. Writes (send mail, create event) stay
 * behind the dedicated approval-gated endpoints, never here.
 */

export type ConnectorToolContract = {
  /** Registry name used in tool_requests. */
  name: string;
  /** Capability the connection must grant. */
  capability: string;
  /** Google OAuth scopes required for the underlying REST call. */
  requiredScopes: string[];
  /** One-line contract advertised to the model. */
  contract: string;
};

export const CONNECTOR_TOOL_CONTRACTS: ConnectorToolContract[] = [
  {
    name: "gmail.search",
    capability: "gmail",
    requiredScopes: ["https://www.googleapis.com/auth/gmail.readonly"],
    contract:
      'gmail.search {query:string, limit?:1..10} — search the user\'s Gmail (Gmail query syntax, e.g. "from:ali is:unread"); returns message id, from, subject, date, snippet.',
  },
  {
    name: "gmail.read",
    capability: "gmail",
    requiredScopes: ["https://www.googleapis.com/auth/gmail.readonly"],
    contract:
      "gmail.read {messageId:string} — read one Gmail message by id; returns from, to, subject, date and a plain-text body excerpt.",
  },
  {
    name: "calendar.list_events",
    capability: "calendar",
    requiredScopes: [
      "https://www.googleapis.com/auth/calendar.events.readonly",
    ],
    contract:
      "calendar.list_events {query?:string, days?:1..60, limit?:1..20} — list upcoming primary-calendar events within the next `days` (default 7); returns title, start, end, location.",
  },
  {
    name: "drive.search",
    capability: "drive",
    requiredScopes: ["https://www.googleapis.com/auth/drive.readonly"],
    contract:
      "drive.search {query:string, limit?:1..20} — search the user's Google Drive by name/full text; returns file id, name, mimeType, modifiedTime, link.",
  },
];

const CONNECTOR_TOOL_BY_NAME = new Map<string, ConnectorToolContract>(
  CONNECTOR_TOOL_CONTRACTS.map((entry) => [entry.name, entry]),
);

export function isConnectorTool(name: string): boolean {
  return CONNECTOR_TOOL_BY_NAME.has(name);
}

export function connectorToolContract(name: string): ConnectorToolContract | null {
  return CONNECTOR_TOOL_BY_NAME.get(name) ?? null;
}

/** Which connector tool contracts are available for a user's connected capabilities. */
export function connectorToolsForCapabilities(
  connectedCapabilities: string[],
): ConnectorToolContract[] {
  const connected = new Set(connectedCapabilities);
  return CONNECTOR_TOOL_CONTRACTS.filter((entry) =>
    connected.has(entry.capability),
  );
}

function clip(value: unknown, max = 500): string {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

async function googleGet(
  accessToken: string,
  url: string,
  timeoutMs = 8_000,
): Promise<Record<string, unknown>> {
  const response = await fetch(url, {
    signal: AbortSignal.timeout(timeoutMs),
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/json",
    },
  });
  const payload = (await response.json().catch(() => ({}))) as Record<
    string,
    unknown
  >;
  if (!response.ok) {
    const message =
      typeof (payload.error as { message?: unknown })?.message === "string"
        ? String((payload.error as { message?: unknown }).message)
        : `Google API request failed (${response.status})`;
    throw Object.assign(new Error(message), {
      code: response.status === 401 || response.status === 403
        ? "connector_auth_required"
        : "connector_request_failed",
    });
  }
  return payload;
}

function headerValue(
  headers: Array<{ name?: unknown; value?: unknown }>,
  name: string,
): string {
  const match = headers.find(
    (header) => String(header.name ?? "").toLowerCase() === name.toLowerCase(),
  );
  return clip(match?.value ?? "", 240);
}

function decodeBase64Url(value: string): string {
  try {
    return Buffer.from(value.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString(
      "utf8",
    );
  } catch {
    return "";
  }
}

function extractPlainTextBody(payload: Record<string, unknown>): string {
  const parts = Array.isArray(payload.parts)
    ? (payload.parts as Record<string, unknown>[])
    : [];
  const mimeType = String(payload.mimeType ?? "");
  const body = payload.body as { data?: unknown } | undefined;
  if (mimeType === "text/plain" && typeof body?.data === "string") {
    return decodeBase64Url(body.data);
  }
  for (const part of parts) {
    const nested = extractPlainTextBody(part);
    if (nested) return nested;
  }
  if (mimeType === "text/html" && typeof body?.data === "string") {
    return decodeBase64Url(body.data).replace(/<[^>]+>/g, " ");
  }
  return "";
}

async function resolveToken(
  app: FastifyInstance,
  userId: string,
  contract: ConnectorToolContract,
): Promise<string> {
  const { accessToken } = await getConnectorAccessToken(app, {
    userId,
    capability: contract.capability,
    requiredScopes: contract.requiredScopes,
    refreshTimeoutMs: 8_000,
  });
  return accessToken;
}

export async function executeGmailSearch(
  app: FastifyInstance,
  userId: string,
  args: { query: string; limit: number },
): Promise<Record<string, unknown>> {
  const token = await resolveToken(app, userId, CONNECTOR_TOOL_BY_NAME.get("gmail.search")!);
  const listUrl = new URL("https://gmail.googleapis.com/gmail/v1/users/me/messages");
  listUrl.searchParams.set("q", args.query);
  listUrl.searchParams.set("maxResults", String(args.limit));
  const listPayload = await googleGet(token, listUrl.toString());
  const messages = Array.isArray(listPayload.messages)
    ? (listPayload.messages as Record<string, unknown>[]).slice(0, args.limit)
    : [];
  const results = await Promise.all(
    messages.map(async (message) => {
      const id = String(message.id ?? "");
      if (!id) return null;
      const metaUrl = new URL(
        `https://gmail.googleapis.com/gmail/v1/users/me/messages/${encodeURIComponent(id)}`,
      );
      metaUrl.searchParams.set("format", "metadata");
      for (const header of ["From", "Subject", "Date"]) {
        metaUrl.searchParams.append("metadataHeaders", header);
      }
      const meta = await googleGet(token, metaUrl.toString()).catch(() => null);
      if (!meta) return null;
      const headers = Array.isArray((meta.payload as Record<string, unknown>)?.headers)
        ? ((meta.payload as Record<string, unknown>).headers as Array<{
            name?: unknown;
            value?: unknown;
          }>)
        : [];
      return {
        messageId: id,
        from: headerValue(headers, "From"),
        subject: headerValue(headers, "Subject"),
        date: headerValue(headers, "Date"),
        snippet: clip(meta.snippet, 280),
      };
    }),
  );
  const filtered = results.filter(
    (item): item is NonNullable<typeof item> => item != null,
  );
  return { query: args.query, resultCount: filtered.length, results: filtered };
}

export async function executeGmailRead(
  app: FastifyInstance,
  userId: string,
  args: { messageId: string },
): Promise<Record<string, unknown>> {
  const token = await resolveToken(app, userId, CONNECTOR_TOOL_BY_NAME.get("gmail.read")!);
  const url = new URL(
    `https://gmail.googleapis.com/gmail/v1/users/me/messages/${encodeURIComponent(args.messageId)}`,
  );
  url.searchParams.set("format", "full");
  const payload = await googleGet(token, url.toString());
  const messagePayload = (payload.payload as Record<string, unknown>) ?? {};
  const headers = Array.isArray(messagePayload.headers)
    ? (messagePayload.headers as Array<{ name?: unknown; value?: unknown }>)
    : [];
  return {
    messageId: args.messageId,
    from: headerValue(headers, "From"),
    to: headerValue(headers, "To"),
    subject: headerValue(headers, "Subject"),
    date: headerValue(headers, "Date"),
    snippet: clip(payload.snippet, 280),
    body: clip(extractPlainTextBody(messagePayload), 4_000),
  };
}

export async function executeCalendarListEvents(
  app: FastifyInstance,
  userId: string,
  args: { query?: string; days: number; limit: number },
): Promise<Record<string, unknown>> {
  const token = await resolveToken(
    app,
    userId,
    CONNECTOR_TOOL_BY_NAME.get("calendar.list_events")!,
  );
  const now = new Date();
  const timeMax = new Date(now.getTime() + args.days * 24 * 60 * 60 * 1_000);
  const url = new URL(
    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
  );
  url.searchParams.set("timeMin", now.toISOString());
  url.searchParams.set("timeMax", timeMax.toISOString());
  url.searchParams.set("singleEvents", "true");
  url.searchParams.set("orderBy", "startTime");
  url.searchParams.set("maxResults", String(args.limit));
  if (args.query?.trim()) {
    url.searchParams.set("q", args.query.trim());
  }
  const payload = await googleGet(token, url.toString());
  const items = Array.isArray(payload.items)
    ? (payload.items as Record<string, unknown>[]).slice(0, args.limit)
    : [];
  const events = items.map((item) => {
    const start = item.start as { dateTime?: unknown; date?: unknown } | undefined;
    const end = item.end as { dateTime?: unknown; date?: unknown } | undefined;
    return {
      title: clip(item.summary ?? "(başlıksız)", 200),
      start: clip(start?.dateTime ?? start?.date ?? "", 40),
      end: clip(end?.dateTime ?? end?.date ?? "", 40),
      location: clip(item.location ?? "", 200),
    };
  });
  return { days: args.days, resultCount: events.length, results: events };
}

export async function executeDriveSearch(
  app: FastifyInstance,
  userId: string,
  args: { query: string; limit: number },
): Promise<Record<string, unknown>> {
  const token = await resolveToken(app, userId, CONNECTOR_TOOL_BY_NAME.get("drive.search")!);
  const escaped = args.query.replace(/['\\]/g, " ").trim();
  const url = new URL("https://www.googleapis.com/drive/v3/files");
  url.searchParams.set(
    "q",
    `(name contains '${escaped}' or fullText contains '${escaped}') and trashed = false`,
  );
  url.searchParams.set("pageSize", String(args.limit));
  url.searchParams.set(
    "fields",
    "files(id,name,mimeType,modifiedTime,webViewLink)",
  );
  url.searchParams.set("orderBy", "modifiedTime desc");
  const payload = await googleGet(token, url.toString());
  const files = Array.isArray(payload.files)
    ? (payload.files as Record<string, unknown>[]).slice(0, args.limit)
    : [];
  const results = files.map((file) => ({
    fileId: String(file.id ?? ""),
    name: clip(file.name ?? "", 240),
    mimeType: String(file.mimeType ?? ""),
    modifiedTime: clip(file.modifiedTime ?? "", 40),
    link: clip(file.webViewLink ?? "", 400),
  }));
  return { query: args.query, resultCount: results.length, results };
}
