import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { callGeminiFreeStructured } from "../brain/gemini-utility-client.js";

/**
 * Hedef doğrulaması — "adımlar koştu" ile "kullanıcının istediği oldu"nun
 * farkını ölçen katman.
 *
 * NEDEN
 * -----
 * `semanticGoal.successCriteria` üretiliyor, planlama istemine yazılıyor ve
 * sonda HİÇ kontrol edilmiyordu. Bitişteki doğrulama yetenek düzeyindeydi:
 * araç `ok=true` döndü mü, dosya üretildi mi. Yani `status="completed"`
 * yalnızca "adımlar hatasız koştu" demekti.
 *
 * Bu, tek başına bir kalite sorunu değil: sistemdeki BÜTÜN öğrenme
 * mekanizmaları o etikete bakıyor — plan örnek havuzu yalnız `completed`
 * görevlerden besleniyor, başarısızlık analitiği onun tersini sayıyor,
 * sürekli öğrenme boru hattı açılırsa aynı etiketi kullanacak. Gürültülü
 * etiketten öğrenmek, yanlışı öğrenmektir. Bu yüzden önce etiket.
 *
 * KAPSAM — bilinçli olarak DAR
 * ----------------------------
 * Bu katman görevin durumunu DEĞİŞTİRMEZ. Yalnız bir yargı üretir ve kaydeder.
 * Yanlış çalışan bir doğrulayıcının çalışan akışları bozmasını istemiyoruz;
 * önce yargının kendisi ölçülsün, güvenilirliği görülsün, sonra karara
 * bağlanabilir.
 *
 * KIRMIZI ÇİZGİ
 * -------------
 * Kelime/regex eşleştirmesi yok. Karar iki parçalı: ucuz YAPISAL ön-eleme
 * (kriter var mı, sonuç var mı, artefakt bekleniyor muydu) + gerekiyorsa
 * ucuz SEMANTİK çağrı. Semantik katman erişilemezse yargı `unknown` olur —
 * asla uydurma bir "met"/"missed" üretilmez.
 */

export type GoalVerdict = "met" | "partial" | "missed" | "unknown";

export type GoalVerificationResult = {
  verdict: GoalVerdict;
  /** Neden bu yargıya varıldı — insan ve log içindir. */
  reason: string;
  /** Tutturulamayan kriterler (varsa). */
  unmetCriteria: string[];
  confidence: number;
};

export type GoalEvidence = {
  successCriteria: string[];
  /** Görevin ürettiği kullanıcıya dönük metin. */
  resultText: string;
  /** Görev bir artefakt teslim etmeyi beyan etmiş miydi? */
  artifactRequired: boolean;
  /** Gerçekten artefakt üretildi mi? */
  artifactProduced: boolean;
  /** Yürütülen adım sayısı. */
  executedStepCount: number;
};

/**
 * Yapısal ön-eleme. Saf fonksiyon — ağ yok, kolay test edilir.
 *
 * `null` dönerse yapısal olarak karar verilemiyor demektir ve semantik
 * katmana geçilir. Amaç: her görevde model çağırmamak.
 */
export function evaluateGoalEvidence(
  evidence: GoalEvidence,
): GoalVerificationResult | null {
  const criteria = evidence.successCriteria
    .map((item) => String(item ?? "").trim())
    .filter(Boolean);

  if (criteria.length === 0) {
    // Beyan edilmiş bir başarı ölçütü yoksa doğrulanacak bir şey de yok.
    // "met" demek yanıltıcı olurdu — ölçmedik, ölçemedik.
    return {
      verdict: "unknown",
      reason: "no_success_criteria_declared",
      unmetCriteria: [],
      confidence: 1,
    };
  }

  if (evidence.executedStepCount <= 0) {
    return {
      verdict: "missed",
      reason: "no_step_executed",
      unmetCriteria: criteria,
      confidence: 0.9,
    };
  }

  // Beyan edilen artefakt yoksa hedef tutmamıştır; bu deterministik ve
  // tartışmasız — semantik çağrıya gerek yok.
  if (evidence.artifactRequired && !evidence.artifactProduced) {
    return {
      verdict: "missed",
      reason: "declared_artifact_missing",
      unmetCriteria: criteria,
      confidence: 0.95,
    };
  }

  if (!evidence.resultText.trim() && !evidence.artifactProduced) {
    return {
      verdict: "missed",
      reason: "no_result_evidence",
      unmetCriteria: criteria,
      confidence: 0.85,
    };
  }

  // Yapısal olarak temiz: kriterlerin gerçekten karşılanıp karşılanmadığına
  // ancak anlam bakabilir.
  return null;
}

