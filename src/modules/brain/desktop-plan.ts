import type { FastifyInstance } from "fastify";
import { generateGovernedSharedBrainReply } from "./inference.js";

/**
 * Desktop yapılandırılmış planlama köprüsü — elyan.plan.v2.
 *
 * Masaüstü runtime'ı planlama isteğini (araç kataloğu + bağlam + yanıt şeması
 * içeren tek JSON zarfı) daha önce /v1/chat/messages'a düz sohbet mesajı olarak
 * gönderiyordu; persona + blok + typewriter pipeline'ı yanıtı sarmalayıp plan
 * JSON'unu bozuyordu. Bu modül planlama isteğini sohbet pipeline'ına sokmadan
 * doğrudan "planning" workload profiliyle çalıştırır ve saf plan JSON'unu
 * döndürür. Doğrulama (capability varlığı, argüman tipleri) masaüstünde kalır.
 */

export const DESKTOP_PLAN_CONTRACT = "elyan.plan.v2";
export const DESKTOP_COWORK_CONTRACT = "elyan.cowork.v1";

const MAX_PROMPT_CHARS = 48_000;
const PLAN_MAX_COMPLETION_TOKENS = 2_400;
const PLAN_TIMEOUT_MS = 30_000;

export type DesktopPlanInput = {
  userId: string;
  /** Masaüstünün structured_planner.planning_prompt() çıktısı. */
  prompt: string;
  /** İstek zarfı sözleşmesi — şimdilik yalnızca elyan.plan.v2. */
  contract: string;
  /** Onarım turu: geçersiz yanıt + doğrulama hataları veri olarak gelir. */
  repair?: boolean;
  taskId?: string;
  /** Zarfın içindeki ham kullanıcı cümlesi — güvenlik kapıları bunu denetler. */
  userText?: string;
  requestId?: string;
};

export type DesktopPlanResult = {
  ok: boolean;
  contract: string;
  /** Yanıttan çıkarılan ilk JSON nesnesi; bulunamazsa null. */
  plan: Record<string, unknown> | null;
  /** Ham model çıktısı — masaüstü tarafı kendi kurtarma mantığını koşabilsin. */
  text: string;
  provider: string;
  model: string;
  latencyMs: number;
  error?: string;
};

/**
 * Metinden ilk dengeli JSON nesnesini çıkarır. Model markdown çiti veya kısa
 * önsöz eklese bile planı kurtarır; string içi kaçışlara saygılıdır.
 */
export function extractFirstJsonObject(
  text: string,
): Record<string, unknown> | null {
  const source = String(text ?? "");
  const start = source.indexOf("{");
  if (start < 0) return null;
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let index = start; index < source.length; index += 1) {
    const char = source[index];
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (char === "\\") {
        escaped = true;
      } else if (char === '"') {
        inString = false;
      }
      continue;
    }
    if (char === '"') {
      inString = true;
    } else if (char === "{") {
      depth += 1;
    } else if (char === "}") {
      depth -= 1;
      if (depth === 0) {
        const candidate = source.slice(start, index + 1);
        try {
          const parsed: unknown = JSON.parse(candidate);
          if (
            parsed &&
            typeof parsed === "object" &&
            !Array.isArray(parsed)
          ) {
            return parsed as Record<string, unknown>;
          }
          return null;
        } catch {
          return null;
        }
      }
    }
  }
  return null;
}

const PLANNER_SYSTEM_PREFIX = [
  "You are the planning engine for the Elyan desktop runtime.",
  "The request below is a structured planning envelope (contract elyan.plan.v2):",
  "a tool catalog with JSON Schema parameters, execution context, and the exact response schema.",
  "Respond with EXACTLY ONE JSON object that satisfies the response schema in the envelope.",
  "No prose, no markdown fences, no explanations before or after the JSON.",
  "Only use capabilities that exist in the provided tool catalog.",
  "Prefer the smallest correct plan; chain steps with dependsOn when a step consumes a previous step's output.",
].join(" ");

export async function generateDesktopPlan(
  app: FastifyInstance,
  input: DesktopPlanInput,
): Promise<DesktopPlanResult> {
  const prompt = String(input.prompt ?? "").slice(0, MAX_PROMPT_CHARS).trim();
  if (!prompt) {
    return {
      ok: false,
      contract: DESKTOP_PLAN_CONTRACT,
      plan: null,
      text: "",
      provider: "",
      model: "",
      latencyMs: 0,
      error: "empty_planning_prompt",
    };
  }
  if (input.contract !== DESKTOP_PLAN_CONTRACT) {
    return {
      ok: false,
      contract: input.contract,
      plan: null,
      text: "",
      provider: "",
      model: "",
      latencyMs: 0,
      error: "unsupported_plan_contract",
    };
  }

  const inference = await generateGovernedSharedBrainReply(app, {
    userId: input.userId,
    taskId: input.taskId,
    title: "Desktop plan",
    prompt: `${PLANNER_SYSTEM_PREFIX}\n\n${prompt}`,
    workload: "planning",
    route: input.repair ? "desktop_plan_repair" : "desktop_plan",
    meteringSurface: "task",
    maxCompletionTokensOverride: PLAN_MAX_COMPLETION_TOKENS,
    timeoutMsOverride: PLAN_TIMEOUT_MS,
    // Kapılar zarf ŞABLONUNU değil kullanıcının GERÇEK cümlesini denetlesin:
    // zarf metni ("mesaj, arama+üretim", "dışa gönderim" gibi şema açıklamaları)
    // external_send_request kalıplarına takılıyor ve HER anlama/planlama
    // çağrısını blokluyordu. userText verilmediyse davranış değişmez —
    // tüm zarf denetlenir (fail-closed). Güvenlik dengesi: bu endpoint yalnız
    // plan JSON'u üretir; yan etkiler masaüstünde safety_policy + açık onay
    // kapısından geçmeden asla çalışmaz.
    gatePromptOverride: input.userText,
    requestMetadata: {
      desktopPlan: true,
      contract: DESKTOP_PLAN_CONTRACT,
      requestId: input.requestId,
    },
    internalEvaluation: {
      skipUsageValidation: true,
      skipReviewLogging: true,
      refinementPass: true,
    },
  });

  // Güvenlik/kimlik kapıları (backend_gate) planlama zarfını normal kullanıcı
  // metni sanıp yakalayabilir ("shell", "komut" gibi kelimeler). Kapı yanıtı
  // plan değildir — açıkça başarısız dön ki masaüstü kendi fallback zincirine
  // (chat yolu / yerel model / deterministik) düşsün.
  if (inference.answerSource === "backend_gate") {
    return {
      ok: false,
      contract: DESKTOP_PLAN_CONTRACT,
      plan: null,
      text: "",
      provider: inference.provider,
      model: inference.model,
      latencyMs: inference.latencyMs,
      error: "planning_blocked_by_gate",
    };
  }

  const plan = extractFirstJsonObject(inference.text);
  const validPlan =
    plan !== null &&
    (typeof plan.contract === "string" || Array.isArray(plan.steps));
  return {
    ok: validPlan,
    contract: DESKTOP_PLAN_CONTRACT,
    plan: validPlan ? plan : null,
    text: inference.text,
    provider: inference.provider,
    model: inference.model,
    latencyMs: inference.latencyMs,
    error: validPlan ? undefined : "plan_json_not_found",
  };
}
