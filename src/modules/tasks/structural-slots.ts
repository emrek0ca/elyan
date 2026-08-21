/**
 * YAPISAL YUVA ÇIKARIMI — dile ve Türkçe ekine BAĞLI OLMAYAN parçalar.
 *
 * NEDEN
 * -----
 * Bugün iş emrine giden veri tek parçaydı: `topic` = cümlenin tamamı. Ölçülen
 * sonuç (2026-08-22): planlayıcı `open_app{app_name: "Safariden youtube"}`
 * üretti — çünkü elinde ayrıştırılmış hiçbir yuva yoktu. Zarftaki
 * `extractEntities` ise YALNIZCA para tutarı çıkarıyordu.
 *
 * KAPSAM SINIRI (bilinçli)
 * ------------------------
 * Burada yalnız DİLDEN BAĞIMSIZ, yüksek kesinlikli yapılar çıkarılır: saat,
 * tarih, tırnak içi metin, biçim/uzantı, miktar+birim. Sanatçı/şarkı/uygulama
 * adı gibi anlamsal yuvalar BURADA ÇIKARILMAZ — onlar ya masaüstünün gerçek
 * envanterinden (kurulu uygulamalar) ya da anlamsal katmandan gelir. Bu
 * projede Türkçe ek tahmini defalarca sessizce öldü; o yola girilmiyor.
 *
 * Bu yuvalar KANITTIR: planlayıcı istemine veri olarak girer, tek başına
 * hiçbir kapıyı açmaz.
 */

export type StructuralSlotType =
  | "time"
  | "date"
  | "quoted"
  | "format"
  | "quantity";

export type StructuralSlot = {
  type: StructuralSlotType;
  value: string;
  normalized?: string;
};

const TIME_RE = /\b([01]?\d|2[0-3])[:.]([0-5]\d)\b/g;
const ISO_DATE_RE = /\b(\d{4})-(0?[1-9]|1[0-2])-(0?[1-9]|[12]\d|3[01])\b/g;
const DOTTED_DATE_RE = /\b(0?[1-9]|[12]\d|3[01])[./](0?[1-9]|1[0-2])[./](\d{4}|\d{2})\b/g;
// Düz ve eğik tırnaklar; tırnak içi metin en sık gerçek AD taşıyan yapıdır
// ("Karanfil"i çal). Dile bağlı değil.
const QUOTED_RE = /["“”'‘’«»]([^"“”'‘’«»]{1,120})["“”'‘’«»]/g;
const QUANTITY_RE =
  /\b(\d+(?:[.,]\d+)?)\s*(adet|tane|kez|defa|sayfa|slayt|satır|satir|kelime|dakika|saniye|saat|gün|gun|hafta|ay|yıl|yil|mb|gb|kb|tb|px|%)\b/gi;

/**
 * Biçim adları uzantı sözcükleridir; çekim eki almazlar ve İngilizce/Türkçe
 * aynıdır ("pdf yap", "word formatında", "as xlsx").
 */
const FORMAT_TOKENS = new Set([
  "pdf",
  "docx",
  "doc",
  "word",
  "xlsx",
  "xls",
  "excel",
  "csv",
  "pptx",
  "ppt",
  "txt",
  "md",
  "json",
  "png",
  "jpg",
  "jpeg",
  "webp",
  "svg",
  "gif",
  "mp3",
  "mp4",
  "wav",
  "zip",
]);

function pushUnique(slots: StructuralSlot[], slot: StructuralSlot): void {
  const key = `${slot.type}:${slot.value.toLocaleLowerCase("tr-TR")}`;
  if (slots.some((item) => `${item.type}:${item.value.toLocaleLowerCase("tr-TR")}` === key)) {
    return;
  }
  slots.push(slot);
}

export function extractStructuralSlots(message: string): StructuralSlot[] {
  const text = String(message ?? "");
  if (!text.trim()) return [];
  const slots: StructuralSlot[] = [];

  for (const match of text.matchAll(TIME_RE)) {
    const hour = String(Number.parseInt(match[1] ?? "", 10)).padStart(2, "0");
    pushUnique(slots, {
      type: "time",
      value: match[0],
      normalized: `${hour}:${match[2]}`,
    });
  }
  for (const match of text.matchAll(ISO_DATE_RE)) {
    pushUnique(slots, { type: "date", value: match[0], normalized: match[0] });
  }
  for (const match of text.matchAll(DOTTED_DATE_RE)) {
    const year = (match[3] ?? "").length === 2 ? `20${match[3]}` : match[3];
    const month = String(match[2]).padStart(2, "0");
    const day = String(match[1]).padStart(2, "0");
    pushUnique(slots, {
      type: "date",
      value: match[0],
      normalized: `${year}-${month}-${day}`,
    });
  }
  for (const match of text.matchAll(QUOTED_RE)) {
    const inner = (match[1] ?? "").trim();
    if (inner) pushUnique(slots, { type: "quoted", value: inner });
  }
  for (const match of text.matchAll(QUANTITY_RE)) {
    pushUnique(slots, {
      type: "quantity",
      value: match[0].trim(),
      normalized: `${(match[1] ?? "").replace(",", ".")} ${(match[2] ?? "").toLocaleLowerCase("tr-TR")}`,
    });
  }
  // Biçim: sözcük sınırında duran uzantı adları. Kelime içinde geçen "pdf"
  // (ör. "pdfleyici") yakalanmasın diye tokenize edilir.
  for (const token of text.split(/[^\p{L}\p{N}]+/u)) {
    const lowered = token.toLocaleLowerCase("tr-TR");
    if (FORMAT_TOKENS.has(lowered)) {
      pushUnique(slots, { type: "format", value: token, normalized: lowered });
    }
  }
  return slots.slice(0, 24);
}