const goalVerdictSchema = z.object({
  verdict: z.enum(["met", "partial", "missed"]),
  reason: z.string().trim().max(240),
  unmetCriteria: z.array(z.string().trim().max(200)).max(6),
  confidence: z.number().min(0).max(1),
});

const goalVerdictJsonSchema = {
  type: "object",
  additionalProperties: false,
  required: ["verdict", "reason", "unmetCriteria", "confidence"],
  properties: {
    verdict: { type: "string", enum: ["met", "partial", "missed"] },
    reason: { type: "string" },
    unmetCriteria: { type: "array", items: { type: "string" } },
    confidence: { type: "number" },
  },
} as const;

const SYSTEM_PROMPT = [
  "You judge whether a completed desktop task actually satisfied the user's declared success criteria.",
  "You are NOT judging whether the steps ran without error — that is already known.",
  "You judge only this: does the delivered result satisfy what was promised?",
  "",
  "verdict=met     — every criterion is satisfied by the delivered result.",
  "verdict=partial — some criteria satisfied, others clearly not.",
  "verdict=missed  — the result does not satisfy the criteria, even if no error occurred.",
  "",
  "Be strict about substance and lenient about wording: a criterion is satisfied when",
  "the outcome is really there, regardless of how it is phrased. Do not reward a result",
  "that merely DESCRIBES or PROMISES the outcome instead of delivering it.",
  "List every unsatisfied criterion verbatim in unmetCriteria.",
].join("\n");

/**
 * Semantik yargı. Başarısızlıkta `null` döner ve çağıran `unknown` kaydeder —
 * uydurma bir yargı üretmek, yargı üretmemekten kötüdür.
 */
export async function verifyGoalSemantically(
  app: FastifyInstance,
  input: { userId: string; objective: string; evidence: GoalEvidence },
): Promise<GoalVerificationResult | null> {
  try {
    const result = await callGeminiFreeStructured<GoalVerificationResult>(app, {
      feature: "execution_validate",
      userId: input.userId,
      system: SYSTEM_PROMPT,
      payload: {
        objective: input.objective.slice(0, 1_000),
        successCriteria: input.evidence.successCriteria.slice(0, 6),
        deliveredResult: input.evidence.resultText.slice(0, 4_000),
        artifactProduced: input.evidence.artifactProduced,
        executedStepCount: input.evidence.executedStepCount,
      },
      schema: goalVerdictSchema,
      jsonSchema: goalVerdictJsonSchema,
      sensitivity: "none",
      maxOutputTokens: 320,
      timeoutMs: 4_000,
    });
    return result;
  } catch {
    return null;
  }
}

/** Kapının tamamı: yapısal ön-eleme → gerekiyorsa semantik → yargı. */
export async function verifyTaskGoal(
  app: FastifyInstance,
  input: { userId: string; objective: string; evidence: GoalEvidence },
): Promise<GoalVerificationResult> {
  const structural = evaluateGoalEvidence(input.evidence);
  if (structural) return structural;

  const semantic = await verifyGoalSemantically(app, input);
  if (!semantic) {
    return {
      verdict: "unknown",
      reason: "semantics_unavailable",
      unmetCriteria: [],
      confidence: 0,
    };
  }
  return semantic;
}
