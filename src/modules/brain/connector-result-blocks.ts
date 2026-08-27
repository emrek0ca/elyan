import { buildAssistantConnectorResultBlock } from "../chat/message-blocks.js";
import { elyanAssistantBlockEnvelopeSchema } from "../../contracts/assistant-block-schemas.js";
import {
  ELYAN_ASSISTANT_BLOCK_VERSION,
  assistantBlockDigest,
  isSourceWidgetBlockType,
  withCanonicalAssistantBlockEnvelope,
  type CanonicalAssistantBlockEnvelope,
  type SourceWidgetBlockType,
} from "../chat/block-envelope.js";
import { sanitizeEmailHtmlToMarkdown } from "./connector-tools.js";
import type { AgentToolResult } from "./tool-registry.js";
import { asRecord } from "../../lib/record.js";

/**
 * Deterministically normalize successful connector/MCP read results into the
 * seven source-typed widget envelopes. The prose refinement remains a short
 * conversational summary; these blocks are the authoritative data surface.
 * Provider-specific results use source widgets. Arbitrary MCP results use the
 * bounded `connector_result` compatibility envelope until a source-specific
 * widget contract exists for that server.
 */

type ConnectorResultBlock = ReturnType<typeof buildAssistantConnectorResultBlock>;
type NormalizedConnectorBlock =
  | SourceTypedConnectorBlock
  | NonNullable<ConnectorResultBlock>;

export type SourceTypedConnectorBlockType = SourceWidgetBlockType;

export type SourceTypedConnectorSource =
  | "gmail"
  | "calendar"
  | "drive"
  | "notion"
  | "github"
  | "slack";

export type SourceTypedConnectorBlock = CanonicalAssistantBlockEnvelope & {
  type: SourceTypedConnectorBlockType;
  source: SourceTypedConnectorSource;
  visibility: "user_visible";
  isRenderable: true;
};

function asRows(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item),
      )
    : [];
}

function parseEmbeddedJson(value: unknown): unknown {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (
    trimmed.length === 0 ||
    trimmed.length > 500_000 ||
    (!trimmed.startsWith("{") && !trimmed.startsWith("["))
  ) {
    return null;
  }
  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    return null;
  }
}

/**
 * Remote MCP SDKs commonly wrap structured output in `structuredContent`,
 * `result`, or JSON text content. Normalize those transport wrappers here so
 * source adapters never depend on a provider-specific REST response.
 */
function structuredOutputRecords(output: Record<string, unknown>): Record<string, unknown>[] {
  const records: Record<string, unknown>[] = [output];
  const queue: Record<string, unknown>[] = [output];
  const seen = new Set<unknown>([output]);
  while (queue.length > 0 && records.length < 24) {
    const current = queue.shift()!;
    for (const key of [
      "structuredContent",
      "structured_content",
      "result",
      "output",
      "payload",
      "data",
      "metadata",
      "_meta",
    ]) {
      const nested = current[key];
      const nestedRecord = asRecord(nested);
      if (nestedRecord && !seen.has(nestedRecord)) {
        seen.add(nestedRecord);
        records.push(nestedRecord);
        queue.push(nestedRecord);
      }
      const parsed = parseEmbeddedJson(nested);
      const parsedRecord = asRecord(parsed);
      if (parsedRecord && !seen.has(parsedRecord)) {
        seen.add(parsedRecord);
        records.push(parsedRecord);
        queue.push(parsedRecord);
      }
      if (Array.isArray(nested)) {
        records.push({ results: nested });
      }
    }
    const content = Array.isArray(current.content) ? current.content : [];
    for (const entry of content.slice(0, 40)) {
      const entryRecord = asRecord(entry);
      const parsed = parseEmbeddedJson(entryRecord?.text ?? entryRecord?.json ?? entry);
      const parsedRecord = asRecord(parsed);
      if (parsedRecord && !seen.has(parsedRecord)) {
        seen.add(parsedRecord);
        records.push(parsedRecord);
        queue.push(parsedRecord);
      } else if (Array.isArray(parsed)) {
        records.push({ results: parsed });
      }
    }
  }
  return records;
}

function firstRows(
  output: Record<string, unknown>,
  keys: string[] = ["results", "items", "messages", "files", "events", "data", "records"],
): Record<string, unknown>[] {
  for (const record of structuredOutputRecords(output)) {
    for (const key of keys) {
      const rows = asRows(record[key]);
      if (rows.length > 0) return rows.slice(0, 160);
    }
  }
  return [];
}

function str(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function clipped(value: unknown, max = 1_000): string {
  if (value && typeof value === "object") return "";
  return str(value).trim().slice(0, max);
}

function optionalString(value: unknown, max = 1_000): string | undefined {
  const normalized = clipped(value, max);
  return normalized || undefined;
}

function stringList(value: unknown, maxItems = 40, maxLength = 400): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => clipped(item, maxLength))
      .filter(Boolean)
      .slice(0, maxItems);
  }
  const normalized = clipped(value, maxLength * maxItems);
  if (!normalized) return [];
  return normalized
    .split(/[,;\n]/u)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, maxItems);
}

function finiteInteger(value: unknown): number | undefined {
  if (value == null || value === "") return undefined;
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric >= 0
    ? Math.floor(numeric)
    : undefined;
}

function booleanValue(value: unknown, fallback = false): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (["true", "1", "yes", "unread"].includes(normalized)) return true;
    if (["false", "0", "no", "read"].includes(normalized)) return false;
  }
  return fallback;
}

function safeExternalUrl(value: unknown): string | undefined {
  const raw = clipped(value, 2_000);
  if (!raw) return undefined;
  try {
    const parsed = new URL(raw);
    const normalized = parsed.toString();
    return parsed.protocol === "https:" &&
      !parsed.username &&
      !parsed.password &&
      normalized.length <= 2_000
      ? normalized
      : undefined;
  } catch {
    return undefined;
  }
}

function firstString(
  row: Record<string, unknown>,
  keys: string[],
  max = 1_000,
): string {
  for (const key of keys) {
    const value = clipped(row[key], max);
    if (value) return value;
  }
  return "";
}

function firstRecordValue(
  output: Record<string, unknown>,
  keys: string[],
  max = 1_000,
): string {
  for (const record of structuredOutputRecords(output)) {
    const value = firstString(record, keys, max);
    if (value) return value;
  }
  return "";
}

