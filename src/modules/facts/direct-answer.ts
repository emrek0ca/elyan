import type { FastifyInstance } from "fastify";
import { buildAssistantWebSearchBlock } from "../chat/message-blocks.js";
import { resolveFactAnswer } from "./service.js";
import type { FactSelection } from "./select.js";
import type { FactAnswer } from "./types.js";

/**
 * SIFIR-TOKEN ŞERİDİ.
 *
 * Sağlayıcı tipli ve TAM bir cevap döndürdüğünde, turu modele hiç göndermeden
 * deterministik cümle + kaynak kartıyla bitiririz. Kazanç ölçülebilir: model
 * çağrısı yok (bu kod tabanında sade sohbet turu p50 ~4.800 istem token'ı),
 * ilk token beklemesi yok, sağlayıcı gecikmesi dışında bekleme yok.
 *
 * Kapsam BİLEREK dar; şerit yalnız şu koşulların HEPSİ sağlanınca açılır:
 *   - bayrak açık (varsayılan KAPALI — ses şablonlaşır, bu bir ürün kararıdır),
 *   - sağlayıcı ANLAMSAL olarak seçilmiş (domain yedeği değil) ve güveni yüksek,
 *   - tur sohbet şeridinde, ek/görsel/araç yok,
 *   - anlama zarfı yalnız düz bir sohbet cevabı istiyor (tablo/grafik/belge değil),
 *   - kullanıcı gerekçe/yorum istememiş ("neden", "yorumla", "ne yapmalıyım").
 *
 * Bunlardan biri bile tutmazsa `null` döner ve tur normal model yolunda devam
 * eder. Şerit hiçbir koşulda cevabın İÇERİĞİNİ değiştirmez; yalnız o içeriği
 * modelsiz basar.
 */

/** Yorum/öneri isteyen turlar şablon cümleyle savuşturulamaz. */
const REASONING_REQUEST_PATTERN =
  /(?<!\p{L})(neden|niçin|nicin|yorumla|değerlendir|degerlendir|analiz|karşılaştır|karsilastir|ne yapmalıyım|ne yapmaliyim|önerir misin|onerir misin|tavsiye|açıkla|acikla|anlat|explain|why|compare|should i)(?!\p{L})/iu;

export type FactDirectAnswer = {
  text: string;
  answer: FactAnswer;
  block: ReturnType<typeof buildAssistantWebSearchBlock>;
};

export function isFactDirectAnswerEnabled(app: FastifyInstance): boolean {
  return app.config?.ELYAN_FACT_DIRECT_ANSWER_ENABLED === true;
}

/**
 * Turun tipli olgu KANITINI çözer — sıfır-token şeridinden BAĞIMSIZ olarak.
 *
 * NEDEN AYRI: web temellendirme kapısı yalnız kendi bildiği alanlarda (hava,
 * piyasa, haber…) açılır. "New York'ta saat kaç", "sıradaki resmî tatil ne
 * zaman" ya da "son depremler" turları o kapıdan HİÇ geçmez; sağlayıcı
 * yazılsa bile hiç çağrılmazdı. Bu yüzden olgu çözümü kapının önünde,
 * anlamsal seçimin kendi kararıyla yapılır.
 *
 * Sonuç modele KANIT olarak gider; şerit kapalıyken de tur bu veriyle
 * cevaplanır, yani sağlayıcı katmanı bayrağa bağlı değildir.
 */
export async function resolveFactEvidence(
  app: FastifyInstance,
  input: {
    prompt: string;
    domain?: string;
    shortlist?: FactSelection[];
    queryVector?: number[] | null;
  },
): Promise<FactAnswer | null> {
  const resolution = await resolveFactAnswer(app, {
    prompt: input.prompt,
    domain: input.domain,
    shortlist: input.shortlist,
    queryVector: input.queryVector,
  });
  return resolution?.answer ?? null;
}

export async function buildFactDirectAnswer(
  app: FastifyInstance,
  input: {
    prompt: string;
    domain?: string;
    /** Anlama zarfının istediği çıktı türleri; yalnız düz cevap kabul edilir. */
    desiredOutputKinds: string[];
    /** Erken katmanda zaten çözülmüş kanıt; yeniden çözülmez. */
    answer?: FactAnswer | null;
  },
): Promise<FactDirectAnswer | null> {
  if (!isFactDirectAnswerEnabled(app)) return null;
  if (REASONING_REQUEST_PATTERN.test(input.prompt)) return null;
  if (
    input.desiredOutputKinds.length > 0 &&
    !input.desiredOutputKinds.every((kind) => kind === "chat_reply")
  ) {
    return null;
  }

  const answer =
    input.answer ??
    (await resolveFactEvidence(app, { prompt: input.prompt, domain: input.domain }));
  if (!answer) return null;
  if (answer.confidence < 0.9) return null;
  const block = buildAssistantWebSearchBlock({
    query: input.prompt.slice(0, 320),
    queries: [input.prompt.slice(0, 320)],
    confidence: "high",
    retrievedAt: answer.citation.observedAt,
    results: [
      {
        title: answer.citation.title,
        url: answer.citation.url,
        snippet: answer.snippet.slice(0, 400),
        sourceHost: answer.citation.sourceHost,
        verificationState: "verified",
      },
    ],
  });
  if (!block) return null;

  return {
    text: `${answer.directAnswer} Kaynak: ${answer.citation.sourceHost}`,
    answer,
    block,
  };
}
