import { fetchFactText } from "../http.js";
import { matchForeignCurrency } from "../catalog.js";
import {
  defineFactProvider,
  type FactAnswer,
  type FactResolveContext,
} from "../types.js";

type TcmbFxParams = { code: string };

function xmlValue(xml: string, tag: string): string | null {
  const value = xml.match(new RegExp(`<${tag}>([^<]+)</${tag}>`, "iu"))?.[1];
  return value?.trim() || null;
}

function observedAt(xml: string): string | null {
  const value = xml.match(/<Tarih_Date[^>]+(?:Date|Tarih)="([^"]+)"/iu)?.[1];
  if (!value) return null;
  const parts = value.split(/[./-]/u).map((part) => Number(part));
  if (parts.length !== 3 || parts.some((part) => !Number.isFinite(part))) return null;
  const [first, second, third] = parts;
  const year = first > 1900 ? first : third;
  const month = first > 1900 ? second : first;
  const day = first > 1900 ? third : second;
  const date = new Date(Date.UTC(year, month - 1, day, 23, 59, 59));
  return Number.isFinite(date.getTime()) ? date.toISOString() : null;
}

export async function resolveTcmbRate(
  context: FactResolveContext,
  code: string,
): Promise<{ rate: number; observedAt: string; url: string } | null> {
  const url = "https://www.tcmb.gov.tr/kurlar/today.xml";
  const xml = await fetchFactText({
    providerId: "tcmb_fx",
    url,
    timeoutMs: context.timeoutMs,
    maxBytes: 300_000,
  });
  const block = xml.match(
    new RegExp(`<Currency[^>]+CurrencyCode="${code}"[^>]*>([\\s\\S]*?)</Currency>`, "iu"),
  )?.[1];
  if (!block) return null;
  const rawRate = xmlValue(block, "ForexSelling") ?? xmlValue(block, "ForexBuying");
  const rate = Number(rawRate?.replace(",", "."));
  const at = observedAt(xml);
  if (!Number.isFinite(rate) || rate <= 0 || !at) return null;
  return { rate, observedAt: at, url };
}

export const tcmbFxProvider = defineFactProvider<TcmbFxParams>({
  id: "tcmb_fx",
  dataClass: "daily",
  authority: "Türkiye Cumhuriyet Merkez Bankası",
  commercialUse: "allowed",
  allowStale: false,
  units: ["TRY"],
  timeoutMs: 1_500,
  ttlMs: 60 * 60_000,
  fallbackDomain: "market",
  intents: [
    "TCMB dolar kuru kaç lira",
    "euro gösterge kuru ne kadar",
    "resmi döviz kuru nedir",
    "doların bugünkü TCMB kuru",
    "official usd try exchange rate",
  ],
  extract(prompt) {
    const currency = matchForeignCurrency(prompt);
    return currency ? { code: currency.code } : null;
  },
  cacheKey(params) {
    return `tcmb:${params.code}:TRY`;
  },
  async resolve(context, params): Promise<FactAnswer | null> {
    const result = await resolveTcmbRate(context, params.code);
    if (!result) return null;
    return {
      providerId: "tcmb_fx",
      dataClass: "daily",
      snippet: `1 ${params.code} = ${result.rate} TRY; TCMB gösterge kuru; gözlem ${result.observedAt}`,
      directAnswer: `1 ${params.code} = ${result.rate} TRY (TCMB gösterge kuru). Bu, perakende alış/satış fiyatı değildir.`,
      citation: {
        title: `TCMB ${params.code}/TRY gösterge kuru`,
        url: result.url,
        sourceHost: "tcmb.gov.tr",
        observedAt: result.observedAt,
      },
      values: {
        base: params.code,
        quote: "TRY",
        rate: result.rate,
        rateType: "indicative",
      },
      confidence: 0.98,
      ttlMs: 60 * 60_000,
    };
  },
});