function nestedString(
  value: unknown,
  keys: string[],
  max = 1_000,
): string {
  const record = asRecord(value);
  return record ? firstString(record, keys, max) : clipped(value, max);
}

function mailbox(value: unknown): { name: string; address?: string } {
  const record = asRecord(value);
  if (record) {
    const name = firstString(
      record,
      ["name", "displayName", "display_name", "realName", "real_name"],
      160,
    );
    const address = firstString(record, ["address", "email", "emailAddress"], 254);
    return {
      name: name || address.split("@")[0] || "Gönderen bilinmiyor",
      ...(address ? { address } : {}),
    };
  }
  const raw = clipped(value, 320);
  const match = raw.match(/^\s*"?([^"<]+?)"?\s*<([^>]+)>\s*$/u);
  if (match) {
    return {
      name: clipped(match[1], 160) || "Gönderen bilinmiyor",
      ...(optionalString(match[2], 254)
        ? { address: optionalString(match[2], 254) }
        : {}),
    };
  }
  const email = raw.match(/[^\s<>@]+@[^\s<>@]+/u)?.[0];
  if (email) {
    return {
      name: clipped(email.split("@")[0], 160) || "Gönderen bilinmiyor",
      address: clipped(email, 254),
    };
  }
  return { name: raw || "Gönderen bilinmiyor" };
}

function sourceBlock(input: {
  type: SourceTypedConnectorBlockType;
  source: SourceTypedConnectorSource;
  identity: string;
  data: Record<string, unknown>;
  density?: "compact" | "comfortable";
}): SourceTypedConnectorBlock {
  // Identity intentionally excludes mutable rows. `blockId` therefore remains
  // stable across stream retries while the canonical cache digest changes with
  // `data`, allowing clients to skip only genuinely unchanged rebuilds.
  const identityDigest = assistantBlockDigest({
    type: input.type,
    source: input.source,
    data: { identity: input.identity },
    renderHints: { slot: input.type },
    visibility: "user_visible",
  });
  return withCanonicalAssistantBlockEnvelope({
    type: input.type,
    blockId: `${input.type}_${identityDigest}`,
    source: input.source,
    visibility: "user_visible",
    renderHints: {
      sectionRole: input.type,
      renderer: `native_${input.type}`,
      slot: input.type,
      density: input.density ?? "comfortable",
    },
    data: input.data,
    isRenderable: true,
  }) as SourceTypedConnectorBlock;
}

function sourceHint(
  tool: string,
  output: Record<string, unknown>,
): SourceTypedConnectorSource | null {
  const hints = [tool];
  for (const record of structuredOutputRecords(output)) {
    for (const key of [
      "source",
      "provider",
      "app",
      "appId",
      "app_id",
      "integration",
      "connector",
      "serverName",
      "server_name",
      "tool",
      "toolName",
      "tool_name",
    ]) {
      const value = clipped(record[key], 160);
      if (value) hints.push(value);
    }
  }
  const normalized = hints.join(" ").toLowerCase();
  if (/\b(?:gmail|google[._ -]?mail)\b/u.test(normalized)) return "gmail";
  if (/\b(?:calendar|google[._ -]?calendar|gcal)\b/u.test(normalized)) return "calendar";
  if (/\b(?:drive|google[._ -]?drive|gdrive)\b/u.test(normalized)) return "drive";
  if (/\bnotion\b/u.test(normalized)) return "notion";
  if (/\bgithub\b/u.test(normalized)) return "github";
  if (/\bslack\b/u.test(normalized)) return "slack";
  return null;
}

function sourceQuery(output: Record<string, unknown>): string {
  return firstRecordValue(output, ["query", "q", "search", "filter"], 500);
}

function mailListBlock(output: Record<string, unknown>): SourceTypedConnectorBlock {
  const rows = firstRows(output, ["results", "messages", "items", "data"]);
  const items = rows.flatMap((row) => {
    const messageId = firstString(row, ["messageId", "message_id", "id"], 240);
    if (!messageId) return [];
    const threadId =
      firstString(row, ["threadId", "thread_id", "conversationId"], 240) ||
      messageId;
    const sender = mailbox(row.from ?? row.sender ?? row.author);
    const labels = stringList(row.labels ?? row.labelIds ?? row.label_ids, 24, 80);
    const avatarUrl = safeExternalUrl(row.avatarUrl ?? row.avatar_url);
    const receivedAt = firstString(
      row,
      ["receivedAt", "received_at", "date", "timestamp", "internalDate"],
      80,
    );
    if (!receivedAt) return [];
    return [
      {
        messageId,
        threadId,
        senderName: sender.name,
        ...(sender.address ? { senderAddress: sender.address } : {}),
        subject:
          firstString(row, ["subject", "title"], 500) || "(konu yok)",
        preview: firstString(
          row,
          ["preview", "snippet", "bodyPreview", "body_preview"],
          800,
        ),
        receivedAt,
        isUnread:
          booleanValue(row.isUnread ?? row.is_unread) ||
          labels.some((label) => label.toUpperCase() === "UNREAD"),
        ...(avatarUrl ? { avatarUrl } : {}),
        ...(labels.length > 0 ? { labels } : {}),
        action: { kind: "mail.open", messageId, threadId },
      },
    ];
  }).slice(0, 80);
  const query = sourceQuery(output);
  const nextPageToken = firstRecordValue(output, [
    "nextPageToken",
    "next_page_token",
    "nextCursor",
    "next_cursor",
  ], 1_000);
  return sourceBlock({
    type: "mail_list",
    source: "gmail",
    identity: `gmail.search:${query || "inbox"}`,
    data: {
      state: items.length > 0 ? "ready" : "empty",
      title: "Gelen kutusu",
      ...(query ? { query } : {}),
      items,
      ...(nextPageToken ? { nextPageToken } : {}),
    },
    density: "compact",
  });
}

