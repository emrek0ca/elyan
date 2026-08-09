/**
 * Chart veri normalleştirmesi — sözleşmenin "veri her zaman sayısal" kuralı.
 *
 * NEDEN: model chart verisini altı ayrı biçimde gönderiyor (`labels`+`values`,
 * `points:[{x,y}]`, `points:[{label,value}]`, `data:[[x,y]]`, `series:[…]`,
 * `expression`+`range`) ve zaman zaman y değerine SAYI YERİNE FORMÜL STRING'İ
 * yazıyor ("2400+31.2", "yaklaşık 2450"). İstemci bunları tek tek çözmeye
 * çalıştığında ya yanlış çiziyor ya da bloğu düşürüyordu.
 *
 * Buradaki tek iş: hangi biçimde gelirse gelsin GERÇEK sayısal seriye indirmek.
 * Sayıya indirgenemeyen bir hücre veri değildir — o nokta düşer, formül string'i
 * ASLA y değeri olarak taşınmaz.
 */

/** Sayıya benzeyen ama sayı OLMAYAN model çıktısı. */
const NON_NUMERIC_HINTS =
  /(yakla[şs][ıi]k|civar|around|approx|about|tahmin|bilinmiyor|unknown|n\/a|null|\?)/i;

/** Aritmetik ifade/aralık: "2400+31.2", "10-20", "3*4". Bunlar veri değildir. */
const ARITHMETIC_TAIL = /[0-9)\s][+*/^][-+0-9(.\s]/;

/**
 * Bir hücreyi sonlu sayıya indirger; indirgenemiyorsa `null`.
 *
 * Kabul: `1234`, `-12.5`, `"1.234,56"` (TR), `"1,234.56"` (EN), `"%12,4"`,
 * `"2.450,75 TL"`, `"12 %"`. Ret: formül, aralık, "yaklaşık", boş, NaN.
 */
export function coerceFiniteNumber(value: unknown): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "boolean" || value == null) {
    return null;
  }
  if (typeof value !== "string") {
    return null;
  }
  const raw = value.trim();
  if (!raw || NON_NUMERIC_HINTS.test(raw) || ARITHMETIC_TAIL.test(raw)) {
    return null;
  }
  // Para birimi/yüzde/boşluk süsleri atılır; harf kalırsa sayı değildir.
  let cleaned = raw
    .replace(/[%‰]/g, "")
    .replace(/[₺$€£¥]/g, "")
    .replace(/ /g, " ")
    .replace(/\s+/g, "")
    .replace(/^\+/, "");
  if (!cleaned || /[^0-9.,\-eE]/.test(cleaned)) {
    return null;
  }
  const lastComma = cleaned.lastIndexOf(",");
  const lastDot = cleaned.lastIndexOf(".");
  if (lastComma >= 0 && lastDot >= 0) {
    // İki ayraç da varsa SONDAKİ ondalıktır: "1.234,56" → TR, "1,234.56" → EN.
    if (lastComma > lastDot) {
      cleaned = cleaned.replace(/\./g, "").replace(",", ".");
    } else {
      cleaned = cleaned.replace(/,/g, "");
    }
  } else if (lastComma >= 0) {
    // Tek ayraç virgül: üç haneli gruplama ("1,234") ise binlik, değilse ondalık.
    cleaned = /,\d{3}(\D|$)/.test(cleaned)
      ? cleaned.replace(/,/g, "")
      : cleaned.replace(",", ".");
  }
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

function textOf(value: unknown, max = 120): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  if (typeof value !== "string") return "";
  return value.replace(/\s+/g, " ").trim().slice(0, max);
}

const LABEL_KEYS = [
  "label",
  "name",
  "category",
  "date",
  "day",
  "month",
  "year",
  "period",
  "key",
  "title",
  "x",
];
const VALUE_KEYS = [
  "value",
  "y",
  "count",
  "amount",
  "total",
  "score",
  "price",
  "rate",
  "percentage",
  "percent",
];

/** Tek biçimli sayısal seri — istemcinin doğrudan çizebildiği hâl. */
export type NormalizedChartSeries = {
  name?: string;
  labels: string[];
  values: number[];
};

