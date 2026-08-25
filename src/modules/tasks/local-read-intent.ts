/**
 * YEREL BELGE OKUMA NİYETİ — tek tanım, iki tüketici.
 *
 * Canlı arıza (2026-08-25, görev 6126ee16): "Masaüstünde kediler hakkında bi
 * belge var onu özetle" isteği `server_brain` + `normal_chat` olarak
 * yönlendirildi; sunucu beyni masaüstünü göremediği için "Netleştireyim: tam
 * olarak neyi yapmamı istiyorsun?" diye sordu. İstek nettir, sistem anlamadı.
 *
 * İki ayrı katman aynı boşluğu taşıyordu:
 *   1) Yönlendirme: yerel sinyal listesi masaüstüne YAZMAYI tanıyor, ondan
 *      OKUMAYI tanımıyordu.
 *   2) Derleyici: "özetle" bir ÜRETİM fiili sayılıp `document_write` üretiyor,
 *      yani var olan belgeyi okumak yerine yenisini yazmaya kalkıyordu.
 *
 * Tanım burada tek yerde durur; iki katman da buradan okur. Kopyalansaydı biri
 * güncellenip diğeri unutulurdu — aynı arıza başka bir kılıkta geri gelirdi.
 */

import { trStemPattern } from "../../lib/tr-word-boundary.js";

/** İsteği YEREL yapan şey konumdur. */
const LOCAL_FILE_LOCATION_STEMS = trStemPattern([
  "masaüstü", "masaustu", "desktop", "indirilenler", "downloads", "download",
  "belgelerim", "documents", "klasör", "klasor", "dizin", "folder",
  "bilgisayarım", "bilgisayarim", "yerel dosya", "local file", "dosya sistemi",
]);

/** Tüketilecek şeyin bir BELGE olduğunu söyleyen çapa. */
const LOCAL_DOCUMENT_NOUN_STEMS = trStemPattern([
  "belge", "doküman", "dokuman", "dosya", "pdf", "docx", "rapor", "not",
  "metin", "sunum", "tablo", "document", "file",
]);

/** Var olanı TÜKETEN fiiller — üreten değil. */
const LOCAL_DOCUMENT_READ_VERB_STEMS = trStemPattern([
  "özetle", "ozetle", "oku", "incele", "analiz", "değerlendir", "degerlendir",
  "çevir", "cevir", "karşılaştır", "karsilastir", "summarize", "read", "review",
]);

/**
 * Aynı cümlede ÜRETİM/KAYDETME niyeti varsa bu bir okuma isteği değildir.
 *
 * "masaüstündeki raporu özetleyip yeni bir dosyaya kaydet" hem okur hem yazar;
 * o tur yazma yolunun onay kapılarından geçmeli, bu dar okuma şeridinden değil.
 */
const LOCAL_WRITE_INTENT_STEMS = trStemPattern([
  "kaydet", "oluştur", "olustur", "yaz", "hazırla", "hazirla", "kaydeder",
  "dışa aktar", "disa aktar", "export", "sil", "taşı", "tasi", "kopyala",
  "yeniden adlandır", "adlandir", "gönder", "gonder", "paylaş", "paylas",
]);

/**
 * Çıplak bir okuma isteği KISADIR — diğer kapalı şeritlerle (12) tutarlı,
 * "hangi dosya" tarifine biraz pay bırakan bir tavan. Birden çok bağlamı
 * sayan uzun cümle tek bir belge okuması değildir.
 */
const MAX_LOCAL_READ_WORDS = 14;

/**
 * Bu istek, YEREL bir belgeyi okumayı/tüketmeyi mi istiyor?
 *
 * Üç koşul BİRDEN aranır: konum + belge adı + okuma fiili. Tek başına
 * "özetle" sunucu işidir ("şu makaleyi özetle"); yerel yapan şey konumdur.
 */
export function hasLocalDocumentReadIntent(message: string): boolean {
  const normalized = String(message ?? "")
    .trim()
    .replace(/\s+/gu, " ")
    .slice(0, 400);
  if (!normalized) return false;
  if (normalized.split(" ").filter(Boolean).length > MAX_LOCAL_READ_WORDS) return false;
  if (LOCAL_WRITE_INTENT_STEMS.test(normalized)) return false;
  return (
    LOCAL_FILE_LOCATION_STEMS.test(normalized) &&
    LOCAL_DOCUMENT_NOUN_STEMS.test(normalized) &&
    LOCAL_DOCUMENT_READ_VERB_STEMS.test(normalized)
  );
}

/**
 * Okuma isteğinin capability menüsü.
 *
 * Dosya adı açıkça verilmediyse önce ARANMALI: "kediler hakkında bi belge"
 * bir tarif, yol değil. Adı verilmişse arama adımı gereksizdir.
 */
export function localDocumentReadCapabilities(message: string): string[] {
  const named = /(?:[\w\-.() ]+\.(?:pdf|docx?|txt|md|rtf|pptx?|xlsx?|csv))/iu.test(
    String(message ?? ""),
  );
  return named ? ["document_read"] : ["file_search", "document_read"];
}
