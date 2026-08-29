import { fetchFactJson, finiteNumber, readRecord } from "../http.js";
import { defineFactProvider, type FactAnswer } from "../types.js";

/**
 * Son depremler (USGS FDSN). Türkiye için gerçekten değerli bir tipli kaynak:
 * arama sonuçları burada hem yavaş hem de tehlikeli biçimde bayattır.
 *
 * Kapsam BİLEREK dar: "son depremler" sorusu. Konum filtresi eklemedik çünkü
 * yer adı → koordinat + yarıçap eşlemesi ayrı bir doğruluk sorunudur ve yanlış
 * yarıçap, "deprem yok" diyen yanlış bir cevap üretir. Global son liste
 * dürüsttür ve büyüklüğe göre eşiklenir.
 */

type QuakeParams = { minMagnitude: number };

export const earthquakeProvider = defineFactProvider<QuakeParams>({
  id: "usgs_earthquake",
  dataClass: "realtime",
  authority: "United States Geological Survey",
  commercialUse: "allowed",
  allowStale: false,
  units: ["magnitude"],
  timeoutMs: 5_000,
  ttlMs: 5 * 60_000,
  intents: [
    "son depremler nerede oldu",
    "az önce deprem mi oldu",
    "bugün kaç şiddetinde deprem oldu",
    "deprem listesi son 24 saat",
    "recent earthquakes today",
  ],
  extract() {
    return { minMagnitude: 4 };
  },
  cacheKey(params) {
    return `quake:${params.minMagnitude}`;
  },
  async resolve(context, params): Promise<FactAnswer | null> {
    const start = new Date(Date.now() - 24 * 60 * 60_000).toISOString();
    const url = new URL("https://earthquake.usgs.gov/fdsnws/event/1/query");
    url.searchParams.set("format", "geojson");
    url.searchParams.set("starttime", start);
    url.searchParams.set("minmagnitude", String(params.minMagnitude));
    url.searchParams.set("orderby", "time");
    url.searchParams.set("limit", "5");

    const payload = readRecord(
      await fetchFactJson({
        providerId: "usgs_earthquake",
        url: url.toString(),
        timeoutMs: context.timeoutMs,
        maxBytes: 300_000,
      }),
    );
    const features = Array.isArray(payload?.features) ? (payload.features as unknown[]) : [];
    const events = features
      .map((raw) => {
        const properties = readRecord(readRecord(raw)?.properties);
        const magnitude = finiteNumber(properties?.mag);
        const place = typeof properties?.place === "string" ? properties.place : null;
        const time = finiteNumber(properties?.time);
        if (magnitude === null || !place || time === null) return null;
        return { magnitude, place, at: new Date(time).toISOString() };
      })
      .filter((event): event is { magnitude: number; place: string; at: string } => event !== null);
    if (events.length === 0) return null;

    const lines = events.map(
      (event) => `${event.magnitude.toFixed(1)} büyüklüğünde, ${event.place}, ${event.at}`,
    );
    const latest = events[0];

    return {
      providerId: "usgs_earthquake",
      dataClass: "realtime",
      snippet: `Son 24 saatte ${params.minMagnitude}+ büyüklüğündeki depremler: ${lines.join("; ")}`.slice(0, 700),
      directAnswer: `Son 24 saatte kaydedilen en yeni ${params.minMagnitude}+ deprem: ${latest.magnitude.toFixed(1)} büyüklüğünde, ${latest.place} (${latest.at}). Toplam ${events.length} kayıt listelendi.`,
      citation: {
        title: "USGS son deprem kayıtları",
        url: url.toString(),
        sourceHost: "earthquake.usgs.gov",
        observedAt: latest.at,
      },
      values: {
        latestMagnitude: latest.magnitude,
        latestPlace: latest.place,
        eventCount: events.length,
      },
      confidence: 0.9,
      ttlMs: 5 * 60_000,
    };
  },
});
