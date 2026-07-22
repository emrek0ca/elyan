import { eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { tasks } from "../../db/schema.js";
import { extractFirstJsonObject } from "../brain/desktop-plan.js";
import { generateGovernedSharedBrainReply } from "../brain/inference.js";
import { DESKTOP_CAPABILITY_MANIFEST } from "./desktop-capability-manifest.js";
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
 * edilir (görev asla bloklanmaz). Vokabüler = desktop'un TAM kataloğu
 * (DESKTOP_CAPABILITY_MANIFEST, 77 yetenek — runtime TOOL_DECLARATIONS'tan
 * üretilir); desktop planı yine KENDİ kataloğuna karşı doğrular, geçmezse mevcut
 * delegasyon davranışına düşer (regresyon yok).
 */

// Sunucunun önerebileceği yetenekler = desktop'un TAM kataloğu (manifest).
// Onay gerektirenler (mail/shell/dosya-sil/takvim…) modele "risk: onay ister"
// notuyla sunulur ama planlanabilir — güvenlik sınırı DESKTOP'tadır (grant +
// REMOTE_APPROVAL_CAPABILITIES onay kapısı). Böylece sunucu planı desktop'un
// geniş yetenek/araç setinin TAMAMINI kullanabilir; kısa görev + planlama
// aşamaları iki uçta bire bir uyumlu kalır.
const MATERIALIZABLE_CAPABILITIES = DESKTOP_CAPABILITY_MANIFEST.map(
  (entry) => entry.name,
);

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
// İŞ BÖLÜMÜ (kullanıcı kararı): BASİT işler otonom/deterministik kalır (bizim
// "eğitim setimiz" = regex router; hızlı, LLM'siz). KARMAŞIK + adım-adım
// planlama gereken işleri Elyan (server_brain) plana derler: araç/skill seçimini
// ve sıralamayı MODEL muhakeme eder. Plan zayıf/başarısızsa heuristik work-
// order'a fail-safe düşülür (regresyon yok).
//
// Karmaşık = çok-yetenekli (≥2) VEYA açıkça sıralı çok-adımlı istek. Tek-adımlı
// basit görev (tek araç) deterministik yolda kalır.
function isComplexEnough(workOrder: DesktopWorkOrder): boolean {
  const required = (
    Array.isArray(workOrder.requiredCapabilities)
      ? workOrder.requiredCapabilities
      : []
  ).filter((c): c is string => typeof c === "string" && c.trim().length > 0);
  if (required.length >= 2) {
    return true;
  }
  const summary = String(workOrder.goal?.summary ?? "").trim();
  if (SEQUENTIAL_INTENT_RE.test(summary)) {
    return true;
  }
  // Profesyonel/çok-parçalı istekler (avukat/doktor/mühendis/öğrenci işleri) çoğu
  // zaman regex'e tek yetenek gibi görünür ama gerçekte çok-adımlıdır ("bu davayı
  // analiz et ve dilekçe hazırla", "hastanın tahlillerini yorumla ve rapor yaz").
  // Zengin/uzun istek → server_brain plana derlesin (adım adım karar versin).
  // Kısa doğrudan komut ("Safari aç") deterministik/otonom kalır.
  const understanding = workOrder.understanding;
  const desiredOutputs = Array.isArray(understanding?.desiredOutputs)
    ? understanding!.desiredOutputs
    : [];
  if (desiredOutputs.length >= 2) {
    return true;
  }
  const wordCount = summary.split(/\s+/).filter(Boolean).length;
  const clauseSignals = /[,;]| ve | ile | ayrıca | hem .* hem | and | then /i.test(
    ` ${summary} `,
  );
  // ≥8 kelime VEYA birden çok fıkra/bağlaç → çok-adımlı profesyonel iş.
  return wordCount >= 8 || (wordCount >= 5 && clauseSignals);
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

function renderCapabilityCatalog(allowed: Set<string>): string {
  // Manifest'ten yalnız izinli olanları, her yeteneğin ne zaman kullanılacağı
  // (usage) + gerekli argümanları + onay bayrağı ile listele. Bu, modelin
  // doğru yeteneği doğru argümanla seçmesinin kaldıracıdır (skill-benzeri
  // kendini-belgeleyen katalog, desktop tool_catalog ile aynı bilgi).
  return DESKTOP_CAPABILITY_MANIFEST.filter((entry) => allowed.has(entry.name))
    .map((entry) => {
      const req =
        entry.requiredArgs.length > 0
          ? ` [required args: ${entry.requiredArgs.join(", ")}]`
          : "";
      const approval = entry.requiresApproval ? " [needs user approval]" : "";
      const usage = entry.usage ? ` — ${entry.usage}` : "";
      return `- ${entry.name}: ${entry.description}${usage}${req}${approval}`;
    })
    .join("\n");
}

function renderPlanningFewShots(): string {
  return [
    "EXAMPLES:",
    "",
    "Accounting calculation + spreadsheet:",
    "Goal: 12000 TL ve 8500 TL tutarindaki iki faturanin toplam KDV dahil ozetini Excel'e yaz.",
    '{"steps":[',
    '{"id":"s1","capability":"math_solve","args":{"expression":"(12000+8500)*1.20"},"dependsOn":[],"description":"KDV dahil toplam tutari hesapla"},',
    '{"id":"s2","capability":"spreadsheet_write","args":{"title":"Fatura ozeti","sheets":[{"name":"Ozet","rows":[["Kalem","Tutar"],["Fatura 1",12000],["Fatura 2",8500],["KDV dahil toplam","{{steps.s1.output}}"]]}]},"dependsOn":["s1"],"description":"Hesap sonucunu Excel dosyasina yaz"}',
    "]}",
    "",
    "Research + report:",
    "Goal: 2026 elektrikli arac batarya trendlerini arastir ve kisa Word raporu hazirla.",
    '{"steps":[',
    '{"id":"s1","capability":"web_research","args":{"query":"2026 electric vehicle battery trends solid state LFP sodium ion market"},"dependsOn":[],"description":"Guncel kaynaklardan batarya trendlerini arastir"},',
    '{"id":"s2","capability":"document_write","args":{"title":"2026 Elektrikli Arac Batarya Trendleri","content":"{{steps.s1.output}}","format":"docx"},"dependsOn":["s1"],"description":"Arastirma sonucunu Word raporuna donustur"}',
    "]}",
  ].join("\n");
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
    "CAPABILITY CATALOG (use ONLY these exact names; each line: name: what it does — when to use [required args][needs approval]):",
    renderCapabilityCatalog(new Set(allowed)),
    "",
    "RULES:",
    '- Output EXACTLY ONE JSON object, no prose, no markdown fences: {"steps":[...]}',
    '- Each step: {"id":"s1","capability":"<catalog name>","args":{...},"dependsOn":["<earlier id>"],"description":"<short>"}',
    "- Use the smallest correct number of steps (between 2 and " +
      String(MAX_WORK_ORDER_STEPS) +
      ").",
    "- Order steps so each runs after its dependencies; set dependsOn to the ids whose output it consumes.",
    "- Always provide every listed required arg for a capability; put concrete values, use {{steps.<id>.output}} to consume a previous step's result.",
    "- Args must contain executable data, not vague descriptions. Do not write placeholders such as \"the invoice total\", \"the research result\", or \"the user's file\" when a concrete value or dependency reference is available.",
    "- math_solve.args.expression MUST be a numeric/symbolic expression such as \"12000+8500\" or \"(12000+8500)*1.20\". Never pass an explanation like \"faturaların toplamı\" as expression.",
    "- For spreadsheet_write/document_write/presentation_write, put the produced content in args directly and reference prior outputs with {{steps.<id>.output}}. Do not rely on hidden context.",
    "- For web_research, query must be a concrete search query with the key terms from the goal, not a generic instruction.",
    "- For image_generate, prompt must be the full visual prompt the image model should receive, not a short label.",
    "- Steps marked [needs approval] are allowed; the desktop asks the user before running them — plan them normally.",
    "- Only use capabilities from the CATALOG above.",
    '- If the goal cannot be split into >=2 steps from these capabilities, return {"steps":[]}.',
    "",
    renderPlanningFewShots(),
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
