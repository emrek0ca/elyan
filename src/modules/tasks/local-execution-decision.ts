import {
  classifySpeechAct,
  speechActAllowsExecution,
  type SpeechActDecision,
} from "../../core/understanding/speech-act.js";
import type { FastifyBaseLogger } from "fastify";
import {
  evaluateLocalActionEvidence,
  isDesktopCapabilityVectorCacheReady,
} from "./desktop-capability-embedding-match.js";

/**
 * YEREL YÜRÜTME KARARI — TEK SİNYAL DEĞİL, KANIT UZLAŞMASI.
 *
 * NEDEN BÖYLE
 * -----------
 * İki sinyal de TEK BAŞINA yetersiz; ikisi de ölçüldü:
 *
 *  * Yetenek eşleşmesi ezberliyor ve soruyu emirden ayıramıyor
 *    (`eval:routing`: korpus %98.1 → tutulan %57.5, 40.6 puan genelleme payı;
 *     "Chrome nedir" → close_app 0.961 / marj 0.320).
 *  * Konuşma eylemi ekseni tek başına güvenilir değil
 *    (`eval:speech-act`: korpus %96.2 → tutulan %66.7) ve marj dağılımları
 *    çakıştığı için eşikle sertleştirilemiyor.
 *
 * 2026-08-22'de bunlardan BİRİNİ tek başına kapı yapmak canlıya tehlikeli bir
 * kural gönderdi ("Chrome nedir" Chrome'u kapatabilirdi) ve geri alındı.
 *
 * KURAL: yürütme yalnız İKİ KANIT DA aynı yöne işaret ettiğinde açılır.
 *   1) konuşma eylemi yürütmeye izin veriyor (emir / onay / düzeltme), VE
 *   2) istek yetenek uzayında bir YEREL EYLEM yeteneğine oturuyor.
 *
 * Kanıtlardan biri karar veremiyorsa (model soğuk, zaman aşımı) sonuç
 * FAIL-CLOSED: sohbet yolu sürer. Kaçırmak, yanlış iş yapmaktan ucuzdur.
 */
export type LocalExecutionDecision = {
  requiresLocalExecution: boolean;
  capability: string | null;
  speechAct: SpeechActDecision | null;
  capabilityScore: number;
  capabilityMargin: number;
  reason:
    | "speech_act_and_capability_agree"
    | "speech_act_blocks"
    | "capability_not_local_action"
    | "evidence_unavailable";
};

const BLOCKED: Omit<LocalExecutionDecision, "reason" | "speechAct"> = {
  requiresLocalExecution: false,
  capability: null,
  capabilityScore: 0,
  capabilityMargin: 0,
};

export async function decideLocalExecution(input: {
  message: string;
  timeoutMs?: number;
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">;
}): Promise<LocalExecutionDecision> {
  const message = String(input.message ?? "").trim();
  if (!message || !isDesktopCapabilityVectorCacheReady()) {
    return { ...BLOCKED, speechAct: null, reason: "evidence_unavailable" };
  }

  const [speechAct, capabilityEvidence] = await Promise.all([
    classifySpeechAct(message, { timeoutMs: input.timeoutMs }).catch(() => null),
    evaluateLocalActionEvidence({ query: message, logger: input.logger }).catch(
      () => null,
    ),
  ]);

  if (!speechAct || !capabilityEvidence) {
    return { ...BLOCKED, speechAct, reason: "evidence_unavailable" };
  }

  const base = {
    capability: capabilityEvidence.capability,
    capabilityScore: capabilityEvidence.score,
    capabilityMargin: capabilityEvidence.margin,
    speechAct,
  };

  // SORU ASLA YÜRÜTME AÇMAZ. Canlı arızanın sınıfı budur.
  if (!speechActAllowsExecution(speechAct.act)) {
    return { ...base, requiresLocalExecution: false, reason: "speech_act_blocks" };
  }
  // MARJ EŞİĞİ KALIYOR — ÖLÇÜM KARAR VERDİ.
  //
  // Eşiği kaldırmayı denedim: korpus doğruluğu 76.9%→84.6% çıktı ama TUTULAN
  // kümede bir TEHLİKELİ YÜRÜTME belirdi — "terminal ne işe yarar" (bir SORU)
  // → `shell_run` masaüstünde. Konuşma eylemi o cümlede yanılıyor (command,
  // marj 0.014) ve marj eşiği olmayınca onu tutan hiçbir şey kalmıyor.
  //
  // İki hata eşit değil: kaçırma zararsız, yanlış yürütme canlıda zarar verir.
  // Bu yüzden daha çok kaçıran ama SIFIR tehlikeli üreten sürüm seçildi.
  if (!capabilityEvidence.localAction) {
    return {
      ...base,
      requiresLocalExecution: false,
      reason: "capability_not_local_action",
    };
  }
  return {
    ...base,
    requiresLocalExecution: true,
    reason: "speech_act_and_capability_agree",
  };
}
