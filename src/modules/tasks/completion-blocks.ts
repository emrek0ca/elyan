import type { VerifiedNumericPoint } from "../brain/deterministic-chart.js";
import type { ChartIntent } from "../brain/chart-intent-semantic.js";

/**
 * Asistan tamamlama blokları — turun nihai metnini ve tipli bloklarını kurar.
 *
 * `tasks/service.ts` içinden ÇIKARILDI. Taşıma saf: tek satır mantık
 * değişmedi. Bu küme oraya ait değildi — on beş fonksiyonun tamamı yalnız
 * birbirini çağırıyor ve dışarıdan tek bir giriş noktası var
 * (`resolveCompletionAssistantBlocks`). Dosyanın geri kalanı görev yaşam
 * döngüsüyken bu blok markdown ayrıştırma ve blok kurma işi yapıyor; aynı
 * dosyada olmaları tarihsel bir kaza.
 */

import {
  isExplicitChartRequest,
  isExplicitMathOrLatexRequest,
  isExplicitSvgRequest,
  shouldPromoteMarkdownTableToWidget,
} from "../../core/understanding/structured-output-policy.js";
import {
  asRecord as readRecord,
} from "../../lib/record.js";
import {
  chartIntentFromEvidence,
  resolveChartIntent,
} from "../brain/chart-intent-semantic.js";
import {
  deriveChartBlock,
  deriveTableBlock,
} from "../brain/deterministic-chart.js";
import {
  buildAssistantCodeBlock,
  buildAssistantDocumentBlock,
  buildAssistantBlockGroup,
  buildAssistantNextStepsBlock,
  buildAssistantTableBlock,
  normalizeAssistantMessageBlocks,
} from "../chat/message-blocks.js";
import { coerceFiniteNumber } from "../chat/chart-data.js";

function isMarkdownTableDivider(line: string) {
  const normalized = line.trim();
  if (!normalized.includes("|")) {
    return false;
  }
  const cells = normalized
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
  return (
    cells.length > 0 &&
    cells.every((cell) => cell.length > 0 && /^:?-{3,}:?$/.test(cell))
  );
}

function splitMarkdownTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

// Extract the first code fence from response markdown.
// Returns a typed code block AND the matched source span so the caller can
// strip it from the visible text (avoids the "code shown twice" duplication —
// once as markdown, once as the code widget).
function extractMarkdownCodeBlock(responseText: string) {
  const text = String(responseText ?? "");
  const match = /```(\w*)\n([\s\S]+?)```/.exec(text);
  if (!match) return null;
  const language = match[1].trim() || undefined;
  const code = match[2].trim();
  if (!code) return null;
  return {
    block: buildAssistantCodeBlock({ code, language }),
    source: match[0],
  };
}

