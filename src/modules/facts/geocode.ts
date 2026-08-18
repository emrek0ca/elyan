import { fetchFactJson, finiteNumber, readRecord } from "./http.js";
import { normalizeLookupText } from "./catalog.js";
import type { FactProviderId } from "./types.js";

/**
 * Ortak yer çözümleme (Open-Meteo geocoding).
 *
 * Hava, hava kalitesi ve yerel saat sağlayıcılarının üçü de aynı işi yapıyor;
 * tek yerde durur. Yer adı çıkarımı BİLEREK "gürültü temizle, kalanı sor"
 * biçimindedir: yer adlarının kapalı bir listesi yoktur, dolayısıyla doğru
 * araç desen değil, geocoding servisinin kendi bulanık eşleşmesidir.
 */

export type GeoPlace = {
  name: string;
  admin1?: string;
  country?: string;
  latitude: number;
  longitude: number;
  timezone: string;
  label: string;
};

/** Soru kalıplarını at, geriye yer adı adayları kalsın. */
const LOCATION_NOISE_PATTERN =
  /(?<!\p{L})(hava durumu|hava kalitesi|hava nasıl|hava nasil|kaç derece|kac derece|saat kaç|saat kac|yerel saat|yağmur yağacak mı|yagmur yagacak mi|yağmur|yagmur|kar yağacak mı|kar yagacak mi|rüzgar|ruzgar|sıcaklık|sicaklik|nem|weather|forecast|time|bugün|bugun|yarın|yarin|şu an|su an|şu anda|su anda|güncel|guncel|current|today|tomorrow|now|için|icin|nedir|ne kadar|kaç|kac)(?!\p{L})/giu;

export function locationCandidates(prompt: string): string[] {
  const cleaned = String(prompt ?? "")
    .replace(LOCATION_NOISE_PATTERN, " ")
    .replace(/[^\p{L}\p{N}\s.'’-]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!cleaned) return [];
  const words = cleaned
    .split(/\s+/u)
    .map((word) => word.replace(/[’'](?:da|de|ta|te|nin|nın|un|ün)$/iu, ""))
    .filter(Boolean);
  if (words.length === 0) return [];
  const candidates = [
    words.join(" "),
    words.length > 1 ? words.slice(-2).join(" ") : "",
    words.at(-1) ?? "",
  ];
  return [...new Set(candidates.filter(Boolean))].slice(0, 3);
}

function selectPlace(prompt: string, places: unknown[]): GeoPlace | null {
  const promptTokens = new Set(normalizeLookupText(prompt).split(" ").filter(Boolean));
  const scored = places
    .map((raw, index) => {
      const record = readRecord(raw);
      if (!record) return null;
      const latitude = finiteNumber(record.latitude);
      const longitude = finiteNumber(record.longitude);
      const name = typeof record.name === "string" ? record.name : "";
      if (latitude === null || longitude === null || !name) return null;
      const admin1 = typeof record.admin1 === "string" ? record.admin1 : undefined;
      const admin2 = typeof record.admin2 === "string" ? record.admin2 : undefined;
      const country = typeof record.country === "string" ? record.country : undefined;
      const timezone = typeof record.timezone === "string" && record.timezone
        ? record.timezone
        : "auto";
      const haystack = normalizeLookupText([name, admin1, admin2, country].filter(Boolean).join(" "));
      const overlap = [...promptTokens].filter((token) => token && haystack.includes(token)).length;
      const place: GeoPlace = {
        name,
        admin1,
        country,
        latitude,
        longitude,
        timezone,
        label: [name, admin1, country].filter(Boolean).join(", "),
      };
      return { place, score: overlap * 10 - index };
    })
    .filter((entry): entry is { place: GeoPlace; score: number } => entry !== null)
    .sort((left, right) => right.score - left.score);
  return scored[0]?.place ?? null;
}

export async function resolveGeoPlace(input: {
  providerId: FactProviderId;
  prompt: string;
  timeoutMs: number;
}): Promise<GeoPlace | null> {
  for (const candidate of locationCandidates(input.prompt)) {
    const url = new URL("https://geocoding-api.open-meteo.com/v1/search");
    url.searchParams.set("name", candidate);
    url.searchParams.set("count", "8");
    url.searchParams.set("language", "tr");
    url.searchParams.set("format", "json");
    try {
      const payload = await fetchFactJson({
        providerId: input.providerId,
        url: url.toString(),
        timeoutMs: input.timeoutMs,
        maxBytes: 200_000,
      });
      const record = readRecord(payload);
      const places = Array.isArray(record?.results) ? (record.results as unknown[]) : [];
      const place = selectPlace(input.prompt, places);
      if (place) return place;
    } catch {
      /* bir aday tutmazsa sıradakine geç; hepsi tutmazsa null */
    }
  }
  return null;
}
