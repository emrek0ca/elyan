import { fetchFactJson, readRecord } from "../http.js";
import { lookupTokens } from "../catalog.js";
import { defineFactProvider, type FactAnswer } from "../types.js";

type FredMetric = {
  seriesId: string;
  label: string;
  unit: string;
  aliases: string[];
  transform?: "pc1";
};

type FredParams = { metric: FredMetric };

const METRICS: FredMetric[] = [
  {
    seriesId: "CPIAUCSL",
    label: "ABD tüketici enflasyonu",
    unit: "% yıllık",
    aliases: ["enflasyon", "inflation", "cpi"],
    transform: "pc1",
  },
  {
    seriesId: "UNRATE",
    label: "ABD işsizlik oranı",
    unit: "%",
    aliases: ["issizlik", "unemployment"],
  },
  {
    seriesId: "FEDFUNDS",
    label: "Federal fon efektif faiz oranı",
    unit: "%",
    aliases: ["fed", "federal", "faiz", "interest"],
  },
  {
    seriesId: "DGS10",
    label: "ABD 10 yıllık hazine tahvili getirisi",
    unit: "%",
    aliases: ["tahvil", "treasury", "dgs10"],
  },
  {
    seriesId: "GDP",
    label: "ABD gayrisafi yurt içi hasılası",
    unit: "milyar USD",
    aliases: ["gdp", "gsyih", "gsyh"],
  },
];

const US_TOKENS = new Set(["abd", "amerika", "usa", "us", "fed", "federal"]);
const TURKEY_TOKENS = new Set(["turkiye", "turkey", "tcmb", "tuik"]);

export const fredProvider = defineFactProvider<FredParams>({
  id: "fred",
  dataClass: "monthly",
  authority: "Federal Reserve Bank of St. Louis",
  requiresSecret: "fredApiKey",
  commercialUse: "allowed",
  allowStale: true,
  units: ["%", "USD"],
  timeoutMs: 1_500,
  ttlMs: 6 * 60 * 60_000,
  intents: [
    "ABD enflasyonu son açıklanan değer",
    "Amerika işsizlik oranı kaç",
    "Fed efektif faiz oranı nedir",
    "ABD 10 yıllık tahvil faizi",
    "latest FRED macroeconomic observation",
  ],
  extract(prompt) {
    const tokens = lookupTokens(prompt);
    if ([...TURKEY_TOKENS].some((token) => tokens.has(token))) return null;
    const usContext = [...US_TOKENS].some((token) => tokens.has(token));
    const metric = METRICS.find((entry) =>
      entry.aliases.some((alias) => tokens.has(alias)),
    );
    if (!metric) return null;
    if (!usContext && metric.seriesId !== "FEDFUNDS") return null;
    return { metric };
  },
  cacheKey(params) {
    return `fred:${params.metric.seriesId}:${params.metric.transform ?? "lin"}`;
  },
  async resolve(context, params): Promise<FactAnswer | null> {
    const apiKey = context.secrets.fredApiKey;
    if (!apiKey) return null;
    const url = new URL(
      "https://api.stlouisfed.org/fred/series/observations",
    );
    url.searchParams.set("series_id", params.metric.seriesId);
    url.searchParams.set("api_key", apiKey);
    url.searchParams.set("file_type", "json");
    url.searchParams.set("sort_order", "desc");
    url.searchParams.set("limit", "12");
    if (params.metric.transform) {
      url.searchParams.set("units", params.metric.transform);
    }
    const payload = readRecord(
      await fetchFactJson({
        providerId: "fred",
        url: url.toString(),
        timeoutMs: context.timeoutMs,
        maxBytes: 300_000,
      }),
    );
    const observations = Array.isArray(payload?.observations)
      ? payload.observations
      : [];
    const series = observations.flatMap((entry) => {
      const row = readRecord(entry);
      const date = typeof row?.date === "string" ? row.date : "";
      const value = Number(row?.value);
      return /^\d{4}-\d{2}-\d{2}$/u.test(date) && Number.isFinite(value)
        ? [{ date, value: Number(value.toFixed(4)) }]
        : [];
    });
    const latest = series[0];
    if (!latest) return null;
    const observedAt = `${latest.date}T23:59:59.000Z`;
    return {
      providerId: "fred",
      dataClass: "monthly",
      snippet: `${params.metric.label}: ${latest.value} ${params.metric.unit}; gözlem dönemi ${latest.date}; seri ${params.metric.seriesId}`,
      directAnswer: `${params.metric.label} için son FRED gözlemi ${latest.date} tarihinde ${latest.value} ${params.metric.unit}.`,
      citation: {
        title: `${params.metric.label} — FRED ${params.metric.seriesId}`,
        url: `https://fred.stlouisfed.org/series/${params.metric.seriesId}`,
        sourceHost: "fred.stlouisfed.org",
        observedAt,
      },
      values: {
        seriesId: params.metric.seriesId,
        label: params.metric.label,
        value: latest.value,
        unit: params.metric.unit,
        referenceDate: latest.date,
        series: [...series].reverse(),
      },
      confidence: 0.98,
      ttlMs: 6 * 60 * 60_000,
    };
  },
});