function attachmentRows(value: unknown): Array<Record<string, unknown>> {
  return asRows(value).flatMap((attachment) => {
    const attachmentId = firstString(
      attachment,
      ["attachmentId", "attachment_id", "id"],
      240,
    );
    const name = firstString(
      attachment,
      ["name", "filename", "fileName", "file_name"],
      255,
    );
    if (!attachmentId || !name) return [];
    const sizeBytes = finiteInteger(
      attachment.sizeBytes ?? attachment.size_bytes ?? attachment.size,
    );
    const downloadUrl = safeExternalUrl(
      attachment.downloadUrl ?? attachment.download_url ?? attachment.url,
    );
    return [
      {
        attachmentId,
        name,
        ...(optionalString(attachment.mimeType ?? attachment.mime_type, 160)
          ? {
              mimeType: optionalString(
                attachment.mimeType ?? attachment.mime_type,
                160,
              ),
            }
          : {}),
        ...(sizeBytes != null ? { sizeBytes } : {}),
        ...(downloadUrl
          ? { action: { kind: "link.open", url: downloadUrl } }
          : {}),
      },
    ];
  }).slice(0, 40);
}

function hasMailBody(record: Record<string, unknown>): boolean {
  return Boolean(
    firstString(
      record,
      [
        "bodyRichText",
        "body_rich_text",
        "bodyHtml",
        "body_html",
        "htmlBody",
        "html_body",
        "body",
        "html",
      ],
      1,
    ),
  );
}

function mailDetailBlock(
  output: Record<string, unknown>,
): SourceTypedConnectorBlock | null {
  const records = structuredOutputRecords(output);
  const record =
    records.find(
      (candidate) =>
        hasMailBody(candidate) &&
        Boolean(firstString(candidate, ["messageId", "message_id", "id"])),
    ) ??
    records.find(hasMailBody) ??
    records.find((candidate) =>
      Boolean(firstString(candidate, ["messageId", "message_id", "id"])),
    ) ??
    output;
  const messageId = firstString(record, ["messageId", "message_id", "id"], 240);
  if (!messageId) {
    return sourceBlock({
      type: "mail_detail",
      source: "gmail",
      identity: "gmail.read:empty",
      data: { state: "empty" },
    });
  }
  const threadId =
    firstString(record, ["threadId", "thread_id", "conversationId"], 240) ||
    messageId;
  const sender = mailbox(record.from ?? record.sender ?? record.author);
  const rawHtml = firstString(
    record,
    ["bodyHtml", "body_html", "htmlBody", "html_body", "html"],
    500_000,
  );
  const sanitizedMarkdown = rawHtml
    ? sanitizeEmailHtmlToMarkdown(rawHtml)
    : "";
  const declaredFormat = firstString(record, ["bodyFormat", "body_format"], 40);
  const richTextCandidate = firstString(
    record,
    ["bodyRichText", "body_rich_text", "body", "text", "snippet"],
    100_000,
  );
  const sanitizedRichTextCandidate =
    declaredFormat.toLowerCase() === "html" || /<[a-z][^>]*>/iu.test(richTextCandidate)
      ? sanitizeEmailHtmlToMarkdown(richTextCandidate)
      : "";
  const safeRichText =
    sanitizedMarkdown ||
    sanitizedRichTextCandidate ||
    richTextCandidate;
  const attachments = attachmentRows(record.attachments);
  const receivedAt = firstString(
    record,
    ["receivedAt", "received_at", "date", "timestamp"],
    80,
  );
  if (!safeRichText || !receivedAt) {
    return sourceBlock({
      type: "mail_detail",
      source: "gmail",
      identity: `gmail.read:${messageId}`,
      data: { state: "empty" },
    });
  }
  return sourceBlock({
    type: "mail_detail",
    source: "gmail",
    identity: `gmail.read:${messageId}`,
    data: {
      state: "ready",
      messageId,
      threadId,
      senderName: sender.name,
      ...(sender.address ? { senderAddress: sender.address } : {}),
      recipients: [
        ...stringList(record.to ?? record.recipients, 100, 320),
        ...stringList(record.cc, 100, 320),
      ].slice(0, 100),
      subject: firstString(record, ["subject", "title"], 500) || "(konu yok)",
      receivedAt,
      bodyRichText: safeRichText,
      bodyFormat:
        sanitizedMarkdown ||
        sanitizedRichTextCandidate ||
        declaredFormat.toLowerCase() === "markdown"
          ? "markdown"
          : "plain_text",
      attachments,
    },
  });
}

function calendarAgendaBlock(
  output: Record<string, unknown>,
): SourceTypedConnectorBlock {
  const rows = firstRows(output, ["results", "events", "items", "data"]);
  const eventRows = rows.flatMap((row) => {
    const eventId = firstString(row, ["eventId", "event_id", "id"], 240);
    if (!eventId) return [];
    const url = safeExternalUrl(
      row.url ?? row.link ?? row.htmlLink ?? row.html_link ?? row.webLink,
    );
    const startAt =
      firstString(row, ["startAt", "start_at", "startTime", "start_time"], 80) ||
      nestedString(row.start, ["dateTime", "date_time", "date"], 80);
    const endAt =
      firstString(row, ["endAt", "end_at", "endTime", "end_time"], 80) ||
      nestedString(row.end, ["dateTime", "date_time", "date"], 80);
    if (!startAt || !endAt) return [];
    const startRecord = asRecord(row.start);
    const allDay =
      booleanValue(row.allDay ?? row.all_day) ||
      Boolean(startRecord?.date && !startRecord?.dateTime && !startRecord?.date_time);
    return [
      {
        eventId,
        title: firstString(row, ["title", "summary", "name"], 500) || "(başlıksız)",
        startAt,
        endAt,
        allDay,
        ...(optionalString(row.location, 500)
          ? { location: optionalString(row.location, 500) }
          : {}),
        ...(optionalString(row.calendarName ?? row.calendar_name, 160)
          ? {
              calendarName: optionalString(
                row.calendarName ?? row.calendar_name,
                160,
              ),
            }
          : {}),
        hasConflict: booleanValue(row.hasConflict ?? row.has_conflict),
        ...(url ? { url } : {}),
        action: { kind: "calendar.menu", eventId, ...(url ? { url } : {}) },
      },
    ];
  }).slice(0, 160);
  const ranges = eventRows.map((event) => ({
    start: Date.parse(event.startAt),
    end: Date.parse(event.endAt),
  }));
  const events = eventRows.map((event, index) => ({
    ...event,
    hasConflict:
      event.hasConflict ||
      ranges.some(
        (candidate, candidateIndex) =>
          candidateIndex !== index &&
          Number.isFinite(candidate.start) &&
          Number.isFinite(candidate.end) &&
          Number.isFinite(ranges[index]?.start) &&
          Number.isFinite(ranges[index]?.end) &&
          candidate.start < (ranges[index]?.end ?? 0) &&
          candidate.end > (ranges[index]?.start ?? 0),
      ),
  }));
  const query = sourceQuery(output);
  const date =
    firstRecordValue(
      output,
      ["date", "rangeStart", "range_start", "timeMin"],
      120,
    ).slice(0, 10) ||
    firstString(events[0] ?? {}, ["startAt"], 10) ||
    new Date().toISOString().slice(0, 10);
  const timeZone =
    firstRecordValue(
      output,
      ["timeZone", "time_zone", "timezone"],
      120,
    ) || "UTC";
  return sourceBlock({
    type: "calendar_agenda",
    source: "calendar",
    identity: `calendar.list:${date}:${timeZone}:${query}`,
    data: {
      state: events.length > 0 ? "ready" : "empty",
      date,
      timeZone,
      events,
    },
    density: "compact",
  });
}

