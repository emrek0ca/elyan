import { fetchFactJson, readRecord } from "../http.js";
import { lookupTokens } from "../catalog.js";
import { defineFactProvider, type FactAnswer } from "../types.js";

/**
 * Resmî tatiller (Nager.Date). Ülke kodu küçük bir katalogdan çözülür;
 * eşleşme yoksa Türkiye varsayılır — çünkü tatili sorulan ülke belirtilmediğinde
 * kullanıcının kendi ülkesi kastedilir ve cevap ülkeyi açıkça yazar.
 */

const COUNTRY_ALIASES: Array<{ code: string; name: string; aliases: string[] }> = [
  { code: "TR", name: "Türkiye", aliases: ["turkiye", "turkiyede", "turk", "turkey"] },
  { code: "DE", name: "Almanya", aliases: ["almanya", "germany", "alman"] },
  { code: "US", name: "ABD", aliases: ["abd", "amerika", "usa", "birlesik"] },
  { code: "GB", name: "Birleşik Krallık", aliases: ["ingiltere", "britanya", "uk"] },
  { code: "FR", name: "Fransa", aliases: ["fransa", "france", "fransiz"] },
  { code: "NL", name: "Hollanda", aliases: ["hollanda", "netherlands"] },
  { code: "AZ", name: "Azerbaycan", aliases: ["azerbaycan", "azerbaijan"] },
];

type HolidayParams = { code: string; name: string; year: number };

export const holidayProvider = defineFactProvider<HolidayParams>({
  id: "nager_holidays",
  dataClass: "daily",
  authority: "Nager.Date",
  commercialUse: "allowed",
  allowStale: true,
  units: ["date"],
  timeoutMs: 4_000,
  ttlMs: 24 * 60 * 60_000,
  intents: [
    "bir sonraki resmi tatil ne zaman",
    "bu yıl resmi tatiller hangi günler",
    "yarın tatil mi",
    "bayram hangi güne denk geliyor",
    "public holidays this year",
  ],
  extract(prompt) {
    const tokens = lookupTokens(prompt);
    const matched = COUNTRY_ALIASES.find((country) =>
      country.aliases.some((alias) => tokens.has(alias)),
    );
    const country = matched ?? COUNTRY_ALIASES[0];
    return { code: country.code, name: country.name, year: new Date().getFullYear() };
  },
  cacheKey(params) {
    return `holiday:${params.code}:${params.year}`;
  },
  async resolve(context, params): Promise<FactAnswer | null> {
    const url = `https://date.nager.at/api/v3/PublicHolidays/${params.year}/${params.code}`;
    const payload = await fetchFactJson({
      providerId: "nager_holidays",
      url,
      timeoutMs: context.timeoutMs,
      maxBytes: 200_000,
    });
    const entries = Array.isArray(payload) ? payload : [];
    const today = new Date().toISOString().slice(0, 10);
    const holidays = entries
      .map((raw) => {
        const record = readRecord(raw);
        const date = typeof record?.date === "string" ? record.date : null;
        const localName = typeof record?.localName === "string" ? record.localName : null;
        return date && localName ? { date, localName } : null;
      })
      .filter((entry): entry is { date: string; localName: string } => entry !== null)
      .sort((left, right) => left.date.localeCompare(right.date));
    if (holidays.length === 0) return null;

    const upcoming = holidays.filter((entry) => entry.date >= today).slice(0, 4);
    const shown = upcoming.length > 0 ? upcoming : holidays.slice(-4);
    const next = shown[0];
    const observedAt = new Date().toISOString();

    return {
      providerId: "nager_holidays",
      dataClass: "daily",
      snippet:
        `${params.name} ${params.year} resmî tatilleri (yaklaşanlar): ` +
        shown.map((entry) => `${entry.date} ${entry.localName}`).join("; "),
      directAnswer:
        upcoming.length > 0
          ? `${params.name} için sıradaki resmî tatil ${next.date} tarihinde: ${next.localName}.`
          : `${params.name} için ${params.year} yılında kalan resmî tatil görünmüyor; son tatil ${next.date} (${next.localName}).`,
      citation: {
        title: `${params.name} ${params.year} resmî tatilleri`,
        url,
        sourceHost: "date.nager.at",
        observedAt,
      },
      values: {
        country: params.name,
        year: params.year,
        nextHolidayDate: next.date,
        nextHolidayName: next.localName,
      },
      confidence: 0.88,
      ttlMs: 24 * 60 * 60_000,
    };
  },
});
