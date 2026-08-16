/**
 * EYLEM KUTUPLULUĞU — yönlendirmenin yapısal boyutu.
 *
 * NEDEN VAR
 * ---------
 * `matchDesktopCapabilitiesSemantically` bir kelime torbası benzerliği:
 * kelime tokenleri (ağırlık 1), 3-5 karakterlik n-gramlar (0.18) ve ikili
 * komşuluklar (0.65). Bu kurguda bir tokenin ağırlığı UZUNLUĞUYLA artıyor:
 *
 *   chrome (6 harf) → 1.00 + 9 n-gram × 0.18 = 2.62
 *   kapat  (5 harf) → 1.00 + 6 n-gram × 0.18 = 2.08
 *   ac     (2 harf) → 1.00 + 0 n-gram        = 1.00   ← "aç"
 *
 * Yani "Chrome'u aç" ile "Chrome'u kapat" arasındaki TEK fark, vektördeki EN
 * HAFİF özellik; nesne adı ("chrome") eylemi eziyor. Türkçe eylem fiilleri
 * kısa olduğu için (aç, sil, kur, yaz) bu yapısal olarak kaçınılmaz. Canlı
 * sonuç: "Chrome'u aç" ve "Finder'ı aç" top-1'de `close_app` üretiyordu —
 * istenenin TERSİ eylem.
 *
 * Prob cümlesi eklemek bunu çözmez (aynı dipsiz kuyu): benzerlik kütlesi yine
 * nesnede toplanır. Doğru çözüm eylemi bir ÖZELLİK değil, TİPLİ BİR BOYUT
 * olarak ele almak — ve zıt kutupları elemek.
 *
 * NASIL
 * -----
 * Sorgudan ve yetenek kimliğinden birer kutup çıkarılır. İkisi de biliniyor
 * VE zıtsa belirleyici bir ceza uygulanır; aynıysa küçük bir destek verilir.
 * Kutup çıkarılamıyorsa hiçbir şey yapılmaz — katman yalnız EMİN olduğunda
 * konuşur, sıralamanın geri kalanı semantik katmanın işi olarak kalır.
 *
 * Sorgu tarafı TAM TOKEN eşleşmesiyle çalışır, önek/sınır ile değil. Bunun
 * sebebi ölçülmüş bir tuzak: `ac` kökünü ek toleransıyla aramak "açıkla"
 * (→ `acikla`), "acele", "acaba" kelimelerini de yakalar. Çekim listesi bu
 * yüzden kapalı, küçük ve denetlenebilir tutuldu.
 */

export type CapabilityActionPolarity = "open" | "close" | "create" | "delete";

const OPPOSITE: Record<CapabilityActionPolarity, CapabilityActionPolarity> = {
  open: "close",
  close: "open",
  create: "delete",
  delete: "create",
};

/**
 * Zıt kutup cezası. Skorlar pratikte 0.3–0.6 aralığında; 0.5 zıt eylemin
 * top-1'e çıkmasını kesin olarak engeller ama yeteneği listeden tamamen
 * silmez (top-3'te kalabilir, teşhis için değerli).
 */
export const ACTION_CONFLICT_PENALTY = 0.5;

/** Aynı kutup desteği bilinçli olarak sınırlı: zıt eylemi veto ederken
 * semantik katmanın nesne/alan ayrımını korur. */
export const ACTION_MATCH_BOOST = 0.2;

/**
 * Sorgu tarafı çekim listeleri.
 *
 * `normalizeText` çıktısı üzerinde çalışır: küçük harf, aksan ayrıştırılmış
 * (aç → ac, sil → sil, kaldır → kaldir). Listeler bu yüzden aksansız yazılı.
 */
const QUERY_FORMS: Record<CapabilityActionPolarity, ReadonlySet<string>> = {
  open: new Set([
    // aç ve çekimleri
    "ac", "acar", "acsana", "acsanize", "acin", "aciniz", "acalim", "acsin",
    "acabilir", "aciver", "acip", "acmak",
    "baslat", "baslatir", "baslatsana", "baslatin",
    "calistir", "calistirir", "calistirsana", "calistirin", "calistiriver",
    "gidelim", "sekme", "sekmeye", "sekmesi", "sekmeden",
    "open", "opens", "launch", "start",
  ]),
  close: new Set([
    "kapat", "kapatir", "kapatsana", "kapatsanize", "kapatin", "kapatiniz",
    "kapatalim", "kapatsin", "kapatabilir", "kapativer", "kapatip", "kapatmak",
    "kapa", "kapan", "sonlandir", "sonlandirir",
    "cik", "ciksana", "ciksanize", "cikin", "cikiver", "cikmak", "ciksin",
    "close", "closes", "quit", "exit", "terminate",
  ]),
  create: new Set([
    "olustur", "olusturur", "olustursana", "olusturun", "olusturalim",
    "yarat", "yaratir", "ekle", "ekler", "eklesene", "ekleyin",
    "kaydet", "kaydeder", "kaydetsene",
    "create", "add", "new", "make", "generate", "save",
  ]),
  delete: new Set([
    "sil", "siler", "silsene", "silin", "siliniz", "silelim", "silmek",
    "kaldir", "kaldirir", "kaldirsana", "kaldirin",
    "delete", "remove", "erase", "clear", "drop",
  ]),
};

