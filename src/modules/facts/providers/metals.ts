import { fetchFactJson, readRecord } from "../http.js";
import { lookupTokens, normalizeLookupText } from "../catalog.js";
import { defineFactProvider, type FactAnswer } from "../types.js";
import { resolveTcmbRate } from "./tcmb-fx.js";

type MetalParams = {
  symbol: "GOLD" | "SILVER";
  ticker: "XAU" | "XAG";
  label: "Altın" | "Gümüş";
  history: boolean;
};

const TROY_OUNCE_GRAMS = 31.1034768;

function numeric(value: unknown): number | null {
  const parsed =
    typeof value === "number"
      ? value
      : typeof value === "string"
        ? Number(value.replace(/,/gu, ""))
        : Number.NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function firstValue(
  value: unknown,
  keys: RegExp[],
  depth = 0,
): unknown {
  if (depth > 3 || !value || typeof value !== "object") return null;
  if (Array.isArray(value)) {
    for (const item of value.slice(0, 8)) {
      const found = firstValue(item, keys, depth + 1);
      if (found != null) return found;
    }
    return null;
  }
  for (const [key, entry] of Object.entries(value)) {
    if (keys.some((pattern) => pattern.test(key))) return entry;
  }
  for (const entry of Object.values(value)) {
    const found = firstValue(entry, keys, depth + 1);
    if (found != null) return found;
  }
  return null;
}

function timestamp(payload: unknown): string | null {
  const raw = firstValue(payload, [/(?:timestamp|last.updated|date|time)$/iu]);
  const parsed = new Date(String(raw ?? ""));
  return Number.isFinite(parsed.getTime()) ? parsed.toISOString() : null;
}

function historySeries(payload: unknown): Array<{ date: string; usdPerOunce: number }> {
  const record = readRecord(payload);
  const candidates = [record?.data, record?.values, record?.history].find(Array.isArray);
  if (!Array.isArray(candidates)) return [];
  return candidates
    .flatMap((entry) => {
      const row = readRecord(entry);
      const date = String(row?.date ?? row?.timestamp ?? "").slice(0, 10);
      const value = numeric(row?.value ?? row?.price ?? row?.close);
      return /^\d{4}-\d{2}-\d{2}$/u.test(date) && value
        ? [{ date, usdPerOunce: value }]
        : [];
    })
    .sort((left, right) => left.date.localeCompare(right.date))
    .slice(-30);
}

export const metalsProvider = defineFactProvider<MetalParams>({
  id: "alpha_vantage_metals",
  dataClass: "realtime",
  authority: "Alpha Vantage",
  requiresSecret: "alphaVantageApiKey",
  commercialUse: "conditional",
  allowStale: false,
  units: ["USD/troy_ounce", "TRY/gram"],
  timeoutMs: 1_500,
  ttlMs: 30_000,
  fallbackDomain: "market",
  intents: [
    "güncel altın fiyatı nedir",
    "gram altın spot değeri kaç lira",
    "ons altın kaç dolar",
    "gümüşün canlı fiyatı",
    "altının son 30 günlük fiyat grafiği",
    "gold spot price right now",
  ],
  extract(prompt) {
    const tokens = lookupTokens(prompt);
    const silver = ["gumus", "silver", "xag"].some((token) => tokens.has(token));
    const gold = ["altin", "gold", "xau"].some((token) => tokens.has(token));
    if (!silver && !gold) return null;
    const normalized = normalizeLookupText(prompt);
    const history = /(?:son\s+)?\d+\s+gun|tarihsel|gecmis|history|trend|grafik|tablo/iu.test(
      normalized,
    );
    return silver
      ? { symbol: "SILVER", ticker: "XAG", label: "Gümüş", history }
      : { symbol: "GOLD", ticker: "XAU", label: "Altın", history };
  },
  cacheKey(params) {
    return `metal:${params.ticker}:${params.history ? "30d" : "spot"}`;
  },
  async resolve(context, params): Promise<FactAnswer | null> {
    const key = context.secrets.alphaVantageApiKey;
    if (!key) return null;
    const url = new URL("https://www.alphavantage.co/query");
    url.searchParams.set(
      "function",
      params.history ? "GOLD_SILVER_HISTORY" : "GOLD_SILVER_SPOT",
    );
    url.searchParams.set("symbol", params.symbol);
    if (params.history) url.searchParams.set("interval", "daily");
    url.searchParams.set("apikey", key);

    const [payload, usdTry] = await Promise.all([
      fetchFactJson({
        providerId: "alpha_vantage_metals",
        url: url.toString(),
        timeoutMs: context.timeoutMs,
        maxBytes: 500_000,
      }),
      resolveTcmbRate(context, "USD").catch(() => null),
    ]);
    const series = params.history ? historySeries(payload) : [];
    const spotUsd =
      series.at(-1)?.usdPerOunce ??
      numeric(
        firstValue(payload, [
          /^(?:price|spot.price|current.price|value)$/iu,
          /price/iu,
        ]),
      );
    const observedAt =
      timestamp(payload) ??
      (series.at(-1)?.date
        ? `${series.at(-1)?.date}T23:59:59.000Z`
        : null);
    if (!spotUsd || !observedAt) return null;
    const gramTry = usdTry
      ? Number(((spotUsd * usdTry.rate) / TROY_OUNCE_GRAMS).toFixed(2))
      : null;
    const directAnswer = gramTry
      ? `${params.label} spot değeri ${spotUsd} USD/ons; TCMB USD/TRY gösterge kuruyla gram karşılığı ${gramTry} TL.`
      : `${params.label} spot değeri ${spotUsd} USD/ons. Gram-TL karşılığı şu an resmi kurla doğrulanamadı.`;
    const publicUrl = `https://www.alphavantage.co/query?function=${
      params.history ? "GOLD_SILVER_HISTORY" : "GOLD_SILVER_SPOT"
    }&symbol=${params.symbol}`;
    return {
      providerId: "alpha_vantage_metals",
      dataClass: params.history ? "daily" : "realtime",
      snippet: [
        `${params.ticker}/USD ${spotUsd} troy ons`,
        gramTry == null ? null : `${params.label.toLowerCase()} gram-TL spot eşdeğeri ${gramTry}`,
        `gözlem ${observedAt}`,
        "perakende alış/satış fiyatı değildir",
        series.length > 0
          ? `30 günlük seri: ${series.map((row) => `${row.date}=${row.usdPerOunce}`).join(", ")}`
          : null,
      ]
        .filter(Boolean)
        .join("; ")
        .slice(0, 4_500),
      directAnswer,
      citation: {
        title: `${params.label} ${params.history ? "30 günlük" : "canlı"} spot verisi`,
        url: publicUrl,
        sourceHost: "alphavantage.co",
        observedAt,
      },
      values: {
        symbol: params.ticker,
        usdPerTroyOunce: spotUsd,
        ...(gramTry == null ? {} : { gramTrySpotEquivalent: gramTry }),
        ...(usdTry == null ? {} : { usdTryIndicativeRate: usdTry.rate }),
        retailPrice: false,
        ...(series.length > 0 ? { series } : {}),
      },
      confidence: usdTry ? 0.96 : 0.91,
      ttlMs: params.history ? 10 * 60_000 : 30_000,
    };
  },
});
