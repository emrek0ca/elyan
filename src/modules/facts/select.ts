import type { FastifyBaseLogger } from "fastify";
import { embedTextsForStorage, embedQueryForStorage } from "../brain/semantic-embedder.js";
import { FACT_PROVIDERS } from "./registry.js";
import type { FactProvider } from "./types.js";

/**
 * SAĞLAYICI SEÇİMİ — e5 ile, regex ile değil.
 *
 * Her sağlayıcının niyet ifadeleri bir kez gömülür (süreç ömrü boyunca
 * önbellekte) ve kullanıcı turu ile kosinüs benzerliği ölçülür. İki kapı var:
 *
 *   1. MUTLAK EŞİK — top-1 benzerliği bunun altındaysa hiçbir sağlayıcı
 *      seçilmez. e5 normalize vektör döndürdüğü için bu skor karşılaştırılabilir.
 *   2. KISA LİSTE — "hava durumu" ile "hava kalitesi" e5 uzayında birbirine
 *      ÇOK yakındır; tek bir top-1 kararına bağlanmak kırılgandır. Bunun
 *      yerine eşiği geçen ve top-1'e yakın en fazla iki aday sırayla denenir;
 *      ilk GERÇEK cevap üreten kazanır. Sağlayıcılar turda kendi varlıklarını
 *      bulamazsa zaten `null` döndüğü için bu, kullanıcının sormadığı veriyi
 *      vermeye yol açmaz — yalnız yakın-beraberlikte çıkmaz sokağı kaldırır.
 *
 * Kısa liste tek adaya İNDİRGENMEZ: canlı ölçümde (regresyon testi) "hava
 * durumu" turu top-1'de hava KALİTESİ sağlayıcısını seçebiliyor; eski katı
 * top-1 kuralında o tur hiç cevaplanamıyordu.
 *
 * e5 çalışmıyorsa (worker kapalı/cooldown) seçim YAPILMAZ; çağıran taraf
 * yalnızca mevcut `FreshDataPolicy.domain` sinyaline bağlı yedek yolu kullanır.
 * Böylece bu modül ikinci bir sözcük-deseni sahibi hâline gelmez.
 */

/**
 * Ham skor tabanı. 0.82'den 0.85'e ÇIKARILDI (2026-08-28).
 *
 * Sebep canlı bir arıza: "Bir önceki cevabını kısalt" isteğine kullanıcı
 * DEPREM RAPORU aldı. İstem `usgs_earthquake` sağlayıcısına 0.8608 puan
 * veriyor ve eski taban 0.82 idi; sağlayıcı çağrıldı, sonucu kanıt olarak
 * isteme girdi ve model onunla cevap verdi.
 */
const ABSOLUTE_THRESHOLD = 0.85;

/**
 * EN İYİ ADAYIN İKİNCİYE FARKI — asıl kapı budur.
 *
 * ÖLÇÜLEN ARIZA: ham skor bu uzayda HER ZAMAN yüksektir ve tek başına hiçbir
 * turu elemiyordu. "Fotosentezi 3 cümleyle açıkla." hava durumu sağlayıcısına
 * 0.839, "Selam nasılsın?" 0.829 veriyordu; eşik 0.82. Sonuç: HER sohbet turu
 * iki sağlayıcılık bir kısa liste üretip her birini ağ üzerinden deniyordu.
 * Bedeli ilk token'ın önünde 767 ms — modelin kendi 440 ms'sinden fazla.
 *
 * Doğru soru "skor yüksek mi?" değil, "model gerçekten BİR sağlayıcI seçti
 * mi?". Olgusal olmayan bir istemde tüm sağlayıcılar neredeyse berabere kalır
 * (model fikirsizdir); gerçek bir eşleşmede biri öne çıkar. Ölçüm:
 *
 *   olgusal DEĞİL   "Selam nasılsın?"           0.0001
 *                   "Python'da liste sıralama"  0.0007
 *                   "Fotosentezi açıkla"        0.0012
 *                   "Bana bir şiir yaz"         0.0024
 *                   "1350 TL'nin KDV'si"        0.0025
 *                   "Atatürk'ün ilkeleri"       0.0061
 *   ————————————————— eşik 0.012 (boşluğun ortası) —————————————————
 *   olgusal         "Dolar kaç TL?"             0.0174
 *                   "Bugün hava nasıl?"         0.0188
 *                   "İstanbul'da hava kaç derece?" 0.0302
 *                   "Bitcoin fiyatı"            0.0487
 *                   "Euro ne kadar oldu?"       0.0595
 *                   "Yarın yağmur yağacak mı?"  0.0670
 *
 * İki küme arasında 2.8 kat boşluk var. Aynı sinyal
 * `rankSemanticTextCandidates` içinde `transformerMinMargin` olarak zaten
 * kullanılıyor; olgu seçicisinde eksikti.
 *
 * Tek sağlayıcı varsa marj tanımsızdır ve kapı uygulanmaz — ölçemediği bir
 * şey yüzünden turu kısıtlamak yanlış tarafa düşmek olurdu.
 */