// Extract structured document sections from responses with 3+ markdown headings.
// This activates the mobile document_block widget (PDF preview + share).
function extractMarkdownDocumentBlock(responseText: string) {
  const text = String(responseText ?? "").replace(/\r\n?/g, "\n");
  const lines = text.split("\n");

  const sections: Array<{ heading?: string; content: string; level: number }> =
    [];
  let currentHeading: string | undefined;
  let currentLevel = 1;
  let currentLines: string[] = [];
  let headingCount = 0;

  const flush = () => {
    const content = currentLines.join("\n").trim();
    if (content || currentHeading) {
      sections.push({ heading: currentHeading, content, level: currentLevel });
    }
    currentLines = [];
  };

  for (const line of lines) {
    const hMatch = /^(#{1,3})\s+(.+)/.exec(line.trim());
    if (hMatch) {
      flush();
      currentLevel = hMatch[1].length;
      currentHeading = hMatch[2].trim();
      headingCount += 1;
    } else {
      currentLines.push(line);
    }
  }
  flush();

  // Only extract when there are enough real sections with content
  const validSections = sections.filter(
    (s) => s.content.length > 0 || s.heading,
  );
  if (headingCount < 2 || validSections.length === 0) return null;

  const totalWords = validSections.reduce(
    (sum, s) => sum + s.content.split(/\s+/).filter(Boolean).length,
    0,
  );
  if (totalWords < 60) return null;

  // Treat the first section without heading as document title if it's short
  let title: string | undefined;
  const firstSection = validSections[0];
  if (
    !firstSection.heading &&
    firstSection.content.length < 120 &&
    validSections.length > 1
  ) {
    title = firstSection.content.split("\n")[0]?.trim();
    validSections.shift();
  } else if (
    firstSection.heading &&
    validSections.every((s) => s.level >= firstSection.level)
  ) {
    title = firstSection.heading;
    firstSection.heading = undefined;
  }

  const wordCount = validSections.reduce(
    (sum, s) =>
      sum +
      (s.heading ?? "").split(/\s+/).length +
      s.content.split(/\s+/).filter(Boolean).length,
    0,
  );

  // Document widget renders the full content — the raw text is redundant
  // alongside it, so signal "consume the whole response".
  return {
    block: buildAssistantDocumentBlock({
      title,
      sections: validSections,
      format: "report",
      wordCount,
    }),
    source: text,
  };
}

function extractMarkdownTableBlock(responseText: string) {
  const normalized = String(responseText ?? "").replace(/\r\n?/g, "\n");
  const lines = normalized.split("\n");
  for (let index = 0; index <= lines.length - 3; index += 1) {
    const headerLine = lines[index]?.trim() ?? "";
    const dividerLine = lines[index + 1]?.trim() ?? "";
    if (!headerLine.includes("|") || !isMarkdownTableDivider(dividerLine)) {
      continue;
    }
    const columns = splitMarkdownTableRow(headerLine);
    if (columns.length === 0) {
      continue;
    }

    const rows: string[][] = [];
    let lastRow = index + 1; // divider line
    for (let rowIndex = index + 2; rowIndex < lines.length; rowIndex += 1) {
      const rowLine = lines[rowIndex]?.trim() ?? "";
      if (!rowLine || !rowLine.includes("|")) {
        break;
      }
      if (isMarkdownTableDivider(rowLine)) {
        lastRow = rowIndex;
        continue;
      }
      const row = splitMarkdownTableRow(rowLine);
      if (row.length !== columns.length) {
        break;
      }
      rows.push(row);
      lastRow = rowIndex;
    }

    if (rows.length === 0) {
      continue;
    }

    // Source span = headerLine .. lastRow (joined back). Caller strips this
    // from the visible text so the table is not also rendered as markdown.
    const source = lines.slice(index, lastRow + 1).join("\n");
    return {
      block: buildAssistantTableBlock({ columns, rows }),
      source,
    };
  }

  return null;
}

// Some model outputs come back as a single bare JSON object whose `type` is
// one of our known structured block types. Render them as a real block widget
// instead of leaking JSON as plain text.
const STRUCTURED_BLOCK_TYPES = new Set<string>([
  "status",
  "summary",
  "next_steps",
  "desktop_suggestion",
  "actionable",
  "attachment_context",
  "context_signal",
  "memory_echo",
  "table",
  "chart",
  "math",
  "svg",
  "document_block",
]);

/**
 * Splits a response that starts with a single typed-block JSON object from any
 * trailing prose. Models prompted with "emit a status block, then write your
 * reply" return both in one turn (e.g.
 *   {"type":"status","status":"needs_desktop",...}\nMasaüstünüzdeki dosya…
 * ). The previous bare-only extractor missed this hybrid shape because the
 * string did not end in "}", and the raw JSON leaked into chat (prod bug).
 *
 * Approach: walk balanced braces from the first "{" to locate the boundary,
 * parse just that slice, and return both the block and any remaining text.
 * Quote/escape aware so braces inside strings cannot fool the depth counter.
 */
function extractLeadingJsonBlock(
  responseText: string,
): { block: Record<string, unknown>; rest: string } | null {
  const text = String(responseText ?? "");
  const start = text.indexOf("{");
  if (start === -1) return null;
  // Only treat it as a leading block when nothing meaningful precedes the "{".
  if (text.slice(0, start).trim().length > 0) return null;

  let depth = 0;
  let inString = false;
  let escape = false;
  let end = -1;
  for (let i = start; i < text.length; i += 1) {
    const ch = text[i];
    if (escape) {
      escape = false;
      continue;
    }
    if (ch === "\\") {
      escape = true;
      continue;
    }
    if (ch === '"') {
      inString = !inString;
      continue;
    }
    if (inString) continue;
    if (ch === "{") depth += 1;
    else if (ch === "}") {
      depth -= 1;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  if (end === -1) return null;

  const candidate = text.slice(start, end + 1);
  try {
    const parsed = JSON.parse(candidate) as Record<string, unknown>;
    const type = String(parsed?.type ?? "")
      .trim()
      .toLowerCase();
    if (!STRUCTURED_BLOCK_TYPES.has(type)) return null;
    return { block: parsed, rest: text.slice(end + 1).trimStart() };
  } catch {
    return null;
  }
}

function shouldAcceptStructuredBlock(input: {
  block: Record<string, unknown>;
  prompt?: string | null;
  selectedWorkload?: string | null;
}) {
  const type = String(input.block.type ?? "")
    .trim()
    .toLowerCase();
  const selectedWorkload = String(input.selectedWorkload ?? "")
    .trim()
    .toLowerCase();
  // SUNUCU TÜRETMESİ NİYET FİLTRESİNİN ÜSTÜNDEDİR.
  //
  // Bu blok modelin serbest çıktısı değil; sunucunun SEMANTİK bir niyet
  // kararından sonra deterministik olarak ürettiği veridir. Aşağıdaki
  // kapılar hâlâ kelime desenine bakıyor; onlara sormak, az önce "bu turda
  // grafik isteniyor" diye verilmiş semantik kararı bir kelime listesiyle
  // iptal etmek olurdu — ve türetilen grafik tam burada sessizce silinirdi.
  const derivedBy = readRecord(input.block.renderHints)?.derivedBy;
  if (typeof derivedBy === "string" && derivedBy.startsWith("server_")) {
    return true;
  }
  if (type === "table") {
    return shouldPromoteMarkdownTableToWidget({
      prompt: input.prompt,
      selectedWorkload: input.selectedWorkload,
    });
  }
  if (type === "chart") {
    return isExplicitChartRequest(input.prompt ?? "");
  }
  if (type === "svg") {
    return isExplicitSvgRequest(input.prompt ?? "");
  }
  if (type === "math") {
    return isExplicitMathOrLatexRequest(input.prompt ?? "");
  }
  if (type === "document_block") {
    return selectedWorkload === "document_generate";
  }
  return true;
}

function filterAssistantBlocksByIntent(input: {
  blocks: unknown[];
  prompt?: string | null;
  selectedWorkload?: string | null;
}) {
  return input.blocks.filter((block) => {
    if (!block || typeof block !== "object" || Array.isArray(block)) {
      return true;
    }
    return shouldAcceptStructuredBlock({
      block: block as Record<string, unknown>,
      prompt: input.prompt,
      selectedWorkload: input.selectedWorkload,
    });
  });
}

function cleanInlineMarkdown(value: unknown, maxLength = 160) {
  return String(value ?? "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, maxLength);
}

function structuredBlockToPlainFallback(
  block: Record<string, unknown>,
): string {
  const type = String(block.type ?? "")
    .trim()
    .toLowerCase();
  if (type !== "table") {
    return "";
  }
  const columns = Array.isArray(block.columns)
    ? block.columns
        .map((column) => cleanInlineMarkdown(column, 80))
        .filter(Boolean)
    : [];
  const rows = Array.isArray(block.rows) ? block.rows.slice(0, 12) : [];
  if (columns.length === 0 || rows.length === 0) {
    return "";
  }
  const title = cleanInlineMarkdown(block.title, 120);
  const lines = title ? [`${title}:`] : [];
  for (const rawRow of rows) {
    const row = Array.isArray(rawRow)
      ? rawRow
      : rawRow && typeof rawRow === "object" && !Array.isArray(rawRow)
        ? Object.values(rawRow as Record<string, unknown>)
        : [];
    const cells = row.map((cell) => cleanInlineMarkdown(cell, 140));
    const head = cells[0];
    if (!head) {
      continue;
    }
    const details = cells
      .slice(1, columns.length)
      .map((cell, index) => {
        const label = columns[index + 1] ?? "";
        return cell ? `${label ? `${label}: ` : ""}${cell}` : "";
      })
      .filter(Boolean)
      .join("; ");
    lines.push(`- ${head}${details ? `: ${details}` : ""}`);
  }
  return lines.join("\n");
}

function stripDanglingStructuredJsonTail(text: string): string {
  const value = String(text ?? "");
  const lastBrace = Math.max(value.lastIndexOf("{"), value.lastIndexOf("["));
  if (lastBrace < 0) {
    return value;
  }

  const tail = value.slice(lastBrace).trim();
  if (!tail || /[}\]]$/.test(tail)) {
    return value;
  }
  const opener = value[lastBrace];
  if (
    (opener === "{" && tail.includes("}")) ||
    (opener === "[" && tail.includes("]"))
  ) {
    return value;
  }

  try {
    JSON.parse(tail);
    return value;
  } catch {
    const prefix = value.slice(0, lastBrace).trimEnd();
    const cleaned = prefix.replace(/[,\s:;]+$/u, "").trimEnd();
    return cleaned || prefix;
  }
}

type ExtractedPlanningList = {
  items: string[];
  sourceLines: string[];
};

/**
 * Planning is the one workload where a short prose acknowledgement is not a
 * sufficient completion. This extractor only promotes an explicit ordered or
 * bulleted list already written by the model; it never invents steps from
 * keywords or from a session title.
 */
function extractExplicitPlanningList(value: string): ExtractedPlanningList | null {
  const items: string[] = [];
  const sourceLines: string[] = [];
  const seen = new Set<string>();
  for (const line of value.split("\n")) {
    const match = line.match(/^\s*(?:(?:\d+)[.)-]|[-*•])\s+(.+?)\s*$/u);
    const item = match?.[1]?.replace(/\s+/g, " ").trim();
    if (!item || item.length < 3) continue;
    const key = item.toLocaleLowerCase("tr-TR");
    if (seen.has(key)) continue;
    seen.add(key);
    items.push(item.slice(0, 240));
    sourceLines.push(line);
    if (items.length >= 6) break;
  }
  return items.length >= 3 ? { items, sourceLines } : null;
}

function numericToken(value: unknown): number | null {
  return coerceFiniteNumber(value);
}

function collectNumericValues(value: unknown, output: number[] = []): number[] {
  if (output.length >= 240) return output;
  const direct = numericToken(value);
  if (direct != null) {
    output.push(direct);
    return output;
  }
  if (Array.isArray(value)) {
    for (const item of value) collectNumericValues(item, output);
    return output;
  }
  const record = readRecord(value);
  if (record) {
    for (const nested of Object.values(record)) {
      collectNumericValues(nested, output);
    }
  }
  return output;
}

function numericEvidenceValues(input: {
  prompt?: string | null;
  contextTexts?: Array<string | null | undefined>;
}): number[] {
  return [input.prompt ?? "", ...(input.contextTexts ?? [])]
    .flatMap((value) =>
      String(value ?? "")
        .match(/-?\d+(?:[.,]\d+)?/gu)
        ?.map(numericToken)
        .filter((item): item is number => item != null) ?? [],
    );
}

function isNumericBlockGrounded(input: {
  block: unknown;
  numericPoints?: VerifiedNumericPoint[];
  prompt?: string | null;
  contextTexts?: Array<string | null | undefined>;
}): boolean {
  const record = readRecord(input.block);
  const type = String(record?.type ?? "");
  if (type !== "table" && type !== "chart") return true;
  if (String(readRecord(record?.renderHints)?.derivedBy ?? "").startsWith("server_")) {
    return true;
  }
  const values = collectNumericValues(
    type === "table"
      ? record?.rows
      : [record?.values, record?.points, record?.data, record?.series],
  );
  if (values.length === 0) return true;
  if ((input.numericPoints?.length ?? 0) >= 2) return true;
  const evidence = numericEvidenceValues(input);
  return values.every((value) =>
    evidence.some((candidate) => Math.abs(candidate - value) < 1e-9),
  );
}

function deterministicNumericComparison(input: {
  prompt?: string | null;
  numericPoints?: VerifiedNumericPoint[];
}): string | null {
  const points = input.numericPoints ?? [];
  if (points.length < 2) return null;
  const prompt = String(input.prompt ?? "").toLocaleLowerCase("tr-TR");
  const asksHighest = /(?<!\p{L})(en yüksek|en yuksek|en fazla|maksimum|maximum|highest|max)(?!\p{L})/iu.test(prompt);
  const asksLowest = /(?<!\p{L})(en düşük|en dusuk|en az|minimum|lowest|min)(?!\p{L})/iu.test(prompt);
  if (!asksHighest && !asksLowest) return null;
  const selected = points.reduce((best, point) =>
    asksLowest
      ? point.value < best.value
        ? point
        : best
      : point.value > best.value
        ? point
        : best,
  );
  const value = selected.value.toLocaleString("tr-TR", {
    maximumFractionDigits: 6,
  });
  return `${asksLowest ? "En düşük" : "En yüksek"} değer ${selected.label}: ${value}.`;
}

function stripUnfulfilledChartPromise(value: string): string {
  return value
    .split(/(?<=[.!?])\s+/u)
    .filter(
      (sentence) =>
        !(
          /(?<!\p{L})(işte|iste|hazır|hazir|oluşturdum|olusturdum|çizdim|cizdim|gösterdim|gosterdim)(?:\s+\S+){0,3}\s+(grafik|grafiği|grafigi|chart)(?!\p{L})/iu.test(
            sentence,
          ) ||
          /(?<!\p{L})(grafik|grafiği|grafigi|chart)(?:\s+\S+){0,2}\s+(hazır|hazir|oluşturdum|olusturdum|çizdim|cizdim|gösterdim|gosterdim)(?!\p{L})/iu.test(
            sentence,
          ) ||
          /(?<!\p{L})(işte|iste)\s+(trend|dağılım|dagilim|görünüm|gorunum)(?!\p{L})/iu.test(
            sentence,
          )
        ),
    )
    .join(" ")
    .trim();
}

export function resolveCompletionAssistantBlocks(input: {
  responseText: string;
  assistantBlocks?: unknown[];
  prompt?: string | null;
  selectedWorkload?: string | null;
  planIntent?: boolean;
  /**
   * Sohbet bağlamı, EN YENİ mesaj başta. "Bir polinom yaz" → "grafiğini çiz"
   * akışında ifade istekte değil, önceki asistan mesajındadır.
   */
  contextTexts?: Array<string | null | undefined>;
  /** Web grounding / araç katmanından gelen doğrulanmış sayısal seri. */
  numericPoints?: VerifiedNumericPoint[];
  /**
   * SEMANTİK grafik niyeti (`resolveChartIntent`). Verildiğinde karar
   * BUDUR — kelime deseni değil. Verilmediğinde kanıta düşülür: bağlamda
   * gerçekten çizilebilir bir ifade ya da sayısal seri var mı?
   */
  chartIntent?: ChartIntent;
}): { blocks: unknown[]; text: string } {
  let assistantBlocks = filterAssistantBlocksByIntent({
    blocks: Array.isArray(input.assistantBlocks)
      ? [...input.assistantBlocks]
      : [],
    prompt: input.prompt,
    selectedWorkload: input.selectedWorkload,
  });
  const normalizedBlocks = normalizeAssistantMessageBlocks({
    blocks: assistantBlocks,
  });

  const hasTableBlock = normalizedBlocks.some((b) => b.type === "table");
  const hasCodeBlock = normalizedBlocks.some((b) => b.type === "code");
  const hasDocumentBlock = normalizedBlocks.some(
    (b) => b.type === "document_block",
  );

  // Normalize line endings first — extractor sources are reconstructed from
  // LF-only lines, so `text.split(source)` would never match CRLF content
  // and the duplicate markdown would remain in chat (bug seen in prod).
  let text = String(input.responseText ?? "").replace(/\r\n?/g, "\n");
  const sourcesToStrip: string[] = [];

  if (input.planIntent === true) {
    const hasCompleteNextSteps = normalizedBlocks.some((block) => {
      if (block.type !== "next_steps") return false;
      const items = (block as { items?: unknown }).items;
      return Array.isArray(items) && items.length >= 3;
    });
    if (!hasCompleteNextSteps) {
      assistantBlocks = assistantBlocks.filter((candidate) => {
        const record = readRecord(candidate);
        if (record?.type !== "next_steps") return true;
        const data = readRecord(record.data);
        const items = record.items ?? data?.items;
        return !Array.isArray(items) || items.length >= 3;
      });
      const explicitList = extractExplicitPlanningList(text);
      const nextSteps = explicitList
        ? buildAssistantNextStepsBlock(explicitList.items, {
            title: "Sonraki adımlar",
            priority: 2,
          })
        : null;
      if (nextSteps) {
        assistantBlocks.push(nextSteps);
        sourcesToStrip.push(...explicitList!.sourceLines);
      }
    }
  }

  // Extract markdown table if model didn't produce a typed table block.
  // The model sometimes emits more than one markdown table in a single reply
  // (e.g. a full data table followed by a truncated variant). Loop until no
  // further table shows up so none stays as raw markdown that would render
  // as a second, duplicate-looking table on the client.
  if (
    !hasTableBlock &&
    shouldPromoteMarkdownTableToWidget({
      prompt: input.prompt,
      selectedWorkload: input.selectedWorkload,
    })
  ) {
    let scan = text;
    while (true) {
      const parsedTable = extractMarkdownTableBlock(scan);
      if (!parsedTable) break;
      assistantBlocks.push(parsedTable.block);
      sourcesToStrip.push(parsedTable.source);
      // Continue scanning after the extracted span so a second table on the
      // same page is picked up too, without re-matching the first one.
      const idx = scan.indexOf(parsedTable.source);
      if (idx < 0) break;
      scan = scan.slice(idx + parsedTable.source.length);
    }
  }

  // Extract code fences → syntax-highlighted code block for mobile
  if (!hasCodeBlock) {
    const parsedCode = extractMarkdownCodeBlock(text);
    if (parsedCode) {
      assistantBlocks.push(parsedCode.block);
      sourcesToStrip.push(parsedCode.source);
    }
  }

  // Extract structured headings → document_block (PDF preview + share on mobile)
  // Only when no other rich block is present to avoid double-rendering
  if (!hasDocumentBlock && !hasTableBlock) {
    const parsedDoc = extractMarkdownDocumentBlock(text);
    if (parsedDoc) {
      assistantBlocks.push(parsedDoc.block);
      sourcesToStrip.push(parsedDoc.source);
    }
  }

  // The model often emits a typed-block JSON (e.g. status:needs_desktop) at the
  // start of its turn, sometimes ALONE and sometimes followed by a prose reply.
  // Promote the JSON to a typed block and keep only the trailing prose as
  // visible text — otherwise the raw JSON leaks into chat as plain text.
  const leadingJson = extractLeadingJsonBlock(text);
  if (leadingJson) {
    const acceptLeadingBlock = shouldAcceptStructuredBlock({
      block: leadingJson.block,
      prompt: input.prompt,
      selectedWorkload: input.selectedWorkload,
    });
    if (acceptLeadingBlock) {
      assistantBlocks.push(leadingJson.block);
      text = leadingJson.rest;
    } else {
      const fallback = structuredBlockToPlainFallback(leadingJson.block);
      text = [fallback, leadingJson.rest]
        .map((part) => part.trim())
        .filter(Boolean)
        .join("\n\n");
    }
  }

  // DETERMİNİSTİK GRAFİK/TABLO (A1/A4).
  //
  // Model yapısal çıktı üretemediğinde tur `continuity fallback`'e düşüyor ve
  // kullanıcı grafik yerine özür görüyordu. Oysa grafiğin verisi sunucuda
  // zaten var: ya bağlamdaki matematiksel ifade, ya cevabın kendi markdown
  // tablosu, ya da web grounding'in doğrulanmış sayısal serisi. Model
  // emisyonu BİRİNCİL, bu türetme İKİNCİL — yalnız blok gerçekten yoksa
  // devreye girer.
  const hasChartLikeBlock = assistantBlocks.some((block) => {
    const type = String(readRecord(block)?.type ?? "");
    return type === "chart" || type === "math_surface_3d";
  });
  // Niyet SEMANTİK gelir; gelmediyse kelimeye değil KANITA bakılır
  // (bağlamda çizilebilir ifade / doğrulanmış sayısal seri var mı?).
  const chartIntent =
    input.chartIntent ??
    chartIntentFromEvidence({
      prompt: input.prompt ?? "",
      contextTexts: input.contextTexts,
      numericPointCount: input.numericPoints?.length ?? 0,
    });
  if (!hasChartLikeBlock && chartIntent.wantsChart) {
    const derivedChart = deriveChartBlock({
      prompt: input.prompt ?? "",
      responseText: text,
      contextTexts: input.contextTexts,
      numericPoints: input.numericPoints,
      preferredChartType: chartIntent.family === "surface" ? "surface3d" : null,
    });
    if (derivedChart) {
      assistantBlocks.push(derivedChart);
    }
  }
  const hasTableBlockNow = assistantBlocks.some(
    (block) => String(readRecord(block)?.type ?? "") === "table",
  );
  if (
    !hasTableBlockNow &&
    (input.numericPoints?.length ?? 0) >= 2 &&
    shouldPromoteMarkdownTableToWidget({
      prompt: input.prompt,
      selectedWorkload: input.selectedWorkload,
    })
  ) {
    const derivedTable = deriveTableBlock({
      prompt: input.prompt ?? "",
      responseText: text,
      numericPoints: input.numericPoints,
    });
    if (derivedTable) {
      assistantBlocks.push(derivedTable);
    }
  }

  // Explicit user/tool numeric points outrank a partial model table. Rebuild
  // the requested widget so omitted rows cannot pass schema validation as a
  // complete answer.
  if (
    (input.numericPoints?.length ?? 0) >= 2 &&
    shouldPromoteMarkdownTableToWidget({
      prompt: input.prompt,
      selectedWorkload: input.selectedWorkload,
    })
  ) {
    const derivedTable = deriveTableBlock({
      prompt: input.prompt ?? "",
      responseText: text,
      numericPoints: input.numericPoints,
    });
    if (derivedTable) {
      assistantBlocks = assistantBlocks.filter(
        (block) => String(readRecord(block)?.type ?? "") !== "table",
      );
      assistantBlocks.push(derivedTable);
    }
  }

  // Strip every extracted span so the inline text doesn't duplicate the widget.
  for (const span of sourcesToStrip) {
    if (!span) continue;
    text = text.split(span).join("");
  }
  // Collapse leftover blank lines from the strips.
  text = stripDanglingStructuredJsonTail(
    text.replace(/\n{3,}/g, "\n\n").trim(),
  );

  const normalizedCompletionBlocks = normalizeAssistantMessageBlocks({
    blocks: filterAssistantBlocksByIntent({
      blocks: assistantBlocks,
      prompt: input.prompt,
      selectedWorkload: input.selectedWorkload,
    }).filter((block) =>
      isNumericBlockGrounded({
        block,
        numericPoints: input.numericPoints,
        prompt: input.prompt,
        contextTexts: input.contextTexts,
      }),
    ),
  });
  const surfacePriority = (block: { type: string }) => {
    if (["clarification", "approval_needed", "actionable", "proactive_touch"].includes(block.type)) return 6;
    if (["dispatch_widget", "task_trace", "goal_progress", "status", "tool_call"].includes(block.type)) return 5;
    if (["artifact", "file", "pdf_generate", "pdf_viewer"].includes(block.type)) return 4;
    if (["table", "chart", "math_surface_3d"].includes(block.type)) return 3;
    if (["web_search", "connector_result", "mail_list", "calendar_agenda", "drive_files", "notion_page", "github_activity", "slack_messages"].includes(block.type)) return 2;
    return 1;
  };
  const blocks = normalizedCompletionBlocks.length <= 3
    ? normalizedCompletionBlocks
    : (() => {
        const ranked = normalizedCompletionBlocks
          .map((block, index) => ({ block, index, priority: surfacePriority(block) }))
          .sort((left, right) => right.priority - left.priority || left.index - right.index);
        const primary = ranked.slice(0, 2).sort((left, right) => left.index - right.index);
        const overflow = ranked.slice(2).sort((left, right) => left.index - right.index);
        const detail = buildAssistantBlockGroup(
          overflow.map((item) => item.block),
          { title: "Ayrıntılar", renderHints: { density: "compact", sectionRole: "detail" } },
        );
        return [...primary.map((item) => item.block), ...(detail ? [detail] : [])];
      })();
  const comparison = deterministicNumericComparison(input);
  if (comparison) text = comparison;
  if (
    chartIntent.wantsChart &&
    !blocks.some((block) =>
      ["chart", "math_surface_3d"].includes(String(block.type)),
    )
  ) {
    text = stripUnfulfilledChartPromise(text);
    if (!text) {
      text = "Grafik oluşturmak için doğrulanmış sayısal veri bulunamadı.";
    }
  }
  return {
    blocks,
    text,
  };
}
