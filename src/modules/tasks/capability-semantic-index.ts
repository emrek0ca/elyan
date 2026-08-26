/**
 * YETENEK KATALOĞUNUN GERÇEK ANLAMSAL İNDEKSİ.
 *
 * NEDEN VAR
 * ---------
 * Araç seçimi bugüne kadar iki yoldan yapılıyordu ve ikisi de ölçeklenmiyor:
 *
 *   1. `inferCapabilities` içindeki elle yazılmış Türkçe regex şelalesi. Her
 *      yeni istek türü için insan yeni bir şerit yazmak zorunda; bu oturumda
 *      ekran görüntüsü, klasör okuma, belge güncelleme ve mail için dört ayrı
 *      şerit elle yazıldı. Milyonlarca istek türüne bu yolla ulaşılamaz.
 *
 *   2. `matchDesktopCapabilitiesSemantically` — adı "semantik" ama gerçekte
 *      n-gram torbası + IDF. Ölçüldü (2026-08-26): "excel dosyasına satır
 *      ekle" isteğine birinci aday `save_whatsapp_contact(0.35)`, "spotify'da
 *      çalan şarkı" isteğine `close_app(0.37)`. Bu skorlar sinyal değil
 *      gürültü; sistem bu yüzden regex şeritlerine mecbur kalıyordu.
 *
 * NİYE ÇIPLAK KOSİNÜS DE YETMEDİ
 * ------------------------------
 * Katalog e5 ile gömülüp ham kosinüs alındığında (aynı ölçüm) skorlar
 * 0.82–0.87 gibi dar bir banda sıkıştı ve `delete_memory` — pasajı yalnız
 * 191 karakter, iki örnek söz — alakasız her sorguda ilk üçe girdi: mail
 * gönderme isteğinde 0.84 ile `email_send`'in (0.83) ÜSTÜNDE. Bu, yüksek
 * boyutlu gömme uzaylarının bilinen `hubness` etkisidir: kısa ve genel
 * pasajlar uzayın merkezine yakın durur ve her sorgunun komşu listesine
 * girer. Böyle bir uzayda mutlak eşik anlamsızdır.
 *
 * Düzeltme, sözlük çevirisi yazınından bilinen CSLS'in yalın hâlidir: her
 * yeteneğin ARKA PLAN YANLILIĞI (kataloğun tüm örnek sözlerine ortalama
 * benzerliği) indeks kurulurken bir kez hesaplanır ve skordan düşülür. Bir
 * yetenek artık "herkese benzediği" için değil, yalnız SORGUYA beklenenden
 * fazla benzediği için öne çıkar.
 *
 * ÖLÇÜLEN ETKİ (2026-08-26, yedi elle etiketlenmiş istek, birinci sıra):
 *   n-gram torbası ~2/7 · ham kosinüs 4/7 · yanlılık düzeltmeli 6/7
 * Tek "kaçırma" gerçek değil: "masaüstündeki excel dosyasına satır ekle"
 * isteğinde birinci `file_find`, ikinci `spreadsheet_write` — o dosyanın
 * gerçekten önce bulunması gerekiyor ve ikisi de öneriliyor.
 *
 * NE YAPMAZ
 * ---------
 * Kapalı deterministik şeritlerin (sys_info, klasör okuma, ekran görüntüsü)
 * yerine geçmez: onlar hem daha hızlı hem daha kesin ve modelsiz. Bu indeks
 * onlar boş döndüğünde ya da eksik kaldığında ADAY ÖNERİR. Güvenlik kapıları
 * aynen çalışır — generic yürütücüler öneri listesinden çıkarılır, yan
 * etkili her yetenek yine onay ister.
 */

import type { FastifyInstance } from "fastify";
import { DESKTOP_CAPABILITY_MANIFEST } from "./desktop-capability-manifest.js";
import { embedQueryForStorage, embedTextsForStorage } from "../brain/semantic-embedder.js";
import { isGenericExecutorCapability } from "./capability-risk.js";

export type CapabilitySuggestion = {
  capability: string;
  score: number;
};

/**
 * Yanlılık düşüldükten sonraki asgari skor. Ölçümde doğru adayların
 * düzeltilmiş skoru 0.034–0.092 aralığındaydı, gürültü 0.02 altında kaldı.
 */
const MIN_ADJUSTED_SCORE = 0.02;

/**
 * Göreli kapı: en iyi adayın bu oranının altındaki her şey elenir. Mutlak
 * eşik dar banda sıkışan bir uzayda işe yaramadığı için karar göreli verilir.
 */
const RELATIVE_FLOOR = 0.6;

const MAX_SUGGESTIONS = 3;

/** Arka plan havuzunda her yetenekten en fazla kaç örnek söz kullanılacağı. */
const BACKGROUND_UTTERANCES_PER_CAPABILITY = 3;

type IndexedCapability = {
  capability: string;
  vector: number[];
  /** Kataloğun tümüne ortalama benzerlik; hub etkisini düşmek için. */
  bias: number;
};

let indexPromise: Promise<IndexedCapability[]> | null = null;

