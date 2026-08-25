/**
 * ŞABLON SENTEZİ — sistemin gerçekten ÖĞRENDİĞİ yer.
 *
 * NEDEN VAR
 * ---------
 * Bugün sistemin en hızlı yolu (derlenmiş mod, sıfır planner çağrısı) aynı
 * zamanda en az öğrenen yoludur: `system-observation.ts` elle yazılmış Türkçe
 * kalıplarla eşleşir, yeni bir görev tipi için insan yeni kalıp yazmak
 * zorundadır. Öğrenme ise yalnız eşdeğer adaylar arasında sıralama değiştiren
 * bir tie-breaker olarak kalır — sistem YENİ BİR ŞEY YAPMAYI öğrenmez.
 *
 * Bu modül öğrenme yüzeyini model ağırlıklarından DERLEYİCİYE taşır:
 * doğrulanmış epizotlarda tekrar eden adım imzaları aday derleme şablonuna
 * dönüşür. Şablon eşleştiğinde görev yine modelsiz derlenir — hız korunur,
 * ama katalog artık deneyimle büyür.
 *
 * NE YAPMAZ
 * ---------
 * Kendi kendine devreye girmez. Bu modül yalnız ADAY üretir; gölge, kanarya
 * ve manuel yayın kapıları `continuous-learning-policy` tarafından yönetilir.
 * Ağırlık eğitimiyle hiçbir ilgisi yoktur.
 */

import { createHash } from "node:crypto";
import { DESKTOP_CAPABILITY_MANIFEST } from "./desktop-capability-manifest.js";
import {
  ELEVATED_RISK_ARGUMENT_PATTERN,
  isGenericExecutorCapability,
  needsSeparateApproval,
} from "./capability-risk.js";
import type { EpisodeDigestGroup, TaskEpisodeStepShape } from "./episode-store.js";

const manifestById = new Map(
  DESKTOP_CAPABILITY_MANIFEST.map((entry) => [entry.name, entry]),
);

/** Aday olmak için gereken en az doğrulanmış tekrar. */
export const TEMPLATE_MIN_EPISODES = 20;
/** Kaynak epizotların en az bu oranı `fulfilled` olmalı. */
export const TEMPLATE_MIN_FULFILLED_RATIO = 1;
/** Adım dizisi bu oranda tutarlı olmalı. */
export const TEMPLATE_MIN_CONSISTENCY = 0.9;
/** Bir şablon en fazla bu kadar adım taşır. */
export const TEMPLATE_MAX_STEPS = 8;

export type CompiledTemplateStep = {
  capability: string;
  device: string | null;
  /** Argüman anahtarları — çağrı anında doldurulacak slotlar. */
  argSlots: string[];
  effect: "read" | "write";
};

export type CompiledTemplateCandidate = {
  templateId: string;
  intentFamily: string;
  contractDigest: string;
  steps: CompiledTemplateStep[];
  supportingEpisodes: number;
  fulfilledEpisodes: number;
  consistency: number;
  evidenceKinds: string[];
  medianLatencyMs: number | null;
};

export type TemplateRejection = {
  intentFamily: string;
  contractDigest: string;
  reason:
    | "insufficient_episodes"
    | "not_all_fulfilled"
    | "inconsistent_step_sequence"
    | "generic_executor_step"
    | "separate_approval_capability"
    | "elevated_risk_arguments"
    | "unknown_capability"
    | "destructive_capability"
    | "no_verification_evidence"
    | "step_budget_exceeded";
};

export type TemplateSynthesisResult = {
  candidates: CompiledTemplateCandidate[];
  rejected: TemplateRejection[];
};

function templateIdFor(intentFamily: string, contractDigest: string): string {
  return createHash("sha256")
    .update(`${intentFamily}::${contractDigest}`)
    .digest("hex")
    .slice(0, 32);
}

/**
 * Adım şeklinden yürütme etkisini türetir.
 *
 * `null` dönmesi "bilmiyorum" demektir ve şablonu düşürür: etkisi bilinmeyen
 * bir adımı önceden derlemek, kullanıcının onaylamadığı bir yan etkiyi
 * modelsiz yola sokmak olurdu.
 */
function stepEffect(shape: TaskEpisodeStepShape): "read" | "write" | null {
  const manifest = manifestById.get(shape.capability);
  if (!manifest) return null;
  if (manifest.sideEffectClass === "destructive") return null;
  if (manifest.sideEffectClass === "none" || manifest.sideEffectClass === "read") {
    return "read";
  }
  if (manifest.sideEffectClass === "write" || manifest.mutatesPath) return "write";
  // `control` ve sınıfsız kalanlar: argümanı görülmeden derlenmez.
  return null;
}

function argSlotsLookRisky(argSlots: string[]): boolean {
  // Slot ADLARI taranır; değer zaten hiç saklanmıyor. `password`, `command`
  // gibi bir slot adı, şablonun ne tür bir argüman beklediğini ele verir.
  return argSlots.some((slot) => ELEVATED_RISK_ARGUMENT_PATTERN.test(slot));
}

