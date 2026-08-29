import { fetchFactJson, readRecord } from "../http.js";
import { lookupTokens } from "../catalog.js";
import { defineFactProvider, type FactAnswer } from "../types.js";

type Indicator = { code: string; label: string; unit: string; aliases: string[] };
type MacroParams = { countryCode: string; country: string; indicator: Indicator };

const INDICATORS: Indicator[] = [
  { code: "FP.CPI.TOTL.ZG", label: "Tüketici enflasyonu", unit: "%", aliases: ["enflasyon", "inflation", "tufe", "cpi"] },
  { code: "NY.GDP.MKTP.CD", label: "Gayrisafi yurt içi hasıla", unit: "USD", aliases: ["gsyih", "gsyh", "gdp", "ekonomi"] },
  { code: "SL.UEM.TOTL.ZS", label: "İşsizlik oranı", unit: "%", aliases: ["issizlik", "unemployment"] },
  { code: "SP.POP.TOTL", label: "Nüfus", unit: "kişi", aliases: ["nufus", "population"] },
  { code: "NY.GDP.MKTP.KD.ZG", label: "Ekonomik büyüme", unit: "%", aliases: ["buyume", "growth"] },
];

const COUNTRIES = [
  { code: "TR", name: "Türkiye", aliases: ["turkiye", "turkey", "tr"] },
  { code: "US", name: "ABD", aliases: ["abd", "amerika", "usa", "united states"] },
  { code: "DE", name: "Almanya", aliases: ["almanya", "germany"] },
  { code: "GB", name: "Birleşik Krallık", aliases: ["ingiltere", "britanya", "uk"] },
  { code: "FR", name: "Fransa", aliases: ["fransa", "france"] },
];

export const worldBankProvider = defineFactProvider<MacroParams>({
  id: "world_bank",
  dataClass: "annual",
  authority: "World Bank",
  commercialUse: "allowed",
  allowStale: true,
  units: ["%", "USD", "person"],
  timeoutMs: 1_500,
  ttlMs: 24 * 60 * 60_000,
  intents: [
    "Türkiye enflasyon oranı kaç",
    "ülkenin son açıklanan GSYİH değeri",
    "işsizlik oranı nedir",
    "nüfus kaç kişi",
    "World Bank economic indicator",
  ],
  extract(prompt) {
    const tokens = lookupTokens(prompt);
    const indicator = INDICATORS.find((entry) =>
      entry.aliases.some((alias) => tokens.has(alias)),
    );
    if (!indicator) return null;
    const country =
      COUNTRIES.find((entry) => entry.aliases.some((alias) => tokens.has(alias))) ??
      COUNTRIES[0];
    return { countryCode: country.code, country: country.name, indicator };
  },
  cacheKey(params) {
    return `macro:${params.countryCode}:${params.indicator.code}`;
  },
  async resolve(context, params): Promise<FactAnswer | null> {
    const url = new URL(
      `https://api.worldbank.org/v2/country/${params.countryCode}/indicator/${params.indicator.code}`,
    );
    url.searchParams.set("format", "json");
    url.searchParams.set("per_page", "10");
    const payload = await fetchFactJson({
      providerId: "world_bank",
      url: url.toString(),
      timeoutMs: context.timeoutMs,
      maxBytes: 300_000,
    });
    if (!Array.isArray(payload)) return null;
    const metadata = readRecord(payload[0]);
    const rows = Array.isArray(payload[1]) ? payload[1] : [];
    const latest = rows
      .map((entry) => readRecord(entry))
      .find((entry) => entry && typeof entry.value === "number");
    if (!latest || typeof latest.value !== "number") return null;
    const year = String(latest.date ?? "");
    const lastUpdated = String(metadata?.lastupdated ?? "");
    const observed = new Date(lastUpdated || `${year}-12-31T23:59:59Z`);
    if (!Number.isFinite(observed.getTime())) return null;
    const value = Number(latest.value.toFixed(2));
    return {
      providerId: "world_bank",
      dataClass: "annual",
      snippet: `${params.country} ${params.indicator.label}: ${value} ${params.indicator.unit}; referans yılı ${year}; World Bank güncellemesi ${lastUpdated || "belirtilmedi"}`,
      directAnswer: `${params.country} için son World Bank ${params.indicator.label.toLocaleLowerCase("tr-TR")} değeri ${year} yılında ${value} ${params.indicator.unit}.`,
      citation: {
        title: `${params.country} — ${params.indicator.label}`,
        url: url.toString(),
        sourceHost: "api.worldbank.org",
        observedAt: observed.toISOString(),
      },
      values: {
        country: params.country,
        indicatorCode: params.indicator.code,
        indicator: params.indicator.label,
        referenceYear: year,
        value,
        unit: params.indicator.unit,
      },
      confidence: 0.98,
      ttlMs: 24 * 60 * 60_000,
    };
  },
});