const MIN_SELECTION_MARGIN = 0.015;

/**
 * EŞİKLER DAR — VE BU BİLİNÇLİ.
 *
 * 18 Türkçe istemlik birleşik ölçümde (2026-08-28) İKİ SİNYAL DE TEK BAŞINA
 * ayırmıyor:
 *
 *   skor    olgu 0.8555–0.9418   olgusal değil 0.7788–0.8608   → örtüşüyor
 *   marj    olgu 0.0174–0.0670   olgusal değil 0.0001–0.0251   → örtüşüyor
 *
 * Birlikte ayırıyorlar (skor ≥ 0.85 VE marj ≥ 0.015) ama paylar ince:
 * skorda 0.0057 ("Bir önceki cevabını uzat" 0.8498 ↔ "İstanbul'da hava kaç
 * derece?" 0.8555), marjda 0.0037 ("Bir önceki cevabını kısalt" 0.0137 ↔
 * "Dolar kaç TL?" 0.0174). Bu, ölçülen kümeye uydurulmuş bir sınırdır; bir
 * ilke değildir ve genelleme garantisi yoktur.
 *
 * Yine de sıkılaştırmak doğru, çünkü HATALAR SİMETRİK DEĞİL:
 *   yanlış pozitif → alakasız canlı veri isteme kanıt olarak girer ve model
 *                    onunla cevap verir (deprem raporu). YANLIŞ CEVAP.
 *   yanlış negatif → canlı veri alınmaz, model kendi bilgisiyle cevaplar.
 *                    Muhtemelen BAYAT ama yanlış değil.
 *
 * Sınırı gevşetmek isteyen, önce ölçüm setini genişletmeli — bu kod tabanında
 * aynı hata iki kez küçük örneklemle yapıldı (olgu seçimi ve masaüstü rota
 * yükseltmesi; ikincisi geri alındı).
 */
/** Top-1'e bu kadar yakın adaylar da denenir. */
const SHORTLIST_WINDOW = 0.03;
const SHORTLIST_MAX = 2;

/**
 * NİYET KATALOĞU AÇILIŞTA ISITILIR.
 *
 * Ölçüm (canlı konteyner, 2026-08-19): katalog tembel kurulduğunda İLK olgu
 * turu 4.614 ms ödüyordu — 7 sağlayıcının 35 niyet cümlesi o turun içinde
 * gömülüyor. Tur bu bütçeyi karşılayamayınca sağlayıcı seçilemiyor ve istek
 * sessizce tam web aramasına düşüyor: kullanıcı "Hatay hava durumu" sorusuna
 * MGM/Wikipedia sonuçlarından derlenmiş bir cevap alıyor.
 *
 * Aynı hata sınıfı bu kod tabanında daha önce `primeSemanticComputeWorker`
 * ile çözülmüştü ("ilk KULLANICI turu ödüyordu"); burada tekrarlanmış. Isıtma
 * açılışta bir kez denenir, başarısız olursa hiçbir yol kötüleşmez — seçim
 * yapılamaz, domain yedeği devralır.
 */
const SELECTION_EMBED_TIMEOUT_MS = 2_500;
/** Isıtma yolunun bütçesi: model yüklemesi dahil, kimseyi bekletmiyor. */
const WARMUP_EMBED_TIMEOUT_MS = 60_000;

let intentVectors: Array<{ provider: FactProvider<unknown>; vectors: number[][] }> | null = null;
let intentVectorsPromise: Promise<void> | null = null;