function driveFilesBlock(output: Record<string, unknown>): SourceTypedConnectorBlock {
  const rows = firstRows(output, ["results", "files", "items", "data"]);
  const files = rows.flatMap((row) => {
    const fileId = firstString(row, ["fileId", "file_id", "id"], 240);
    if (!fileId) return [];
    const url = safeExternalUrl(row.url ?? row.link ?? row.webViewLink ?? row.web_view_link);
    if (!url) return [];
    const mimeType =
      firstString(row, ["mimeType", "mime_type", "contentType", "content_type"], 240) ||
      "application/octet-stream";
    const kind = firstString(row, ["kind", "type"], 120) || driveTypeLabel(mimeType);
    const sizeBytes = finiteInteger(row.sizeBytes ?? row.size_bytes ?? row.size);
    return [
      {
        fileId,
        name: firstString(row, ["name", "title"], 500) || "(adsız)",
        mimeType,
        kind,
        ...(sizeBytes != null ? { sizeBytes } : {}),
        ...(optionalString(row.modifiedAt ?? row.modified_at ?? row.modifiedTime, 80)
          ? {
              modifiedAt: optionalString(
                row.modifiedAt ?? row.modified_at ?? row.modifiedTime,
                80,
              ),
            }
          : {}),
        ...(optionalString(
          nestedString(
            row.ownerName ?? row.owner_name ?? row.owner,
            ["displayName", "display_name", "name", "emailAddress", "email"],
            160,
          ),
          160,
        )
          ? {
              ownerName: optionalString(
                nestedString(
                  row.ownerName ?? row.owner_name ?? row.owner,
                  ["displayName", "display_name", "name", "emailAddress", "email"],
                  160,
                ),
                160,
              ),
            }
          : {}),
        action: { kind: "link.open", url },
      },
    ];
  }).slice(0, 160);
  const query = sourceQuery(output);
  return sourceBlock({
    type: "drive_files",
    source: "drive",
    identity: `drive.search:${query || "recent"}`,
    data: {
      state: files.length > 0 ? "ready" : "empty",
      title: "Drive dosyaları",
      ...(query ? { query } : {}),
      files,
      availableTypes: [
        ...new Set(files.map((file) => file.kind).filter(Boolean)),
      ].slice(0, 40),
    },
    density: "compact",
  });
}

function notionSummaryBlocks(row: Record<string, unknown>): Array<Record<string, string>> {
  const structured = asRows(row.summaryBlocks ?? row.summary_blocks ?? row.blocks)
    .flatMap((block) => {
      const text = firstString(block, ["text", "plain_text", "content", "summary"], 2_000);
      if (!text) return [];
      return [{ kind: firstString(block, ["kind", "type"], 80) || "text", text }];
    })
    .slice(0, 40);
  if (structured.length > 0) return structured;
  const summary = firstString(
    row,
    ["summary", "preview", "description", "text", "bodyPreview", "body_preview"],
    2_000,
  );
  return summary ? [{ kind: "text", text: summary }] : [];
}

function notionPageBlocks(output: Record<string, unknown>): SourceTypedConnectorBlock[] {
  const listRows = firstRows(output, ["results", "pages", "items", "data"]);
  const singleRow = structuredOutputRecords(output).find(
    (record) =>
      Boolean(firstString(record, ["pageId", "page_id", "id"])) &&
      Boolean(record.url ?? record.link ?? record.webUrl ?? record.web_url),
  );
  const rows = listRows.length > 0 ? listRows : singleRow ? [singleRow] : [];
  const query = sourceQuery(output);
  const blocks = rows.flatMap((row) => {
    const pageId = firstString(row, ["pageId", "page_id", "id"], 240);
    const url = safeExternalUrl(row.url ?? row.link ?? row.webUrl ?? row.web_url);
    if (!pageId || !url) return [];
    const breadcrumb = Array.isArray(row.breadcrumb)
      ? stringList(row.breadcrumb, 16, 240)
      : stringList(row.breadcrumb ?? row.path, 16, 240);
    const title = firstString(row, ["title", "name"], 500) || "(başlıksız)";
    const summaryBlocks = notionSummaryBlocks(row);
    const data: Record<string, unknown> = {
      state: "ready",
      pageId,
      title,
      breadcrumb,
      summaryBlocks:
        summaryBlocks.length > 0
          ? summaryBlocks
          : [{ kind: "title", text: title }],
      action: { kind: "link.open", url },
      ...(optionalString(
        row.lastEditedAt ?? row.last_edited_at ?? row.lastEditedTime ?? row.last_edited_time ?? row.updatedAt,
        80,
      )
        ? {
            lastEditedAt: optionalString(
              row.lastEditedAt ?? row.last_edited_at ?? row.lastEditedTime ?? row.last_edited_time ?? row.updatedAt,
              80,
            ),
          }
        : {}),
    };
    return [
      sourceBlock({
        type: "notion_page",
        source: "notion",
        identity: `notion.page:${pageId}`,
        data,
      }),
    ];
  });
  if (blocks.length > 0) return blocks;
  return [
    sourceBlock({
      type: "notion_page",
      source: "notion",
      identity: `notion.search:${query || "recent"}`,
      data: { state: "empty" },
    }),
  ];
}

