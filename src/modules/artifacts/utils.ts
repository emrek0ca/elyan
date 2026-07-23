import { createHash, randomUUID } from "node:crypto";

export function compactText(value: unknown): string {
  return String(value ?? "")
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function normalizeLocale(value: unknown): string {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (normalized === "en" || normalized.startsWith("en-")) {
    return "en";
  }
  return "tr";
}

export function stableArtifactId(input: { type: string; text: string; taskId?: string | null }): string {
  const digest = createHash("sha256")
    .update(`${input.type}:${input.taskId ?? ""}:${input.text}`)
    .digest("hex")
    .slice(0, 18);
  return `artifact_${digest || randomUUID()}`;
}

export function normalizeKey(value: unknown): string {
  const base = compactText(value)
    .toLocaleLowerCase("tr-TR")
    .replace(/[İIı]/g, "i")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^\p{L}\p{N}]+/gu, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");
  return base || "value";
}

export function safeFileSlug(value: unknown): string {
  const slug = normalizeKey(value).slice(0, 80);
  return slug || "elyan-cikti";
}

export function parseNumericValue(raw: unknown): number | null {
  const value = compactText(raw)
    .replace(/[₺$€]/g, "")
    .replace(/\s+/g, "");
  if (!value) {
    return null;
  }
  let normalized = value;
  if (normalized.includes(",") && normalized.includes(".")) {
    normalized = normalized.replace(/\./g, "").replace(",", ".");
  } else if (/^\d{1,3}(?:\.\d{3})+$/.test(normalized)) {
    normalized = normalized.replace(/\./g, "");
  } else if (normalized.includes(",") && !normalized.includes(".")) {
    normalized = normalized.replace(",", ".");
  }
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

export function normalizeCurrency(raw: unknown): "TRY" | "USD" | "EUR" | "unknown" {
  const value = compactText(raw).toLocaleLowerCase("tr-TR");
  if (value === "tl" || value === "try" || value === "₺") return "TRY";
  if (value === "usd" || value === "$") return "USD";
  if (value === "eur" || value === "€") return "EUR";
  return "unknown";
}

export function formatMoney(amount: number, currency = "TRY", locale = "tr-TR"): string {
  const formatted = new Intl.NumberFormat(locale, {
    maximumFractionDigits: Number.isInteger(amount) ? 0 : 2,
  }).format(amount);
  return currency === "TRY" ? `${formatted} TL` : `${formatted} ${currency}`;
}

export function escapeMarkdownTableCell(value: unknown): string {
  return String(value ?? "")
    .replace(/\r?\n/g, " ")
    .replace(/\|/g, "\\|")
    .trim();
}

export type ExtractedMoney = {
  label: string;
  amount: number;
  rawAmount: string;
  currency: "TRY" | "USD" | "EUR" | "unknown";
  isTotal: boolean;
};

function cleanMoneyLabel(value: string): string {
  return compactText(value)
    .replace(/^[,.;:\s-]+/, "")
    .replace(/\b(?:ve|ile)$/i, "")
    .replace(/^(?:toplam\s+)(?=\d+\s*\p{L})/iu, "")
    .replace(/^(?:toplam\s+)(?!$)/iu, (match) => match.trim().toLocaleLowerCase("tr-TR") === "toplam" ? match : "")
    .replace(/[=:]$/u, "")
    .trim();
}

export function extractMoneyItems(text: string): ExtractedMoney[] {
  const items: ExtractedMoney[] = [];
  const pattern =
    /(?<label>[\p{L}\p{N}\s%.,/()_-]{2,90}?)(?:=|:)?\s*(?<amount>(?:₺|\$|€)?\s*\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(?<currency>tl|try|₺|usd|\$|eur|€)\b/giu;
  for (const match of text.matchAll(pattern)) {
    const amount = parseNumericValue(match.groups?.amount ?? "");
    if (amount == null) {
      continue;
    }
    const rawLabel = cleanMoneyLabel(match.groups?.label ?? "");
    const normalizedLabel = rawLabel.toLocaleLowerCase("tr-TR");
    const isTotal =
      /\b(genel\s+toplam|grand\s+total|total)\b/i.test(normalizedLabel) ||
      normalizedLabel === "toplam";
    const label = isTotal
      ? rawLabel || "Genel toplam"
      : rawLabel.replace(/^toplam\s+/iu, "").trim() || "Kalem";
    items.push({
      label,
      amount,
      rawAmount: compactText(`${match.groups?.amount ?? ""} ${match.groups?.currency ?? ""}`),
      currency: normalizeCurrency(match.groups?.currency),
      isTotal,
    });
  }

  const seen = new Set<string>();
  return items.filter((item) => {
    const key = `${item.label}:${item.amount}:${item.currency}:${item.isTotal}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 80);
}

export type ExtractedDataPoint = {
  label: string;
  value: number;
  rawValue: string;
  currency: "TRY" | "USD" | "EUR" | "unknown";
};

export function extractRequestedTableColumns(text: string): string[] {
  const normalized = compactText(text);
  const captures = [
    /(?:kolonları|kolonlari|kolonlar|sütunları|sutunlari|sütunlar|sutunlar|columns?)\s*(?:şunlar\s+olsun|sunlar\s+olsun|olsun|olarak)?\s*[:：]\s*([^\n.]+)/iu,
    /(?:şu|su)\s+(?:kolonlarla|sütunlarla|sutunlarla)\s+(.+?)\s+(?:excel|tablo|xlsx|oluştur|olustur|hazırla|hazirla)/iu,
    /([\p{L}][\p{L}\p{N}_-]*(?:\s*(?:,|\bve\b|\band\b|&)\s*[\p{L}][\p{L}\p{N}_-]*)+)\s+(?:kolonlarıyla|kolonlariyla|sütunlarıyla|sutunlariyla|kolonlarla|sütunlarla|sutunlarla)/iu,
  ];
  let captured = "";
  for (const pattern of captures) {
    const match = pattern.exec(normalized);
    if (match?.[1]) {
      captured = compactText(match[1]);
      break;
    }
  }
  if (!captured) return [];
  return captured
    .split(/\s*(?:,|;|\||\bve\b|\band\b|&)\s*/iu)
    .map((item) => compactText(item).replace(/^["'“”‘’]+|["'“”‘’.,;:\s]+$/g, ""))
    .filter((item) => item.length > 0)
    .slice(0, 16);
}

export function extractExplicitNumericSequence(text: string): number[] {
  const match = /(?<values>-?\d+(?:[.,]\d+)?(?:\s*(?:,|\bve\b|\band\b)\s*-?\d+(?:[.,]\d+)?){1,40})\s+(?:sayı(?:lar)?(?:ının|in|ları|lar)?|numbers?)/iu.exec(
    compactText(text),
  );
  if (!match?.groups?.values) return [];
  const rawValues = match.groups.values
    .split(/\s*(?:,|\bve\b|\band\b)\s*/iu)
    .filter(Boolean);
  const values = rawValues
    .map((value) => Number(value.replace(",", ".")))
    .filter((value) => Number.isFinite(value));
  return values.length === rawValues.length ? values.slice(0, 500) : [];
}

export function extractDataPoints(text: string): ExtractedDataPoint[] {
  const chunks = compactText(text)
    .split(/[,;\n]+/)
    .map((chunk) => chunk.trim())
    .filter(Boolean);
  const points: ExtractedDataPoint[] = [];
  const explicitChunkPattern =
    /^(?<label>[\p{L}\p{N}][\p{L}\p{N}\s%/()._-]{0,59}?)\s*(?:=|:)\s*(?<value>\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(?<currency>tl|try|₺|usd|\$|eur|€|%)?\s*[.!]?$/iu;
  const implicitChunkPattern =
    /^(?<label>[\p{L}][\p{L}\p{N}\s%/()._-]{1,59}?)\s+(?<value>\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(?<currency>tl|try|₺|usd|\$|eur|€|%)?(?:\s+(?:veri(?:siyle)?|data|değer(?:i|leri)?(?:yle)?|ile|kullanarak)\b.*)?\s*[.!]?$/iu;
  for (const chunk of chunks) {
    const prefixedCandidate = chunk.includes(":")
      ? chunk.slice(chunk.lastIndexOf(":") + 1).trim()
      : chunk;
    const match =
      explicitChunkPattern.exec(chunk) ??
      implicitChunkPattern.exec(prefixedCandidate);
    if (!match) {
      continue;
    }
    const value = parseNumericValue(match.groups?.value ?? "");
    const label = compactText(match.groups?.label ?? "");
    if (value == null || !label || /\b(toplam|total)\b/i.test(label)) {
      continue;
    }
    points.push({
      label,
      value,
      rawValue: compactText(match.groups?.value ?? ""),
      currency: normalizeCurrency(match.groups?.currency),
    });
  }

  if (points.length > 0) {
    return points.slice(0, 500);
  }

  const moneyItems = extractMoneyItems(text).filter((item) => !item.isTotal);
  return moneyItems.map((item) => ({
    label: item.label,
    value: item.amount,
    rawValue: item.rawAmount,
    currency: item.currency,
  }));
}

export function extractFooterText(text: string): string | null {
  const patterns = [
    /(?:en\s+alt(?:\s+kısmında|\s+kisminda)?|alt(?:ına|ina|a|ta|ta\s+kısmında|ta\s+kisminda))\s+(.+?)\s+(?:yazsın|yazsin|yaz|olsun|ekle)(?:[.!?]|$)/iu,
    /(?:footer|dipnot)\s+(?:olarak\s+)?(.+?)\s+(?:yazsın|yazsin|yaz|olsun|ekle)(?:[.!?]|$)/iu,
  ];
  for (const pattern of patterns) {
    const match = pattern.exec(text);
    const captured = compactText(match?.[1] ?? "")
      .replace(/^["'“”‘’]+|["'“”‘’]+$/g, "");
    if (captured.length >= 2) {
      return captured;
    }
  }
  return null;
}

export function detectLanguage(text: string): string {
  return /[çğıöşü]/i.test(text) ||
    /\b(bunu|şunu|tablo|grafik|belge|metin|yaz|hazırla|oluştur)\b/i.test(text)
    ? "tr"
    : "en";
}

export function hasLocalPrivateDataRequest(text: string): boolean {
  return /\b(bilgisayar[ıi]m(?:da|de|daki|deki)?|masa[üu]st[üu]m(?:de|deki)?|indirilenler(?:deki)?|downloads|desktop(?:taki)?|local file|yerel dosya|son pdf|son belge|son dosya|klas[öo]r)\b/iu.test(text);
}

export function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function readString(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