export type NormalizedSurfacePoint = { x: number; y: number; z: number };

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

/**
 * Nokta listesini (`points`/`data`) sayısal etiket-değer ikilisine indirger.
 *
 * Desteklenen biçimler:
 *   `[{x, y}]` · `[{label, value}]` · `[{date, value}]` · `[[x, y]]` ·
 *   `[1, 2, 3]` (etiket = 1'den sıra) · `[{name, count}]`
 */
export function normalizePointList(
  input: unknown,
  limit = 1_500,
): NormalizedChartSeries | null {
  if (!Array.isArray(input) || input.length === 0) return null;
  const labels: string[] = [];
  const values: number[] = [];
  for (const entry of input.slice(0, limit)) {
    if (Array.isArray(entry)) {
      if (entry.length < 2) continue;
      const value = coerceFiniteNumber(entry[1]);
      if (value == null) continue;
      labels.push(textOf(entry[0]) || String(labels.length + 1));
      values.push(value);
      continue;
    }
    if (isRecord(entry)) {
      let value: number | null = null;
      for (const key of VALUE_KEYS) {
        if (key in entry) {
          value = coerceFiniteNumber(entry[key]);
          if (value != null) break;
        }
      }
      if (value == null) continue;
      let label = "";
      for (const key of LABEL_KEYS) {
        if (key in entry) {
          label = textOf(entry[key]);
          if (label) break;
        }
      }
      labels.push(label || String(labels.length + 1));
      values.push(value);
      continue;
    }
    const scalar = coerceFiniteNumber(entry);
    if (scalar == null) continue;
    labels.push(String(labels.length + 1));
    values.push(scalar);
  }
  if (values.length === 0) return null;
  return { labels, values };
}

/** `[{x,y,z}]` üçlülerini yüzey noktalarına indirger (3B bloklar için). */
export function normalizeSurfacePoints(
  input: unknown,
  limit = 1_500,
): NormalizedSurfacePoint[] | null {
  if (!Array.isArray(input) || input.length === 0) return null;
  const points: NormalizedSurfacePoint[] = [];
  for (const entry of input.slice(0, limit)) {
    if (Array.isArray(entry) && entry.length >= 3) {
      const x = coerceFiniteNumber(entry[0]);
      const y = coerceFiniteNumber(entry[1]);
      const z = coerceFiniteNumber(entry[2]);
      if (x == null || y == null || z == null) continue;
      points.push({ x, y, z });
      continue;
    }
    if (!isRecord(entry)) continue;
    const x = coerceFiniteNumber(entry.x);
    const y = coerceFiniteNumber(entry.y);
    const z = coerceFiniteNumber(entry.z ?? entry.value);
    if (x == null || y == null || z == null) continue;
    points.push({ x, y, z });
  }
  return points.length >= 4 ? points : null;
}

/**
 * `series` dizisini sayısal serilere indirger. Bir serinin verisi
 * `labels`+`values`, `points` ya da `data` içinde olabilir; hepsi aynı
 * kanonik hâle iner.
 */
export function normalizeSeriesList(
  input: unknown,
  maxSeries = 8,
): NormalizedChartSeries[] | null {
  if (!Array.isArray(input) || input.length === 0) return null;
  const result: NormalizedChartSeries[] = [];
  for (const entry of input.slice(0, maxSeries)) {
    if (!isRecord(entry)) continue;
    const name = textOf(entry.name ?? entry.label ?? entry.title, 120) || undefined;
    const values = Array.isArray(entry.values ?? entry.y)
      ? ((entry.values ?? entry.y) as unknown[])
          .map(coerceFiniteNumber)
          .filter((value): value is number => value != null)
      : [];
    if (values.length > 0) {
      const rawLabels = Array.isArray(entry.labels ?? entry.categories ?? entry.x)
        ? ((entry.labels ?? entry.categories ?? entry.x) as unknown[])
            .map((label) => textOf(label))
            .filter(Boolean)
        : [];
      const labels =
        rawLabels.length >= values.length
          ? rawLabels.slice(0, values.length)
          : values.map((_, index) => rawLabels[index] ?? String(index + 1));
      result.push({ ...(name ? { name } : {}), labels, values });
      continue;
    }
    const fromPoints =
      normalizePointList(entry.points) ?? normalizePointList(entry.data);
    if (fromPoints) {
      result.push({ ...(name ? { name } : {}), ...fromPoints });
    }
  }
  return result.length > 0 ? result : null;
}

