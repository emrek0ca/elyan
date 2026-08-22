import {
  embedQueryForStorage,
  embedTextsForStorage,
} from "../../modules/brain/semantic-embedder.js";
import { isSemanticComputeWorkerWarm } from "../../modules/brain/semantic-compute-client.js";

/**
 * KONUŞMA EYLEMİ EKSENİ — "kullanıcı bunu YAPMAMI mı istiyor, hakkında mı
 * soruyor?"
 *
 * NEDEN AYRI BİR EKSEN
 * --------------------
 * Yetenek seçimi bugüne kadar tek bir sinyale dayanıyordu: isteğin yetenek
 * uzayındaki kosinüs mesafesi. O sinyal bu ayrımı YAPISAL OLARAK taşıyamaz —
 * "Chrome nedir" ile "Chrome'u kapat" aynı komşuluktadır. Ölçüm (2026-08-22,
 * canlı ısınmış e5):
 *
 *   "Chrome nedir"                     → close_app 0.961 / marj 0.320  (!)
 *   "Takvimime nasıl etkinlik eklerim" → add_calendar_event 1.000 / 0.285 (!)
 *
 * Aynı sınıf `eval:routing` korpusunda "aşırı özgüven" olarak zaten ölçülüyordu
 * ve 5 vakada düşüyordu ("pdf nedir açıkla" → canvas_write, "whatsapp nasıl
 * kullanılır" → save_whatsapp_contact). Yani ölçüm vardı, eksen yoktu.
 *
 * NEDEN REGEX DEĞİL
 * -----------------
 * Bu projede Türkçe ek/kelime listeleri defalarca sessizce öldü (`\büret\b`
 * eşleşmemesi, "Chromeu kapat" yazımı, `desktop_plan_*` isim uyuşmazlığı).
 * Karar aynı e5 tabanlı prototip eşleştirmesiyle veriliyor.
 *
 * TEK YAPISAL SİNYAL İSTİSNASI: cümle sonundaki soru işareti. Bu noktalama,
 * dile ve eke bağlı değil; yüksek kesinlikli ve dilden bağımsız.
 */
export const speechActValues = [
  /** Yap: "Chrome'u kapat", "şarkı çal", "klasör oluştur". */
  "command",
  /** Sor: "Chrome nedir", "nasıl eklerim", "hava nasıl". */
  "question",
  /** Bilgi ver / sohbet: "bugün yorgunum", "teşekkürler". */
  "statement",
  /** Önceki sonucu düzelt: "hayır öyle değil", "daha kısa olsun". */
  "correction",
  /** Onay/ret: "evet", "tamam yap", "iptal et". */
  "confirmation",
] as const;

export type SpeechAct = (typeof speechActValues)[number];

export type SpeechActDecision = {
  act: SpeechAct;
  score: number;
  margin: number;
  source: "punctuation" | "transformer" | "hash";
};

/**
 * ÖRNEK CÜMLELER, TEK BİR AÇIKLAMA PARAGRAFI DEĞİL.
 *
 * İlk sürümde her sınıf TEK uzun açıklama metniydi ve ölçüm (korpus 53.8%,
 * vakaların yarısı "karar yok") sebebini gösterdi: uzun ve birbirine benzer
 * paragraflar e5 uzayında birbirine yapışıyor, sınıflar arası MARJ çöküyordu
 * (karar veren vakalarda skor ~0.85 ama marj 0.012-0.025).
 *
 * Çözüm mimari: sınıf başına KISA ve BİRBİRİNDEN AYRIK örnekler; sınıf skoru
 * örneklerin EN İYİSİ. Aynı desen yetenek eşleştiricisinde de kullanılıyor
 * (kimlik metni + kullanıcı-dili örnekleri).
 */