function githubActivityBlock(output: Record<string, unknown>): SourceTypedConnectorBlock {
  const rows = firstRows(output, ["results", "items", "activities", "data"]);
  const items = rows.flatMap((row) => {
    const url = safeExternalUrl(row.url ?? row.htmlUrl ?? row.html_url ?? row.link);
    if (!url) return [];
    const number = finiteInteger(row.number ?? row.issueNumber ?? row.issue_number ?? row.prNumber);
    const urlNumber = finiteInteger(url.split("/").filter(Boolean).at(-1));
    const activityNumber = number ?? urlNumber;
    if (activityNumber == null || activityNumber <= 0) return [];
    const repository =
      firstString(row, ["repo", "repositoryName", "repository_name"], 255) ||
      nestedString(row.repository, ["fullName", "full_name", "nameWithOwner", "name_with_owner", "name"], 255);
    const activityId =
      firstString(row, ["activityId", "activity_id", "nodeId", "node_id", "id"], 240) ||
      clipped(`${repository}:${activityNumber}`, 255);
    const rawKind = firstString(row, ["kind", "type"], 80).toLowerCase();
    const kind = rawKind.includes("pull") || rawKind === "pr" ? "pull_request" : "issue";
    const rawStatus = firstString(row, ["status", "state"], 80).toLowerCase();
    const status =
      rawStatus === "merged" || booleanValue(row.merged)
        ? "merged"
        : rawStatus === "draft" || booleanValue(row.draft)
          ? "draft"
          : rawStatus === "closed"
            ? "closed"
            : "open";
    return [
      {
        activityId,
        kind,
        number: activityNumber,
        title: firstString(row, ["title", "name", "summary"], 500) || "(başlıksız)",
        repository: repository || "unknown",
        status,
        ...(optionalString(
          nestedString(
            row.author ?? row.authorName ?? row.user,
            ["login", "name", "displayName", "display_name"],
            160,
          ),
          160,
        )
          ? {
              author: optionalString(
                nestedString(
                  row.author ?? row.authorName ?? row.user,
                  ["login", "name", "displayName", "display_name"],
                  160,
                ),
                160,
              ),
            }
          : {}),
        ...(optionalString(row.updatedAt ?? row.updated_at, 80)
          ? { updatedAt: optionalString(row.updatedAt ?? row.updated_at, 80) }
          : {}),
        action: { kind: "link.open", url },
      },
    ];
  }).slice(0, 160);
  const query = sourceQuery(output);
  return sourceBlock({
    type: "github_activity",
    source: "github",
    identity: `github.activity:${query || "involving-me"}`,
    data: {
      state: items.length > 0 ? "ready" : "empty",
      title: "GitHub etkinliği",
      items,
    },
    density: "compact",
  });
}

function slackMessagesBlock(output: Record<string, unknown>): SourceTypedConnectorBlock {
  const rows = firstRows(output, ["results", "messages", "items", "data"]);
  const messages = rows.flatMap((row) => {
    const url = safeExternalUrl(row.permalink ?? row.url ?? row.link);
    if (!url) return [];
    const timestamp = firstString(row, ["timestamp", "ts", "createdAt", "created_at"], 80);
    const channelId =
      firstString(row, ["channelId", "channel_id"], 240) ||
      nestedString(row.channel, ["id", "channelId", "channel_id"], 240);
    const messageId =
      firstString(row, ["messageId", "message_id", "id"], 240) ||
      clipped(`${channelId}:${timestamp}`, 255);
    const text = firstString(row, ["text", "message", "content"], 20_000);
    if (!channelId || !timestamp || !messageId || !text) return [];
    const avatarUrl = safeExternalUrl(row.avatarUrl ?? row.avatar_url);
    return [
      {
        messageId,
        channelId,
        channelName:
          firstString(row, ["channelName", "channel_name"], 160) ||
          nestedString(row.channel, ["name", "channelName", "channel_name"], 160) ||
          clipped(channelId, 160),
        authorName:
          firstString(row, ["authorName", "author_name", "userName", "user_name"], 160) ||
          nestedString(row.author ?? row.user, ["name", "realName", "real_name", "displayName", "display_name"], 160) ||
          "Bilinmeyen",
        text,
        timestamp,
        ...(optionalString(row.threadTs ?? row.thread_ts, 80)
          ? { threadTs: optionalString(row.threadTs ?? row.thread_ts, 80) }
          : {}),
        ...(avatarUrl ? { avatarUrl } : {}),
        action: { kind: "link.open", url },
      },
    ];
  }).slice(0, 160);
  const query = sourceQuery(output);
  const channel = firstRecordValue(output, ["channelId", "channel_id", "channel"]);
  return sourceBlock({
    type: "slack_messages",
    source: "slack",
    identity: `slack.messages:${channel}:${query}`,
    data: {
      state: messages.length > 0 ? "ready" : "empty",
      title: "Slack mesajları",
      messages,
    },
    density: "compact",
  });
}

/**
 * Build the normal production block surface for connector and remote-MCP read
 * results. Successful empty list queries deliberately produce an `empty`
 * source block; failed calls stay on the existing safe prose error path.
 */
export function buildSourceTypedConnectorBlocks(
  results: AgentToolResult[],
): NormalizedConnectorBlock[] {
  const blocks: NormalizedConnectorBlock[] = [];
  for (const result of results) {
    if (!result.ok || result.permission !== "read" || !result.output) continue;
    if (result.tool.startsWith("mcp__")) {
      const block = genericConnectorBlock(result.tool, result.output);
      if (block) blocks.push(block);
      continue;
    }
    const source = sourceHint(result.tool, result.output);
    if (!source) continue;
    if (source === "gmail") {
      const normalizedTool = result.tool.toLowerCase();
      const looksLikeDetail =
        normalizedTool.includes("read") ||
        normalizedTool.includes("get_message") ||
        normalizedTool.includes("get-message") ||
        structuredOutputRecords(result.output).some((record) =>
          hasMailBody(record),
        );
      if (looksLikeDetail) {
        const block = mailDetailBlock(result.output);
        if (block) blocks.push(block);
      } else {
        blocks.push(mailListBlock(result.output));
      }
      continue;
    }
    if (source === "calendar") {
      blocks.push(calendarAgendaBlock(result.output));
      continue;
    }
    if (source === "drive") {
      blocks.push(driveFilesBlock(result.output));
      continue;
    }
    if (source === "notion") {
      blocks.push(...notionPageBlocks(result.output));
      continue;
    }
    if (source === "github") {
      blocks.push(githubActivityBlock(result.output));
      continue;
    }
    blocks.push(slackMessagesBlock(result.output));
  }
  return blocks.flatMap((block) => {
    const parsed = elyanAssistantBlockEnvelopeSchema.safeParse(block);
    return parsed.success ? [parsed.data as NormalizedConnectorBlock] : [];
  });
}

