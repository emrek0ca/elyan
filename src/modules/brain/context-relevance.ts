import { estimateTokens } from "./text-metrics.js";
import { contentTerms } from "./lexical-turkish.js";

/**
 * Bağlam kapısı: hatırlatmayı ITMEK yerine ÇEKMEK.
 *
 * Önceki davranış: elde ne varsa her turda prompt'a giriyordu — geçmiş
 * epizod, davranış kalıpları, bilgi tabanı rehberi, hafıza sonuçları. Bunun
 * iki maliyeti var. Birincisi hız: her blok token'dır, her token gecikmedir.
 * İkincisi ve daha kötüsü kalite: alakasız hatırlatma modeli dağıtır.
 * "Bana bir şarkı öner" derken geçen haftaki fatura görevini prompt'a
 * koymak, hatırlamamaktan kötüdür.
 *
 * Buradaki skorlama kasten BASİT ve açıklanabilir tutuldu: embedding çağrısı
 * yok, ek gecikme yok. Amaç mükemmel sıralama değil, bariz alakasızı elemek.
 * Karar her zaman gerekçesiyle döner; kapının kendisi de denetlenebilir olmalı.
 *
 * ÖNEMLİ SINIR: buraya yalnız *isteğe bağlı hatırlatmalar* girer. Güvenlik
 * direktifleri, araç protokolü, kullanıcının bu turda eklediği belge ve bu
 * turda yapılan arama sonuçları kapıya HİÇ uğramaz — onlar bağlam değil,
 * turun kendisidir.
 */

export type ContextCandidate = {
  /** Blok metni; boşsa aday sayılmaz. */
  text: string | null | undefined;
  /**
   * Bloğun tazeliği (0..1). Zamanla değeri düşen kaynaklar için verilir;
   * zamansız kaynaklarda 1 bırakılır.
   */
  freshness?: number;
  /** Bu iş türünde bloğun taşıdığı temel değer (0..1). */
  affinity?: number;
};

export type ContextGateDecision = {
  name: string;
  admitted: boolean;
  score: number;
  tokens: number;
  /** İnsan tarafından okunabilir gerekçe — telemetriye gider. */
  reason: string;
};

export type ContextGateResult = {
  /** Kapıyı geçen bloklar; geçemeyenler `null`. */
  blocks: Record<string, string | null>;
  decisions: ContextGateDecision[];
  admittedTokens: number;
  droppedTokens: number;
};

/** Bu eşiğin altındaki blok prompt'a hiç girmez. */
const ADMISSION_THRESHOLD = 0.28;

/**
 * Örtüşme için kullanılan terim kümesi.
 *
 * İki şey burada kasıtlı olarak ayıklanır. Birincisi durak kelimeler: "bir",
 * "ve", "the" her metinde vardır ve alakayı değil dili ölçer. İkincisi ve
 * daha önemlisi KOMUT kelimeleri — "yaz", "kaydet", "masaüstüne", "1 sayfalık"
 * kullanıcının ne istediğini değil işin nasıl teslim edileceğini söyler.
 * Bunlar sinyale karışırsa geçmişteki her masaüstü işi her yeni masaüstü
 * isteğine alakalı görünür; kapı o zaman eleme yapmaz, gürültü geçirir.
 *
 * Terimler ayrıca köklerine indirilir: Türkçe eklemeli bir dil olduğu için
 * "ilkeleri" ile "ilke" tam-token karşılaştırmasında eşleşmez ve alakalı bir
 * blok yalnız çekim eki yüzünden elenir.
 */
function tokenizeForOverlap(value: string): Set<string> {
  return new Set(contentTerms(value, { limit: 64 }));
}

/**
 * Sorgu ile blok arasındaki terim örtüşmesi (0..1).
 *
 * Payda sorgunun kendisidir, bloğun değil: uzun bir blok yalnız büyük olduğu
 * için yüksek puan almamalı. Sorulan şeyin ne kadarına dokunuyor, o ölçülür.
 */
function overlapRatio(query: Set<string>, block: Set<string>): number {
  if (query.size === 0 || block.size === 0) return 0;
  let hits = 0;
  for (const word of query) {
    if (block.has(word)) hits += 1;
  }
  return hits / query.size;
}

export function gateOptionalContext(input: {
  prompt: string;
  candidates: Record<string, ContextCandidate>;
}): ContextGateResult {
  const queryTerms = tokenizeForOverlap(input.prompt ?? "");
  const blocks: Record<string, string | null> = {};
  const decisions: ContextGateDecision[] = [];
  let admittedTokens = 0;
  let droppedTokens = 0;

  for (const [name, candidate] of Object.entries(input.candidates)) {
    const text = typeof candidate.text === "string" ? candidate.text.trim() : "";
    if (!text) {
      blocks[name] = null;
      continue;
    }

    const tokens = estimateTokens(text);
    const freshness = clamp01(candidate.freshness ?? 1);
    const affinity = clamp01(candidate.affinity ?? 1);
    const overlap = overlapRatio(queryTerms, tokenizeForOverlap(text));

    // Örtüşme tek başına karar veremez: sorgu çok kısa olabilir ("devam et")
    // ya da blok kullanıcının kelimeleriyle değil özetle yazılmış olabilir.
    // Bu yüzden örtüşme bir TABANIN üstüne eklenir; işin türüne uygun ve taze
    // bir blok, kelimesi geçmese de bir şansı hak eder.
    const score = clamp01((0.35 + 0.65 * overlap) * freshness * affinity);
    const admitted = score >= ADMISSION_THRESHOLD;

    blocks[name] = admitted ? text : null;
    if (admitted) {
      admittedTokens += tokens;
    } else {
      droppedTokens += tokens;
    }
    decisions.push({
      name,
      admitted,
      score: Math.round(score * 1000) / 1000,
      tokens,
      reason: admitted
        ? `örtüşme ${pct(overlap)} · tazelik ${pct(freshness)} · uyum ${pct(affinity)}`
        : `eşik altı (${pct(score)} < ${pct(ADMISSION_THRESHOLD)}): örtüşme ${pct(overlap)} · tazelik ${pct(freshness)} · uyum ${pct(affinity)}`,
    });
  }

  return { blocks, decisions, admittedTokens, droppedTokens };
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

function pct(value: number): string {
  return `%${Math.round(value * 100)}`;
}

/**
 * Zamanla değer kaybeden kaynaklar için tazelik (0..1).
 *
 * Doğrusal bir düşüş kasıtlı: yarı ömür eğrisi burada kesinlik yanılsaması
 * yaratırdı — elimizdeki tek gerçek sinyal "ne kadar eski".
 */
export function freshnessFromAge(
  updatedAt: Date | null | undefined,
  horizon: number,
): number {
  if (!updatedAt || Number.isNaN(updatedAt.getTime())) return 0.5;
  const age = Date.now() - updatedAt.getTime();
  if (age <= 0) return 1;
  if (age >= horizon) return 0;
  return 1 - age / horizon;
}
