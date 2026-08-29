import { fetchFactJson, finiteNumber, readRecord } from "../http.js";
import { matchForeignCurrency } from "../catalog.js";
import { defineFactProvider, type FactAnswer } from "../types.js";

/**
 * Döviz kuru (Frankfurter / ECB referans kurları).
 *
 * ÖNEMLİ DÜRÜSTLÜK NOTU: ECB kurları GÜNLÜK referans kurlarıdır, canlı piyasa
 * değil. Cevap bunu açıkça söyler — "anlık kur" diye sunmak, doğru sayıyı
 * yanlış iddiayla vermek olurdu.
 */

type FxParams = { code: string };

export const fxProvider = defineFactProvider<FxParams>({
  id: "frankfurter",
  dataClass: "daily",
  authority: "European Central Bank via Frankfurter",
  commercialUse: "allowed",
  allowStale: false,
  units: ["TRY"],
  timeoutMs: 4_000,
  ttlMs: 60 * 60_000,
  fallbackDomain: "market",
  intents: [
    "dolar kaç lira",
    "euro kuru ne kadar",
    "sterlin bugün kaç TL",
    "döviz kuru nedir",
    "usd try exchange rate today",
  ],
  extract(prompt) {
    const currency = matchForeignCurrency(prompt);
    return currency ? { code: currency.code } : null;
  },
  cacheKey(params) {
    return `fx:${params.code}:TRY`;
  },
  async resolve(context, params): Promise<FactAnswer | null> {
    const url = new URL("https://api.frankfurter.app/latest");
    url.searchParams.set("from", params.code);
    url.searchParams.set("to", "TRY");

    const payload = readRecord(
      await fetchFactJson({
        providerId: "frankfurter",
        url: url.toString(),
        timeoutMs: context.timeoutMs,
        maxBytes: 100_000,
      }),
    );
    const rates = readRecord(payload?.rates);
    const rate = finiteNumber(rates?.TRY);
    const date = typeof payload?.date === "string" ? payload.date : null;
    if (rate === null || rate <= 0 || !date) return null;

    if (!/^\d{4}-\d{2}-\d{2}$/u.test(date)) return null;
    // Gözlem anı günün SONU: ECB referans kuru o gün için geçerlidir ve
    // gün başını damgalamak veriyi olduğundan bayat gösterirdi.
    const observedAt = `${date}T23:59:59.000Z`;
    // Kanıt satırının biçimi bir SÖZLEŞMEDİR: sayısal kanıt çıkarıcı ve
    // regresyon testi "1 USD = 42.75 TRY" kalıbını okur.
    const snippet =
      `1 ${params.code} = ${rate} TRY; referans tarihi ${date}; ` +
      "ECB günlük referans kuru, anlık piyasa fiyatı değildir";

    return {
      providerId: "frankfurter",
      dataClass: "daily",
      snippet,
      directAnswer: `1 ${params.code} = ${rate} TRY (ECB günlük referans kuru, ${date}). Bu anlık piyasa fiyatı değil, günlük referans kurdur.`,
      citation: {
        title: `${params.code}/TRY referans kuru`,
        url: url.toString(),
        sourceHost: "api.frankfurter.app",
        observedAt,
      },
      values: { base: params.code, quote: "TRY", rate, referenceDate: date },
      confidence: 0.92,
      ttlMs: 60 * 60_000,
    };
  },
});
