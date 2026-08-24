import { trStemPattern } from "../../lib/tr-word-boundary.js";

export type SystemInfoQuery =
  | "battery"
  | "cpu"
  | "ram"
  | "disk"
  | "network"
  | "time"
  | "date"
  | "all";

const SYSTEM_OBSERVATION_CUE_PATTERN = trStemPattern([
  "kaç", "durum", "kullanım", "kullanim", "seviye", "yüzde", "yuzde",
  "kalan", "boş", "bos", "bağlı", "bagli", "göster", "goster", "söyle",
  "soyle", "kontrol", "öğren", "ogren",
]);
const LOCAL_DEVICE_PATTERN = trStemPattern([
  "bilgisayar", "laptop", "macbook", "mac", "cihaz", "makine", "sistem",
]);
const NON_OBSERVATION_SYSTEM_PATTERN = trStemPattern([
  "araştır", "arastir", "trend", "makale", "rapor", "kaydet", "karşılaştır",
  "karsilastir", "satın", "satin",
]);

/**
 * Shared, model-free compiler for read-only local system observations.
 * Turkish stems intentionally accept possessive/case suffixes while research
 * phrases such as "batarya trendlerini araştır" remain outside this path.
 */
export function parseSystemInfoQuery(message: string): SystemInfoQuery | null {
  const normalized = String(message ?? "")
    .trim()
    .replace(/\s+/gu, " ")
    .slice(0, 320)
    .toLocaleLowerCase("tr-TR");
  if (!normalized || NON_OBSERVATION_SYSTEM_PATTERN.test(normalized)) return null;

  const hasDeviceContext = LOCAL_DEVICE_PATTERN.test(normalized);
  const hasObservationCue =
    SYSTEM_OBSERVATION_CUE_PATTERN.test(normalized) ||
    /(?:ne\s+alemde|ne\s+kadar|nedir|ne\s+durumda|\?)/iu.test(normalized);
  if (!hasDeviceContext && !hasObservationCue) return null;

  if (trStemPattern(["pil", "şarj", "sarj", "batarya"]).test(normalized)) return "battery";
  if (trStemPattern(["cpu", "işlemci", "islemci", "processor"]).test(normalized)) return "cpu";
  if (trStemPattern(["ram", "bellek", "memory"]).test(normalized)) return "ram";
  if (
    trStemPattern(["disk", "depolama", "storage"]).test(normalized) ||
    /(?:boş|bos)\s+alan/iu.test(normalized)
  ) return "disk";
  if (
    trStemPattern(["wifi", "wi-fi", "ağ", "ag", "network"]).test(normalized) ||
    /(?:internet\s+bağlantı|internet\s+baglanti|ip\s+adres)/iu.test(normalized)
  ) return "network";
  if (trStemPattern(["tarih", "date"]).test(normalized)) return "date";
  if (trStemPattern(["saat", "zaman", "time"]).test(normalized)) return "time";
  if (
    hasDeviceContext &&
    /(?:sistem|bilgisayar|cihaz).{0,30}(?:durum|bilgi)|(?:durum|bilgi).{0,30}(?:sistem|bilgisayar|cihaz)/iu.test(normalized)
  ) return "all";
  return null;
}