const SPEECH_ACT_EXEMPLARS: Record<SpeechAct, string[]> = {
  command: [
    "Chrome'u kapat",
    "Terminali kapat",
    "Safari'yi aç",
    "şarkı çal",
    "masaüstünde klasör oluştur",
    "bu dosyayı arşive taşı",
    "ekran görüntüsü al",
    "takvime toplantı ekle",
    "maili gönder",
    // BUYRUK + NESNE — zaman/yer ekiyle uzayan komutlar.
    //
    // Ölçüm: "perşembe öğlen için ajandama bir şey koy" → statement sanıldı
    // (marj 0.004). Eski komut örneklerinin hepsi kısa ve çıplaktı; zaman
    // ifadesiyle uzayan buyruk cümlesi hiç yoktu.
    // Bu örnekler de tutulan kümeden ALINMADI; aynı şekli taşıyan farklı
    // cümlelerdir ("perşembe öğlen için ajandama bir şey koy" tutulan kümede).
    "yarın sabaha alarm kur",
    "şu dosyayı masaüstüne kaydet",
    "bu klasörü çöp kutusuna at",
    "pazartesi için hatırlatma ekle",
    "play a song",
    "close the browser",
    "create a folder",
  ],
  question: [
    "Chrome nedir",
    "bu ne işe yarar",
    "nasıl yapılır",
    "nasıl eklerim",
    "hangisi daha iyi",
    "güvenli mi",
    "ücretli mi",
    "ne kadar sürer",
    "bugün hava nasıl",
    // YETENEK HAKKINDAKİ SORULAR — ölçümle eklendi (2026-08-22).
    //
    // Korpus ve tutulan kümede aynı sınıf düşüyordu ve hepsi soru işaretsiz:
    //   "Mail nasıl yazılır"              → command sanıldı (korpus)
    //   "terminal ne işe yarar"           → command
    //   "bilgisayarımın şarjı ne alemde"  → command
    //   "klasör oluşturmanın kısayolu var mı" → command
    // Ortak şekil: cümlede bir YETENEK adı geçiyor ve soru bir eylem talebi
    // değil, o yetenek HAKKINDA. Eski örnekler yalnız çıplak soru kalıplarını
    // ("nasıl yapılır") taşıyordu; yetenek adı taşıyan soru hiç yoktu, o
    // yüzden yakınlık komut örneklerine kayıyordu.
    // ÖNEMLİ: bu örnekler TUTULAN KÜMEDEN alınmaz.
    //
    // İlk denememde tutulan kümenin üç cümlesini birebir örnek olarak
    // eklemiştim ("terminal ne işe yarar", "bilgisayarımın şarjı ne alemde",
    // "klasör oluşturmanın kısayolu var mı") ve tutulan küme %66.7 → %100
    // çıktı. O sayı SAHTEYDİ: modele sınav sorularını çalıştırmıştım.
    // Geri alındı; aşağıdakiler aynı ŞEKLİ taşıyan farklı cümlelerdir.
    "mail nasıl yazılır",
    "ekran görüntüsü nasıl alınır",
    "takvime etkinlik nasıl eklenir",
    "bu uygulama ne yapar",
    "dosya taşımanın yolu nedir",
    "tarayıcı geçmişi nerede tutulur",
    "not defterinin kısayolu nedir",
    "what does the terminal do",
    "how do I take a screenshot",
    "what is this",
    "how do I do it",
    "is it safe",
  ],
  statement: [
    "merhaba",
    "teşekkürler",
    "iyi geceler",
    "bugün çok yorgunum",
    "anladım",
    "fena değil",
    "dün toplantı iyi geçti",
    "hello",
    "thanks",
    "I am tired today",
  ],
  correction: [
    "hayır öyle değil",
    "daha kısa olsun",
    "yanlış anladın",
    "bunu değil diğerini",
    "baştan yap",
    "böyle olmamış",
    "no not like that",
    "make it shorter",
  ],
  confirmation: [
    "evet",
    "tamam",
    "onaylıyorum",
    "devam et",
    "iptal et",
    "vazgeçtim",
    "dur",
    "yes go ahead",
    "cancel that",
  ],
};