/**
 * Yetenek tarafı: kutup, kanonik kimliğin PARÇALARINDAN türetilir. El ile
 * tek tek işaretleme yok — yeni bir yetenek `close_` ya da `_delete` adıyla
 * eklendiğinde kutbunu otomatik kazanır, listenin bayatlaması mümkün değil.
 */
const ID_SEGMENT_POLARITY: ReadonlyArray<[string, CapabilityActionPolarity]> = [
  ["open", "open"],
  ["close", "close"],
  ["delete", "delete"],
  ["add", "create"],
  ["make", "create"],
  ["save", "create"],
  ["generate", "create"],
];

// These are safety vetoes, not a replacement router. They stop a clearly
// incompatible side-effect tool from winning when a typed resource/channel
// signal is present; the remaining candidates are still ranked normally.
const WHOLE_MACHINE_TARGETS = new Set([
  "makine", "makineyi", "bilgisayar", "bilgisayari", "ekran", "ekrani",
  "sistem", "sistemi",
]);
const TERMINAL_TARGETS = new Set(["terminal", "oturum", "shell"]);
const EXPLANATION_MARKERS = new Set(["fark", "arasindaki", "nedir", "nasil"]);
const SAFETY_VETO = -0.8;

function segmentsOf(canonicalId: string): string[] {
  return canonicalId.toLowerCase().split(/[._\-\s]+/g).filter(Boolean);
}

export function resolveCapabilityActionPolarity(
  canonicalId: string,
): CapabilityActionPolarity | null {
  // `close` is overloaded in resource/session capabilities. The user-facing
  // app action is the only close polarity that should compete for a bare
  // application request; browser/shell session cleanup has its own contract.
  if (canonicalId === "browser_session.close" || canonicalId === "shell_session_close") {
    return null;
  }
  if (canonicalId === "browser_control") return "open";
  const segments = new Set(segmentsOf(canonicalId));
  for (const [segment, polarity] of ID_SEGMENT_POLARITY) {
    if (segments.has(segment)) return polarity;
  }
  return null;
}

/**
 * Sorgunun kutbu. Birden fazla kutup görülürse `null` döner: "aç ve kapat"
 * gibi bir turda eleme yapmak, yanlış yeteneği elemekten daha risklidir.
 */
export function resolveQueryActionPolarity(
  normalizedQuery: string,
): CapabilityActionPolarity | null {
  const tokens = normalizedQuery.split(" ").filter(Boolean);
  const seen = new Set<CapabilityActionPolarity>();
  for (const token of tokens) {
    for (const polarity of ["open", "close", "create", "delete"] as const) {
      if (QUERY_FORMS[polarity].has(token)) seen.add(polarity);
    }
  }
  if (seen.size !== 1) return null;
  return [...seen][0];
}

/**
 * Skora eklenecek düzeltme. Pozitif = destek, negatif = ceza, 0 = karışma.
 */
export function actionPolarityAdjustment(input: {
  queryPolarity: CapabilityActionPolarity | null;
  capabilityId: string;
}): number {
  if (!input.queryPolarity) return 0;
  const capabilityPolarity = resolveCapabilityActionPolarity(input.capabilityId);
  if (!capabilityPolarity) return 0;
  if (capabilityPolarity === input.queryPolarity) return ACTION_MATCH_BOOST;
  if (OPPOSITE[input.queryPolarity] === capabilityPolarity) {
    return -ACTION_CONFLICT_PENALTY;
  }
  return 0;
}

export function capabilitySafetyAdjustment(input: {
  normalizedQuery: string;
  capabilityId: string;
}): number {
  const tokens = input.normalizedQuery.split(" ").filter(Boolean);
  const hasAny = (values: ReadonlySet<string>) => tokens.some((token) => values.has(token));
  const hasWhatsApp = tokens.some((token) => token === "whatsapp" || token.startsWith("whatsapp"));

  if (
    input.capabilityId === "close_app" &&
    (hasAny(WHOLE_MACHINE_TARGETS) || hasAny(TERMINAL_TARGETS))
  ) {
    return SAFETY_VETO;
  }
  if (
    input.capabilityId === "email_send" &&
    (hasWhatsApp || (tokens.includes("once") && tokens.includes("goreyim")))
  ) {
    return SAFETY_VETO;
  }
  if (
    input.capabilityId === "spreadsheet_write" &&
    hasAny(EXPLANATION_MARKERS)
  ) {
    return SAFETY_VETO;
  }
  return 0;
}