/**
 * Bir chart bloğunun HER giriş biçimini tek sayısal gösterime indirir.
 * `expression` yolu burada çözülmez — örnekleme çağıranda (function-sampler)
 * yapılır, çünkü aralık/çözünürlük kararları oraya ait.
 */
export function normalizeChartData(input: {
  labels?: unknown;
  values?: unknown;
  points?: unknown;
  data?: unknown;
  series?: unknown;
  seriesName?: string | null;
}): NormalizedChartSeries[] | null {
  const series = normalizeSeriesList(input.series);
  if (series) return series;

  const values = Array.isArray(input.values)
    ? input.values
        .map(coerceFiniteNumber)
        .filter((value): value is number => value != null)
    : [];
  if (values.length > 0) {
    const rawLabels = Array.isArray(input.labels)
      ? input.labels.map((label) => textOf(label)).filter(Boolean)
      : [];
    const labels =
      rawLabels.length >= values.length
        ? rawLabels.slice(0, values.length)
        : values.map((_, index) => rawLabels[index] ?? String(index + 1));
    return [
      {
        ...(input.seriesName ? { name: textOf(input.seriesName, 80) } : {}),
        labels,
        values,
      },
    ];
  }

  const fromPoints =
    normalizePointList(input.points) ?? normalizePointList(input.data);
  if (fromPoints) {
    return [
      {
        ...(input.seriesName ? { name: textOf(input.seriesName, 80) } : {}),
        ...fromPoints,
      },
    ];
  }
  return null;
}

/** Kartezyen türlerde her istemcinin desteklemesi beklenen etkileşimler. */
export const CARTESIAN_CHART_INTERACTIONS = [
  "tooltip",
  "trackball",
  "zoom",
  "pan",
  "type_switch",
  "share",
] as const;

/** Pasta/ısı haritası eksen ölçeklemez; tür değişimi de anlamsız. */
export const RADIAL_CHART_INTERACTIONS = ["tooltip", "share"] as const;

/** 3B yüzeyde eksen değişimi yok; yakınlaştırma/döndürme istemciye kalır. */
export const SURFACE_CHART_INTERACTIONS = ["tooltip", "zoom", "pan", "share"] as const;

export function defaultChartInteractions(
  chartType: string,
): Array<"tooltip" | "trackball" | "zoom" | "pan" | "type_switch" | "fullscreen" | "share"> {
  if (chartType === "pie" || chartType === "heatmap") {
    return [...RADIAL_CHART_INTERACTIONS];
  }
  if (chartType === "surface3d" || chartType === "mesh") {
    return [...SURFACE_CHART_INTERACTIONS];
  }
  return [...CARTESIAN_CHART_INTERACTIONS];
}

/**
 * Büyük serileri istemciye göndermeden önce seyreltir. 240 örnek bir telefon
 * ekranında zaten piksel başına birden çok noktadır; şema sınırı da 240.
 * Uçlar KORUNUR (ilk/son nokta trendin okunmasında belirleyici).
 */
export function downsampleSeries(
  series: NormalizedChartSeries,
  maxPoints = 240,
): NormalizedChartSeries {
  const total = series.values.length;
  if (total <= maxPoints) return series;
  const labels: string[] = [];
  const values: number[] = [];
  const step = (total - 1) / (maxPoints - 1);
  for (let index = 0; index < maxPoints; index += 1) {
    const source = Math.min(total - 1, Math.round(index * step));
    labels.push(series.labels[source] ?? String(source + 1));
    values.push(series.values[source]);
  }
  return { ...(series.name ? { name: series.name } : {}), labels, values };
}
