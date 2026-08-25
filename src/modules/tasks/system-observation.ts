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
/**
 * Gözlem OLMAYAN fiiller.
 *
 * Bir sistem gözlemi turun ASIL EYLEMİ olmalıdır. Canlı hata (2026-08-24):
 * "Bugünkü sağlık, takvim, saat, cihaz durumu ve bildirim bağlamına göre kısa
 * ama tam bir çalışma planı çıkar." cümlesi yalnız "saat" geçtiği için
 * `sys_info(time)` olarak derleniyordu; masaüstü eşleşmemişse kullanıcı bir
 * PLANLAMA sorusuna karşılık "önce bilgisayar eşle" cevabı alıyordu.
 *
 * Üretici/yaratıcı bir fiil varsa istek gözlem değildir.
 */
const NON_OBSERVATION_SYSTEM_PATTERN = trStemPattern([
  "araştır", "arastir", "trend", "makale", "rapor", "kaydet", "karşılaştır",
  "karsilastir", "satın", "satin",
  "plan", "hazırla", "hazirla", "oluştur", "olustur", "yaz", "özetle",
  "ozetle", "öner", "oner", "çıkar", "cikar", "analiz", "değerlendir",
  "degerlendir", "taslak", "liste",
]);

/**
 * Çıplak gözlem KISADIR. Birden çok bağlamı sayan uzun bir cümle, içinde
 * "saat" ya da "durum" geçse bile tek bir sistem okuması değildir.
 */
const MAX_OBSERVATION_WORDS = 12;

/** Kimlik bilgisi isteği — kapalı salt-okuma şeridine giremez. */
const CREDENTIAL_REQUEST_PATTERN = trStemPattern([
  "şifre", "sifre", "parola", "password", "passphrase", "secret", "gizli anahtar",
  "anahtar", "token", "kimlik bilgisi", "credential",
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
  if (normalized.split(" ").filter(Boolean).length > MAX_OBSERVATION_WORDS) return null;
  // KİMLİK BİLGİSİ İSTEĞİ GÖZLEM DEĞİLDİR.
  //
  // "wifi şifresini göster" ağ terimi ve durum ipucu taşıdığı için ağ
  // gözlemine derleniyordu. İki ayrı zarar: kullanıcı parola sorup ağ durumu
  // cevabı alır, VE istek onay gerektiren kimlik bilgisi yolundan kaçar.
  // Fail-closed: dinamik yola bırakılır, orada onay kapısı çalışır.
  if (CREDENTIAL_REQUEST_PATTERN.test(normalized)) return null;

  // AĞ DURUMU KENDİ ÇAPASINI TAŞIR.
  //
  // "internete bağlı mıyım" gibi sorular genel gözlem ipuçlarının hiçbirine
  // uymuyor ve dinamik döngüye düşüyordu. Ama ağ terimi + bağlantı-durumu
  // ipucu birlikte geldiğinde niyet tektir ve kapalıdır.
  //
  // Sadece ağ terimine bakmak YETMEZ: "internetten bir şey indir" de ağ
  // terimi taşır. Bu yüzden iki koşul birden aranır.
  const NETWORK_TERM = trStemPattern(["wifi", "wi-fi", "ağ", "ag", "network", "internet"]);
  const NETWORK_STATE_CUE = trStemPattern([
    "bağlı", "bagli", "bağlantı", "baglanti", "kopuk", "çekiyor", "cekiyor",
    "var mı", "var mi", "nasıl", "nasil",
  ]);
  if (NETWORK_TERM.test(normalized) && NETWORK_STATE_CUE.test(normalized)) {
    return "network";
  }

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
    trStemPattern(["wifi", "wi-fi", "ağ", "ag", "network", "internet"]).test(normalized) ||
    /(?:ip\s+adres)/iu.test(normalized)
  ) return "network";
  if (trStemPattern(["tarih", "date"]).test(normalized)) return "date";
  if (trStemPattern(["saat", "zaman", "time"]).test(normalized)) return "time";
  if (
    hasDeviceContext &&
    /(?:sistem|bilgisayar|cihaz).{0,30}(?:durum|bilgi)|(?:durum|bilgi).{0,30}(?:sistem|bilgisayar|cihaz)/iu.test(normalized)
  ) return "all";
  return null;
}