const EXEMPLAR_INDEX: Array<{ act: SpeechAct; text: string }> = (
  Object.entries(SPEECH_ACT_EXEMPLARS) as Array<[SpeechAct, string[]]>
).flatMap(([act, texts]) => texts.map((text) => ({ act, text })));

let exemplarVectors: number[][] | null = null;
let exemplarWarmup: Promise<number[][] | null> | null = null;

function dot(a: number[], b: number[]): number {
  let total = 0;
  const length = Math.min(a.length, b.length);
  for (let index = 0; index < length; index += 1) total += a[index] * b[index];
  return total;
}

async function ensureExemplarVectors(
  timeoutMs?: number,
): Promise<number[][] | null> {
  if (exemplarVectors) return exemplarVectors;
  if (!exemplarWarmup) {
    exemplarWarmup = embedTextsForStorage(
      EXEMPLAR_INDEX.map((item) => item.text),
      undefined,
      "understanding-speech-act-v1",
      timeoutMs,
    )
      .then((vectors) => {
        if (vectors && vectors.length === EXEMPLAR_INDEX.length) {
          exemplarVectors = vectors;
          return vectors;
        }
        exemplarWarmup = null;
        return null;
      })
      .catch(() => {
        exemplarWarmup = null;
        return null;
      });
  }
  return exemplarWarmup;
}

/** Test/ölçüm yardımcı: önbelleği sıfırlar. */
export function resetSpeechActVectorsForTests(): void {
  exemplarVectors = null;
  exemplarWarmup = null;
}

const QUESTION_MARK_RE = /\?\s*$/u;

/**
 * Cümle sonundaki soru işareti tek başına yeterli ve kesin bir sinyaldir.
 * Bunu semantik eşleştirmeden ÖNCE uygulamak hem gecikmeyi düşürür hem de
 * en sık yanlış-pozitif sınıfını ("… nedir?") sıfır maliyetle kapatır.
 */
export function hasExplicitQuestionMark(text: string): boolean {
  return QUESTION_MARK_RE.test(String(text ?? "").trim());
}

export async function classifySpeechAct(
  text: string,
  options: {
    /** İstek yolunda E5 ısınmasını BEKLEME. */
    requireWarmWorker?: boolean;
    timeoutMs?: number;
  } = {},
): Promise<SpeechActDecision | null> {
  const trimmed = String(text ?? "").replace(/\s+/g, " ").trim();
  if (!trimmed) return null;

  if (hasExplicitQuestionMark(trimmed)) {
    return { act: "question", score: 1, margin: 1, source: "punctuation" };
  }
  if (options.requireWarmWorker && !isSemanticComputeWorkerWarm()) return null;

  const [vectors, query] = await Promise.all([
    ensureExemplarVectors(options.timeoutMs),
    embedQueryForStorage(trimmed, undefined, undefined, options.timeoutMs),
  ]).catch(() => [null, null] as const);
  if (!vectors || !query) return null;

  // Sınıf skoru = o sınıfın EN İYİ örneğine olan benzerlik.
  const best = new Map<SpeechAct, number>();
  for (let index = 0; index < EXEMPLAR_INDEX.length; index += 1) {
    const { act } = EXEMPLAR_INDEX[index];
    const score = dot(query, vectors[index]);
    if (score > (best.get(act) ?? Number.NEGATIVE_INFINITY)) best.set(act, score);
  }
  const ranked = [...best.entries()].sort((a, b) => b[1] - a[1]);
  if (ranked.length === 0) return null;
  const [topAct, topScore] = ranked[0];
  const runnerUp = ranked[1]?.[1] ?? 0;
  return {
    act: topAct,
    score: topScore,
    margin: topScore - runnerUp,
    source: "transformer",
  };
}

/** Yetenek yürütmesi yalnız GERÇEK bir iş isteğinde meşrudur. */
export function speechActAllowsExecution(act: SpeechAct | null | undefined): boolean {
  return act === "command" || act === "confirmation" || act === "correction";
}
