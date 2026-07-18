import { buildAssistantConnectorResultBlock } from "../chat/message-blocks.js";
import type { AgentToolResult } from "./tool-registry.js";

/**
 * Deterministically turn successful connector/MCP list-shaped tool results
 * into typed `connector_result` blocks so the mobile block-widget renders the
 * structured data natively instead of depending on the LLM to reformat JSON in
 * prose.
 *
 * The prose refinement still runs for the conversational summary; these blocks
 * are the authoritative structured surface merged alongside it. Only list-shaped
 * read results become widgets — single-message reads and write results stay in
 * the prose reply where a one-row widget would add nothing.
 */

type ConnectorResultBlock = ReturnType<typeof buildAssistantConnectorResultBlock>;

function asRows(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item),
      )
    : [];
}

function firstRows(
  output: Record<string, unknown>,
  keys: string[] = ["results", "items", "messages", "files", "events", "data", "records"],
): Record<string, unknown>[] {
  for (const key of keys) {
    const rows = asRows(output[key]);
    if (rows.length > 0) return rows;
  }
  return [];
}

function str(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
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
 * Build structured table blocks from the successful connector read results in a
 * turn. Non-list tools (gmail.read, writes) and failed calls yield nothing.
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
