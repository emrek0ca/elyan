import { fetchFactJson, finiteNumber, readRecord } from "../http.js";
import { locationCandidates, resolveGeoPlace, type GeoPlace } from "../geocode.js";
import { defineFactProvider, type FactAnswer } from "../types.js";

/**
 * Canlı hava durumu (Open-Meteo). `web-grounding.ts` içindeki gömülü
 * uygulamanın birebir taşınmış hâli; davranış korunur, sahibi değişir.
 */

function weatherCodeDescription(code: number): string {
  if (code === 0) return "açık";
  if ([1, 2].includes(code)) return "az bulutlu";
  if (code === 3) return "kapalı";
  if ([45, 48].includes(code)) return "sisli";
  if ([51, 53, 55, 56, 57].includes(code)) return "çiseli";
  if ([61, 63, 65, 66, 67, 80, 81, 82].includes(code)) return "yağmurlu";
  if ([71, 73, 75, 77, 85, 86].includes(code)) return "kar yağışlı";
  if ([95, 96, 99].includes(code)) return "gök gürültülü fırtınalı";
  return "değişken";
}

type WeatherParams = { prompt: string };

export const weatherProvider = defineFactProvider<WeatherParams>({
  id: "open_meteo",
  dataClass: "hourly",
  authority: "Open-Meteo",
  commercialUse: "conditional",
  allowStale: true,
  units: ["°C", "%", "km/h", "mm"],
  timeoutMs: 5_000,
  ttlMs: 10 * 60_000,
  fallbackDomain: "weather",
  intents: [
    "bugün hava nasıl olacak",
    "şu an dışarısı kaç derece",
    "yarın yağmur yağacak mı",
    "hava durumu nedir",
    "dışarı çıkarken mont almalı mıyım, hava soğuk mu",
    "what is the weather right now",
    "will it rain today",
  ],
  extract(prompt) {
    return locationCandidates(prompt).length > 0 ? { prompt } : null;
  },
  cacheKey(params) {
    return `weather:${locationCandidates(params.prompt).join("|").toLowerCase()}`;
  },
  async resolve(context, params): Promise<FactAnswer | null> {
    const place: GeoPlace | null = await resolveGeoPlace({
      providerId: "open_meteo",
      prompt: params.prompt,
      timeoutMs: context.timeoutMs,
    });
    if (!place) return null;

    const url = new URL("https://api.open-meteo.com/v1/forecast");
    url.searchParams.set("latitude", String(place.latitude));
    url.searchParams.set("longitude", String(place.longitude));
    url.searchParams.set(
      "current",
      "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,cloud_cover,wind_speed_10m",
    );
    url.searchParams.set("hourly", "precipitation_probability");
    url.searchParams.set("daily", "temperature_2m_max,temperature_2m_min,precipitation_probability_max");
    url.searchParams.set("forecast_days", "2");
    url.searchParams.set("timezone", place.timezone || "auto");

    const payload = readRecord(
      await fetchFactJson({
        providerId: "open_meteo",
        url: url.toString(),
        timeoutMs: context.timeoutMs,
      }),
    );
    const current = readRecord(payload?.current);
    const hourly = readRecord(payload?.hourly);
    const daily = readRecord(payload?.daily);
    const temperature = finiteNumber(current?.temperature_2m);
    const observedLocal = typeof current?.time === "string" ? current.time : null;
    if (temperature === null || !observedLocal) return null;
    // GÖZLEM ANI GERÇEK BİR AN OLMALI.
    //
    // Open-Meteo `current.time` alanını YERİN SAATİNDE, ofset yazmadan
    // döndürür ("2026-07-10T11:00"). Bunu doğrudan `Date` ile ayrıştırmak
    // sunucunun saat dilimine göre kayan, bazen günlerce yanlış bir an üretir
    // ve tazelik kapısı veriyi bayat sayıp kanıtı düşürür. Doğru an, aynı
    // yanıttaki `utc_offset_seconds` ile hesaplanır; alan yoksa dürüst olan
    // ÇEKİM anını kullanmaktır — yerel damgayı UTC sanmak değil.
    const utcOffsetSeconds = finiteNumber(payload?.utc_offset_seconds);
    const parsedLocal = Date.parse(`${observedLocal}Z`);
    const observedAt =
      utcOffsetSeconds !== null && Number.isFinite(parsedLocal)
        ? new Date(parsedLocal - utcOffsetSeconds * 1_000).toISOString()
        : new Date().toISOString();

    const weatherCode = finiteNumber(current?.weather_code) ?? -1;
    const condition = weatherCodeDescription(weatherCode);
    const apparent = finiteNumber(current?.apparent_temperature);
    const humidity = finiteNumber(current?.relative_humidity_2m);
    const precipitation = finiteNumber(current?.precipitation);
    const wind = finiteNumber(current?.wind_speed_10m);
    const cloudCover = finiteNumber(current?.cloud_cover);
    const hourlyTimes = Array.isArray(hourly?.time) ? (hourly.time as unknown[]) : [];
    const rainSeries = Array.isArray(hourly?.precipitation_probability)
      ? (hourly.precipitation_probability as unknown[])
      : [];
    const currentHourIndex = hourlyTimes.findIndex((time) => time === observedLocal);
    const rainProbability = finiteNumber(rainSeries[currentHourIndex >= 0 ? currentHourIndex : 0]);
    const maxTemperature = finiteNumber(
      Array.isArray(daily?.temperature_2m_max) ? (daily.temperature_2m_max as unknown[])[0] : null,
    );
    const minTemperature = finiteNumber(
      Array.isArray(daily?.temperature_2m_min) ? (daily.temperature_2m_min as unknown[])[0] : null,
    );
    const maxRainProbability = finiteNumber(
      Array.isArray(daily?.precipitation_probability_max)
        ? (daily.precipitation_probability_max as unknown[])[0]
        : null,
    );

    const details = [
      `${place.label} gözlemi (${observedLocal})`,
      `sıcaklık ${temperature} °C`,
      apparent === null ? null : `hissedilen ${apparent} °C`,
      `durum ${condition}`,
      humidity === null ? null : `nem %${humidity}`,
      wind === null ? null : `rüzgar ${wind} km/sa`,
      precipitation === null ? null : `anlık yağış ${precipitation} mm`,
      rainProbability === null ? null : `şu saat yağış olasılığı %${rainProbability}`,
      maxTemperature === null || minTemperature === null
        ? null
        : `bugün en düşük ${minTemperature} °C, en yüksek ${maxTemperature} °C`,
      maxRainProbability === null ? null : `bugün en yüksek yağış olasılığı %${maxRainProbability}`,
      cloudCover === null ? null : `bulutluluk %${cloudCover}`,
    ].filter((value): value is string => Boolean(value));

    const directAnswer = [
      `${place.label} için şu anki hava durumu: ${temperature} °C, ${condition}`,
      humidity === null ? null : `%${humidity} nem`,
      wind === null ? null : `${wind} km/sa rüzgar`,
      rainProbability === null ? null : `yağış olasılığı %${rainProbability}`,
    ]
      .filter((value): value is string => Boolean(value))
      .join(", ")
      .concat(
        minTemperature !== null && maxTemperature !== null
          ? `. Bugünün en düşük sıcaklığı ${minTemperature} °C, en yüksek ${maxTemperature} °C.`
          : ".",
      );

    return {
      providerId: "open_meteo",
      dataClass: "hourly",
      snippet: details.join("; ").slice(0, 700),
      directAnswer,
      citation: {
        title: `${place.label} canlı hava durumu`,
        url: url.toString(),
        sourceHost: "api.open-meteo.com",
        observedAt,
      },
      values: {
        location: place.label,
        observationLocalTime: observedLocal,
        temperatureC: temperature,
        condition,
        ...(humidity === null ? {} : { humidityPercent: humidity }),
        ...(wind === null ? {} : { windKmh: wind }),
        ...(minTemperature === null ? {} : { minTemperatureC: minTemperature }),
        ...(maxTemperature === null ? {} : { maxTemperatureC: maxTemperature }),
      },
      confidence: 0.95,
      ttlMs: 10 * 60_000,
    };
  },
});
