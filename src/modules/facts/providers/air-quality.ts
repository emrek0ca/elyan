import { fetchFactJson, finiteNumber, readRecord } from "../http.js";
import { locationCandidates, resolveGeoPlace } from "../geocode.js";
import { defineFactProvider, type FactAnswer } from "../types.js";

/** Avrupa AQI bandı — sayıyı insan diline çeviren tek yer. */
function aqiBand(value: number): string {
  if (value <= 20) return "iyi";
  if (value <= 40) return "makul";
  if (value <= 60) return "orta";
  if (value <= 80) return "kötü";
  if (value <= 100) return "çok kötü";
  return "aşırı kötü";
}

type AirParams = { prompt: string };

export const airQualityProvider = defineFactProvider<AirParams>({
  id: "open_meteo_air",
  dataClass: "hourly",
  authority: "Open-Meteo",
  commercialUse: "conditional",
  allowStale: true,
  units: ["AQI", "µg/m³"],
  timeoutMs: 5_000,
  ttlMs: 30 * 60_000,
  intents: [
    "hava kalitesi nasıl",
    "bugün hava kirliliği ne durumda",
    "polen ve partikül madde seviyesi yüksek mi",
    "dışarıda spor yapmak sağlıklı mı, hava temiz mi",
    "air quality index right now",
  ],
  extract(prompt) {
    return locationCandidates(prompt).length > 0 ? { prompt } : null;
  },
  cacheKey(params) {
    return `air:${locationCandidates(params.prompt).join("|").toLowerCase()}`;
  },
  async resolve(context, params): Promise<FactAnswer | null> {
    const place = await resolveGeoPlace({
      providerId: "open_meteo_air",
      prompt: params.prompt,
      timeoutMs: context.timeoutMs,
    });
    if (!place) return null;

    const url = new URL("https://air-quality-api.open-meteo.com/v1/air-quality");
    url.searchParams.set("latitude", String(place.latitude));
    url.searchParams.set("longitude", String(place.longitude));
    url.searchParams.set("current", "european_aqi,pm10,pm2_5,ozone,nitrogen_dioxide");
    url.searchParams.set("timezone", place.timezone || "auto");

    const payload = readRecord(
      await fetchFactJson({
        providerId: "open_meteo_air",
        url: url.toString(),
        timeoutMs: context.timeoutMs,
      }),
    );
    const current = readRecord(payload?.current);
    const aqi = finiteNumber(current?.european_aqi);
    const observedAt = typeof current?.time === "string" ? current.time : null;
    if (aqi === null || !observedAt) return null;

    const pm25 = finiteNumber(current?.pm2_5);
    const pm10 = finiteNumber(current?.pm10);
    const ozone = finiteNumber(current?.ozone);
    const no2 = finiteNumber(current?.nitrogen_dioxide);
    const band = aqiBand(aqi);

    const details = [
      `${place.label} hava kalitesi gözlemi (${observedAt})`,
      `Avrupa AQI ${aqi} (${band})`,
      pm25 === null ? null : `PM2.5 ${pm25} µg/m³`,
      pm10 === null ? null : `PM10 ${pm10} µg/m³`,
      ozone === null ? null : `ozon ${ozone} µg/m³`,
      no2 === null ? null : `azot dioksit ${no2} µg/m³`,
    ].filter((value): value is string => Boolean(value));

    return {
      providerId: "open_meteo_air",
      dataClass: "hourly",
      snippet: details.join("; ").slice(0, 700),
      directAnswer:
        `${place.label} hava kalitesi şu an ${band} (Avrupa AQI ${aqi})` +
        (pm25 === null ? "." : `; PM2.5 ${pm25} µg/m³.`),
      citation: {
        title: `${place.label} hava kalitesi`,
        url: url.toString(),
        sourceHost: "air-quality-api.open-meteo.com",
        observedAt: new Date(observedAt).toISOString(),
      },
      values: {
        location: place.label,
        europeanAqi: aqi,
        band,
        ...(pm25 === null ? {} : { pm25 }),
        ...(pm10 === null ? {} : { pm10 }),
      },
      confidence: 0.9,
      ttlMs: 30 * 60_000,
    };
  },
});