/**
 * YEREL KLASÖR OKUMA — ikinci modelsiz derleyici şeridi.
 *
 * NEDEN EKLENDİ
 * -------------
 * Ölçüm (2026-08-25, yerel kullanıcı testi): dosya/klasör okuma isteklerinin
 * BEŞTE BEŞİ derlenemiyor ve dinamik ajan döngüsüne düşüyordu —
 * "Masaüstünde hangi klasörler var?", "Downloads klasörümde ne var?" gibi
 * tamamen kapalı, salt-okuma istekler için planner modeli çağrılıyordu.
 * Sistem gözlemi (`sys_info`) için kurulan kapalı sözleşmenin aynısı burada
 * da geçerlidir: hedef bellidir, eylem tektir, yan etkisi yoktur.
 *
 * FAIL-CLOSED: kök AÇIKÇA söylenmemişse derlenmez. "Hangi klasörler var?"
 * tek başına neyin listeleneceğini söylemez; belirsizliği tahmin etmektense
 * dinamik yola bırakmak doğrudur.
 */
export type LocalListingRoot = "~/Desktop" | "~/Downloads" | "~/Documents";

export type LocalListingQuery = {
  capability: "directory_tree";
  root: LocalListingRoot;
};

/** Listeleme İSTEĞİ — "göster/listele/ne var" ailesi. */
const LISTING_CUE_PATTERN = trStemPattern([
  "listele", "liste", "göster", "goster", "neler", "hangi", "kaç", "kac",
  "içeri", "iceri", "içinde", "icinde", "bak",
]);

/**
 * Listeleme OLMAYAN fiiller.
 *
 * `NON_OBSERVATION_SYSTEM_PATTERN` burada kullanılamaz: o küme "liste"
 * kelimesini de reddediyor ve "klasörleri listele" isteğini düşürürdü. Bu
 * yüzden listeleme şeridinin kendi dışlama kümesi var — üretim ve mutasyon
 * fiilleri.
 */
const NON_LISTING_VERB_PATTERN = trStemPattern([
  "araştır", "arastir", "rapor", "kaydet", "oluştur", "olustur", "yaz",
  "hazırla", "hazirla", "özetle", "ozetle", "sil", "taşı", "tasi", "kopyala",
  "yeniden adlandır", "adlandir", "aç", "ac", "çalıştır", "calistir",
  "gönder", "gonder", "paylaş", "paylas", "indir", "yükle", "yukle",
]);

const LISTING_ROOTS: Array<{ root: LocalListingRoot; pattern: RegExp }> = [
  { root: "~/Desktop", pattern: trStemPattern(["masaüstü", "masaustu", "desktop"]) },
  {
    root: "~/Downloads",
    pattern: trStemPattern(["indirilen", "downloads", "download", "indirme"]),
  },
  {
    root: "~/Documents",
    pattern: trStemPattern(["belge", "belgelerim", "documents", "dokuman", "doküman"]),
  },
];

/** Listelenecek şeyin gerçekten DOSYA SİSTEMİ olduğunu doğrulayan çapa. */
const FILESYSTEM_TARGET_PATTERN = trStemPattern([
  "klasör", "klasor", "dizin", "folder", "dosya", "file", "içerik", "icerik",
]);

const MAX_LISTING_WORDS = 12;

export function parseLocalListingQuery(message: string): LocalListingQuery | null {
  const normalized = String(message ?? "")
    .trim()
    .replace(/\s+/gu, " ")
    .slice(0, 320)
    .toLocaleLowerCase("tr-TR");
  if (!normalized) return null;
  if (normalized.split(" ").filter(Boolean).length > MAX_LISTING_WORDS) return null;
  if (NON_LISTING_VERB_PATTERN.test(normalized)) return null;

  const hasListingCue =
    LISTING_CUE_PATTERN.test(normalized) ||
    /(?:ne\s+var|neler\s+var|ne\s+kadar\s+dosya)/iu.test(normalized);
  if (!hasListingCue) return null;

  // Kök AÇIKÇA söylenmiş olmalı: belirsiz hedef derlenmez.
  const match = LISTING_ROOTS.find((entry) => entry.pattern.test(normalized));
  if (!match) return null;

  // "masaüstü" tek başına yetmez; listelenen şey dosya sistemi olmalı.
  // ("masaüstünde ne var" gibi çıplak biçimler için hedef çapası aranır.)
  if (!FILESYSTEM_TARGET_PATTERN.test(normalized) && !/(?:ne\s+var|neler\s+var)/iu.test(normalized)) {
    return null;
  }

  return { capability: "directory_tree", root: match.root };
}