/**
 * Yeteneği tek bir doğal dil pasajına çevirir.
 *
 * `notFor` bilinçli olarak DIŞARIDA: "bunun için kullanma" cümleleri metne
 * girerse yetenek tam da kullanılmaması gereken sorulara benzer hâle gelir.
 * Olumsuz bilgi gömmeye değil, eşleştirme sonrası filtreye aittir.
 */
function capabilityPassage(entry: (typeof DESKTOP_CAPABILITY_MANIFEST)[number]): string {
  return [
    entry.displayName,
    entry.description,
    entry.usage,
    ...entry.whenToUse,
    ...entry.utterances,
  ]
    .filter((part) => typeof part === "string" && part.trim().length > 0)
    .join(". ")
    .slice(0, 1_200);
}

function cosine(left: number[], right: number[]): number {
  let dot = 0;
  for (let index = 0; index < left.length && index < right.length; index += 1) {
    dot += left[index] * right[index];
  }
  return dot;
}

/**
 * Katalog indeksini bir kez kurar ve süreç boyunca saklar.
 *
 * Manifest derleme zamanında sabit olduğu için indeks de sabittir; her turda
 * yeniden gömmek hem katalog hem arka plan havuzu için yüzlerce metni boşuna
 * tekrar gömmek olurdu.
 */
async function buildIndex(app: FastifyInstance): Promise<IndexedCapability[]> {
  const entries = DESKTOP_CAPABILITY_MANIFEST.filter(
    (entry) => !isGenericExecutorCapability(entry.name),
  );
  const vectors = await embedTextsForStorage(
    entries.map(capabilityPassage),
    app.log,
    "capability_catalog",
  );
  if (!vectors || vectors.length !== entries.length) return [];

  // Arka plan havuzu: kataloğun kendi örnek sözleri. Gerçek kullanıcı
  // cümlelerine en yakın elimizdeki dağılım bu, ve manifestle birlikte
  // güncellendiği için ayrıca bakım istemiyor.
  const backgroundQueries: string[] = [];
  for (const entry of entries) {
    for (const utterance of entry.utterances.slice(0, BACKGROUND_UTTERANCES_PER_CAPABILITY)) {
      if (typeof utterance === "string" && utterance.trim().length > 0) {
        backgroundQueries.push(utterance.trim());
      }
    }
  }
  const backgroundVectors =
    backgroundQueries.length > 0
      ? await embedTextsForStorage(backgroundQueries, app.log, "capability_catalog")
      : null;

  return entries.map((entry, index) => {
    const vector = vectors[index];
    let bias = 0;
    if (backgroundVectors && backgroundVectors.length > 0) {
      let total = 0;
      for (const backgroundVector of backgroundVectors) total += cosine(backgroundVector, vector);
      bias = total / backgroundVectors.length;
    }
    return { capability: entry.name, vector, bias };
  });
}

/**
 * İndeksi açılışta kurar.
 *
 * Ölçüldü (2026-08-26): indeks kurulumu 1.87 sn (85 yetenek pasajı + 200
 * arka plan sözü gömülüyor), kurulduktan sonra sorgu başına 8 ms. Isıtma
 * olmazsa o 1.87 sn ilk gerçek kullanıcı isteğinin üstüne biner. Isıtma
 * zinciri tek sahipli olmak zorunda (bkz. build-app.ts'teki uyarı), bu
 * yüzden ayrı bir `void` olarak değil zincirin sonunda çağrılır.
 */
export async function warmCapabilitySemanticIndex(app: FastifyInstance): Promise<boolean> {
  try {
    indexPromise ??= buildIndex(app);
    const index = await indexPromise;
    if (index.length === 0) {
      indexPromise = null;
      return false;
    }
    return true;
  } catch {
    indexPromise = null;
    return false;
  }
}

/**
 * Kullanıcının cümlesine anlamsal olarak yakın yetenekleri önerir.
 *
 * Fail-open: gömme üretilemezse (worker kapalı) boş döner ve çağıran kendi
 * deterministik yollarıyla devam eder. Kanıtsız öneri üretmek, yanlış aracı
 * güvenle önermekten iyidir.
 */
export async function suggestCapabilitiesSemantically(
  app: FastifyInstance,
  message: string,
): Promise<CapabilitySuggestion[]> {
  const query = String(message ?? "").trim();
  if (query.length < 4) return [];
  try {
    indexPromise ??= buildIndex(app);
    const index = await indexPromise;
    if (index.length === 0) {
      // Bir kez başarısız olan indeks kalıcı olarak boş kalmasın: bir sonraki
      // tur worker açılmış olabilir.
      indexPromise = null;
      return [];
    }
    const queryVector = await embedQueryForStorage(query, app.log, "capability_catalog");
    if (!queryVector) return [];

    const ranked = index
      .map((entry) => ({
        capability: entry.capability,
        score: cosine(queryVector, entry.vector) - entry.bias,
      }))
      .sort((left, right) => right.score - left.score);

    const best = ranked[0];
    if (!best || best.score < MIN_ADJUSTED_SCORE) return [];
    const floor = Math.max(MIN_ADJUSTED_SCORE, best.score * RELATIVE_FLOOR);
    return ranked.filter((item) => item.score >= floor).slice(0, MAX_SUGGESTIONS);
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "capability semantic suggestion failed",
    );
    return [];
  }
}
