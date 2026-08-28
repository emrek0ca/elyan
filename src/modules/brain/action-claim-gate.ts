import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { callGeminiFreeStructured } from "./gemini-utility-client.js";

/**
 * Eylem-taahhüdü kapısı (RC-2).
 *
 * NEDEN
 * -----
 * Sunucu beyni (shared_brain) turunda model, yapamadığı bir işi yapmış gibi
 * anlatabiliyor: "elyan-test.txt oluşturuluyor", "ekranınızı inceliyorum,
 * lütfen bekleyin", "gece vakti trenini ayarladım". O turda hiçbir araç
 * çalışmadığı hâlde bu anlatı `result` olarak yazılıp görev `completed`
 * işaretleniyordu. Kullanıcı için hiçbir hata hata gibi görünmüyordu.
 *
 * Mevcut factuality/grounding kapıları BELGE ve SAYI iddialarını yakalıyor
 * ama EYLEM iddialarını yakalamıyor. Bu kapı tam o boşluğu kapatır.
 *
 * KIRMIZI ÇİZGİ
 * -------------
 * Sinyal REGEX/kelime-listesi OLAMAZ ("oluşturuluyor" aramak yasaktır ve
 * robot hissi verir). Doğru sinyal iki parçalıdır:
 *   1. YAPISAL: bu turda kaç araç yürütüldü, bir artefakt üretildi mi?
 *      (deterministik, bedava)
 *   2. SEMANTİK: metin bir dış-etkili eylemin YAPILDIĞINI/YAPILMAKTA
 *      olduğunu iddia ediyor mu? (ucuz, yapılandırılmış Gemini çağrısı —
 *      `visual-intent-semantic.ts` ile aynı desen)
 * Taahhüt VAR + yürütme kanıtı YOK = uydurma.
 *
 * DAYANIKLILIK
 * ------------
 * Gemini çağrısı başarısız olursa (kota/ağ/bayrak) semantik sonuç `null`
 * döner ve kapı İZİN VERİR — asla gereksiz yere reddetmez (RC-5). Bu kapı
 * en-iyi-çaba bir emniyet ağıdır; kalıcı yapısal garanti hedef-durumu
 * (goal state) katmanının işidir.
 */

export type ActionClaimSemantics = {
  /**
   * Metin, dış dünyada somut ve araç gerektiren bir eylemin YAPILDIĞINI ya da
   * ŞU AN YAPILMAKTA olduğunu iddia ediyor mu? Bir soruyu cevaplamak, sohbet
   * etmek, içerik üretmek (metin/şiir/açıklama/plan) ya da bir şey yapmayı
   * ÖNERMEK bu kapsamda DEĞİLDİR.
   */
  assertsPerformedAction: boolean;
  /** Kısa, nötr özet: iddia edilen eylem nedir. Kanıt/log içindir. */
  actionSummary: string;
  confidence: number;
};

const actionClaimSchema = z.object({
  assertsPerformedAction: z.boolean(),
  actionSummary: z.string().trim().max(200),
  confidence: z.number().min(0).max(1),
});

const actionClaimJsonSchema = {
  type: "object",
  additionalProperties: false,
  required: ["assertsPerformedAction", "actionSummary", "confidence"],
  properties: {
    assertsPerformedAction: { type: "boolean" },
    actionSummary: { type: "string", maxLength: 200 },
    confidence: { type: "number", minimum: 0, maximum: 1 },
  },
} as const;

const SYSTEM_PROMPT = [
  "You audit one assistant reply and decide a single thing:",
  "does the reply CLAIM that a concrete, side-effecting action in the outside world",
  "was performed, or is being performed right now?",
  "",
  "The user writes in any language (often Turkish). Understand meaning, never match keywords.",
  "",
  "COUNTS as a performed/in-progress action (assertsPerformedAction = true):",
  "- creating, writing, editing, moving or deleting a file on a device",
  "- inspecting/looking at the user's screen or open apps ('ekranınızı inceliyorum')",
  "- opening, closing or controlling an application",
  "- sending a message/email, changing a setting, editing an EXISTING image",
  "- any 'I did X' / 'X is being done' about a tool-requiring, real-world side effect.",
  "",
  "Does NOT count (assertsPerformedAction = false):",
  "- answering a question, chatting, giving an opinion ('bugün iyiyim')",
  "- PRODUCING CONTENT as the reply itself: prose, a poem, an explanation, a plan,",
  "  a math solution, a table/chart drawn from provided or public data",
  "- OFFERING or PROMISING to do something later ('yapabilirim', 'istersen ayarlarım'),",
  "  or asking the user for something needed to proceed",
  "- describing how the user could do it themselves.",
  "",
  "The reply text is the ONLY evidence about what was claimed. Do not infer intent",
  "from anything else. Give a calibrated confidence.",
].join("\n");

/**
 * Saf karar mantığı — AĞSIZ, deterministik, test edilebilir.
 *
 * Yapısal ön-eleme kapıyı çoğu turda hiç semantik çağrıya bile götürmeden
 * kapatır: gerçek araç yürütülmüşse, bir artefakt üretilmişse, tur zaten
 * etiketli bir geri-düşüşse ya da rota sunucu beyni değilse uydurma riski
 * yoktur.
 */