type ToolCallProvider =
  | "gmail"
  | "drive"
  | "calendar"
  | "notion"
  | "github"
  | "slack"
  | "linear"
  | "mcp"
  | "connector"
  | "runtime"
  | "web";

/** Icon hint for a tool_call row. Unknown tools fall back to a generic icon. */
function toolCallProvider(tool: string): ToolCallProvider | undefined {
  const normalized = tool.toLowerCase();
  if (normalized.includes("gmail") || normalized.includes("mail")) return "gmail";
  if (normalized.includes("drive")) return "drive";
  if (normalized.includes("calendar")) return "calendar";
  if (normalized.includes("notion")) return "notion";
  if (normalized.includes("github")) return "github";
  if (normalized.includes("slack")) return "slack";
  if (normalized.includes("linear")) return "linear";
  if (
    normalized.includes("web") ||
    normalized.includes("fetch") ||
    normalized.includes("search")
  ) {
    return "web";
  }
  if (
    normalized.includes("memory") ||
    normalized.includes("goal") ||
    normalized.includes("numeric")
  ) {
    return "runtime";
  }
  if (normalized.includes("mcp") || normalized.includes("connector")) return "mcp";
  return undefined;
}

const TOOL_RESULT_ARRAY_KEYS = [
  "results",
  "messages",
  "items",
  "files",
  "events",
  "rows",
  "pages",
  "records",
] as const;

/** "N sonuç" / short scalar hint — what the tool found, for the row subtitle. */
function toolCallResultSummary(result: AgentToolResult): string | undefined {
  const output = result.output;
  if (!output) return undefined;
  for (const key of TOOL_RESULT_ARRAY_KEYS) {
    const value = output[key];
    if (Array.isArray(value)) {
      return value.length === 0 ? "Sonuç yok" : `${value.length} sonuç`;
    }
  }
  if (output.used === false) return "Kullanılmadı";
  return optionalString(output.title ?? output.summary, 160);
}

/**
 * Turns the agent's tool telemetry (which tool, how long, ok/error, what it
 * found) into a single user-visible `tool_call` block. Complements the
 * source-typed data blocks: the answer chain is now traceable end to end.
 */
export function buildToolCallBlock(
  results: AgentToolResult[],
): CanonicalAssistantBlockEnvelope | null {
  if (results.length === 0) return null;
  const calls = results.map((result, index) => {
    const call: Record<string, unknown> = {
      callId: `${result.tool}_${index}`.slice(0, 255),
      toolName: clipped(result.tool, 160) || "tool",
      status: result.ok ? "ok" : "error",
    };
    const provider = toolCallProvider(result.tool);
    if (provider) call.provider = provider;
    if (Number.isFinite(result.durationMs)) {
      call.durationMs = Math.min(
        Math.max(0, Math.round(result.durationMs)),
        3_600_000,
      );
    }
    if (result.ok) {
      const summary = toolCallResultSummary(result);
      if (summary) call.resultSummary = summary;
    } else {
      const code = clipped(result.error?.code, 80) || "tool_error";
      const message = clipped(result.error?.message, 240) || "Araç hata verdi.";
      call.error = { code, message };
    }
    return call;
  });
  const block = withCanonicalAssistantBlockEnvelope({
    type: "tool_call",
    version: ELYAN_ASSISTANT_BLOCK_VERSION,
    source: "runtime",
    visibility: "user_visible",
    renderHints: {
      sectionRole: "tool_call",
      renderer: "native_tool_call",
      slot: "tool_call",
    },
    data: { calls },
    isRenderable: true,
  });
  const parsed = elyanAssistantBlockEnvelopeSchema.safeParse(block);
  return parsed.success
    ? (parsed.data as CanonicalAssistantBlockEnvelope)
    : null;
}

/** Compact an RFC From header ("Ali Veli <ali@x.com>") to the display name. */
function displayFrom(value: unknown): string {
  const raw = str(value).trim();
  const named = raw.match(/^\s*"?([^"<]+?)"?\s*<[^>]+>\s*$/);
  return (named ? named[1] : raw).trim();
}

