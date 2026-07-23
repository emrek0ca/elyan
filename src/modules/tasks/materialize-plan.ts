import { eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { tasks } from "../../db/schema.js";
import { extractFirstJsonObject } from "../brain/desktop-plan.js";
import { generateGovernedSharedBrainReply } from "../brain/inference.js";
import { DESKTOP_CAPABILITY_MANIFEST } from "./desktop-capability-manifest.js";
import { DESKTOP_SKILL_MANIFEST } from "./desktop-skill-manifest.js";
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
 * (DESKTOP_CAPABILITY_MANIFEST — runtime TOOL_DECLARATIONS'tan üretilir) ve
 * skill kataloğu (DESKTOP_SKILL_MANIFEST — runtime skill_catalog'tan üretilir);
 * desktop planı yine KENDİ kataloğuna karşı doğrular, geçmezse mevcut delegasyon
 * davranışına düşer (regresyon yok).
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
const STEP_TEMPLATE_RE = /\{\{\s*steps\.([A-Za-z0-9_-]+)/g;

const MATERIALIZE_TIMEOUT_MS = 20_000;
const MATERIALIZE_MAX_TOKENS = 2_400;

type TaskRow = typeof tasks.$inferSelect;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function templateStepReferences(value: unknown): Set<string> {
  const refs = new Set<string>();
  if (Array.isArray(value)) {
    for (const item of value) {
      for (const ref of templateStepReferences(item)) refs.add(ref);
    }
    return refs;
  }
  const record = asRecord(value);
  if (record) {
    for (const item of Object.values(record)) {
      for (const ref of templateStepReferences(item)) refs.add(ref);
    }
    return refs;
  }
  if (typeof value !== "string" || !value.includes("{{")) return refs;
  for (const match of value.matchAll(STEP_TEMPLATE_RE)) {
    const id = String(match[1] ?? "").trim();
    if (id) refs.add(id);
  }
  return refs;
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

function renderSkillCatalog(allowed: Set<string>): string {
  if (!allowed.has("run_skill")) {
    return "(run_skill is not allowed for this work order)";
  }
  return DESKTOP_SKILL_MANIFEST.map((entry) => {
    const req =
      entry.requiredParameters.length > 0
        ? ` [payload required: ${entry.requiredParameters.join(", ")}]`
        : "";
    const params =
      entry.parameters.length > 0
        ? ` [payload fields: ${entry.parameters.join(", ")}]`
        : "";
    const steps =
      entry.stepCapabilities.length > 0
        ? ` [internal chain: ${entry.stepCapabilities.join(" -> ")}]`
        : "";
    const confirmation = entry.requiresConfirmation ? " [may need user approval]" : "";
    const expected =
      entry.expectedInputs.length > 0
        ? ` [best inputs: ${entry.expectedInputs.join(", ")}]`
        : "";
    return `- ${entry.id} (${entry.name}, ${entry.category}): ${entry.description}${req}${params}${expected}${steps}${confirmation}`;
  }).join("\n");
}

export function renderPlanningFewShots(): string {
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
    "Accounting calculation + research + report:",
    "Goal: 12000 TL ve 8500 TL hizmet faturasi icin yuzde 20 KDV hesapla, KDV kurallarini arastir ve Word raporu hazirla.",
    '{"steps":[',
    '{"id":"s1","capability":"math_solve","args":{"expression":"(12000+8500)*0.20"},"dependsOn":[],"description":"Iki faturanin yuzde 20 KDV tutarini hesapla"},',
    '{"id":"s2","capability":"web_research","args":{"query":"hizmet faturasi KDV yuzde 20 kurallari Turkiye"},"dependsOn":[],"description":"KDV kurallari icin kaynak arastir"},',
    '{"id":"s3","capability":"text_analyze","args":{"prompt":"KDV hesabi ve arastirma sonucunu muhasebe raporu icin analiz et","sourceContext":"KDV hesabi: {{steps.s1.output}}\\n\\nArastirma: {{steps.s2.output}}","mode":"accounting"},"dependsOn":["s1","s2"],"description":"Hesap ve arastirma sonucunu teslim cikti icin analiz et"},',
    '{"id":"s4","capability":"document_write","args":{"title":"KDV Hesaplama ve Kural Ozeti","content":"KDV hesabi: {{steps.s1.output}}\\n\\nArastirma: {{steps.s2.output}}\\n\\nAnaliz: {{steps.s3.output}}","format":"docx"},"dependsOn":["s1","s2","s3"],"description":"Hesap, arastirma ve analiz sonucunu Word raporuna yaz"}',
    "]}",
    "",
    "Legal research + defense draft:",
    "Goal: Kira uyusmazligini ve tahliye davasi savunmasini arastir, dosya ozetini analiz et ve savunma dilekcesi taslagi hazirla.",
    '{"steps":[',
    '{"id":"s1","capability":"web_research","args":{"query":"kira uyusmazligi tahliye davasi savunma dilekcesi mevzuat emsal"},"dependsOn":[],"description":"Mevzuat ve emsal savunma baglamini arastir"},',
    '{"id":"s2","capability":"text_analyze","args":{"prompt":"Arastirma sonucunu savunma dilekcesi icin hukuki arguman ve riskler acisindan analiz et","sourceContext":"Arastirma: {{steps.s1.output}}","mode":"legal"},"dependsOn":["s1"],"description":"Arastirma baglamini savunma stratejisi icin analiz et"},',
    '{"id":"s3","capability":"document_write","args":{"title":"Savunma Dilekcesi Taslagi","content":"Arastirma: {{steps.s1.output}}\\n\\nAnaliz: {{steps.s2.output}}\\n\\nBu baglamlari kullanarak savunma dilekcesi taslagi hazirla.","format":"docx"},"dependsOn":["s1","s2"],"description":"Arastirma ve analiz sonucundan savunma dilekcesi taslagini yaz"}',
    "]}",
    "",
    "Legal private file + public research + defense draft:",
    "Goal: Bu dosya metnini analiz et: kiraci tahliye itirazi. Kira uyusmazligi mevzuatini arastir ve savunma dilekcesi hazirla.",
    '{"steps":[',
    '{"id":"s1","capability":"document_read","args":{"text":"Kiraci tahliye itirazi dosya metni kullanici tarafindan paylasildi.","mode":"read"},"dependsOn":[],"description":"Ozel dosya/metin baglamini yerel olarak oku"},',
    '{"id":"s2","capability":"web_research","args":{"query":"kira uyusmazligi tahliye itirazi savunma dilekcesi mevzuat emsal"},"dependsOn":[],"description":"Public mevzuat ve emsal kaynaklarini arastir"},',
    '{"id":"s3","capability":"text_analyze","args":{"prompt":"Ozel dosya ve public mevzuat baglamindan savunma stratejisi analizi yap","sourceContext":"Dosya baglami: {{steps.s1.output}}\\n\\nPublic arastirma: {{steps.s2.output}}","mode":"legal"},"dependsOn":["s1","s2"],"description":"Dosya ve arastirma baglamini savunma icin analiz et"},',
    '{"id":"s4","capability":"document_write","args":{"title":"Savunma Dilekcesi Taslagi","content":"Dosya baglami: {{steps.s1.output}}\\n\\nPublic arastirma: {{steps.s2.output}}\\n\\nAnaliz: {{steps.s3.output}}\\n\\nBu baglamlari kullanarak savunma dilekcesi taslagi hazirla.","format":"docx"},"dependsOn":["s1","s2","s3"],"description":"Ozel dosya, public arastirma ve analizden dilekce taslagi yaz"}',
    "]}",
    "",
    "Private inline data + analysis report:",
    "Goal: Tahlil sonuclarini yorumla ve rapor cikar: Hb 10.5, ferritin 8, B12 220.",
    '{"steps":[',
    '{"id":"s1","capability":"document_read","args":{"text":"Tahlil sonuclari: Hb 10.5, ferritin 8, B12 220.","mode":"read"},"dependsOn":[],"description":"Kullanicinin paylastigi ozel veriyi yerel olarak oku"},',
    '{"id":"s2","capability":"text_analyze","args":{"prompt":"Tahlil sonuclarini rapor icin yorumla; tani koyma","sourceContext":"Veri: {{steps.s1.output}}","mode":"medical"},"dependsOn":["s1"],"description":"Okunan veriyi rapor icin analiz et"},',
    '{"id":"s3","capability":"document_write","args":{"title":"Tahlil Yorum Raporu","content":"Okunan veri uzerinden analiz raporu hazirla.\\n\\nVeri: {{steps.s1.output}}\\n\\nAnaliz: {{steps.s2.output}}","format":"docx"},"dependsOn":["s1","s2"],"description":"Okunan veri ve analiz sonucunu rapora donustur"}',
    "]}",
    "",
    "Student research + presentation:",
    "Goal: Kuantum annealing ile klasik optimizasyon farkini arastir, adim adim acikla ve 5 sayfalik sunum hazirla.",
    '{"steps":[',
    '{"id":"s1","capability":"web_research","args":{"query":"quantum annealing vs classical optimization explanation examples"},"dependsOn":[],"description":"Konu icin guncel ve anlasilir kaynak arastir"},',
    '{"id":"s2","capability":"text_analyze","args":{"prompt":"Arastirma sonucunu ogrenci sunumu icin ozetle, karsilastir ve adim adim aciklama omurgasi cikar","sourceContext":"Arastirma: {{steps.s1.output}}","mode":"student"},"dependsOn":["s1"],"description":"Arastirma sonucunu ogrenci sunumu icin analiz et"},',
    '{"id":"s3","capability":"presentation_write","args":{"title":"Kuantum Annealing ve Klasik Optimizasyon","prompt":"Analiz: {{steps.s2.output}}\\n\\nArastirma: {{steps.s1.output}}\\n\\nBu baglamla 5 sayfalik, adim adim aciklayan ogrenci sunumu hazirla"},"dependsOn":["s1","s2"],"description":"Analiz ve arastirma sonucundan sunum hazirla"}',
    "]}",
    "",
    "Research + spreadsheet:",
    "Goal: Muhasebeci gibi calis. 12000 TL ve 8500 TL faturanin yuzde 20 KDV tutarini hesapla ve Excel tablosu hazirla.",
    '{"steps":[',
    '{"id":"s1","capability":"math_solve","args":{"expression":"(12000+8500)*0.20"},"dependsOn":[],"description":"Iki faturanin KDV tutarini hesapla"},',
    '{"id":"s2","capability":"spreadsheet_write","args":{"title":"KDV Hesap Tablosu","sheets":[{"name":"KDV","rows":[["Kalem","Deger"],["Fatura 1",12000],["Fatura 2",8500],["KDV tutari","{{steps.s1.output}}"]]}]},"dependsOn":["s1"],"description":"Hesap sonucunu Excel tablosuna yaz"}',
    "]}",
    "",
    "Optimization decision support:",
    "Goal: A deger 10 maliyet 4, B deger 7 maliyet 3, C deger 12 maliyet 8; kapasite 10. Problemi karar degiskenleri, amac fonksiyonu ve kisitlarla modelle, coz ve uygulanabilirligi dogrula.",
    '{"steps":[',
    '{"id":"s1","capability":"quantum_model_problem","args":{"prompt":"A deger 10 maliyet 4, B deger 7 maliyet 3, C deger 12 maliyet 8; kapasite 10. Karar degiskenleri binary secim, amac toplam degeri maksimize etmek, kisit toplam maliyet <= 10.","problemClass":"optimization"},"dependsOn":[],"description":"Problemi karar degiskenleri, amac fonksiyonu, kisitlar ve QUBO/Ising forma donustur"},',
    '{"id":"s2","capability":"quantum_run_experiment","args":{"prompt":"{{steps.s1.output}}","algorithm":"qaoa","shots":1024},"dependsOn":["s1"],"description":"Aday cozumu klasik/kuantum-hibrit cozucuyle uret"},',
    '{"id":"s3","capability":"quantum_compare_classical","args":{"prompt":"{{steps.s2.output}}"},"dependsOn":["s2"],"description":"Cozumu klasik baseline ve uygulanabilirlik kisitlariyla dogrula"},',
    '{"id":"s4","capability":"quantum_generate_report","args":{"prompt":"Model: {{steps.s1.output}}\\n\\nCozum: {{steps.s2.output}}\\n\\nDogrulama: {{steps.s3.output}}","title":"Karar Destek Optimizasyon Raporu"},"dependsOn":["s1","s2","s3"],"description":"Karar destek raporunu ve dogrulama ozetini uret"}',
    "]}",
    "",
    "Research + report:",
    "Goal: 2026 elektrikli arac batarya trendlerini arastir ve kisa Word raporu hazirla.",
    '{"steps":[',
    '{"id":"s1","capability":"web_research","args":{"query":"2026 electric vehicle battery trends solid state LFP sodium ion market"},"dependsOn":[],"description":"Guncel kaynaklardan batarya trendlerini arastir"},',
    '{"id":"s2","capability":"document_write","args":{"title":"2026 Elektrikli Arac Batarya Trendleri","content":"{{steps.s1.output}}","format":"docx"},"dependsOn":["s1"],"description":"Arastirma sonucunu Word raporuna donustur"}',
    "]}",
    "",
    "Skill-backed prepared workflow:",
    "Goal: Verilen analiz sonucundan profesyonel DOCX raporu hazirla ve kaydet.",
    '{"steps":[',
    '{"id":"s1","capability":"text_analyze","args":{"prompt":"Kullanici baglamini profesyonel rapor bolumlerine ayir","sourceContext":"Kullanici baglami ve onceki veriler","mode":"professional"},"dependsOn":[],"description":"Rapor icin baglami analiz et"},',
    '{"id":"s2","capability":"run_skill","args":{"skillId":"document.docx_from_context","payload":{"title":"Profesyonel Rapor","text":"{{steps.s1.output}}","outputPath":"Profesyonel Rapor.docx"}},"dependsOn":["s1"],"description":"Hazir DOCX skill akisi ile raporu olustur ve kaydet"}',
    "]}",
    "",
    "Screen-action workflow:",
    "Goal: Chrome'u ac, yeni sekme ac, ekrandaki arama kutusuna kuantum optimizasyon yaz ve sonucu kontrol et.",
    '{"steps":[',
    '{"id":"s1","capability":"open_app","args":{"app_name":"Chrome"},"dependsOn":[],"description":"Chrome uygulamasini ac"},',
    '{"id":"s2","capability":"browser_control","args":{"action":"new_tab","browser":"chrome"},"dependsOn":["s1"],"description":"Yeni bos sekme ac"},',
    '{"id":"s3","capability":"desktop_operator.observe_screen","args":{"query":"Chrome yeni sekme sayfasinda arama/adres kutusu gorunuyor mu?"},"dependsOn":["s2"],"description":"Ekran durumunu gozlemle"},',
    '{"id":"s4","capability":"desktop_operator.execute_action","args":{"action":"type","text":"kuantum optimizasyon","target":"Chrome adres veya arama kutusu","reason":"Kullanici arama metnini yazmamizi istedi"},"dependsOn":["s3"],"description":"Arama metnini kutuya yaz"},',
    '{"id":"s5","capability":"desktop_operator.execute_action","args":{"action":"press","key":"ENTER","reason":"Aramayi baslat"},"dependsOn":["s4"],"description":"Aramayi baslat"},',
    '{"id":"s6","capability":"desktop_operator.observe_screen","args":{"query":"Arama sonuclari yuklendi mi? Basliklari ve gorunen durumu ozetle."},"dependsOn":["s5"],"description":"Son durumu gozlemle ve dogrula"}',
    "]}",
    "",
    "Screen-action delegated loop:",
    "Goal: Ekrandaki ayarlar penceresinde Wi-Fi bolumunu bul ve ac.",
    '{"steps":[',
    '{"id":"s1","capability":"desktop_operator.observe_screen","args":{"query":"Aktif pencerede ayarlar veya Wi-Fi ile ilgili gorunen ogeleri bul"},"dependsOn":[],"description":"Mevcut ekrani gozlemle"},',
    '{"id":"s2","capability":"desktop_operator.run","args":{"goal":"Ayarlar penceresinde Wi-Fi bolumunu bul ve ac; her eylemden sonra ekrani gozlemleyip dogrula, belirsiz veya riskli eylemde dur.","maxActions":8},"dependsOn":["s1"],"description":"Gozlem-karar-eylem dongusuyle Wi-Fi bolumunu ac"}',
    "]}",
  ].join("\n");
}

export function buildPlanningPrompt(
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
    "TOOL CAPABILITY CATALOG (use ONLY these exact capability names; each line: name: what it does — when to use [required args][needs approval]):",
    renderCapabilityCatalog(new Set(allowed)),
    "",
    "SKILL CATALOG (prepared local workflows; execute them ONLY through capability run_skill with args.skillId and args.payload):",
    renderSkillCatalog(new Set(allowed)),
    "",
    "PLAN MODE DECISION:",
    `- Existing backend work type hint: ${String(workOrder.workType ?? "unknown")}. Use it as a hint, but override it when the goal clearly requires another mode.`,
    "- DATA WORKFLOW: use this when the task is mainly research, private file/text reading, analysis, math, optimization, or artifact creation. Typical chain: gather/read/research -> analyze/model/calculate -> write/export/report/verify.",
    "- SCREEN-ACTION WORKFLOW: use this when the task must operate a visible app or website UI: open/focus app -> observe screen -> act (click/type/press/scroll) -> observe/verify -> repeat or close.",
    "- For UI tasks with a known browser primitive (open URL, search, new tab), prefer browser_control for that primitive, then observe/act only for visible UI follow-up.",
    "- For multi-click or uncertain UI tasks, prefer desktop_operator.run after an initial observe_screen; give it a concrete goal, maxActions, and a stop condition. For a single precise UI action, use desktop_operator.execute_action after observe_screen.",
    "- Never mix private data workflow with screen-action unless the user actually asks to use an app UI. A legal/medical/student report is usually DATA WORKFLOW; clicking buttons, scrolling pages, filling fields, or closing popups is SCREEN-ACTION WORKFLOW.",
    "",
    "RULES:",
    '- Output EXACTLY ONE JSON object, no prose, no markdown fences: {"steps":[...]}',
    '- Each step: {"id":"s1","capability":"<catalog name>","args":{...},"dependsOn":["<earlier id>"],"description":"<short>"}',
    "- Use the smallest correct number of steps (between 2 and " +
      String(MAX_WORK_ORDER_STEPS) +
      ").",
    "- Order steps so each runs after its dependencies; set dependsOn to the ids whose output it consumes.",
    "- The plan must be executable as a professional chain, not a short suggestion. Every user-requested deliverable needs a writer/export/verification step, not just analysis prose.",
    "- For each meaningful phase, use descriptions that can be shown as live progress. Keep them concrete: researching source, reading file, analyzing evidence, writing document, verifying artifact, observing screen, clicking target, retrying after failed state.",
    "- If an action can be verified, add a follow-up observation/readback/artifact-producing step. Do not mark UI or file work complete from intention alone.",
    "- Always provide every listed required arg for a capability; put concrete values, use {{steps.<id>.output}} to consume a previous step's result.",
    "- When a skill is a better fit than manually chaining primitive tools, create a step with capability \"run_skill\", args.skillId set to the exact skill id, and args.payload containing the skill's required payload fields. Do not invent capability names from skill ids.",
    "- Choose between primitive tools and skills deliberately: use primitive tools when you need fine-grained research/read/analyze/write dependencies; use run_skill when the skill catalog describes the exact prepared workflow or artifact creation.",
    "- Args must contain executable data, not vague descriptions. Do not write placeholders such as \"the invoice total\", \"the research result\", or \"the user's file\" when a concrete value or dependency reference is available.",
    "- math_solve.args.expression MUST be a numeric/symbolic expression such as \"12000+8500\" or \"(12000+8500)*1.20\". Never pass an explanation like \"faturaların toplamı\" as expression.",
    "- For tax/VAT/KDV requests, decide whether the user asks for tax amount or tax-included total: KDV amount for 12000 and 8500 at 20% is \"(12000+8500)*0.20\"; tax-included total is \"(12000+8500)*1.20\".",
    "- For spreadsheet_write/document_write/presentation_write, put the produced content in args directly and reference prior outputs with {{steps.<id>.output}}. Do not rely on hidden context.",
    "- Match the user's requested output artifact: Excel/table/spreadsheet/xlsx -> spreadsheet_write; presentation/slides/pptx -> presentation_write; Word/report/petition/document/docx -> document_write. Do not use document_write for a requested presentation or spreadsheet when the matching writer is available.",
    "- For screen-action workflows, every desktop_operator.execute_action must have a concrete action plus target/text/key/reason as applicable, and should depend on a preceding screen observation. Verify important UI state with desktop_operator.observe_screen after actions.",
    "- Use desktop_operator.run for visible UI goals that need iterative observe -> decide -> act behavior. Include args.goal, args.maxActions, and a stop/fail condition in the goal text.",
    "- For spreadsheet_write, provide concrete rows/sheets and place calculation/research outputs into cells with {{steps.<id>.output}}.",
    "- For presentation_write, provide a concrete title and prompt/content that consumes research/read outputs with {{steps.<id>.output}}.",
    "- If the user provides inline private facts, test values, case notes, project notes, pasted text, or a local file to read/analyze/summarize before writing, start with document_read or file_read when available, then feed {{steps.<id>.output}} into document_write/presentation_write/spreadsheet_write.",
    "- If text_analyze is available and the task asks to analyze/interpret/evaluate/summarize/explain/compare or produce a professional/student artifact, insert text_analyze between gathering/calculation/research and the writer. Its sourceContext must reference prior outputs with {{steps.<id>.output}}, and the writer must consume {{steps.<analysis_id>.output}}.",
    "- Do not send private inline facts, file contents, medical/test values, legal case facts, or local document summaries to web_research. Use web_research only for public background/source lookup, and merge it later in writer args.",
    "- For web_research, query must be a concrete search query with key terms only. Do not pass the full user goal, private case facts, file summaries, or writing instructions as the query.",
    "- For professional workflows, preserve private case/test/project facts in writer args, but keep web_research queries public and generic enough for source lookup.",
    "- For optimization/decision-support workflows that mention decision variables, objective functions, constraints, QUBO/Ising, QAOA, knapsack, capacity, or solver verification, use the decision-support chain: quantum_model_problem -> quantum_run_experiment -> quantum_compare_classical -> quantum_generate_report.",
    "- In optimization plans, quantum_model_problem.args.prompt must include concrete decision variables/objective/constraints from the user; later steps must consume prior outputs with {{steps.<id>.output}} and quantum_generate_report must include the model, solution, and verification outputs.",
    "- For image_generate, prompt must be the full visual prompt the image model should receive, not a short label.",
    "- Steps marked [needs approval] are allowed; the desktop asks the user before running them — plan them normally.",
    "- Approval is surfaced to the user as one Full Computer Access task approval. Do not split one workflow into repeated approvals unless a later step is irreversible/non-idempotent such as sending email, payment, deletion, or overwriting a user file.",
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
export function normalizeMaterializedSteps(
  rawPlan: Record<string, unknown> | null,
  allowedCapabilities: Iterable<string> = MATERIALIZABLE_CAPABILITIES,
): DesktopWorkOrderStep[] | null {
  if (!rawPlan) return null;
  const rawSteps = Array.isArray(rawPlan.steps) ? rawPlan.steps : [];
  const allowed = new Set(
    [...allowedCapabilities].map((capability) => String(capability ?? "").trim()),
  );
  const seenIds = new Set<string>();
  const normalized: DesktopWorkOrderStep[] = [];
  for (let index = 0; index < rawSteps.length; index += 1) {
    if (normalized.length >= MAX_WORK_ORDER_STEPS) break;
    const step = asRecord(rawSteps[index]);
    if (!step) continue;
    const capability = String(step.capability ?? "").trim();
    if (!capability || !CAPABILITY_NAME_RE.test(capability)) continue;
    if (!allowed.has(capability)) continue;
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
    const explicit = (step.dependsOn ?? []).filter(
      (d) => validIds.has(d) && d !== step.id,
    );
    const inferred = [...templateStepReferences({
      args: step.args,
      forEach: (step as Record<string, unknown>).forEach,
    })].filter((d) => validIds.has(d) && d !== step.id);
    step.dependsOn = [...new Set([...explicit, ...inferred])];
  }
  return normalized.length >= 2 ? normalized : null;
}

/**
 * ÖZELEŞTİRİ (reflect-and-revise): server_brain kendi taslak planını eleştirel
 * gözden geçirip düzeltir. Muhakeme kalitesini yükseltir: eksik adım, muğlak
 * argüman (grounding), yanlış araç/mod, kopuk veri akışı bir tur içinde
 * düzeltilir. Fail-safe: revizyon boş/kötü/gate'e takılırsa TASLAK korunur
 * (asla regresyon yok). Reddedilen görevler zaten heuristik yola düşer.
 */
async function critiqueAndRevisePlan(
  app: FastifyInstance,
  userId: string,
  taskId: string,
  workOrder: DesktopWorkOrder,
  draftSteps: DesktopWorkOrderStep[],
  allowed: string[],
): Promise<DesktopWorkOrderStep[]> {
  try {
    const summary = String(workOrder.goal?.summary ?? "").slice(0, 4_000);
    const draftJson = JSON.stringify({
      steps: draftSteps.map((s) => ({
        id: s.id,
        capability: s.capability,
        args: s.args,
        dependsOn: s.dependsOn ?? [],
        description: s.description,
      })),
    });
    const critiquePrompt = [
      "You are Elyan's own plan reviewer. Critically re-examine YOUR OWN draft plan for the goal and output the best corrected plan. Reason step by step, then output only JSON.",
      "",
      "GOAL:",
      summary,
      "",
      "DRAFT PLAN:",
      draftJson,
      "",
      "SELF-CRITIQUE CHECKLIST — fix EVERY issue you find:",
      "1) Grounding: every arg holds concrete executable data or a {{steps.<id>.output}} reference. Remove vague placeholders ('the total', 'the file', 'the research result').",
      "2) Right method/mode: Excel->spreadsheet_write, slides->presentation_write, doc/report/petition->document_write, UI action->desktop_operator, analysis->text_analyze between gather and writer; run_skill when a catalog skill fits exactly.",
      "3) Completeness: no missing prerequisite (read/research before analyze; analyze before write; observe before/after risky UI actions).",
      "4) Data flow: dependsOn is correct and each consumer references its producer with {{steps.<id>.output}}.",
      "5) math_solve.expression numeric only; web_research.query short & public (no private facts).",
      "6) Smallest correct plan (2..16 steps).",
      "",
      "CAPABILITY CATALOG (allowed names only):",
      renderCapabilityCatalog(new Set(allowed)),
      "",
      'Output EXACTLY ONE JSON object {"steps":[...]} with the corrected plan. If the draft is already optimal, return it unchanged. No prose, no markdown fences.',
    ].join("\n");
    const revision = await generateGovernedSharedBrainReply(app, {
      userId,
      taskId,
      title: "Desktop plan (self-critique)",
      prompt: critiquePrompt,
      workload: "planning",
      route: "desktop_plan_critique",
      meteringSurface: "task",
      maxCompletionTokensOverride: MATERIALIZE_MAX_TOKENS,
      timeoutMsOverride: MATERIALIZE_TIMEOUT_MS,
      requestMetadata: { desktopPlanCritique: true },
      internalEvaluation: {
        skipUsageValidation: true,
        skipReviewLogging: true,
        refinementPass: true,
      },
    });
    if (revision.answerSource === "backend_gate" || !revision.text.trim()) {
      return draftSteps;
    }
    const revised = normalizeMaterializedSteps(
      extractFirstJsonObject(revision.text),
      allowed,
    );
    // Güven: revize plan geçerli (≥2 adım) ise kullan; yoksa taslak korunur.
    return revised && revised.length >= 2 ? revised : draftSteps;
  } catch {
    return draftSteps;
  }
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

    const draftSteps = normalizeMaterializedSteps(
      extractFirstJsonObject(inference.text),
      allowed,
    );
    if (!draftSteps) return; // gerçek ayrıştırma yok → heuristik korunur.

    // ÖZELEŞTİRİ: model kendi planını eleştirel gözden geçirip düzeltir
    // (muhakeme kalitesi). Fail-safe: revizyon zayıfsa taslak korunur.
    const steps = await critiqueAndRevisePlan(
      app,
      task.userId,
      task.id,
      workOrder,
      draftSteps,
      allowed,
    );

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