export function evaluateActionClaimEvidence(input: {
  route: string;
  executedToolCount: number;
  hasArtifactEvidence: boolean;
  fallbackUsed: boolean;
  hasVisibleText: boolean;
  semantics: ActionClaimSemantics | null;
  confidenceThreshold?: number;
}): { fabricated: boolean; reason: string; actionSummary: string } {
  const threshold = input.confidenceThreshold ?? 0.7;

  // Yapısal kanıt varsa iddia uydurma olamaz.
  if (input.route !== "shared_brain") {
    return { fabricated: false, reason: "not_shared_brain", actionSummary: "" };
  }
  if (input.executedToolCount > 0) {
    return { fabricated: false, reason: "tools_executed", actionSummary: "" };
  }
  if (input.hasArtifactEvidence) {
    return { fabricated: false, reason: "artifact_produced", actionSummary: "" };
  }
  if (input.fallbackUsed) {
    return { fabricated: false, reason: "labeled_fallback", actionSummary: "" };
  }
  if (!input.hasVisibleText) {
    return { fabricated: false, reason: "no_visible_text", actionSummary: "" };
  }

  // Semantik karar veremediyse (Gemini yoksa) İZİN VER — gereksiz ret yasak.
  if (!input.semantics) {
    return { fabricated: false, reason: "semantics_unavailable", actionSummary: "" };
  }

  if (
    input.semantics.assertsPerformedAction &&
    input.semantics.confidence >= threshold
  ) {
    return {
      fabricated: true,
      reason: "action_claim_without_execution",
      actionSummary: input.semantics.actionSummary,
    };
  }

  return { fabricated: false, reason: "no_action_claim", actionSummary: "" };
}

/**
 * Semantik tespit — ucuz, yapılandırılmış Gemini çağrısı. Başarısızlıkta
 * `null` döner (kapı izin verir).
 */
export async function detectActionClaimSemantics(
  app: FastifyInstance,
  input: { userId: string; responseText: string },
): Promise<ActionClaimSemantics | null> {
  const text = String(input.responseText ?? "").trim();
  if (!text) return null;
  try {
    const result = await callGeminiFreeStructured<ActionClaimSemantics>(app, {
      feature: "execution_validate",
      userId: input.userId,
      system: SYSTEM_PROMPT,
      payload: { reply: text.slice(0, 4_000) },
      schema: actionClaimSchema,
      jsonSchema: actionClaimJsonSchema,
      sensitivity: "none",
      maxOutputTokens: 200,
      timeoutMs: 3_500,
    });
    return result;
  } catch (error) {
    // SEBEBİ YUTMA. Bu kapı daha önce sessizce ölmüştü (emekli model, 404) ve
    // "semantics_unavailable" uyarısı NEDEN'i söylemediği için arıza aylarca
    // görünmez kaldı. Uyarı hâlâ fail-open'dır; yalnız artık teşhis edilebilir.
    app.log?.warn?.(
      {
        gate: "action_claim",
        reason: "semantic_call_failed",
        error: error instanceof Error ? error.message : String(error),
      },
      "action claim semantics call failed",
    );
    return null;
  }
}

/**
 * Kapının tamamı: yapısal ön-eleme → gerekiyorsa semantik → karar.
 *
 * `fabricated: true` dönerse çağıran taraf turu `completed` YAZMAMALI; mevcut
 * failure yolunu tetiklemeli (insan-etiketli mesaj + `message.error`).
 */
export async function detectFabricatedActionClaim(
  app: FastifyInstance,
  input: {
    userId: string;
    route: string;
    responseText: string;
    executedToolCount: number;
    hasArtifactEvidence: boolean;
    fallbackUsed: boolean;
  },
): Promise<{ fabricated: boolean; reason: string; actionSummary: string }> {
  const hasVisibleText = Boolean(String(input.responseText ?? "").trim());

  // Semantik çağrıdan ÖNCE ucuz yapısal ön-eleme: riski olmayan turlarda
  // Gemini'ye hiç gitme.
  const preCheck = evaluateActionClaimEvidence({
    route: input.route,
    executedToolCount: input.executedToolCount,
    hasArtifactEvidence: input.hasArtifactEvidence,
    fallbackUsed: input.fallbackUsed,
    hasVisibleText,
    semantics: null,
  });
  if (preCheck.reason !== "semantics_unavailable") {
    // Yapısal olarak zaten temiz (araç yürüdü / artefakt / fallback / rota /
    // metin yok). Semantiğe gerek yok.
    return preCheck;
  }

  const semantics = await detectActionClaimSemantics(app, {
    userId: input.userId,
    responseText: input.responseText,
  });

  // FAIL-OPEN GÖRÜNÜR OLMALI.
  //
  // Semantik karar veremediğinde kapı bilerek İZİN VERİR (gereksiz ret yasak).
  // Ama bu sessiz olduğu sürece kapının çalışıp çalışmadığı ölçülemez: canlıda
  // `GEMINI_FAST_MODEL` emekli bir modele işaret ediyordu, her çağrı 404 ile
  // null dönüyordu ve kapı HER TURDA devre dışıydı — asistan "şarkıyı
  // çalıyorum" dedi, hiçbir şey çalışmadı, hiçbir uyarı düşmedi (2026-08-22).
  //
  // Bu satır uydurmayı engellemez; engelleyicinin ÖLDÜĞÜNÜ duyurur.
  if (!semantics) {
    app.log?.warn?.(
      {
        gate: "action_claim",
        outcome: "fail_open",
        reason: "semantics_unavailable",
        model: String(app.config?.GEMINI_FAST_MODEL ?? ""),
      },
      "action claim gate could not evaluate; turn allowed without semantic check",
    );
  }

  return evaluateActionClaimEvidence({
    route: input.route,
    executedToolCount: input.executedToolCount,
    hasArtifactEvidence: input.hasArtifactEvidence,
    fallbackUsed: input.fallbackUsed,
    hasVisibleText,
    semantics,
  });
}
