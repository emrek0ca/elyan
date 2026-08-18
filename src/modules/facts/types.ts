import type { FastifyBaseLogger } from "fastify";

/**
 * TİPLİ OLGU SAĞLAYICI KATMANI.
 *
 * NEDEN AYRI BİR MODÜL
 * --------------------
 * Deterministik REST kaynakları (hava, kur, kripto) bugüne kadar
 * `web-grounding.ts` içinde GÖMÜLÜ üç özel durumdu ve seçimleri REGEX'ti:
 * `/bitcoin|btc/`, `/dolar|usd/` — yani "Solana kaç TL" aramaya düşüyor,
 * "Çankırı'ya gidiyorum mont alayım mı" hava sağlayıcısını hiç tetiklemiyordu.
 * Bu, bu kod tabanının belgelenmiş baskın hata sınıfı: sözcük deseni anlamı
 * temsil edemez ve her yeni kaynak o sınıfı bir kat daha büyütür.
 *
 * Katmanın sözleşmesi üç maddedir:
 *   1. SEÇİM ANLAMSALDIR. Sağlayıcı, e5 ile niyet ifadeleri üzerinden seçilir;
 *      top-1 marjı eşiğin altındaysa HİÇBİR sağlayıcı seçilmez ve tur normal
 *      web temellendirmesine düşer.
 *   2. VARLIK ÇIKARIMI KATALOGDANDIR. Coin/para birimi gibi varlıklar regex
 *      ile değil, normalize edilmiş katalog araması ile bulunur — yeni bir
 *      coin eklemek yeni bir desen değil, yeni bir satırdır.
 *   3. BAŞARISIZLIK ARAMAYA DÜŞER, TAHMİNE DEĞİL. Sağlayıcı hata verirse
 *      sonuç `null`'dur; uydurma bir sayı asla üretilmez.
 */

export type FactProviderId =
  | "open_meteo"
  | "open_meteo_air"
  | "frankfurter"
  | "coingecko"
  | "local_time"
  | "usgs_earthquake"
  | "nager_holidays";

/** Veri sınıfı — TTL ve tazelik beklentisini birlikte taşır. */
export type FactDataClass = "realtime" | "hourly" | "daily";

export type FactCitation = {
  title: string;
  url: string;
  sourceHost: string;
  /** Sağlayıcının BİLDİRDİĞİ gözlem anı — bizim istek anımız değil. */
  observedAt: string;
};

export type FactAnswer = {
  providerId: FactProviderId;
  dataClass: FactDataClass;
  /** Modele verilecek kanıt satırı. Anahtar/kimlik verisi içermez. */
  snippet: string;
  /**
   * Modelsiz basılabilecek, tek cümlelik deterministik cevap.
   * Sıfır-token şeridi bunu kullanır; şerit kapalıyken de kanıt olarak gider.
   */
  directAnswer: string;
  citation: FactCitation;
  /** Kart/tipli blok üretimi için yapılandırılmış değerler. */
  values: Record<string, string | number>;
  confidence: number;
  ttlMs: number;
};

export type FactResolveContext = {
  timeoutMs: number;
  logger?: Pick<FastifyBaseLogger, "warn" | "debug">;
};

export type FactProvider<P = unknown> = {
  id: FactProviderId;
  /**
   * e5 ile gömülecek niyet ifadeleri. Kelime listesi DEĞİL — kullanıcının
   * gerçekten yazacağı cümlelerdir; benzerlik bunlar üzerinden ölçülür.
   */
  intents: string[];
  dataClass: FactDataClass;
  timeoutMs: number;
  ttlMs: number;
  /**
   * e5 çalışmadığında kullanılacak ÜST AKIŞ sinyali. Yeni bir regex sahibi
   * yaratmamak için mevcut `FreshDataPolicy.domain` değerlerine bağlanır;
   * karşılığı olmayan sağlayıcı e5 yokken hiç seçilmez (arama devralır).
   */
  fallbackDomain?: "weather" | "market";
  /** Turun bu sağlayıcı için gereken varlığı taşıyıp taşımadığı. */
  extract(prompt: string): P | null;
  /** Önbellek anahtarının parametre parçası. */
  cacheKey(params: P): string;
  resolve(context: FactResolveContext, params: P): Promise<FactAnswer | null>;
};

/** Tip silme yardımcısı: kayıt defteri heterojen parametre tiplerini tutar. */
export function defineFactProvider<P>(provider: FactProvider<P>): FactProvider<unknown> {
  return provider as unknown as FactProvider<unknown>;
}