/** Human-friendly short date from an RFC/ISO date string; falls back to raw. */
function shortDate(value: unknown): string {
  const raw = str(value).trim();
  if (!raw) return "";
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return parsed.toLocaleString("tr-TR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function providerForTool(tool: string): Parameters<typeof buildAssistantConnectorResultBlock>[0]["provider"] {
  const normalized = tool.toLowerCase();
  if (normalized.includes("gmail") || normalized.includes("mail")) return "gmail";
  if (normalized.includes("drive")) return "drive";
  if (normalized.includes("calendar")) return "calendar";
  if (normalized.includes("notion")) return "notion";
  if (normalized.includes("github")) return "github";
  if (normalized.includes("slack")) return "slack";
  if (normalized.includes("linear")) return "linear";
  if (normalized.includes("mcp")) return "mcp";
  return "connector";
}

function kindForTool(tool: string): string {
  const normalized = tool.toLowerCase();
  if (normalized.includes("gmail")) return "email_list";
  if (normalized.includes("drive")) return "file_list";
  if (normalized.includes("calendar")) return "event_list";
  if (normalized.includes("notion")) return "page_list";
  if (normalized.includes("github") && normalized.includes("issue")) return "issue_list";
  if (normalized.includes("github")) return "repo_list";
  if (normalized.includes("slack")) return "message_list";
  return "item_list";
}

function urlFrom(row: Record<string, unknown>): string {
  return str(row.url || row.webLink || row.htmlLink || row.link || row.permalink || row.browser_url);
}

const DRIVE_MIME_LABELS: Record<string, string> = {
  "application/vnd.google-apps.document": "Doküman",
  "application/vnd.google-apps.spreadsheet": "Tablo",
  "application/vnd.google-apps.presentation": "Sunum",
  "application/vnd.google-apps.folder": "Klasör",
  "application/pdf": "PDF",
};

function driveTypeLabel(mimeType: unknown): string {
  const mime = str(mimeType);
  if (DRIVE_MIME_LABELS[mime]) return DRIVE_MIME_LABELS[mime];
  const tail = mime.split(/[./]/).pop() ?? "";
  return tail ? tail.toUpperCase() : "Dosya";
}

function gmailBlock(tool: string, output: Record<string, unknown>): ConnectorResultBlock {
  const rows = firstRows(output, ["results", "messages", "items", "data"]);
  if (rows.length === 0) return null;
  return buildAssistantConnectorResultBlock({
    provider: "gmail",
    tool,
    title: "Gelen kutusu",
    kind: "email_list",
    summary: `${rows.length} e-posta`,
    items: rows.map((row) => ({
      title: str(row.subject) || "(konu yok)",
      subtitle: displayFrom(row.from),
      detail: str(row.snippet || row.preview || row.bodyPreview),
      timestamp: shortDate(row.date),
      url: urlFrom(row),
      kind: "email",
      status: str(row.status || row.labelIds),
    })),
    columns: ["Kimden", "Konu", "Tarih"],
    rows: rows.map((row) => [
      displayFrom(row.from),
      str(row.subject) || "(konu yok)",
      shortDate(row.date),
    ]),
  });
}

function calendarBlock(tool: string, output: Record<string, unknown>): ConnectorResultBlock {
  const rows = firstRows(output, ["results", "events", "items", "data"]);
  if (rows.length === 0) return null;
  return buildAssistantConnectorResultBlock({
    provider: "calendar",
    tool,
    title: "Yaklaşan etkinlikler",
    kind: "event_list",
    summary: `${rows.length} etkinlik`,
    items: rows.map((row) => ({
      title: str(row.title || row.summary) || "(başlıksız)",
      subtitle: shortDate(row.start),
      detail: str(row.location || row.description),
      timestamp: shortDate(row.end),
      url: urlFrom(row),
      kind: "event",
    })),
    columns: ["Başlık", "Başlangıç", "Bitiş", "Yer"],
    rows: rows.map((row) => [
      str(row.title || row.summary) || "(başlıksız)",
      shortDate(row.start),
      shortDate(row.end),
      str(row.location),
    ]),
  });
}

function driveBlock(tool: string, output: Record<string, unknown>): ConnectorResultBlock {
  const rows = firstRows(output, ["results", "files", "items", "data"]);
  if (rows.length === 0) return null;
  return buildAssistantConnectorResultBlock({
    provider: "drive",
    tool,
    title: "Drive dosyaları",
    kind: "file_list",
    summary: `${rows.length} dosya`,
    items: rows.map((row) => ({
      title: str(row.name || row.title) || "(adsız)",
      subtitle: driveTypeLabel(row.mimeType),
      timestamp: shortDate(row.modifiedTime || row.updatedAt),
      url: urlFrom(row),
      kind: "file",
    })),
    columns: ["Ad", "Tür", "Değiştirilme"],
    rows: rows.map((row) => [
      str(row.name || row.title),
      driveTypeLabel(row.mimeType),
      shortDate(row.modifiedTime),
    ]),
  });
}

function genericConnectorTitle(tool: string): string {
  const normalized = tool.toLowerCase();
  if (normalized.includes("notion")) return "Notion sonuçları";
  if (normalized.includes("github")) return "GitHub sonuçları";
  if (normalized.includes("slack")) return "Slack sonuçları";
  if (normalized.includes("linear")) return "Linear sonuçları";
  return "Bağlantı sonuçları";
}

function genericValue(row: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = str(row[key]).trim();
    if (value) return value;
  }
  return "";
}

function genericConnectorBlock(
  tool: string,
  output: Record<string, unknown>,
): ConnectorResultBlock {
  const rows = firstRows(output);
  if (rows.length === 0) return null;
  return buildAssistantConnectorResultBlock({
    provider: providerForTool(tool),
    tool,
    title: genericConnectorTitle(tool),
    kind: kindForTool(tool),
    summary: `${rows.length} sonuç`,
    items: rows.map((row) => ({
      title: genericValue(row, [
        "title",
        "name",
        "subject",
        "summary",
        "text",
        "repo",
        "repository",
        "path",
        "url",
      ]) || "(başlıksız)",
      subtitle: genericValue(row, ["from", "owner", "author", "email", "type", "kind", "mimeType"]),
      detail: genericValue(row, ["description", "snippet", "bodyPreview", "preview", "state", "status"]),
      timestamp: shortDate(
        genericValue(row, [
          "updatedAt",
          "updated_at",
          "modifiedTime",
          "lastEditedTime",
          "last_edited_time",
          "createdAt",
          "created_at",
          "date",
        ]),
      ),
      url: urlFrom(row),
      kind: genericValue(row, ["type", "kind", "app"]) || kindForTool(tool),
      status: genericValue(row, ["state", "status"]),
    })),
    columns: ["Başlık", "Tür", "Güncelleme"],
    rows: rows.map((row) => [
      genericValue(row, [
        "title",
        "name",
        "subject",
        "summary",
        "text",
        "repo",
        "repository",
        "path",
        "url",
      ]) || "(başlıksız)",
      genericValue(row, ["type", "kind", "mimeType", "state", "status", "app"]) ||
        tool.split(".")[0] ||
        "sonuç",
      shortDate(
        genericValue(row, [
          "updatedAt",
          "updated_at",
          "modifiedTime",
          "lastEditedTime",
          "last_edited_time",
          "createdAt",
          "created_at",
          "date",
        ]),
      ),
    ]),
  });
}

const CONNECTOR_TABLE_BUILDERS: Record<
  string,
  (tool: string, output: Record<string, unknown>) => ConnectorResultBlock
> = {
  "gmail.search": gmailBlock,
  "calendar.list_events": calendarBlock,
  "drive.search": driveBlock,
};

/**
 * Legacy provider adapter. New provider-specific calls must use
 * `buildSourceTypedConnectorBlocks`; keeping this export prevents older stored
 * `connector_result` messages and focused compatibility tests from breaking.
 */
export function buildConnectorResultBlocks(
  results: AgentToolResult[],
): unknown[] {
  const blocks: unknown[] = [];
  for (const result of results) {
    if (!result.ok || !result.output) continue;
    const builder = CONNECTOR_TABLE_BUILDERS[result.tool];
    const block = builder
      ? builder(result.tool, result.output)
      : genericConnectorBlock(result.tool, result.output);
    if (block) blocks.push(block);
  }
  return blocks;
}

