import { fetchFactJson, readRecord } from "../http.js";
import { matchForeignCurrency, normalizeLookupText } from "../catalog.js";
import { defineFactProvider, type FactAnswer } from "../types.js";

type EvdsParams = { code: string; days: number };

function ddmmyyyy(date: Date): string {
  return [
    String(date.getUTCDate()).padStart(2, "0"),
    String(date.getUTCMonth() + 1).padStart(2, "0"),
    String(date.getUTCFullYear()),
  ].join("-");
}

function isoDate(value: unknown): string | null {
  const raw = String(value ?? "").trim();
  const match = raw.match(/^(\d{2})[-./](\d{2})[-./](\d{4})$/u);
  if (match) return `${match[3]}-${match[2]}-${match[1]}`;
  const parsed = new Date(raw);
  return Number.isFinite(parsed.getTime())
    ? parsed.toISOString().slice(0, 10)
    : null;
}

function seriesValue(row: Record<string, unknown>, code: string): number | null {
  const target = `TP_DK_${code}_A`;
  const entry = Object.entries(row).find(([key]) =>
    key.toUpperCase().replace(/\./gu, "_").startsWith(target),
  );
  const value = Number(String(entry?.[1] ?? "").replace(",", "."));
  return Number.isFinite(value) && value > 0 ? value : null;
}

export const tcmbEvdsProvider = defineFactProvider<EvdsParams>({
  id: "tcmb_evds",
  dataClass: "daily",
  authority: "Türkiye Cumhuriyet Merkez Bankası EVDS",
  requiresSecret: "tcmbEvdsApiKey",
  commercialUse: "conditional",
  allowStale: true,
  units: ["TRY"],
  timeoutMs: 1_500,
  ttlMs: 6 * 60 * 60_000,
  fallbackDomain: "market",
  intents: [
    "doların son otuz günlük resmi kuru",
    "euro tarihsel TCMB kur serisi",
    "döviz kurunu tablo ve grafik yap",
    "historical official usd try series",
  ],
  extract(prompt) {
    const currency = matchForeignCurrency(prompt);
    if (!currency) return null;
    const normalized = normalizeLookupText(prompt);
    if (!/(?:son\s+\d+\s+gun|tarihsel|gecmis|history|trend|grafik|tablo|seri)/u.test(normalized)) {
      return null;
    }
    const requestedDays = Number(
      normalized.match(/(?:son\s+)?(\d{1,3})\s+gun/u)?.[1] ?? 30,
    );
    return {
      code: currency.code,
      days: Math.max(2, Math.min(365, requestedDays)),
    };
  },
  cacheKey(params) {
    return `evds:${params.code}:TRY:${params.days}d`;
  },
  async resolve(context, params): Promise<FactAnswer | null> {
    const key = context.secrets.tcmbEvdsApiKey;
    if (!key) return null;
    const end = new Date();
    const start = new Date(end.getTime() - params.days * 24 * 60 * 60_000);
    const seriesCode = `TP.DK.${params.code}.A`;
    const url = new URL(
      `https://evds3.tcmb.gov.tr/igmevdsms-dis/series=${seriesCode}`,
    );
    url.searchParams.set("startDate", ddmmyyyy(start));
    url.searchParams.set("endDate", ddmmyyyy(end));
    url.searchParams.set("type", "json");
    const payload = readRecord(
      await fetchFactJson({
        providerId: "tcmb_evds",
        url: url.toString(),
        timeoutMs: context.timeoutMs,
        maxBytes: 500_000,
        headers: { key },
      }),
    );
    const items = Array.isArray(payload?.items) ? payload.items : [];
    const series = items.flatMap((entry) => {
      const row = readRecord(entry);
      if (!row) return [];
      const date = isoDate(row.Tarih ?? row.DATE ?? row.date);
      const rate = seriesValue(row, params.code);
      return date && rate != null ? [{ date, rate }] : [];
    });
    const latest = series.at(-1);
    if (!latest) return null;
    const observedAt = `${latest.date}T23:59:59.000Z`;
    return {
      providerId: "tcmb_evds",
      dataClass: "daily",
      snippet: `TCMB EVDS ${params.code}/TRY ${series.length} günlük gözlem; son değer ${latest.date} tarihinde ${latest.rate} TRY`,
      directAnswer: `TCMB EVDS serisinde son ${params.code}/TRY gösterge kuru ${latest.date} tarihinde ${latest.rate} TRY.`,
      citation: {
        title: `TCMB EVDS ${params.code}/TRY tarihsel kur serisi`,
        url: url.toString(),
        sourceHost: "evds3.tcmb.gov.tr",
        observedAt,
      },
      values: {
        label: `${params.code}/TRY TCMB gösterge kuru`,
        unit: "TRY",
        seriesCode,
        series,
      },
      confidence: 0.98,
      ttlMs: 6 * 60 * 60_000,
    };
  },
});
