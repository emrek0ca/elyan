import { buildAssistantTableBlock } from "../chat/message-blocks.js";
import type { AgentToolResult } from "./tool-registry.js";

/**
 * Deterministically turn successful connector (Gmail/Calendar/Drive) tool
 * results into typed `table` blocks so the mobile block-widget renders the
 * structured data natively (sort/copy/share/fullscreen) instead of depending on
 * the LLM to reformat the JSON into a markdown table in prose.
 *
 * The prose refinement still runs for the conversational summary; these blocks
 * are the authoritative structured surface merged alongside it. Only list-shaped
 * read results become tables — single-message reads and write results stay in
 * the prose reply where a one-row table would add nothing.
 */

type TableBlock = ReturnType<typeof buildAssistantTableBlock>;

function asRows(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item),
      )
    : [];
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

function gmailTable(output: Record<string, unknown>): TableBlock {
  const rows = asRows(output.results);
  if (rows.length === 0) return null;
  return buildAssistantTableBlock({
    title: "Gelen kutusu",
    columns: ["Kimden", "Konu", "Tarih"],
    rows: rows.map((row) => [
      displayFrom(row.from),
      str(row.subject) || "(konu yok)",
      shortDate(row.date),
    ]),
    summary: `${rows.length} e-posta`,
  });
}

function calendarTable(output: Record<string, unknown>): TableBlock {
  const rows = asRows(output.results);
  if (rows.length === 0) return null;
  return buildAssistantTableBlock({
    title: "Yaklaşan etkinlikler",
    columns: ["Başlık", "Başlangıç", "Bitiş", "Yer"],
    rows: rows.map((row) => [
      str(row.title) || "(başlıksız)",
      shortDate(row.start),
      shortDate(row.end),
      str(row.location),
    ]),
    summary: `${rows.length} etkinlik`,
  });
}

function driveTable(output: Record<string, unknown>): TableBlock {
  const rows = asRows(output.results);
  if (rows.length === 0) return null;
  return buildAssistantTableBlock({
    title: "Drive dosyaları",
    columns: ["Ad", "Tür", "Değiştirilme"],
    rows: rows.map((row) => [
      str(row.name),
      driveTypeLabel(row.mimeType),
      shortDate(row.modifiedTime),
    ]),
    summary: `${rows.length} dosya`,
  });
}

const CONNECTOR_TABLE_BUILDERS: Record<
  string,
  (output: Record<string, unknown>) => TableBlock
> = {
  "gmail.search": gmailTable,
  "calendar.list_events": calendarTable,
  "drive.search": driveTable,
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
    if (!builder) continue;
    const block = builder(result.output);
    if (block) blocks.push(block);
  }
  return blocks;
}