/**
 * Source-typed connector blocks are authoritative tool output. Persist them
 * before the optional prose-refinement pass so a timeout or provider failure
 * cannot turn a successful connector call into an empty "checking..." message.
 */
export function mergeAuthoritativeConnectorResultBlocks(
  existingBlocks: unknown[],
  connectorBlocks: unknown[],
): unknown[] {
  if (connectorBlocks.length === 0) return existingBlocks;
  const hasSourceTypedIncoming = connectorBlocks.some((block) => {
    const type = clipped(asRecord(block)?.type, 80);
    return isSourceWidgetBlockType(type);
  });
  const blockId = (block: unknown): string => {
    const record = asRecord(block);
    return clipped(record?.blockId ?? record?.stableBlockId, 240);
  };
  const incomingById = new Map<string, unknown>();
  for (const block of connectorBlocks) {
    const id = blockId(block);
    if (id) incomingById.set(id, block);
  }

  const merged: unknown[] = [];
  const emitted = new Set<string>();
  for (const existing of existingBlocks) {
    if (
      hasSourceTypedIncoming &&
      clipped(asRecord(existing)?.type, 80) === "connector_result"
    ) {
      continue;
    }
    const id = blockId(existing);
    const replacement = id ? incomingById.get(id) : undefined;
    if (replacement) {
      if (!emitted.has(id)) {
        merged.push(replacement);
        emitted.add(id);
      }
      continue;
    }
    merged.push(existing);
  }
  for (const incoming of connectorBlocks) {
    const id = blockId(incoming);
    if (id) {
      if (emitted.has(id)) continue;
      merged.push(incomingById.get(id) ?? incoming);
      emitted.add(id);
      continue;
    }
    // Legacy blocks predate blockId. Preserve them append-only; normal
    // production never emits this shape anymore.
    merged.push(incoming);
  }
  return merged;
}

export function connectorResultFallbackText(
  blocks: unknown[],
  results: AgentToolResult[] = [],
): string {
  const first = blocks.find(
    (block): block is Record<string, unknown> =>
      Boolean(block) && typeof block === "object" && !Array.isArray(block),
  );
  if (first) {
    const data = asRecord(first.data) ?? first;
    if (first.type === "mail_list") {
      const count = asRows(data.items).length;
      return count > 0
        ? `Gelen kutusu — ${count} e-posta`
        : "Gelen kutusunda eşleşen e-posta bulunamadı.";
    }
    if (first.type === "mail_detail") {
      if (data.state === "empty") return "E-posta içeriği boş.";
      const subject = clipped(data.subject, 500) || "(konu yok)";
      const sender = clipped(data.senderName, 240) || "Gönderen bilinmiyor";
      return `${subject} — ${sender}`;
    }
    if (first.type === "calendar_agenda") {
      const count = asRows(data.events).length;
      return count > 0
        ? `${count} takvim etkinliği hazır.`
        : "Bu aralıkta eşleşen takvim etkinliği bulunamadı.";
    }
    if (first.type === "drive_files") {
      const count = asRows(data.files).length;
      return count > 0
        ? `${count} Drive dosyası hazır.`
        : "Drive'da eşleşen dosya bulunamadı.";
    }
    if (first.type === "notion_page") {
      return data.state === "empty"
        ? "Notion'da eşleşen sayfa bulunamadı."
        : clipped(data.title, 500) || "Notion sayfası hazır.";
    }
    if (first.type === "github_activity") {
      const count = asRows(data.items).length;
      return count > 0
        ? `${count} GitHub kaydı hazır.`
        : "GitHub'da eşleşen kayıt bulunamadı.";
    }
    if (first.type === "slack_messages") {
      const count = asRows(data.messages).length;
      return count > 0
        ? `${count} Slack mesajı hazır.`
        : "Slack'te eşleşen mesaj bulunamadı.";
    }
    const title = str(first.title ?? data.title).trim();
    const summary = str(first.summary ?? data.summary).trim();
    const blockText = [title, summary].filter(Boolean).join(" — ");
    if (blockText) return blockText;
  }

  const successful = results.find((result) => result.ok && result.output);
  if (!successful?.output) return "Bağlı hesaptaki sonuçlar hazır.";
  if (successful.tool === "gmail.read") {
    // The block kill switch suppresses rendering, not sanitization. Reuse the
    // same adapter so a remote connector cannot inject raw HTML into prose.
    const detail = mailDetailBlock(successful.output);
    const data = asRecord(detail?.data);
    if (!data || data.state === "empty") return "E-posta içeriği boş.";
    const subject = clipped(data.subject, 500) || "(konu yok)";
    const from = clipped(data.senderName, 240) || "Gönderen bilinmiyor";
    const body = clipped(data.bodyRichText, 100_000);
    return [`${subject} — ${from}`, body].filter(Boolean).join("\n\n");
  }
  if (successful.tool === "gmail.search") {
    const count = firstRows(successful.output, ["results", "messages", "items"]).length;
    return count > 0
      ? `Gelen kutusu — ${count} e-posta`
      : "Gelen kutusunda eşleşen e-posta bulunamadı.";
  }
  if (successful.tool === "calendar.list_events") {
    const count = firstRows(successful.output, ["results", "events", "items"]).length;
    return count > 0
      ? `${count} takvim etkinliği hazır.`
      : "Bu aralıkta eşleşen takvim etkinliği bulunamadı.";
  }
  if (successful.tool === "drive.search") {
    const count = firstRows(successful.output, ["results", "files", "items"]).length;
    return count > 0
      ? `${count} Drive dosyası hazır.`
      : "Drive'da eşleşen dosya bulunamadı.";
  }
  if (successful.tool === "notion.search") {
    const count = firstRows(successful.output, ["results", "pages", "items"]).length;
    return count > 0
      ? `${count} Notion sayfası hazır.`
      : "Notion'da eşleşen sayfa bulunamadı.";
  }
  if (successful.tool === "github.search") {
    const count = firstRows(successful.output, ["results", "items"]).length;
    return count > 0
      ? `${count} GitHub kaydı hazır.`
      : "GitHub'da eşleşen kayıt bulunamadı.";
  }
  if (successful.tool === "slack.search") {
    const count = firstRows(successful.output, ["results", "messages", "items"]).length;
    return count > 0
      ? `${count} Slack mesajı hazır.`
      : "Slack'te eşleşen mesaj bulunamadı.";
  }
  return "Bağlı hesap isteği tamamlandı.";
}
