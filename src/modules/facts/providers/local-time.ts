import { locationCandidates, resolveGeoPlace } from "../geocode.js";
import { defineFactProvider, type FactAnswer } from "../types.js";

/**
 * Bir yerdeki YEREL SAAT.
 *
 * Üçüncü parti bir "world time" servisi BİLEREK kullanılmadı: saat, geocoding
 * zaten IANA zaman dilimini döndürdüğü için `Intl` ile deterministik olarak
 * hesaplanabilir. Bir ağ bağımlılığı daha eklemek, hem gecikme hem de
 * çalışmama riski katardı — üstelik hesaplanabilir bir şey için.
 */

type TimeParams = { prompt: string };

function formatInZone(timeZone: string, at: Date): { time: string; date: string } | null {
  try {
    const time = new Intl.DateTimeFormat("tr-TR", {
      timeZone,
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(at);
    const date = new Intl.DateTimeFormat("tr-TR", {
      timeZone,
      day: "2-digit",
      month: "long",
      year: "numeric",
      weekday: "long",
    }).format(at);
    return { time, date };
  } catch {
    return null;
  }
}

export const localTimeProvider = defineFactProvider<TimeParams>({
  id: "local_time",
  dataClass: "realtime",
  timeoutMs: 4_000,
  ttlMs: 30_000,
  intents: [
    "orada saat kaç",
    "New York'ta şu an saat kaç",
    "Londra ile aramızda kaç saat fark var",
    "o ülkede yerel saat nedir",
    "what time is it in Tokyo right now",
  ],
  extract(prompt) {
    return locationCandidates(prompt).length > 0 ? { prompt } : null;
  },
  cacheKey(params) {
    return `time:${locationCandidates(params.prompt).join("|").toLowerCase()}`;
  },
  async resolve(context, params): Promise<FactAnswer | null> {
    const place = await resolveGeoPlace({
      providerId: "local_time",
      prompt: params.prompt,
      timeoutMs: context.timeoutMs,
    });
    if (!place || !place.timezone || place.timezone === "auto") return null;
    const now = new Date();
    const formatted = formatInZone(place.timezone, now);
    if (!formatted) return null;

    const snippet =
      `${place.label} yerel saati ${formatted.time} (${formatted.date}); ` +
      `zaman dilimi ${place.timezone}; ölçüm anı ${now.toISOString()}`;

    return {
      providerId: "local_time",
      dataClass: "realtime",
      snippet,
      directAnswer: `${place.label} için yerel saat şu an ${formatted.time} (${place.timezone}).`,
      citation: {
        title: `${place.label} yerel saati`,
        url: "https://geocoding-api.open-meteo.com/v1/search",
        sourceHost: "geocoding-api.open-meteo.com",
        observedAt: now.toISOString(),
      },
      values: {
        location: place.label,
        localTime: formatted.time,
        localDate: formatted.date,
        timeZone: place.timezone,
      },
      confidence: 0.94,
      ttlMs: 30_000,
    };
  },
});
