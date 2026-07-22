import { eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { tasks } from "../../db/schema.js";
import { extractFirstJsonObject } from "../brain/desktop-plan.js";
import { generateGovernedSharedBrainReply } from "../brain/inference.js";
import {
  MAX_WORK_ORDER_STEPS,
  type DesktopWorkOrder,
  type DesktopWorkOrderStep,
} from "./desktop-work-order.js";

/**
 * Hibrit sunucu-materyalizasyonu — dispatch worker'da (HTTP create yolundan
 * UZAK) çalışır.
 *
 * Bugün karmaşık görev iki kez planlanıyordu: (1) backend görev yaratımında
 * regex/keyword heuristik work-order üretir (dependsOn yok, karmaşık görev tek
 * jenerik `desktop_operator.run` adımına çöker), (2) desktop bu heuristik plana
 * güvenmeyip çok-adımlı her görevde sunucuya İKİNCİ bir planlama round-trip'i
 * yapar. Bu modül, KARMAŞIK görevlerde sunucu beynine (120b "planning" workload)
 * tam bağımlılık-graflı bir planı ÖNCEDEN derletip work-order'a VERİ olarak
 * yazar ve `planSource:"server_materialized"` ile işaretler. Desktop bu işareti
 * görünce plana güvenir ve ekstra round-trip olmadan yürütür.
 *
 * Güvenlik: fail-SAFE. Basit görevler dokunulmaz (heuristik). Karmaşık görevde
 * herhangi bir hata/timeout/zayıf çıktı → work-order heuristik haliyle dispatch
 * edilir (görev asla bloklanmaz). Sunucu vokabüleri desktop'un tam kataloğundan
 * (66 yetenek) dardır; bu yüzden desktop planı KEND İ kataloğuna karşı doğrular,
 * geçmezse mevcut delegasyon davranışına düşer (regresyon yok).
 */

// Sunucunun güvenle önerebileceği yetenek adları (desktop kataloğunun bilinen
// alt kümesi). Desktop tam 66-yetenek kataloğuna karşı doğrular; bu liste yalnız
// modele makul bir kelime dağarcığı verir.
const MATERIALIZABLE_CAPABILITIES = [
  "web_research",
  "retrieve_context",
  "document_read",
  "document_write",
  "spreadsheet_write",
  "presentation_write",
  "canvas_write",
  "image_generate",
  "image_fetch",
  "image_read",
  "image_edit",
  "browser_control",
  "open_app",
  "close_app",
  "make_directory",
  "play_media",
  "sys_info",
] as const;

const CAPABILITY_NAME_RE = /^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$/;
const SEQUENTIAL_INTENT_RE =
  /\b(sonra|ardından|ardindan|daha sonra|önce|once|then|after that|afterwards|finally|en son)\b/i;

const MATERIALIZE_TIMEOUT_MS = 20_000;
const MATERIALIZE_MAX_TOKENS = 2_400;

type TaskRow = typeof tasks.$inferSelect;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/**
 * Görev, sunucu-materyalizasyonuna değecek kadar karmaşık mı?
 * Sinyal: work-order'ın çok-yetenekli olması (≥2) VEYA hedefte sıralı-niyet.
 */
function isComplexEnough(workOrder: DesktopWorkOrder): boolean {
  const required = Array.isArray(workOrder.requiredCapabilities)
    ? workOrder.requiredCapabilities
    : [];
  if (required.length >= 2) {
    return true;
  }
  const summary = String(workOrder.goal?.summary ?? "");
  return required.length >= 1 && SEQUENTIAL_INTENT_RE.test(summary);
}

function buildAllowedCapabilities(workOrder: DesktopWorkOrder): string[] {
  const required = Array.isArray(workOrder.requiredCapabilities)
    ? workOrder.requiredCapabilities.filter(
        (c): c is string => typeof c === "string" && c.trim().length > 0,
      )
    : [];
  const union = new Set<string>([...required, ...MATERIALIZABLE_CAPABILITIES]);
  return [...union];
}

function buildPlanningPrompt(
  workOrder: DesktopWorkOrder,
  allowed: string[],
): string {
  const summary = String(workOrder.goal?.summary ?? "").slice(0, 4_000);
  const language = String(workOrder.goal?.language ?? "unknown");
  const entities = (Array.isArray(workOrder.entities) ? workOrder.entities : [])
    .slice(0, 8)
    .map((e) => `- ${e.type}: ${e.value}`)
    .join("\n");
  return [
    "You are the Elyan desktop task planner. Decompose the user's goal into an ordered,",
    "dependency-linked plan of desktop capability steps that the desktop runtime executes step by step.",
    "",
    "GOAL:",
    summary,
    "",
    "CONTEXT:",
    `- language: ${language}`,
    entities ? `- entities:\n${entities}` : "- entities: (none)",
    "",
    "ALLOWED CAPABILITIES (use ONLY these exact names):",
    allowed.map((c) => `- ${c}`).join("\n"),
    "",
    "RULES:",
    '- Output EXACTLY ONE JSON object, no prose, no markdown fences: {"steps":[...]}',
    '- Each step: {"id":"s1","capability":"<allowed name>","args":{...},"dependsOn":["<earlier id>"],"description":"<short>"}',
    "- Use the smallest correct number of steps (between 2 and " +
      String(MAX_WORK_ORDER_STEPS) +
      ").",
    "- Order steps so each runs after its dependencies; set dependsOn to the ids whose output it consumes.",
    "- args: concrete arguments for the capability (e.g. web_research -> {\"query\":\"...\"}, document_write -> {\"path\":\"...\",\"content\":\"...\"}). Use {} if unknown.",
    "- Only use capabilities from the ALLOWED list.",
    '- If the goal cannot be split into >=2 steps from these capabilities, return {"steps":[]}.',
  ].join("\n");
}

/**
 * Model çıktısını güvenli DesktopWorkOrderStep[]'e normalize eder. Bilinmeyen/
 * bozuk adımları eler, id'leri benzersizleştirir, dependsOn'u geçerli id'lerle
 * sınırlar, MAX_WORK_ORDER_STEPS ile kırpar. <2 adım kalırsa null döner
 * (gerçek bir ayrıştırma yok → heuristik korunur).
 */
function normalizeMaterializedSteps(
  rawPlan: Record<string, unknown> | null,
): DesktopWorkOrderStep[] | null {
  if (!rawPlan) return null;
  const rawSteps = Array.isArray(rawPlan.steps) ? rawPlan.steps : [];
  const seenIds = new Set<string>();
  const normalized: DesktopWorkOrderStep[] = [];
  for (let index = 0; index < rawSteps.length; index += 1) {
    if (normalized.length >= MAX_WORK_ORDER_STEPS) break;
    const step = asRecord(rawSteps[index]);
    if (!step) continue;
    const capability = String(step.capability ?? "").trim();
    if (!capability || !CAPABILITY_NAME_RE.test(capability)) continue;
    let id = String(step.id ?? "").trim();
    if (!id || seenIds.has(id)) id = `s${normalized.length + 1}`;
    seenIds.add(id);
    const args = asRecord(step.args) ?? {};
    const dependsOn = (Array.isArray(step.dependsOn) ? step.dependsOn : [])
      .map((d) => String(d ?? "").trim())
      .filter((d) => d.length > 0);
    normalized.push({
      id,
      capability,
      description: String(step.description ?? "").slice(0, 220),
      args,
      dependsOn,
    });
  }
  // dependsOn yalnız plan içindeki geçerli id'lere işaret etsin (dangling temizle).
  const validIds = new Set(normalized.map((s) => s.id));
  for (const step of normalized) {
    step.dependsOn = (step.dependsOn ?? []).filter(
      (d) => validIds.has(d) && d !== step.id,
    );
  }
  return normalized.length >= 2 ? normalized : null;
}

/**
 * Dispatch worker kancası: karmaşık desktop görevlerinde work-order planını
 * sunucuda materyalize edip task satırına persist eder. Basit görevlerde ve her
 * hata durumunda no-op (heuristik plan korunur). İdempotent: zaten materyalize
 * edilmiş görevleri (lease-retry) yeniden planlamaz.
 */
export async function maybeMaterializeDesktopPlan(
  app: FastifyInstance,
  task: TaskRow,
): Promise<void> {
  try {
    const payload = asRecord(task.payload);
    if (!payload) return;
    const workOrder = asRecord(payload.desktopWorkOrder) as
      | DesktopWorkOrder
      | null;
    if (!workOrder) return;
    const planPreview = asRecord(workOrder.planPreview);
    if (!planPreview) return;
    // İdempotent: zaten sunucu-materyalize (retry) → dokunma.
    if (planPreview.planSource === "server_materialized") return;
    if (!isComplexEnough(workOrder)) return;

    const allowed = buildAllowedCapabilities(workOrder);
    const prompt = buildPlanningPrompt(workOrder, allowed);

    // Aynı primitif + workload (generateDesktopPlan'ın kullandığı) — yeni beyin
    // makinesi yok. Persona/blok/typewriter pipeline'ı atlanır (saf plan JSON).
    const inference = await generateGovernedSharedBrainReply(app, {
      userId: task.userId,
      taskId: task.id,
      title: "Desktop plan (materialize)",
      prompt,
      workload: "planning",
      route: "desktop_plan_materialize",
      meteringSurface: "task",
      maxCompletionTokensOverride: MATERIALIZE_MAX_TOKENS,
      timeoutMsOverride: MATERIALIZE_TIMEOUT_MS,
      requestMetadata: { desktopPlanMaterialize: true },
      internalEvaluation: {
        skipUsageValidation: true,
        skipReviewLogging: true,
        refinementPass: true,
      },
    });
    // backend_gate = güvenlik/kimlik kapısı planı yakaladı → plan değil.
    if (inference.answerSource === "backend_gate" || !inference.text.trim()) {
      return;
    }

    const steps = normalizeMaterializedSteps(
      extractFirstJsonObject(inference.text),
    );
    if (!steps) return; // gerçek ayrıştırma yok → heuristik korunur.

    const updatedPlanPreview = {
      ...planPreview,
      steps,
      planSource: "server_materialized" as const,
      contract: "elyan.compiled_plan.v1" as const,
    };
    const updatedPayload = {
      ...payload,
      desktopWorkOrder: {
        ...workOrder,
        planPreview: updatedPlanPreview,
      },
    };

    await app.db
      .update(tasks)
      .set({ payload: updatedPayload, updatedAt: new Date() })
      .where(eq(tasks.id, task.id));

    // Çağıranın elindeki task nesnesini de güncelle (lease DB'den yeniden okur
    // ama tutarlılık için bellek içi kopyayı da hizala).
    task.payload = updatedPayload as TaskRow["payload"];
  } catch (error) {
    // Fail-safe: materyalizasyon asla dispatch'i bloklamaz.
    app.log.warn(
      { taskId: task.id, error },
      "desktop plan materialization skipped; dispatching heuristic work order",
    );
  }
}
