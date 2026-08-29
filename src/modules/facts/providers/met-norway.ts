import { fetchFactJson, finiteNumber, readRecord } from "../http.js";
import { locationCandidates, resolveGeoPlace } from "../geocode.js";
import { defineFactProvider, type FactAnswer } from "../types.js";

type WeatherParams = { prompt: string };

export const metNorwayProvider = defineFactProvider<WeatherParams>({
  id: "met_norway",
  dataClass: "hourly",
  authority: "MET Norway",
  commercialUse: "allowed",
  allowStale: true,
  units: ["°C", "%", "m/s", "mm"],
  timeoutMs: 1_500,
  ttlMs: 10 * 60_000,
  fallbackDomain: "weather",
  intents: [
    "bugün hava nasıl",
    "şu an kaç derece",
    "yağmur yağacak mı",
    "rüzgar ne kadar güçlü",
    "current weather forecast",
  ],
  extract(prompt) {
    return locationCandidates(prompt).length > 0 ? { prompt } : null;
  },
  cacheKey(params) {
    return `weather:${locationCandidates(params.prompt).join("|").toLowerCase()}`;
  },
  async resolve(context, params): Promise<FactAnswer | null> {
    const place = await resolveGeoPlace({
      providerId: "met_norway",
      prompt: params.prompt,
      timeoutMs: context.timeoutMs,
    });
    if (!place) return null;
    const url = new URL("https://api.met.no/weatherapi/locationforecast/2.0/compact");
    url.searchParams.set("lat", place.latitude.toFixed(4));
    url.searchParams.set("lon", place.longitude.toFixed(4));
    const payload = readRecord(
      await fetchFactJson({
        providerId: "met_norway",
        url: url.toString(),
        timeoutMs: context.timeoutMs,
        maxBytes: 500_000,
      }),
    );
    const properties = readRecord(payload?.properties);
    const series = Array.isArray(properties?.timeseries)
      ? properties.timeseries
      : [];
    const first = readRecord(series[0]);
    const data = readRecord(first?.data);
    const instant = readRecord(readRecord(data?.instant)?.details);
    const nextHour = readRecord(data?.next_1_hours);
    const summary = readRecord(nextHour?.summary);
    const nextDetails = readRecord(nextHour?.details);
    const temperature = finiteNumber(instant?.air_temperature);
    const at = typeof first?.time === "string" ? first.time : null;
    if (temperature === null || !at) return null;
    const humidity = finiteNumber(instant?.relative_humidity);
    const wind = finiteNumber(instant?.wind_speed);
    const precipitation = finiteNumber(nextDetails?.precipitation_amount);
    const condition =
      typeof summary?.symbol_code === "string"
        ? summary.symbol_code.replace(/_/gu, " ")
        : "bilinmiyor";
    return {
      providerId: "met_norway",
      dataClass: "hourly",
      snippet: [
        `${place.label} sıcaklık ${temperature} °C`,
        `durum ${condition}`,
        humidity == null ? null : `nem %${humidity}`,
        wind == null ? null : `rüzgar ${wind} m/s`,
        precipitation == null ? null : `önümüzdeki saat yağış ${precipitation} mm`,
        `gözlem ${at}`,
      ]
        .filter(Boolean)
        .join("; "),
      directAnswer: `${place.label} için şu an ${temperature} °C; hava ${condition}.`,
      citation: {
        title: `${place.label} hava tahmini`,
        url: url.toString(),
        sourceHost: "api.met.no",
        observedAt: new Date(at).toISOString(),
      },
      values: {
        location: place.label,
        temperatureC: temperature,
        condition,
        ...(humidity == null ? {} : { humidityPercent: humidity }),
        ...(wind == null ? {} : { windMetersPerSecond: wind }),
        ...(precipitation == null ? {} : { precipitationNextHourMm: precipitation }),
      },
      confidence: 0.97,
      ttlMs: 10 * 60_000,
    };
  },
});