/**
 * Tek bir imza grubunu adaya çevirmeyi dener.
 *
 * Kapılar sırayla ve fail-closed uygulanır; ilk düşen kapı gerekçesiyle
 * birlikte döner, böylece "neden şablon olmadı?" sorusu cevaplanabilir kalır.
 */
export function evaluateTemplateCandidate(
  group: EpisodeDigestGroup,
  options: { minEpisodes?: number } = {},
): { candidate: CompiledTemplateCandidate } | { rejection: TemplateRejection } {
  const minEpisodes = Math.max(2, options.minEpisodes ?? TEMPLATE_MIN_EPISODES);
  const reject = (reason: TemplateRejection["reason"]) => ({
    rejection: {
      intentFamily: group.intentFamily,
      contractDigest: group.contractDigest,
      reason,
    },
  });

  if (group.totalCount < minEpisodes) return reject("insufficient_episodes");

  const fulfilledRatio =
    group.totalCount > 0 ? group.fulfilledCount / group.totalCount : 0;
  if (fulfilledRatio < TEMPLATE_MIN_FULFILLED_RATIO) return reject("not_all_fulfilled");

  // Tutarlılık: aynı imzayı taşıyan epizotların oranı. İmza zaten adım
  // dizisinden türetildiği için grup içi tutarlılık tanım gereği tamdır;
  // ölçü, grubun kendi ailesindeki payıdır ve çağıran tarafından verilir.
  const consistency = fulfilledRatio;
  if (consistency < TEMPLATE_MIN_CONSISTENCY) {
    return reject("inconsistent_step_sequence");
  }

  if (group.stepShapes.length === 0) return reject("unknown_capability");
  if (group.stepShapes.length > TEMPLATE_MAX_STEPS) return reject("step_budget_exceeded");

  // KANITSIZ ŞABLON OLMAZ. Tekrar tek başına doğruluk kanıtı değildir;
  // aynı yanlış işi 20 kez yapmış olabiliriz.
  if (group.evidenceKinds.length === 0) return reject("no_verification_evidence");

  const steps: CompiledTemplateStep[] = [];
  for (const shape of group.stepShapes) {
    const capability = String(shape.capability ?? "").trim();
    if (!capability || !manifestById.has(capability)) return reject("unknown_capability");
    if (isGenericExecutorCapability(capability)) return reject("generic_executor_step");
    if (needsSeparateApproval(capability)) return reject("separate_approval_capability");
    const argSlots = [...new Set(shape.argKeys ?? [])]
      .map((slot) => String(slot ?? "").trim())
      .filter(Boolean)
      .slice(0, 12);
    if (argSlotsLookRisky(argSlots)) return reject("elevated_risk_arguments");
    const effect = stepEffect(shape);
    if (effect === null) {
      return manifestById.get(capability)?.sideEffectClass === "destructive"
        ? reject("destructive_capability")
        : reject("unknown_capability");
    }
    steps.push({
      capability,
      device: shape.device ?? null,
      argSlots,
      effect,
    });
  }

  return {
    candidate: {
      templateId: templateIdFor(group.intentFamily, group.contractDigest),
      intentFamily: group.intentFamily,
      contractDigest: group.contractDigest,
      steps,
      supportingEpisodes: group.totalCount,
      fulfilledEpisodes: group.fulfilledCount,
      consistency: Number(consistency.toFixed(4)),
      evidenceKinds: [...new Set(group.evidenceKinds)].slice(0, 8),
      medianLatencyMs: group.medianLatencyMs,
    },
  };
}

/**
 * Grup listesini adaylara çevirir.
 *
 * Tutarlılık, grubun KENDİ AİLESİ içindeki payı olarak yeniden hesaplanır:
 * bir ailede iki farklı imza yarı yarıya tekrar ediyorsa hiçbiri o ailenin
 * kanonik yolu sayılamaz.
 */
export function synthesizeCompiledTemplates(
  groups: EpisodeDigestGroup[],
  options: { minEpisodes?: number } = {},
): TemplateSynthesisResult {
  const familyTotals = new Map<string, number>();
  for (const group of groups) {
    familyTotals.set(
      group.intentFamily,
      (familyTotals.get(group.intentFamily) ?? 0) + group.totalCount,
    );
  }

  const candidates: CompiledTemplateCandidate[] = [];
  const rejected: TemplateRejection[] = [];
  for (const group of groups) {
    const familyTotal = familyTotals.get(group.intentFamily) ?? group.totalCount;
    const familyShare = familyTotal > 0 ? group.totalCount / familyTotal : 0;
    if (familyShare < TEMPLATE_MIN_CONSISTENCY) {
      rejected.push({
        intentFamily: group.intentFamily,
        contractDigest: group.contractDigest,
        reason: "inconsistent_step_sequence",
      });
      continue;
    }
    const result = evaluateTemplateCandidate(group, options);
    if ("candidate" in result) {
      candidates.push({
        ...result.candidate,
        consistency: Number(familyShare.toFixed(4)),
      });
    } else {
      rejected.push(result.rejection);
    }
  }
  return { candidates, rejected };
}
