import { DESKTOP_CAPABILITY_MANIFEST } from "../tasks/desktop-capability-manifest.js";

/**
 * Yetenek etiketinin CEVAP olarak teslim edilmesini engelleyen tek kapı.
 *
 * NEDEN TEK KAPI
 * --------------
 * Canlıda kullanıcı sırayla "desktop_operator.run", "Belge okuma" ve "Klasör
 * ağacı" cevaplarını gördü. Bunlar yetenek ADI/ETİKETİ; cevap değil. Bir araç
 * kullanıcıya dönük metin üretmediğinde iz özeti mesaj yerine geçiyordu.
 *
 * Sızıntı masaüstünde ONLARCA yerden çıkabiliyor (`assistantMessage` 20+ yerde
 * atanıyor); tek tek yamamak sürekli yeni bir yol atlıyordu. Bu yüzden denetim
 * masaüstünde değil, mobilin okuduğu mesajın MUTLAKA geçtiği backend sınırında
 * yapılır: kaynak hangi kod yolu olursa olsun kapanır.
 *
 * Etiket listesi manifest'ten gelir (tek kaynak `capability_registry`), elle
 * tutulmaz — yeni yetenek eklenince koruma kendiliğinden kapsar.
 */

const FALLBACK_MESSAGE = "İşlem tamamlandı.";

let cachedLabels: Set<string> | null = null;

function labelSet(): Set<string> {
  if (cachedLabels) {
    return cachedLabels;
  }
  const labels = new Set<string>();
  for (const entry of DESKTOP_CAPABILITY_MANIFEST) {
    const name = String(entry?.name ?? "").trim().toLowerCase();
    if (name) {
      labels.add(name);
    }
    const display = String(
      (entry as { displayName?: unknown })?.displayName ?? "",
    )
      .trim()
      .toLowerCase();
    if (display) {
      labels.add(display);
    }
  }
  cachedLabels = labels;
  return labels;
}

/** Metin, yalnızca yetenek adlarından/etiketlerinden mi ibaret? */
export function isCapabilityLabelOnly(value: unknown): boolean {
  const text = String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
  if (!text) {
    return false;
  }
  // Uzun metin etiket değildir; erken çık (sıcak yolda ucuz kalsın).
  if (text.length > 120) {
    return false;
  }
  const labels = labelSet();
  const parts = text
    .split(/[;,\n]+/)
    .map((part) => part.trim().toLowerCase())
    .filter(Boolean);
  if (parts.length === 0) {
    return false;
  }
  // TAM eşleşme aranır: "Belge okuma tamamlandı, 3 sayfa" gerçek bir cevaptır
  // ve teslim edilmelidir; yalnız "Belge okuma" etikettir.
  return parts.every((part) => labels.has(part));
}

/**
 * Kullanıcıya gidecek mesajı denetler. Etiketten ibaretse nötr bir cümleyle
 * değiştirir; gerçek araç çıktısına DOKUNMAZ.
 */
export function ensureUserFacingMessage(value: unknown): string {
  const text = String(value ?? "");
  return isCapabilityLabelOnly(text) ? FALLBACK_MESSAGE : text;
}