function cosine(left: number[], right: number[]): number {
  let dot = 0;
  for (let index = 0; index < left.length && index < right.length; index += 1) {
    dot += left[index] * right[index];
  }
  return dot;
}

async function ensureIntentVectors(
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">,
  embedTimeoutMs: number = SELECTION_EMBED_TIMEOUT_MS,
): Promise<void> {
  if (intentVectors) return;
  if (!intentVectorsPromise) {
    intentVectorsPromise = (async () => {
      const built: Array<{ provider: FactProvider<unknown>; vectors: number[][] }> = [];
      for (const provider of FACT_PROVIDERS) {
        const vectors = await embedTextsForStorage(
          provider.intents,
          logger,
          `facts:intents:${provider.id}`,
          embedTimeoutMs,
        );
        if (!vectors) {
          // Tek bir sağlayıcı gömülemezse katalog EKSİK olur; yarım katalogla
          // seçim yapmak sistematik olarak yanlış sağlayıcıyı seçtirir.
          intentVectorsPromise = null;
          return;
        }
        built.push({ provider, vectors });
      }
      intentVectors = built;
    })();
  }
  await intentVectorsPromise;
}

export type FactSelection = {
  provider: FactProvider<unknown>;
  score: number;
};

export async function selectFactProviders(input: {
  prompt: string;
  queryVector?: number[] | null;
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">;
}): Promise<FactSelection[]> {
  await ensureIntentVectors(input.logger);
  if (!intentVectors) return [];
  // Sorgu gömme KRİTİK YOLDADIR; sınırsız beklemesi turu rehin alır.
  // Zaman aşımında seçim yapılmaz ve domain yedeği devralır.
  const queryVector =
    input.queryVector === undefined
      ? await embedQueryForStorage(
          input.prompt,
          input.logger,
          "facts:query",
          SELECTION_EMBED_TIMEOUT_MS,
        )
      : input.queryVector;
  if (!queryVector) return [];

  const scored = intentVectors
    .map(({ provider, vectors }) => ({
      provider,
      score: vectors.reduce((best, vector) => Math.max(best, cosine(queryVector, vector)), -1),
    }))
    .sort((left, right) => right.score - left.score);

  const top = scored[0];
  if (!top || top.score < ABSOLUTE_THRESHOLD) return [];
  const runnerUp = scored[1];
  if (runnerUp && top.score - runnerUp.score < MIN_SELECTION_MARGIN) return [];
  return scored
    .filter((entry) => entry.score >= top.score - SHORTLIST_WINDOW)
    .slice(0, SHORTLIST_MAX);
}

/**
 * Açılışta çağrılır. Beklenmez (`void`): ısıtma turu kimseyi geciktirmez.
 *
 * ISITMAYA İSTEK YOLUNUN ZAMAN AŞIMI UYGULANMAZ. İlk denemede uygulandı ve
 * canlıda `ready:false` döndü: açılışta ONNX oturumu henüz kurulmamış oluyor,
 * 2.5 sn yetmiyor, katalog kurulamıyor ve bedeli yine ilk KULLANICI turu
 * ödüyordu — yani ısıtma hiçbir işe yaramıyordu. Aynı ders
 * `primeSemanticComputeWorker` yorumunda zaten yazılı: "ısıtmanın çağıran
 * zaman aşımı YOK".
 *
 * Model gerçekten hazır olana kadar birkaç kez, artan aralıklarla denenir.
 * Hepsi tutmazsa hiçbir yol kötüleşmez: seçim yapılamaz, domain yedeği
 * devralır ve istek yolu kendi sıkı bütçesiyle çalışmaya devam eder.
 */
export async function primeFactSelection(
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">,
): Promise<boolean> {
  const backoffMs = [0, 5_000, 15_000, 30_000];
  for (const delay of backoffMs) {
    if (delay > 0) {
      await new Promise((resolve) => {
        const timer = setTimeout(resolve, delay);
        timer.unref?.();
      });
    }
    await ensureIntentVectors(logger, WARMUP_EMBED_TIMEOUT_MS).catch(() => undefined);
    if (intentVectors) return true;
    // Başarısız deneme, sıradakinin yeniden kurmasına izin vermeli.
    intentVectorsPromise = null;
  }
  return false;
}

export function resetFactSelectionForTests(): void {
  intentVectors = null;
  intentVectorsPromise = null;
}
