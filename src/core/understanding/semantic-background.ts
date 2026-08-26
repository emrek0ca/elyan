/**
 * ANLAMSAL SKORLARIN ORTAK TABANI.
 *
 * NEDEN VAR
 * ---------
 * Yüksek boyutlu gömme uzaylarında kosinüs skorları dar bir banda sıkışır ve
 * bazı adaylar `hub` olur: kısa, genel ya da alanının tamamını anlatan
 * metinler her sorgunun komşu listesine girer. Böyle bir uzayda MUTLAK eşik
 * anlamını yitirir — ve bu projede iki ayrı yerde tam olarak bu yaşandı:
 *
 *   · Yetenek kataloğunda `delete_memory` (pasajı 191 karakter) alakasız
 *     sorgularda 0.85 alıp `email_send`'in üstüne çıkıyordu.
 *   · Connector seçiminde ölçüldü (2026-08-26): "teşekkürler" 0.852,
 *     "merhaba nasılsın" 0.849, "bir fıkra anlat" 0.831 — üçü de sert
 *     `require` bandında, yani model bu mesajlarda araç çağırmaya
 *     ZORLANIYORDU. On sıradan mesajın beşi.
 *
 * Her iki yerde de çare aynı: adayın ARKA PLAN YANLILIĞINI — sıradan bir
 * kullanıcı cümlesine ortalama benzerliğini — skordan düşmek. Aday artık
 * "herkese benzediği" için değil, yalnız SORGUYA beklenenden fazla
 * benzediği için öne çıkar. (Sözlük çevirisi yazınındaki CSLS'in yalın hâli.)
 *
 * HAVUZUN SEÇİMİ KRİTİKTİR
 * ------------------------
 * İlk denemede connector adaylarının kendi metinleri havuz yapıldı ve sonuç
 * DAHA KÖTÜ oldu: hepsi birbirine benzeyen arama araçları olduğu için
 * yanlılık şişti ve meşru mail istekleri de elendi. Havuz, ADAY dağılımını
 * değil SORGU dağılımını temsil etmek zorunda.
 *
 * Bu yüzden havuz, desktop kataloğunun `utterances` alanıdır: bunlar gerçek
 * kullanıcı cümleleridir, geniş bir konu yelpazesine yayılırlar ve manifestle
 * birlikte güncellendikleri için ayrıca bakım istemezler.
 */

import type { FastifyBaseLogger } from "fastify";
import { DESKTOP_CAPABILITY_MANIFEST } from "../../modules/tasks/desktop-capability-manifest.js";
import { embedTextsForStorage } from "../../modules/brain/semantic-embedder.js";

/** Havuza her yetenekten en fazla kaç örnek söz girer. */
const UTTERANCES_PER_CAPABILITY = 3;

const EMBED_LABEL = "semantic_background";

let backgroundPromise: Promise<number[][]> | null = null;

export function cosineSimilarity(left: number[], right: number[]): number {
  let dot = 0;
  for (let index = 0; index < left.length && index < right.length; index += 1) {
    dot += left[index] * right[index];
  }
  return dot;
}

async function buildBackground(logger?: FastifyBaseLogger): Promise<number[][]> {
  const queries: string[] = [];
  for (const entry of DESKTOP_CAPABILITY_MANIFEST) {
    for (const utterance of entry.utterances.slice(0, UTTERANCES_PER_CAPABILITY)) {
      if (typeof utterance === "string" && utterance.trim().length > 0) {
        queries.push(utterance.trim());
      }
    }
  }
  if (queries.length === 0) return [];
  const vectors = await embedTextsForStorage(queries, logger, EMBED_LABEL);
  return vectors ?? [];
}

/**
 * Arka plan havuzunu bir kez kurar ve süreç boyunca saklar.
 *
 * Boş dönerse önbellek TEMİZLENİR: gömücü worker'ı henüz açılmamış olabilir
 * ve bir sonraki çağrı yeniden denemeli. Kalıcı boş bir havuz, yanlılığı
 * sessizce sıfırlayıp düzeltmeyi etkisiz bırakırdı.
 */
export async function getSemanticBackground(
  logger?: FastifyBaseLogger,
): Promise<number[][]> {
  try {
    backgroundPromise ??= buildBackground(logger);
    const background = await backgroundPromise;
    if (background.length === 0) backgroundPromise = null;
    return background;
  } catch {
    backgroundPromise = null;
    return [];
  }
}

/**
 * Bir adayın arka plan yanlılığı: havuzdaki sıradan cümlelere ortalama
 * benzerliği. Havuz yoksa 0 döner — yani düzeltme uygulanmaz ve çağıran
 * eskisi gibi davranır. Fail-open burada doğru: ölçemediğimiz bir düzeltmeyi
 * uydurmak, düzeltmesiz çalışmaktan kötüdür.
 */
export function backgroundBias(vector: number[], background: number[][]): number {
  if (background.length === 0) return 0;
  let total = 0;
  for (const backgroundVector of background) {
    total += cosineSimilarity(backgroundVector, vector);
  }
  return total / background.length;
}

/**
 * Havuzu ve türetilmiş yanlılıkları sıfırlar.
 *
 * Havuz süreç ömrü boyunca önbelleklenir; testler aynı süreçte sırayla
 * koştuğu için bir testin kurduğu havuz diğerine sızardı.
 */
export function resetSemanticBackgroundForTests(): void {
  backgroundPromise = null;
}
