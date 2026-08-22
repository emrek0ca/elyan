import { failureTaxonomyEntries } from "../../config/failure-taxonomy.js";
import { createHash } from "node:crypto";
import { trStemPattern, unicodeWordPattern } from "../../lib/tr-word-boundary.js";
import type {
  CommandRouteDecision,
  SemanticDesktopDispatchContract,
} from "../routing-policy/service.js";
import type { UnderstandingEnvelope } from "../../core/understanding/types.js";
import type { RemoteMcpSelectionMetadata } from "../integrations/provider-registry.js";
import { extractStructuralSlots } from "./structural-slots.js";
import { DESKTOP_CAPABILITY_MANIFEST } from "./desktop-capability-manifest.js";
import { matchDesktopCapabilitiesSemantically } from "./desktop-capability-ontology.js";

// Work order adım bütçesi. Eskiden 8'e sabitliydi ve karmaşık (çok-adımlı)
// görevler masaüstünde WORK_ORDER_STEP_BUDGET_EXCEEDED ile reddediliyordu.
// Desktop planner MAX_PLAN_STEPS=16 ile hizalandı (runtime/desktop_work_order.py
// MAX_STEPS ile birlikte güncellenir).
export const MAX_WORK_ORDER_STEPS = 16;
export function isDesktopPlanPreparationPending(
  payload: unknown,
): boolean {
  const root =
    payload && typeof payload === "object" && !Array.isArray(payload)
      ? (payload as Record<string, unknown>)
      : null;
  const order =
    root?.desktopWorkOrder &&
    typeof root.desktopWorkOrder === "object" &&
    !Array.isArray(root.desktopWorkOrder)
      ? (root.desktopWorkOrder as Record<string, unknown>)
      : null;
  const preview =
    order?.planPreview &&
    typeof order.planPreview === "object" &&
    !Array.isArray(order.planPreview)
      ? (order.planPreview as Record<string, unknown>)
      : null;
  const preparation =
    preview?.planPreparation &&
    typeof preview.planPreparation === "object" &&
    !Array.isArray(preview.planPreparation)
      ? (preview.planPreparation as Record<string, unknown>)
      : null;
  return preparation?.status === "pending";
}

export type DesktopWorkOrderStep = {
  id: string;
  capability: string;
  description: string;
  args: Record<string, unknown>;
  /**
   * Bağımlılık grafı — bu adım hangi adım id'lerinin çıktısına dayanır.
   * Sunucu-materyalize planlarda dolu gelir; heuristik planlarda boş/atlanmış
   * (yalnız dizi sırası). Desktop runtime/compiled_plan.py'nin hash'lenen
   * şekliyle hizalıdır (id/capability/args/dependsOn/forEach/resourceScope).
   */
  dependsOn?: string[];
  /** Bu adımın dokunduğu kaynak kapsamı (çakışma/paralellik kararları için). */
  resourceScope?: string[];
  /** {{steps.<id>.items}} gibi bir koleksiyon üzerinde tekrar için (fan-out). */
  forEach?: string;
};

export type DesktopWorkOrder = {
  schema: "elyan.desktop_work_order.v1";
  source: "mobile_chat_dispatch" | "backend_task_route";
  goal: {
    kind: string;
    summary: string;
    language: "tr" | "en" | "unknown";
    sourceTextHash: string;
  };
  semanticGoal?: {
    contract: "elyan.semantic_task_contract.v1";
    objective: string;
    constraints: string[];
    successCriteria: string[];
    requiredCapabilities: string[];
    forbiddenCapabilities: string[];
    ambiguityPolicy: "ask" | "safe_assumption" | "fail_closed";
    risk: {
      localPrivate: boolean;
      sideEffect: boolean;
      irreversible: boolean;
    };
  };
  entities: Array<{
    // Yapısal yuvalar (time/date/quoted/format/quantity) 2026-08-22'de eklendi:
    // iş emrine giden veri tek parçaydı (`topic` = cümlenin tamamı) ve
    // planlayıcı somut argüman üretemiyordu.
    type:
      | "url"
      | "email"
      | "file_hint"
      | "app_hint"
      | "topic"
      | "time"
      | "date"
      | "quoted"
      | "format"
      | "quantity";
    value: string;
  }>;
  constraints: string[];
  workType?: "data_workflow" | "screen_action" | "mixed" | "decision_support";
  requiredCapabilities: string[];
  capabilityAuthorization?: {
    source: "semantic_router";
    allowPrivateRead: boolean;
    sideEffectsRequireApproval: true;
  };
  materializedCapabilityScope?: string[];
  localContextNeeded: string[];
  resourceScope?: {
    contract: "elyan.resource_scope.v1";
    readRoots: string[];
    writeRoots: string[];
  };
  expectedOutputs: Array<{
    kind: "chat_result" | "artifact" | "file_update" | "browser_state" | "system_state";
    format: string;
    required: boolean;
  }>;
  verificationRules: Array<{
    id: string;
    description: string;
    evidence: "runtime_status" | "tool_result" | "artifact" | "state_readback";
  }>;
  execution: {
    mode: "cowork_dispatch";
    approvalPolicy: "capability_policy" | "single_full_access_surface";
    maxSteps: number;
  };
  contextPack?: {
    sourceReference: "none" | "current_prompt" | "previous_answer" | "latest_artifact" | "attachment";
    conversationState?: Record<string, unknown>;
    latestArtifactRef?: Record<string, unknown> | null;
    toolSkillDecision?: Record<string, unknown> | null;
    outputContract?: Record<string, unknown> | null;
    privacyRouting?: Record<string, unknown>;
    desktopPlanningEvidence?: {
      contract: "elyan.desktop_planning_evidence.v1";
      source: "server_read_only_tool_loop";
      toolCount: number;
      okCount: number;
      tools: Array<{
        tool: string;
        ok: boolean;
        permission: "read";
        resultDigest: string | null;
        resultCount: number | null;
        errorCode: string | null;
      }>;
      agentPlan?: {
        stepCount: number;
        tools: string[];
      };
    };
    semanticDesktopContract?: SemanticDesktopDispatchContract;
  };
  executionPlan?: {
    mode: "data_workflow" | "screen_action" | "mixed" | "decision_support";
    intentGraph?: Record<string, unknown>;
    planner: "server_brain";
    allowReplan: boolean;
  };
  verificationPlan?: {
    criteria: DesktopWorkOrder["verificationRules"];
    requireEvidence: boolean;
    noModelClaimCompletion: boolean;
  };
  failurePolicy?: {
    maxReplans: number;
    retryOnRecoverableToolError: boolean;
    stopOnIrreversibleRisk: boolean;
    safeUserMessage: string;
    taxonomy?: Array<{
      code: string;
      class: "dependency" | "permission" | "capability" | "verification" | "model" | "timeout" | "cancelled";
      retryable: boolean;
      replanAllowed: boolean;
    }>;
  };
  replanContext?: {
    includeCompletedOutputs: boolean;
    includeLastError: boolean;
    includeScreenObservation: boolean;
  };
  permissionEnvelope?: {
    mode: "single_full_access_surface";
    coveredPermissions: string[];
    separateApprovalFor: string[];
    ttlSeconds: number;
  };
  /**
   * Present only for work Elyan started on its own while nobody was watching.
   *
   * The desktop treats this as a hard ceiling: only `allowedCapabilities` may
   * run, and anything that would normally pause for approval stops instead —
   * there is no one there to answer. Absent means "the user is present",
   * which is the normal, unrestricted case.
   */
  autonomy?: {
    mode: "night_watch";
    unattended: true;
    jobId: string;
    allowedCapabilities: string[];
    evidence: { source: string; ref: string; note: string };
  };
  planPreview: {
    summary: string;
    privacyClass: "public_text" | "local_private" | "side_effect";
    steps: DesktopWorkOrderStep[];
    dispatchOptimization?: {
      strategy: "quantum_guided_dispatch_v1";
      source: "backend_neural_readiness";
      active: boolean;
      score: number;
      classicalBaselineScore: number | null;
      advantageScore: number | null;
      qualified: boolean;
      benchmarkSource: "measured";
      admissionWeight: number;
      metric: string;
    };
    responsiveExecution?: {
      strategy: "quantum_liveness_guard_v1";
      source: "backend_neural_readiness";
      active: boolean;
      livenessScore: number;
      qualified: boolean;
      benchmarkSource: "measured";
      boostWeight: number;
      metric: "responsive_execution_liveness";
    };
    livenessGuard?: {
      strategy: "quantum_replan_liveness_guard_v1";
      source: "backend_neural_readiness";
      active: boolean;
      timeoutRisk: "low" | "medium" | "high";
      maxReplans: number;
      earlyProgressCheckpoint: boolean;
      safeStopOnTimeout: boolean;
      metric: "responsive_execution_liveness";
    };
    /**
     * Planın kaynağı ve güven sınıfı. `heuristic` yalnız eski uyumluluk için
     * tutulur; yeni desktop işi ya server planner tarafından materialize edilir
     * ya da registry'nin doğrudan-güvenli tek adımlı planı olarak işaretlenir.
     */
    planSource?:
      | "heuristic"
      | "server_materialized"
      | "deterministic_registry";
    materializationSource?:
      | "model"
      | "model_transport_repair"
      | "semantic_compiler"
      | "deterministic_registry";
    /**
     * New tasks are not deliverable while model planning is pending. Older
     * work orders without this field remain ready for backward compatibility.
     */
    planPreparation?: {
      status: "pending" | "ready" | "failed";
      outcome?:
        | "materialized"
        | "deterministic_materialized"
        | "planning"
        | "model_plan_unavailable";
      preparedAt?: string;
    };
    planCache?: {
      contract: "elyan.plan_cache.v1";
      status: "hit" | "stored";
      keyHash: string;
      source: "memory_lru" | "reliability_store";
      cachedAt: string;
      fingerprints?: {
        goalDeltaHash: string;
        capabilityManifestHash: string;
        skillManifestHash?: string;
      };
      hitCount?: number;
    };
    /** Sunucu-materyalize planlarda kanonik yürütme sözleşmesi. */
    contract?: "elyan.compiled_plan.v1";
    liveNarrationPlan?: Array<{
      phase: "planning" | "observing" | "executing" | "verifying" | "replanning" | "completed";
      message: string;
    }>;
  };
  /** Safe target/evidence only; credentials and raw MCP config never enter a work order. */
  remoteMcp?: RemoteMcpSelectionMetadata;
  understanding?: {
    schemaVersion: UnderstandingEnvelope["schema_version"];
    intent: UnderstandingEnvelope["intent"];
    entities: UnderstandingEnvelope["entities"];
    constraints: UnderstandingEnvelope["constraints"];
    desiredOutputs: UnderstandingEnvelope["desired_outputs"];
    successCriteria: UnderstandingEnvelope["success_criteria"];
    ambiguities: UnderstandingEnvelope["ambiguities"];
    risk: UnderstandingEnvelope["risk"];
    intentGraph?: UnderstandingEnvelope["intent_graph"];
    sourceReference?: UnderstandingEnvelope["source_reference"];
    latestArtifactRef?: UnderstandingEnvelope["latest_artifact_ref"];
    conversationState?: UnderstandingEnvelope["conversation_state"];
    toolSkillDecision?: UnderstandingEnvelope["tool_skill_decision"];
    outputContract?: UnderstandingEnvelope["output_contract"];
    privacyRouting?: UnderstandingEnvelope["privacy_routing"];
    ambiguityPolicy?: UnderstandingEnvelope["ambiguity_policy"];
    confidence: number;
  };
};

export type DirectDesktopAppCommand = {
  capability: "open_app" | "close_app";
  appName: string;
};

export type DirectImageFetchCommand = {
  query: string;
  destination: "~/Desktop" | "~/Downloads" | "~/Pictures" | "~/Documents";
  count: number;
};

/**
 * Çok kelimeli GERÇEK uygulama adları. Doğrudan-komut kestirmesi yalnız bunlar
 * için birden fazla sözcüğe izin verir.
 *
 * Gerekçe (canlı arıza 2026-08-21, görev 66443c57 "Safariden youtube u aç"):
 * `app` grubu boşluğa izin verdiği için desen TÜM ÖBEĞİ uygulama adı sandı ve
 * deterministik kestirme `open_app{app_name:"Safariden youtube"}` üretti. Bu
 * plan model planlayıcısını tamamen ATLADIĞI için istek hiç çözümlenmedi:
 * masaüstü "Safariden youtube bu bilgisayarda bulunamadi" (APP_NOT_FOUND)
 * dedi, kendi kendini düzeltip Safari'yi açtı, ardından YouTube'a gitmek için
 * gereken tarayıcı yeteneği iş emri kapsamında (`["open_app"]`) olmadığı için
 * görev CAPABILITY_SCOPE_MISMATCH ile ÖLDÜ. Safari açıldı, YouTube açılmadı.
 *
 * Kestirme bir OPTİMİZASYONdur: eşleşmediğinde model planlayıcısına düşmek
 * güvenli yöndür (ve artık ucuzdur). Bu yüzden liste dar tutulur.
 */
const KNOWN_MULTI_WORD_APPS = new Set([
  "app store",
  "activity monitor",
  "adobe acrobat",
  "adobe photoshop",
  "android studio",
  "disk utility",
  "final cut pro",
  "google chrome",
  "logic pro",
  "microsoft edge",
  "microsoft excel",
  "microsoft outlook",
  "microsoft powerpoint",
  "microsoft teams",
  "microsoft word",
  "quicktime player",
  "sublime text",
  "system settings",
  "visual studio code",
  "vs code",
]);

export function parseDirectDesktopAppCommand(message: string): DirectDesktopAppCommand | null {
  const compact = compactText(message, 240);
  const match = compact.match(
    /^(?:(?:lütfen|lutfen|şimdi|simdi|bana)\s+)*(?<app>[\p{L}\p{N}][\p{L}\p{N} ._'’+-]{0,79}?)\s+(?:(?<appnoun>uygulamasını|uygulamasini|uygulamayı|uygulamayi|programını|programini|programı|programi)\s+)?(?<verb>aç|ac|başlat|baslat|çalıştır|calistir|kapat|durdur|sonlandır|sonlandir)(?:(?:abilir|ebilir)|(?:ır|ir|ur|ür|ar|er))?(?:\s+(?:mı|mi|mu|mü)(?:sın|sin|sun|sün|sınız|siniz|sunuz|sünüz)?)?(?:\s+(?:lütfen|lutfen))?[.!?]*$/iu,
  );
  const rawApp = match?.groups?.app?.trim() ?? "";
  const verb = match?.groups?.verb?.toLocaleLowerCase("tr-TR") ?? "";
  if (!rawApp || !verb) return null;
  const appName = rawApp
    .replace(
      /^(?:masaüstümde|masaustumde|masaüstünde|masaustunde|bilgisayarımda|bilgisayarimda|desktop(?:ımda|imda)?|on my desktop)\s+/iu,
      "",
    )
    .replace(/['’](?:y?[ıiuü])$/iu, "")
    // Turkish accusative/possessive suffixes are sometimes dictated or typed
    // without the apostrophe ("Chrome u kapat").  Keep this normalization
    // narrow so a real multi-word app name is not rewritten.
    .replace(/\s+(?:y?[ıiuü])$/iu, "")
    .trim();
  if (!appName) return null;
  // ÇOK SÖZCÜKLÜ ÖBEK KENDİLİĞİNDEN UYGULAMA ADI DEĞİLDİR.
  //
  // "Safariden youtube u aç" bileşik bir istektir (tarayıcıyı aç + adrese
  // git); tek adımlık `open_app` kestirmesi onu çözemez. Ama "Hesap Makinesi
  // uygulamasını aç" gerçekten çok sözcüklü bir uygulamadır — ve yerelleşmiş
  // adlar (Sistem Ayarları, Etkinlik İzlencesi…) bir listeye sığmaz.
  //
  // Ayrım Türkçe ek TAHMİNİYLE değil, KULLANICININ KENDİ SÖZÜYLE yapılır:
  // "uygulamasını/programını" diyorsa önceki sözcükler bir uygulama adıdır.
  // Bu işaret yoksa yalnız bilinen çok sözcüklü uygulamalara izin verilir;
  // gerisi model planlayıcısına düşer (kestirme bir optimizasyondur, karar
  // mercii değil).
  const declaredAsApplication = Boolean(match?.groups?.appnoun);
  if (
    /\s/u.test(appName) &&
    !declaredAsApplication &&
    !KNOWN_MULTI_WORD_APPS.has(appName.toLocaleLowerCase("tr-TR"))
  ) {
    return null;
  }
  return {
    capability: /^(?:kapat|durdur|sonlandır|sonlandir)$/iu.test(verb) ? "close_app" : "open_app",
    appName,
  };
}

export type DirectFolderCreateCommand = {
  folderName: string;
  locationHint: string;
};

/**
 * "Masaüstüne Emre adında klasör oluştur" gibi doğrudan klasör isteği.
 * Bunu tanımayınca work order jenerik operator planına düşüyor ve masaüstünde
 * onay çıkmazı üretiyordu — klasör oluşturma zararsız `make_directory`
 * adımına gider.
 */
export function parseDirectFolderCreateCommand(
  message: string,
): DirectFolderCreateCommand | null {
  const compact = compactText(message, 240);
  const normalized = compact.toLocaleLowerCase("tr-TR");
  const wantsFolder = unicodeWordPattern(String.raw`\b(?:klasör|klasor|dizin|folder)\b`, "i").test(normalized);
  const wantsCreate = unicodeWordPattern(String.raw`\b(?:oluştur|olustur|yarat|aç|ac|create|make|mkdir)\b`, "i").test(normalized);
  if (!wantsFolder || !wantsCreate) return null;
  const nameMatch = compact.match(
    /(?:["'«»](?<quoted>[^"'«»]{1,80})["'«»]|(?<plain>[\p{L}\p{N}_-]{1,60}))\s+(?:adında|adinda|adlı|adli|isimli|ismiyle|named)\s+(?:bir\s+)?(?:klasör|klasor|dizin|folder)/iu,
  );
  const folderName = (nameMatch?.groups?.quoted ?? nameMatch?.groups?.plain ?? "").trim();
  const locationHint = /masaüstü|masaustu|desktop/iu.test(normalized)
    ? "~/Desktop"
    : /indirilenler|downloads/iu.test(normalized)
      ? "~/Downloads"
      : /belgeler|documents/iu.test(normalized)
        ? "~/Documents"
        : "~/Desktop";
  return { folderName, locationHint };
}

/**
 * TÜRKÇE EK TOLERANSI — PLANLAMA SİNYALLERİ.
 *
 * Bu dosyadaki niyet kalıpları `\b` ile kök arıyordu. Türkçe eklemeli bir dil
 * olduğu için ASCII `\b` ekli biçimlerde SESSİZCE ölüyor. Ölçüldü:
 *
 *   /\b(?:indir|kaydet|download|save)\b/  ✗ "kaydeder misin", "indirir misin"
 *   /\b(...|dosya|belge|rapor|sunum)\b/   ✗ "dosyayı kaydet", "raporu hazırla"
 *   /\b(terminal|komut|shell)\b/          ✗ "terminali kapat", "şu komutu koştur"
 *   /\b(ekran|...|uygulama|program)\b/    ✗ "uygulamayı kapat", "ekranda ne var"
 *
 * `unicodeWordPattern` bu sorunu ÇÖZMEZ — o yalnız sınırı Unicode'a taşır;
 * "raporu"da "u" yine harf olduğu için sınır oluşmaz. Ek toleransı için tek
 * doğru araç `trStemPattern`.
 *
 * Neden önemli: bu sinyaller beklenen ÇIKTIYI (artefakt/dosya) ve görev türünü
 * belirliyor. "raporu hazırla" isteğinde dosya çıktısı beklenmiyorsa plan
 * kapsama doğrulaması da çalışmıyor — kullanıcının yaşadığı "yaptım ama dosya
 * yok" arızasının kaynağı bu.
 *
 * `exclude` listeleri ölçülerek eklendi: ek toleransı kontrolsüz bırakılırsa
 * "indir" kökü "indirim"i, "not" kökü "noter"i, "yazı" kökü "yazılım"ı yakalar.
 */
const SAVE_INTENT_PATTERN = trStemPattern(
  ["indir", "kaydet", "kayded", "download", "save"],
  { exclude: ["indirim", "indirimi", "indirimli", "indirime", "indirgeme", "indirgemeli"] },
);
const TERMINAL_CONTEXT_PATTERN = trStemPattern(["terminal", "komut", "shell"], {
  exclude: ["komutan\\p{L}*", "komuta"],
});
const SCREEN_OR_APP_PATTERN = trStemPattern(
  ["ekran", "screenshot", "uygulama", "program"],
  { exclude: ["ekranı kapat"] },
);
const SCREEN_CONTEXT_PATTERN = trStemPattern(
  ["ekran", "screenshot", "görüntü", "goruntu", "pencere", "window"],
  { exclude: ["görüntülü", "goruntulu", "windows"] },
);
const BROWSER_CONTEXT_PATTERN = trStemPattern([
  "chrome",
  "safari",
  "firefox",
  "edge",
  "browser",
  "tarayıcı",
  "tarayici",
  "sekme",
]);
const PRESENTATION_PATTERN = trStemPattern([
  "pptx",
  "powerpoint",
  "sunum",
  "slayt",
  "slide",
  "presentation",
]);
const DOCUMENT_NOUN_PATTERN = trStemPattern(
  ["pdf", "docx", "xlsx", "csv", "svg", "dosya", "belge", "rapor", "sunum", "slayt", "presentation"],
  { exclude: ["belgesel", "belgeseli", "belgeselleri"] },
);

export function parseDirectImageFetchCommand(message: string): DirectImageFetchCommand | null {
  const compact = compactText(message, 400);
  const normalized = compact.toLocaleLowerCase("tr-TR");
  const hasImage = unicodeWordPattern(String.raw`\b(?:resim|resmi|resmini|görsel|gorsel|görseli|gorseli|foto|fotoğraf|fotograf|image|picture)\b`, "i").test(normalized);
  const hasSave = SAVE_INTENT_PATTERN.test(normalized);
  const hasGeneration = unicodeWordPattern(String.raw`\b(?:çiz|ciz|oluştur|olustur|üret|uret|generate|tasarla|yap)\b`, "i").test(normalized);
  if (!hasImage || !hasSave || hasGeneration) return null;

  const subjectMatch = compact.match(
    unicodeWordPattern(String.raw`(.+?)\s+(?:resim|resmi|resmini|görsel|gorsel|görseli|gorseli|foto(?:ğraf|graf)?|image|picture)\b`, "i"),
  );
  let query = subjectMatch?.[1]?.trim() ?? "";
  query = query
    .replace(/^(?:(?:lütfen|lutfen|bana|bir|şu|su|bu|İnternetten|internetten|webden|google'dan|googledan)\s+)+/u, "")
    .replace(/^(?:(?:chrome|safari|firefox|edge|tarayıcı|tarayici|browser)(?:den|dan|de|da)?\s+)+/iu, "")
    .replace(/^[1-5]\s+(?:adet\s+)?/iu, "")
    .trim();
  if (!query) return null;

  let destination: DirectImageFetchCommand["destination"] = "~/Desktop";
  if (/\b(?:indirilenler(?:e|den|de)?|downloads?)\b/iu.test(normalized)) destination = "~/Downloads";
  else if (unicodeWordPattern(String.raw`\b(?:resimler|pictures|fotoğraflar|fotograflar)\b`, "i").test(normalized)) destination = "~/Pictures";
  else if (/\b(?:belgeler|documents?)\b/iu.test(normalized)) destination = "~/Documents";
  const countMatch = normalized.match(/\b([1-5])\s+(?:adet\b)?/iu);
  return { query: compactText(query, 160), destination, count: Number(countMatch?.[1] ?? 1) };
}

export function isDeterministicDesktopAppWorkOrder(
  routeDecision: CommandRouteDecision,
  message: string,
): boolean {
  const isDesktopRoute = routeDecision.route === "desktop_runtime"
    || routeDecision.taskRoute?.operationalRoute === "desktop_runtime";
  return isDesktopRoute && parseDirectDesktopAppCommand(message) !== null;
}

export function isDeterministicDesktopFastWorkOrder(
  routeDecision: CommandRouteDecision,
  message: string,
): boolean {
  const isDesktopRoute = routeDecision.route === "desktop_runtime"
    || routeDecision.taskRoute?.operationalRoute === "desktop_runtime";
  return isDesktopRoute && (
    parseDirectDesktopAppCommand(message) !== null
    || parseDirectImageFetchCommand(message) !== null
  );
}

function compactText(value: unknown, maxLength = 1_000): string {
  const normalized = String(value ?? "")
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 1).trimEnd()}…` : normalized;
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function buildDesktopPlanningEvidenceFromMetadata(
  metadata: Record<string, unknown>,
): NonNullable<DesktopWorkOrder["contextPack"]>["desktopPlanningEvidence"] | null {
  const rawResults = Array.isArray(metadata.toolResults)
    ? metadata.toolResults
    : [];
  const tools = rawResults
    .map((item) => readRecord(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .map((item) => {
      const permission =
        typeof item.permission === "string"
          ? item.permission.toLocaleLowerCase("en-US")
          : "";
      if (permission !== "read") return null;
      const output = readRecord(item.output);
      const directResultCount = item.resultCount;
      const outputResultCount = output?.resultCount;
      const resultCount =
        typeof directResultCount === "number" &&
        Number.isFinite(directResultCount)
          ? directResultCount
          : typeof outputResultCount === "number" &&
              Number.isFinite(outputResultCount)
            ? outputResultCount
            : null;
      return {
        tool: compactText(item.tool, 80),
        ok: item.ok === true,
        permission: "read" as const,
        resultDigest:
          typeof item.resultDigest === "string"
            ? compactText(item.resultDigest, 120)
            : null,
        resultCount,
        errorCode:
          typeof item.errorCode === "string"
            ? compactText(item.errorCode, 80)
            : null,
      };
    })
    .filter(
      (
        item,
      ): item is {
        tool: string;
        ok: boolean;
        permission: "read";
        resultDigest: string | null;
        resultCount: number | null;
        errorCode: string | null;
      } => Boolean(item?.tool),
    )
    .slice(0, 8);
  const agentPlan = readRecord(metadata.agentPlan);
  const rawPlanSteps = Array.isArray(agentPlan?.steps) ? agentPlan.steps : [];
  const planTools = rawPlanSteps
    .map((step) => readRecord(readRecord(step)?.tool_request)?.tool)
    .filter(
      (tool): tool is string =>
        typeof tool === "string" && tool.trim().length > 0,
    )
    .map((tool) => compactText(tool, 80))
    .slice(0, 8);
  if (tools.length === 0 && planTools.length === 0) return null;
  return {
    contract: "elyan.desktop_planning_evidence.v1",
    source: "server_read_only_tool_loop",
    toolCount: tools.length,
    okCount: tools.filter((item) => item.ok).length,
    tools,
    ...(planTools.length > 0
      ? {
          agentPlan: {
            stepCount: rawPlanSteps.length,
            tools: [...new Set(planTools)],
          },
        }
      : {}),
  };
}

function sourceHash(value: string): string {
  return createHash("sha256").update(value).digest("hex").slice(0, 24);
}

function detectLanguage(value: string): "tr" | "en" | "unknown" {
  if (!value.trim()) return "unknown";
  return /[çğıöşü]/i.test(value) || unicodeWordPattern(String.raw`\b(bunu|şunu|dosya|masaüstü|bilgisayar|yap|hazırla|özetle)\b`, "i").test(value)
    ? "tr"
    : "en";
}

function extractEntities(message: string): DesktopWorkOrder["entities"] {
  const entities: DesktopWorkOrder["entities"] = [];
  const seen = new Set<string>();
  const add = (type: DesktopWorkOrder["entities"][number]["type"], value: string) => {
    // The topic is the runtime planner's canonical natural-language goal.
    // Keep the complete bounded request; short structural entities still use
    // the tighter limit so they cannot bloat the work-order envelope.
    const normalized = compactText(value, type === "topic" ? 4_000 : 240);
    const key = `${type}:${normalized.toLocaleLowerCase("tr-TR")}`;
    if (!normalized || seen.has(key)) return;
    seen.add(key);
    entities.push({ type, value: normalized });
  };

  const directAppCommand = parseDirectDesktopAppCommand(message);
  if (directAppCommand) add("app_hint", directAppCommand.appName);

  for (const match of message.matchAll(/https?:\/\/\S+/gi)) add("url", match[0]);
  for (const match of message.matchAll(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi)) add("email", match[0]);
  for (const match of message.matchAll(unicodeWordPattern(String.raw`\b[\wÇĞİÖŞÜçğıöşü ._-]{1,80}\.(?:pdf|docx|xlsx|csv|txt|png|jpg|jpeg|svg)\b`, "gi"))) {
    add("file_hint", match[0]);
  }
  for (const match of message.matchAll(/\b(vs ?code|visual studio code|chrome|safari|finder|terminal|excel|word|numbers|pages)\b/gi)) {
    add("app_hint", match[0]);
  }
  for (const match of message.matchAll(
    unicodeWordPattern(String.raw`\b([\p{L}\p{N}][\p{L}\p{N} ._-]{0,60}?)\s+(?:uygulamasını|uygulamasini|uygulamayı|uygulamayi|programını|programini|programı|programi)\s+(?:aç|ac|kapat|başlat|baslat)(?=$|[\s.,!?])`, "gi"),
  )) {
    const appName = match[1]?.replace(/^(?:(?:lütfen|lutfen|şimdi|simdi|bana)\s+)+/i, "").trim();
    if (appName) add("app_hint", appName);
  }

  // YAPISAL YUVALAR — dile bağlı olmayan parçalar (saat, tarih, tırnak içi ad,
  // biçim, miktar). Planlayıcı istemine `- <tip>: <değer>` olarak girer ve
  // somut argüman üretmesini sağlar. Tek başına hiçbir kapıyı açmaz.
  for (const slot of extractStructuralSlots(message)) {
    add(slot.type, slot.normalized ?? slot.value);
  }

  const topic = compactText(
    message
      .replace(/https?:\/\/\S+/gi, " ")
      .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, " "),
    4_000,
  );
  if (topic) add("topic", topic);
  return entities.slice(0, 16);
}

function semanticDesktopContractFromRoute(
  routeDecision: CommandRouteDecision,
): SemanticDesktopDispatchContract | null {
  return routeDecision.taskRoute?.semanticDesktopContract ?? null;
}

function canonicalSemanticDesktopCapabilities(
  contract: SemanticDesktopDispatchContract | null,
  message = "",
): string[] {
  if (!contract) return [];
  const semanticQuery = [
    ...contract.requiredLocalContext,
    ...contract.evidence,
    message,
  ].join("\n");
  const capabilities = new Set<string>();
  for (const semanticCapability of contract.requiredSemanticCapabilities) {
    const [match] = matchDesktopCapabilitiesSemantically({
      query: [semanticCapability, semanticQuery].join("\n"),
      hints: [semanticCapability],
      intent: contract.intent,
      sideEffectLevel: contract.sideEffectLevel,
      limit: 1,
      threshold: 0.16,
    });
    if (match) capabilities.add(match.capability);
  }
  if (capabilities.size === 0) {
    for (const match of matchDesktopCapabilitiesSemantically({
      query: semanticQuery,
      intent: contract.intent,
      sideEffectLevel: contract.sideEffectLevel,
      limit: 3,
      threshold: 0.18,
    })) {
      capabilities.add(match.capability);
    }
  }
  for (const capability of contract.requiredSemanticCapabilities) {
    const canonical = canonicalRuntimeCapability(capability);
    if (canonical) capabilities.add(canonical);
  }
  if (contract.intent === "screen_action") {
    capabilities.add("desktop_operator.run");
  }
  if (contract.intent === "browser_workflow") {
    capabilities.add("browser_control");
  }
  if (contract.intent === "document_workflow") {
    if (contract.sideEffectLevel === "read") capabilities.add("document_read");
    if (
      contract.sideEffectLevel === "write" ||
      contract.sideEffectLevel === "destructive"
    ) {
      capabilities.add("document_write");
    }
  }
  if (contract.sideEffectLevel === "destructive") {
    capabilities.add("desktop_operator.run");
  }
  return [...capabilities].filter(Boolean).slice(0, 16);
}

function inferLocalContext(
  message: string,
  capabilities: string[],
  contract?: SemanticDesktopDispatchContract | null,
): string[] {
  if (contract?.requiredLocalContext.length) {
    const contexts = new Set<string>();
    for (const context of contract.requiredLocalContext) {
      const normalized = context.trim().toLocaleLowerCase("en-US");
      if (["filesystem", "file", "folder", "document"].includes(normalized)) {
        contexts.add("filesystem");
      } else if (["screen", "window", "computer"].includes(normalized)) {
        contexts.add("screen");
      } else if (["browser", "web"].includes(normalized)) {
        contexts.add("browser");
      } else if (["terminal", "shell"].includes(normalized)) {
        contexts.add("terminal");
      } else if (["app", "application"].includes(normalized)) {
        contexts.add("app");
      } else if (normalized) {
        contexts.add(normalized);
      }
    }
    return [...contexts].slice(0, 12);
  }
  const normalized = message.toLocaleLowerCase("tr-TR");
  const contexts = new Set<string>();
  if (unicodeWordPattern(String.raw`\b(masaüstü\p{L}*|masaustu\p{L}*|desktop|indirilenler\p{L}*|downloads|klasör\p{L}*|klasor\p{L}*|dosya\p{L}*|belge\p{L}*|pdf)\b`, "i").test(normalized)) {
    contexts.add("filesystem");
  }
  // Ek toleransı ŞART: `\bekran\b` "ekrandaki" ile eşleşmez ("d" ASCII harf).
  // Bu kapı yalnız bağlam etiketi üretmiyor; belge görevinden ekran
  // otomasyonunu çıkarma kararı da buna bakıyor. Kaçırırsa "ekrandaki tabloyu
  // word'e aktar" isteğinden ekran erişimi düşer.
  if (SCREEN_CONTEXT_PATTERN.test(normalized) || capabilities.includes("screen_context")) {
    contexts.add("screen");
  }
  if (BROWSER_CONTEXT_PATTERN.test(normalized) || capabilities.includes("browser_control")) {
    contexts.add("browser");
  }
  if (TERMINAL_CONTEXT_PATTERN.test(normalized) || capabilities.includes("shell_run")) {
    contexts.add("terminal");
  }
  if (capabilities.includes("email_send") || capabilities.includes("email_draft")) {
    contexts.add("email");
  }
  if (capabilities.includes("image_fetch") || capabilities.includes("presentation_write")) {
    contexts.add("filesystem");
  }
  return [...contexts];
}

function isImageEditCommand(message: string): boolean {
  const normalized = message.toLocaleLowerCase("tr-TR");
  const explicitEditVerb =
    unicodeWordPattern(String.raw`\b(düzenle|duzenle|değiştir|degistir|kaldır|kaldir|sil|ekle|düzelt|duzelt|iyileştir|iyilestir|netleştir|netlestir|kırp|kirp|retouch|edit|remove|replace|change|erase|enhance|upscale|crop)\b`, "i").test(normalized);
  const visualTarget =
    unicodeWordPattern(String.raw`\b(görsel|gorsel|resim|fotoğraf|fotograf|image|photo|arka plan|yüz|yuz|saç|sac|kıyafet|kiyafet|renk|ışık|isik|kontrast)\b`, "i").test(normalized);
  const explicitEdit = explicitEditVerb && visualTarget;
  const sourceTransform =
    unicodeWordPattern(String.raw`\b(bunu|şunu|sunu|onu|görseli|gorseli|resmi|fotoğrafı|fotografi|this|it|the image|the photo)\b.{0,80}\b(yap|çevir|cevir|dönüştür|donustur|make|turn|transform)\b`, "i").test(normalized) ||
    unicodeWordPattern(String.raw`\b(anime|çizgi film|cizgi film|sinematik|cinematic|vintage|retro|noir|fotogerçekçi|fotogercekci|photorealistic|3d|sulu boya|watercolor|yağlı boya|yagli boya|tarzında|tarzinda|stilinde)\b.{0,60}\b(yap|çevir|cevir|dönüştür|donustur|make|turn|transform)\b`, "i").test(normalized) ||
    /\b(make|turn|transform)\s+(this|it|the image|the photo)\b/iu.test(normalized);
  return explicitEdit || sourceTransform;
}

function inferKind(routeDecision: CommandRouteDecision, message: string): string {
  const semanticDesktopContract = semanticDesktopContractFromRoute(routeDecision);
  const semanticCapabilities = new Set(
    semanticDesktopContract?.requiredSemanticCapabilities ?? [],
  );
  if (semanticCapabilities.has("image_generate")) return "image_generate";
  if (semanticCapabilities.has("image_edit")) return "image_edit";
  if (semanticDesktopContract) {
    switch (semanticDesktopContract.intent) {
      case "screen_action":
        return "computer_task";
      case "file_workflow":
        return "desktop_cowork";
      case "browser_workflow":
        return "browser_task";
      case "document_workflow":
        return "document_task";
    }
  }
  const normalized = message.toLocaleLowerCase("tr-TR");
  if (routeDecision.capabilities.includes("mcp_call_tool")) return "remote_mcp";
  if (parseDirectImageFetchCommand(message)) return "image_fetch";
  if (
    routeDecision.capabilities.some((capability) =>
      capability === "image_edit" || capability === "image.edit"
    ) ||
    // Legacy offline work-order typing only. This branch is intentionally
    // after the semantic contract and never participates in server-vs-desktop
    // routing; a route contract always wins above.
    isImageEditCommand(message)
  ) return "image_edit";
  if (unicodeWordPattern(String.raw`\b(görsel|gorsel|resim|image|illustration|poster|afiş|afis)\b`, "i").test(normalized)
    && unicodeWordPattern(String.raw`\b(üret\p{L}*|uret\p{L}*|oluştur\p{L}*|olustur\p{L}*|çiz\p{L}*|ciz\p{L}*|generate|create|draw)\b`, "i").test(normalized)) return "image_generate";
  if (PRESENTATION_PATTERN.test(normalized)) return "presentation_task";
  if (routeDecision.capabilities.includes("email_send")) return "email_send";
  if (routeDecision.capabilities.includes("email_draft")) return "email_draft";
  if (unicodeWordPattern(String.raw`\b(pdf|docx|xlsx|excel|belge|doküman|dokuman|rapor)\b`, "i").test(normalized)) return "document_task";
  if (/\b(browser|chrome|safari|web|site|url|link)\b/i.test(normalized)) return "browser_task";
  if (TERMINAL_CONTEXT_PATTERN.test(normalized)) return "terminal_task";
  if (SCREEN_OR_APP_PATTERN.test(normalized)) return "computer_task";
  return "desktop_cowork";
}

function canonicalRuntimeCapability(value: string): string | null {
  const normalized = value.trim().toLocaleLowerCase("en-US").replace(/\s+/g, "_");
  const aliases: Record<string, string | null> = {
    "chat.reply": null,
    "document.read": "document_read",
    "document.write": "document_write",
    "document.export": "document_write",
    "spreadsheet.write": "spreadsheet_write",
    "table.generate": "spreadsheet_write",
    "chart.generate": "chart_generate",
    "image.read": "image_read",
    "image.generate": "image_generate",
    "image.edit": "image_edit",
    "svg.generate": "canvas_write",
    "browser.read": "browser_control",
    "desktop.file_access": "document_read",
    "desktop.runtime": "desktop_operator.run",
    filesystem_read: "document_read",
    filesystem_write: "document_write",
    screen_context: "desktop_operator.observe_screen",
    app_control: "desktop_operator.run",
    computer_control: "desktop_operator.run",
    "computer.control": "desktop_operator.run",
  };
  if (Object.prototype.hasOwnProperty.call(aliases, normalized)) return aliases[normalized] ?? null;
  if (normalized.startsWith("desktop.operator.")) {
    return `desktop_operator.${normalized.slice("desktop.operator.".length)}`;
  }
  return normalized.replaceAll(".", "_");
}

function semanticCapabilitiesFromEnvelope(
  envelope?: UnderstandingEnvelope,
): string[] {
  if (!envelope) return [];
  const capabilities = new Set<string>();
  for (const capability of envelope.required_capabilities ?? []) {
    const canonical = canonicalRuntimeCapability(capability.name);
    if (canonical) capabilities.add(canonical);
  }

  const desiredOutputKinds = new Set(
    (envelope.desired_outputs ?? []).map((output) => output.kind),
  );
  const desiredTargets = new Set(
    (envelope.desired_outputs ?? []).map((output) => output.target),
  );
  const outputFormat = String(
    envelope.output_contract?.outputFormat ??
      envelope.output_contract?.outputKind ??
      "",
  ).toLocaleLowerCase("en-US");
  const operation = String(
    envelope.output_contract?.operation ?? "",
  ).toLocaleLowerCase("en-US");
  const needsArtifact =
    desiredTargets.has("artifact") ||
    desiredTargets.has("desktop") ||
    envelope.output_contract?.requiresArtifact === true ||
    ["create", "export", "write"].includes(operation);

  if (envelope.intent.name === "research") capabilities.add("web_research");
  if (envelope.intent.name === "math") capabilities.add("math_solve");
  if (
    envelope.intent.name === "document" ||
    envelope.intent.name === "writing"
  ) {
    capabilities.add("document_write");
  }
  if (
    desiredOutputKinds.has("docx") ||
    (needsArtifact && ["docx", "document"].includes(outputFormat))
  ) {
    capabilities.add("document_write");
  }
  if (
    desiredOutputKinds.has("pdf") ||
    desiredOutputKinds.has("svg") ||
    outputFormat === "pdf" ||
    outputFormat === "svg"
  ) {
    if (outputFormat === "svg" || desiredOutputKinds.has("svg")) {
      capabilities.add("canvas_write");
    } else {
      capabilities.add("document_write");
      capabilities.delete("canvas_write");
    }
  }
  if (
    desiredOutputKinds.has("xlsx") ||
    desiredOutputKinds.has("table") ||
    outputFormat === "xlsx" ||
    outputFormat === "table"
  ) {
    capabilities.add("spreadsheet_write");
  }
  if (
    outputFormat === "pptx" ||
    outputFormat === "presentation"
  ) {
    capabilities.add("presentation_write");
    capabilities.delete("document_write");
  }
  if (desiredOutputKinds.has("chart") || outputFormat === "chart") {
    capabilities.add("chart_generate");
  }
  if (desiredOutputKinds.has("image") || outputFormat === "image") {
    capabilities.add("image_generate");
  }
  if (
    envelope.source_reference === "attachment" ||
    envelope.required_capabilities.some(
      (capability) => capability.name === "document.read",
    )
  ) {
    capabilities.add("document_read");
  }
  if (
    capabilities.has("web_research") &&
    [...capabilities].some((capability) =>
      ["document_write", "spreadsheet_write", "presentation_write", "canvas_write"].includes(capability),
    )
  ) {
    capabilities.add("text_analyze");
  }
  if (
    (envelope.intent_graph?.nodes ?? []).some((node) => node.kind === "analyze")
  ) {
    capabilities.add("text_analyze");
  }
  return [...capabilities].slice(0, 16);
}

function inferCapabilities(
  routeDecision: CommandRouteDecision,
  message: string,
  envelope?: UnderstandingEnvelope,
): string[] {
  const semanticDesktopContract = semanticDesktopContractFromRoute(routeDecision);
  const contractCapabilities =
    canonicalSemanticDesktopCapabilities(semanticDesktopContract, message);
  if (contractCapabilities.length > 0) {
    return contractCapabilities;
  }
  const routeCapabilities = new Set<string>();
  for (const capability of routeDecision.capabilities) {
    const canonical = canonicalRuntimeCapability(capability);
    if (canonical) routeCapabilities.add(canonical);
  }
  const semanticCapabilities = new Set(
    semanticCapabilitiesFromEnvelope(envelope),
  );
  const semanticAuthoritative =
    envelope !== undefined &&
    semanticCapabilities.size > 0 &&
    (
      (
        envelope.intent.source === "semantic_classifier" &&
        envelope.intent.confidence >= 0.75
      ) ||
      envelope.confidence >= 0.75
    ) &&
    (
      (envelope.required_capabilities ?? []).length > 0 ||
      (envelope.desired_outputs ?? []).some((output) => output.target !== "chat") ||
      ["document", "writing", "research", "math"].includes(envelope.intent.name) ||
      envelope.output_contract?.requiresArtifact === true
    );
  if (semanticAuthoritative) {
    return [...semanticCapabilities].slice(0, 16);
  }
  const capabilities = new Set([
    ...routeCapabilities,
    ...semanticCapabilities,
  ]);
  const normalized = message.toLocaleLowerCase("tr-TR");
  const researchRequested = unicodeWordPattern(String.raw`\b(?:araştır\p{L}*|arastir\p{L}*|research|bilgi\s+topla\p{L}*|kaynak\s+topla\p{L}*)\b`, "i").test(normalized);
  const analysisRequested = unicodeWordPattern(String.raw`\b(?:analiz\p{L}*|yorumla\p{L}*|değerlendir\p{L}*|degerlendir\p{L}*|incele\p{L}*|rapor\p{L}*|dilekçe\p{L}*|dilekce\p{L}*|savunma\p{L}*)\b`, "i").test(normalized);
  const calculationRequested = unicodeWordPattern(String.raw`\b(?:hesapla\p{L}*|hesap\p{L}*|kdv|vergi|yüzde|yuzde|%)\b`, "i").test(normalized)
    && /\d/u.test(normalized);
  const presentationRequested = PRESENTATION_PATTERN.test(normalized)
    && unicodeWordPattern(String.raw`\b(?:hazırla\p{L}*|hazirla\p{L}*|oluştur\p{L}*|olustur\p{L}*|üret\p{L}*|uret\p{L}*|yap\p{L}*|çevir\p{L}*|cevir\p{L}*|kaydet\p{L}*|save|create|prepare)\b`, "i").test(normalized);
  const directAppCommand = parseDirectDesktopAppCommand(message);
  const directImageFetch = parseDirectImageFetchCommand(message);
  const imageEditRequested =
    capabilities.has("image_edit") ||
    isImageEditCommand(message);
  const imageGenerateRequested = !imageEditRequested
    && unicodeWordPattern(String.raw`\b(görsel|gorsel|resim|image|illustration|poster|afiş|afis)\b`, "i").test(normalized)
    && unicodeWordPattern(String.raw`\b(üret\p{L}*|uret\p{L}*|oluştur\p{L}*|olustur\p{L}*|çiz\p{L}*|ciz\p{L}*|generate|create|draw)\b`, "i").test(normalized);
  if (directAppCommand) {
    capabilities.add(directAppCommand.capability);
    capabilities.delete("desktop_operator.run");
  }
  if (directImageFetch) {
    capabilities.add("image_fetch");
    capabilities.delete("desktop_operator.run");
  }
  if (imageEditRequested) {
    capabilities.add("image_edit");
    capabilities.delete("image_read");
    capabilities.delete("canvas_write");
    capabilities.delete("desktop_operator.run");
  } else if (imageGenerateRequested) {
    capabilities.add("image_generate");
    capabilities.delete("canvas_write");
    capabilities.delete("desktop_operator.run");
  }
  if (researchRequested) capabilities.add("web_research");
  if (calculationRequested) capabilities.add("math_solve");
  if (presentationRequested) {
    capabilities.add("presentation_write");
    capabilities.delete("desktop_operator.run");
  }
  // FİİL TEK BAŞINA YAZICI YETENEĞİ DOĞURAMAZ.
  //
  // "Masaüstünde kütüphane adlı klasör oluştur" cümlesindeki `oluştur` bu dala
  // düşüyor ve nesnenin ne olduğu sorulmadan `document_write` ekleniyordu.
  // Sonuç canlıda ölçüldü (2026-08-13, görev cc5fed45): klasör istendi, görev
  // "DOCX oluşturuldu" diye bitti.
  //
  // `inferExpectedOutputs` bu tahmini zaten ZORUNLU saymıyor (aşağıdaki
  // `artifactGroundedInRequest` notu), ama `requiredCapabilities` tahmini
  // taşımaya devam ediyor ve masaüstünün plan tamamlayıcısı o listeyi
  // sözleşme sayıp yazıcı adımını ekliyor. Yani ilk düzeltme zincirin
  // yalnızca bir halkasını kapatmış.
  //
  // Klasör isteğinin kendi tanıyıcısı var; ortada belge nesnesi de anılmadıysa
  // yazıcı tahmininin hiçbir dayanağı yok.
  // BURADA EK TOLERANSI KASITLI OLARAK YOK.
  //
  // Kontrol NEGATİF: "içinde belge geçmiyorsa yalnız klasör isteği". Ek
  // toleransı eklenirse "masaüstünde rapor klasörü oluştur" isteğinde "rapor"
  // eşleşir, `folderOnlyRequest` yanlışlıkla false olur ve klasör oluşturma
  // yolu kapanır. Negatif kapılarda geniş eşleşme, dar eşleşmeden PAHALIDIR.
  const folderOnlyRequest =
    parseDirectFolderCreateCommand(message) !== null &&
    !unicodeWordPattern(
      String.raw`\b(dosya|belge|rapor|not|metin|yazı|yazi|pdf|docx|xlsx|pptx|csv|svg)\b`,
      "i",
    ).test(normalized);
  if (!folderOnlyRequest && unicodeWordPattern(String.raw`\b(kaydet\p{L}*|save|yaz\p{L}*|çıkar\p{L}*|cikar\p{L}*|hazırla\p{L}*|hazirla\p{L}*|oluştur\p{L}*|olustur\p{L}*|düzenle\p{L}*|duzenle\p{L}*|export|dışa aktar|disa aktar)\b`, "i").test(normalized)) {
    if (presentationRequested) capabilities.add("presentation_write");
    else if (unicodeWordPattern(String.raw`\b(xlsx|excel|çalışma sayfası|calisma sayfasi)\b`, "i").test(normalized)) capabilities.add("spreadsheet_write");
    else if (unicodeWordPattern(String.raw`\b(pdf|svg|canvas|görsel|gorsel)\b`, "i").test(normalized)) capabilities.add("canvas_write");
    else capabilities.add("document_write");
  }
  if (
    analysisRequested &&
    (
      capabilities.has("document_read") ||
      capabilities.has("web_research") ||
      capabilities.has("math_solve") ||
      capabilities.has("document_write") ||
      capabilities.has("spreadsheet_write") ||
      capabilities.has("presentation_write")
    )
  ) {
    capabilities.add("text_analyze");
  }
  if (
    unicodeWordPattern(String.raw`\b(browser|chrome|safari|site|url|link|tarayıcı|tarayici)\b`, "i").test(normalized)
    || (/\bweb\b/iu.test(normalized) && !researchRequested)
    || /https?:\/\//i.test(message)
  ) {
    capabilities.add("browser_control");
  }
  if (TERMINAL_CONTEXT_PATTERN.test(normalized)) capabilities.add("shell_run");
  if (unicodeWordPattern(String.raw`\b(ekran|screenshot|görüntü|goruntu)\b`, "i").test(normalized)) capabilities.add("desktop_operator.observe_screen");
  return [...capabilities].slice(0, 16);
}

function inferExpectedOutputs(
  message: string,
  capabilities: string[],
  envelope?: UnderstandingEnvelope,
): DesktopWorkOrder["expectedOutputs"] {
  const outputs: DesktopWorkOrder["expectedOutputs"] = [{ kind: "chat_result", format: "elyan_blocks.v2", required: true }];
  const addOutput = (output: DesktopWorkOrder["expectedOutputs"][number]) => {
    if (!outputs.some((candidate) => candidate.kind === output.kind && candidate.required === output.required)) {
      outputs.push(output);
    }
  };
  const normalized = message.toLocaleLowerCase("tr-TR");
  if (parseDirectImageFetchCommand(message)) {
    addOutput({ kind: "artifact", format: "artifact_reference", required: true });
    addOutput({ kind: "file_update", format: "state_readback", required: true });
  }
  if (
    isImageEditCommand(message) ||
    (
      unicodeWordPattern(String.raw`\b(görsel|gorsel|resim|fotoğraf|fotograf|image|photo)\b`, "i").test(normalized) &&
      unicodeWordPattern(String.raw`\b(üret\p{L}*|uret\p{L}*|oluştur\p{L}*|olustur\p{L}*|çiz\p{L}*|ciz\p{L}*|generate|create|draw)\b`, "i").test(normalized)
    )
  ) {
    addOutput({ kind: "artifact", format: "image", required: true });
    addOutput({ kind: "file_update", format: "state_readback", required: true });
  }
  const presentationRequested = PRESENTATION_PATTERN.test(normalized)
    && unicodeWordPattern(String.raw`\b(?:hazırla\p{L}*|hazirla\p{L}*|oluştur\p{L}*|olustur\p{L}*|üret\p{L}*|uret\p{L}*|yap\p{L}*|çevir\p{L}*|cevir\p{L}*|kaydet\p{L}*|save|create|prepare)\b`, "i").test(normalized);
  if (presentationRequested) {
    addOutput({ kind: "artifact", format: "artifact_reference", required: true });
    addOutput({ kind: "file_update", format: "state_readback", required: true });
  }
  const typedArtifactRequested = envelope?.desired_outputs.some(
    (output) => output.target === "artifact" || ["pdf", "docx", "xlsx", "svg", "artifact"].includes(output.kind),
  ) ?? false;
  const semanticArtifactRequested = capabilities.some((capability) =>
    [
      "document_write",
      "spreadsheet_write",
      "presentation_write",
      "canvas_write",
      "image_generate",
      "image_edit",
      "chart_generate",
    ].includes(capability),
  );
  const explicitArtifactCreation =
    DOCUMENT_NOUN_PATTERN.test(normalized) &&
    unicodeWordPattern(String.raw`\b(oluştur|olustur|hazırla|hazirla|dönüştür|donustur|export|dışa aktar|disa aktar|kaydet|yap)\b`, "i").test(normalized);
  // Bir TAHMİN, zorunlu çıktı beyanı üretemez.
  //
  // `typedArtifactRequested` kullanıcının beyan ettiği çıktıdan,
  // `explicitArtifactCreation` cümlenin kendisinden gelir — ikisi de isteğe
  // dayanır ve zorunluluk yazabilir. `semanticArtifactRequested` ise yalnız
  // router'ın YETENEK TAHMİNİNE bakar.
  //
  // Canlı kanıt (replay: klasor-olustur): "Masaüstünde Cabir adında klasör
  // oluştur" turunda tahmine `document_write` karışmış, o da "artifact
  // zorunlu" beyanı üretmişti. Doğru plan (`make_directory`) doğrulayıcıda
  // "required artifact has no artifact-producing capability" ile reddediliyor;
  // daha kötüsü, planlayıcı bu sözleşmeyi tatmin etmek için istenmemiş bir
  // belge üretmeye itiliyordu. Klasör dosya üretmez.
  //
  // Tahminden gelen sinyal korunuyor ama ZORUNLU değil: planlayıcı artefaktın
  // muhtemel olduğunu görür, doğrulayıcı onu şart koşmaz.
  const artifactGroundedInRequest =
    typedArtifactRequested || explicitArtifactCreation;
  if (artifactGroundedInRequest) {
    addOutput({ kind: "artifact", format: "artifact_reference", required: true });
  } else if (semanticArtifactRequested) {
    addOutput({ kind: "artifact", format: "artifact_reference", required: false });
  }
  if (
    semanticArtifactRequested ||
    unicodeWordPattern(String.raw`\b(kaydet|save|düzenle|duzenle|yaz|çıkar|cikar|oluştur|olustur|hazırla|hazirla|üret|uret)\b`, "i").test(normalized)
  ) {
    addOutput({ kind: "file_update", format: "state_readback", required: true });
  }
  if (unicodeWordPattern(String.raw`\b(browser|chrome|safari|site|url|link|tarayıcı|tarayici)\b`, "i").test(normalized)) {
    addOutput({ kind: "browser_state", format: "tool_result", required: false });
  }
  return outputs;
}

function artifactContractForCapabilities(
  capabilities: string[],
  requestedFormat?: string | null,
): {
  desiredKind: UnderstandingEnvelope["desired_outputs"][number]["kind"];
  outputKind: string;
  format: string;
  selected: string;
  surface: NonNullable<
    UnderstandingEnvelope["tool_skill_decision"]
  >["surface"];
} | null {
  if (capabilities.includes("presentation_write")) {
    return {
      desiredKind: "artifact",
      outputKind: "presentation",
      format: "pptx",
      selected: "presentation.write",
      surface: "document",
    };
  }
  if (capabilities.includes("spreadsheet_write")) {
    return {
      desiredKind: "xlsx",
      outputKind: "spreadsheet",
      format: "xlsx",
      selected: "spreadsheet.write",
      surface: "spreadsheet",
    };
  }
  if (capabilities.includes("canvas_write")) {
    return {
      desiredKind: "pdf",
      outputKind: "artifact",
      format: "pdf",
      selected: "canvas.write",
      surface: "document",
    };
  }
  if (capabilities.includes("document_write")) {
    const format =
      requestedFormat?.toLocaleLowerCase("en-US") === "pdf"
        ? "pdf"
        : "docx";
    return {
      desiredKind: format,
      outputKind: "document",
      format,
      selected: "document.write",
      surface: "document",
    };
  }
  if (capabilities.includes("chart_generate")) {
    return {
      desiredKind: "chart",
      outputKind: "chart",
      format: "chart",
      selected: "chart.generate",
      surface: "chart",
    };
  }
  if (
    capabilities.includes("image_generate") ||
    capabilities.includes("image_edit")
  ) {
    return {
      desiredKind: "image",
      outputKind: "image",
      format: "image",
      selected: capabilities.includes("image_edit")
        ? "image.edit"
        : "image.generate",
      surface: "image",
    };
  }
  return null;
}

function reconcileSemanticExecutionContract(
  envelope: UnderstandingEnvelope | undefined,
  capabilities: string[],
): {
  desiredOutputs: UnderstandingEnvelope["desired_outputs"] | undefined;
  outputContract: UnderstandingEnvelope["output_contract"] | undefined;
  toolSkillDecision: UnderstandingEnvelope["tool_skill_decision"] | undefined;
} {
  if (!envelope) {
    return {
      desiredOutputs: undefined,
      outputContract: undefined,
      toolSkillDecision: undefined,
    };
  }
  const artifact = artifactContractForCapabilities(
    capabilities,
    envelope.output_contract?.outputFormat ??
      envelope.desired_outputs.find((output) => output.format)?.format,
  );
  if (!artifact) {
    return {
      desiredOutputs: envelope.desired_outputs,
      outputContract: envelope.output_contract,
      toolSkillDecision: envelope.tool_skill_decision,
    };
  }
  const desiredOutputs = [...envelope.desired_outputs];
  if (
    !desiredOutputs.some(
      (output) =>
        output.target === "artifact" ||
        output.target === "desktop" ||
        output.kind === artifact.desiredKind ||
        output.format === artifact.format,
    )
  ) {
    desiredOutputs.push({
      kind: artifact.desiredKind,
      format: artifact.format,
      target: "desktop",
      confidence: Math.max(0.8, envelope.intent.confidence),
      constraints: [],
    });
  }
  const outputContract: UnderstandingEnvelope["output_contract"] = {
    ...envelope.output_contract,
    pageCount: envelope.output_contract?.pageCount ?? null,
    sourceReference:
      envelope.output_contract?.sourceReference ??
      envelope.source_reference ??
      "current_prompt",
    operation: "write",
    outputKind: artifact.outputKind,
    outputFormat: artifact.format,
    requiresArtifact: true,
    confidence: Math.max(
      0.8,
      envelope.output_contract?.confidence ?? 0,
      envelope.intent.confidence,
    ),
    reasons: [
      ...new Set([
        ...(envelope.output_contract?.reasons ?? []),
        `semantic_capability:${artifact.selected}`,
      ]),
    ],
  };
  const currentDecision = envelope.tool_skill_decision;
  const toolSkillDecision =
    currentDecision?.surface === "chat" ||
    currentDecision?.selected === "chat.reply"
      ? {
          ...currentDecision,
          selected: artifact.selected,
          surface: artifact.surface,
          workload: currentDecision.workload ?? "desktop_handoff",
          confidence: Math.max(0.8, currentDecision.confidence),
          reasons: [
            ...new Set([
              ...currentDecision.reasons,
              `semantic_capability:${artifact.selected}`,
            ]),
          ],
        }
      : currentDecision;
  return { desiredOutputs, outputContract, toolSkillDecision };
}

function semanticSuccessCriteria(
  expectedOutputs: DesktopWorkOrder["expectedOutputs"],
  verificationRules: DesktopWorkOrder["verificationRules"],
  envelope?: UnderstandingEnvelope,
): string[] {
  const criteria = new Set<string>();
  for (const criterion of envelope?.success_criteria ?? []) {
    const description = compactText(criterion.description, 240);
    if (description) criteria.add(description);
  }
  for (const output of expectedOutputs) {
    if (!output.required) continue;
    if (output.kind === "chat_result") {
      criteria.add("User-visible result is delivered through Elyan blocks/task result.");
    } else if (output.kind === "artifact") {
      criteria.add(`Required artifact is produced and returned as ${output.format}.`);
    } else if (output.kind === "file_update") {
      criteria.add("File/output update is backed by artifact or state readback evidence.");
    } else {
      criteria.add(`${output.kind} is verified with tool or state evidence.`);
    }
  }
  for (const rule of verificationRules) {
    if (rule.description) criteria.add(rule.description);
  }
  return [...criteria].slice(0, 10);
}

function forbiddenCapabilitiesForWorkOrder(input: {
  workType: DesktopWorkOrder["workType"];
  capabilities: string[];
  autonomy?: DesktopWorkOrder["autonomy"];
  envelope?: UnderstandingEnvelope;
}): string[] {
  const forbidden = new Set<string>();
  if (input.autonomy) {
    for (const capability of [
      "shell_run",
      "shell_session_run",
      "delete_calendar_event",
      "email_send",
      "send_whatsapp_message",
      "file_patch",
      "git_commit",
      "git_branch",
      "desktop_operator.execute_action",
      "desktop_operator.run",
    ]) {
      if (!input.autonomy.allowedCapabilities.includes(capability)) {
        forbidden.add(capability);
      }
    }
  }
  if (
    input.workType === "data_workflow" &&
    !input.capabilities.some((capability) =>
      capability === "desktop_operator.observe_screen" ||
      capability === "analyze_screen"
    )
  ) {
    forbidden.add("desktop_operator.execute_action");
    forbidden.add("desktop_operator.run");
  }
  if (input.envelope?.privacy_routing?.maySendPrivateContextToServer === false) {
    forbidden.add("private_context_to_web_research");
  }
  return [...forbidden].slice(0, 20);
}

function ambiguityPolicyForWorkOrder(
  envelope: UnderstandingEnvelope | undefined,
  workType: DesktopWorkOrder["workType"],
): NonNullable<DesktopWorkOrder["semanticGoal"]>["ambiguityPolicy"] {
  if ((envelope?.ambiguities ?? []).length > 0) return "ask";
  if (envelope?.risk.side_effect) return "fail_closed";
  return workType === "screen_action" || workType === "mixed" ? "safe_assumption" : "safe_assumption";
}

function failureTaxonomy(): NonNullable<DesktopWorkOrder["failurePolicy"]>["taxonomy"] {
  // TEK KAYNAK: contracts/failure-taxonomy.json. Burada ikinci bir liste
  // tutmak, masaüstündeki metin-eşleşmeli merdivenle sürüklenmenin ta
  // kendisiydi (canlı, 2026-08-21: kapsam uyuşmazlığı güvenlik reddi sanıldı,
  // tur yarım yan etkiyle öldü).
  return failureTaxonomyEntries();
}

function inferCalculationExpression(message: string): string {
  const amounts: string[] = [];
  for (const match of message.matchAll(/(?<![%\p{L}\p{N}])(\d+(?:[.,]\d+)?)\s*(?:tl|try|₺|usd|eur)\b/giu)) {
    const amount = String(match[1] ?? "").replace(",", ".");
    if (amount && !amounts.includes(amount)) amounts.push(amount);
  }
  const percentMatch = message.match(/(?:%|yüzde|yuzde)\s*(\d+(?:[.,]\d+)?)/iu);
  if (amounts.length > 0 && percentMatch) {
    const percent = Number(String(percentMatch[1] ?? "").replace(",", "."));
    if (Number.isFinite(percent)) {
      const multiplier = percent / 100;
      const normalizedMultiplier = Number.isInteger(multiplier) ? String(multiplier) : String(multiplier);
      return `(${amounts.slice(0, 12).join("+")})*${normalizedMultiplier}`;
    }
  }
  const numericExpression = message.match(/(\d+(?:[.,]\d+)?(?:\s*[-+*/]\s*\d+(?:[.,]\d+)?)+)/u);
  return numericExpression ? String(numericExpression[1]).replaceAll(",", ".") : "";
}

function inferTextAnalysisMode(message: string): "professional" | "legal" | "medical" | "accounting" | "technical" | "student" {
  const normalized = message.toLocaleLowerCase("tr-TR");
  if (unicodeWordPattern(String.raw`\b(avukat\p{L}*|hukuk\p{L}*|dava\p{L}*|dilekçe\p{L}*|dilekce\p{L}*|savunma\p{L}*|tahliye\p{L}*|mevzuat\p{L}*|emsal\p{L}*)\b`, "i").test(normalized)) {
    return "legal";
  }
  if (unicodeWordPattern(String.raw`\b(doktor\p{L}*|hekim\p{L}*|hasta\p{L}*|tahlil\p{L}*|laboratuvar\p{L}*|kan\s+sonucu|hb|ferritin|b12|glukoz|kolesterol)\b`, "i").test(normalized)) {
    return "medical";
  }
  if (unicodeWordPattern(String.raw`\b(muhasebe\p{L}*|muhasebeci\p{L}*|fatura\p{L}*|kdv|vergi\p{L}*|tevkifat\p{L}*|bilanço\p{L}*|bilanco\p{L}*|gelir\s+tablosu)\b`, "i").test(normalized)) {
    return "accounting";
  }
  if (unicodeWordPattern(String.raw`\b(öğrenci\p{L}*|ogrenci\p{L}*|ödev\p{L}*|odev\p{L}*|ders\p{L}*|tez\p{L}*|sunum\p{L}*|slayt\p{L}*|okul\p{L}*)\b`, "i").test(normalized)) {
    return "student";
  }
  if (unicodeWordPattern(String.raw`\b(mühendis\p{L}*|muhendis\p{L}*|teknik\p{L}*|optimiz\p{L}*|karar\s+değişken\p{L}*|karar\s+degisken\p{L}*|kısıt\p{L}*|kisit\p{L}*|amaç\s+fonksiyon\p{L}*|amac\s+fonksiyon\p{L}*)\b`, "i").test(normalized)) {
    return "technical";
  }
  return "professional";
}

function safeArtifactFilename(value: string): string {
  return (
    value
      .toLocaleLowerCase("tr-TR")
      .replace(/[ıİ]/g, "i")
      .replace(/[ğĞ]/g, "g")
      .replace(/[üÜ]/g, "u")
      .replace(/[şŞ]/g, "s")
      .replace(/[öÖ]/g, "o")
      .replace(/[çÇ]/g, "c")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 64) || "elyan-belge"
  );
}

function explicitResourceRoot(value: string): string | null {
  const normalized = value.trim().replaceAll("\\", "/");
  if (!normalized || normalized.includes("{{steps.")) return null;
  if (normalized === "workspace" || normalized.startsWith("workspace/")) {
    return "workspace";
  }
  if (normalized === "~/Desktop" || normalized.startsWith("~/Desktop/")) {
    return "~/Desktop";
  }
  if (
    normalized === "~/Downloads" ||
    normalized.startsWith("~/Downloads/")
  ) {
    return "~/Downloads";
  }
  const lastSlash = normalized.lastIndexOf("/");
  if (
    normalized.startsWith("/") ||
    /^[A-Za-z]:\//u.test(normalized) ||
    normalized.startsWith("//")
  ) {
    return lastSlash > 0 ? normalized.slice(0, lastSlash) : normalized;
  }
  return null;
}

function buildSteps(input: {
  message: string;
  title: string;
  summary: string;
  kind: string;
  capabilities: string[];
  entities: DesktopWorkOrder["entities"];
  envelope?: UnderstandingEnvelope;
  inputRefs?: string[];
}): DesktopWorkOrderStep[] {
  const steps: DesktopWorkOrderStep[] = [];
  const url = input.entities.find((entity) => entity.type === "url")?.value;
  const fileHint = input.entities.find((entity) => entity.type === "file_hint")?.value;
  const appHint = input.entities.find((entity) => entity.type === "app_hint")?.value;
  // The direct registry parser is a deliberately narrow degraded fallback
  // for one-step app lifecycle commands. The semantic route remains the
  // authority for general tasks, but once this exact command is accepted its
  // normalized app name must reach the concrete step; otherwise
  // `Chrome u kapat` becomes `close_app` with `{}` and is incorrectly marked
  // as a pending heuristic plan.
  const directAppCommand = parseDirectDesktopAppCommand(input.message);
  const resolvedAppHint = directAppCommand?.appName || appHint;
  const topic = input.entities.find((entity) => entity.type === "topic")?.value ?? "";
  const directImageFetch = parseDirectImageFetchCommand(topic);
  const directFolderCreate = parseDirectFolderCreateCommand(topic || input.title);
  if (directFolderCreate) {
    const folderLabel = directFolderCreate.folderName || "Yeni Klasör";
    steps.push({
      id: "step_make_directory",
      capability: "make_directory",
      description: `"${folderLabel}" klasörü ${directFolderCreate.locationHint} içinde oluşturulacak.`,
      args: {
        path: `${directFolderCreate.locationHint}/${folderLabel}`,
      },
    });
    return steps;
  }
  const researchRequested = input.capabilities.includes("web_research");
  const calculationRequested = input.capabilities.includes("math_solve");
  const analysisRequested = input.capabilities.includes("text_analyze");
  const desktopArtifactTarget =
    input.envelope?.desired_outputs.some(
      (output) => output.target === "desktop",
    ) ??
    unicodeWordPattern(
      String.raw`\b(?:masaüstü\p{L}*|masaustu\p{L}*|desktop)\b`,
      "i",
    ).test(topic);
  const semanticBrief = compactText([
    input.envelope?.intent.topic,
    ...(input.envelope?.entities ?? []).map((entity) => `${entity.type}: ${entity.normalized ?? entity.value}`),
    ...(input.envelope?.constraints ?? [])
      .filter((constraint) => constraint.explicit)
      .map((constraint) => `${constraint.kind}: ${JSON.stringify(constraint.value)}`),
    ...(input.envelope?.success_criteria ?? []).map((criterion) => criterion.description),
  ].filter(Boolean).join("\n"), 3_000) || topic || input.summary;
  // Explicit read-only runtime capabilities are already an authoritative
  // selection from the mobile manifest. Materialize them as concrete steps so
  // a desktop task does not become an empty pending plan when the semantic
  // planner or local agent model is unavailable. `run_skill` stays deferred
  // until a validated skillId is present; inventing one here would be less
  // safe than letting the planner select from the runtime skill catalog.
  if (input.capabilities.includes("retrieve_context")) {
    steps.push({
      id: "step_retrieve_context",
      capability: "retrieve_context",
      description: "İzinli yerel bağlam görevin amacıyla eşleştirilecek.",
      args: {
        query: semanticBrief,
        limit: 6,
      },
    });
  }
  if (input.capabilities.includes("sys_info")) {
    steps.push({
      id: "step_sys_info",
      capability: "sys_info",
      description: "Masaüstü sistem durumu salt-okunur olarak alınacak.",
      args: { query: "all" },
    });
  }
  for (const capability of ["open_app", "close_app"] as const) {
    if (!input.capabilities.includes(capability)) continue;
    steps.push({
      id: `step_${capability}`,
      capability,
      description: resolvedAppHint
        ? `${resolvedAppHint} ${capability === "open_app" ? "açılacak" : "kapatılacak"}.`
        : `Uygulama ${capability === "open_app" ? "açma" : "kapatma"} isteği yerelde çözümlenecek.`,
      args: resolvedAppHint ? { app_name: resolvedAppHint } : {},
    });
  }
  if (input.capabilities.includes("image_fetch") && directImageFetch) {
    steps.push({
      id: "step_image_fetch",
      capability: "image_fetch",
      description: `${directImageFetch.query} için herkese açık bir görsel indirilip dosya varlığı doğrulanacak.`,
      args: {
        query: directImageFetch.query,
        destination: directImageFetch.destination,
        count: directImageFetch.count,
      },
    });
  }
  for (const capability of ["image_generate", "image_edit"] as const) {
    if (!input.capabilities.includes(capability)) continue;
    steps.push({
      id: `step_${capability}`,
      capability,
      description: capability === "image_edit"
        ? "Kullanıcının kaynak görseli yüksek kalite korunarak istenen şekilde düzenlenecek."
        : "Kullanıcının istemi yüksek kaliteli bir görsele dönüştürülecek.",
      args: {
        prompt: topic || semanticBrief,
        imageSize: /\b4k\b/iu.test(topic) ? "4K" : "2K",
        ...(capability === "image_edit" && input.inputRefs?.length
          ? { inputRefs: input.inputRefs }
          : {}),
      },
    });
  }
  if (researchRequested) {
    steps.push({
      id: "step_web_research",
      capability: "web_research",
      description: "Konu güvenilir web kaynaklarından araştırılacak ve kaynak özeti hazırlanacak.",
      args: { query: topic || semanticBrief },
    });
  }
  if (calculationRequested) {
    const expression = inferCalculationExpression(topic || input.summary);
    steps.push({
      id: "step_math_solve",
      capability: "math_solve",
      description: expression ? "Sayısal hesaplama yerel olarak çözülecek." : "Hesaplama gereksinimi yerel matematik aracıyla çözülecek.",
      args: expression ? { expression, mode: "evaluate" } : { expression: topic || semanticBrief, mode: "evaluate" },
    });
  }
  if (input.capabilities.includes("browser_control")) {
    // "Chrome'u kapat/aç" gibi salt uygulama-yaşam-döngüsü görevlerinde URL yoksa
    // genel "search" adımı ekleme — kapatılan tarayıcıyı geri açıp görevi bozuyor.
    const appLifecycleOnly = !url && steps.some(
      (step) => step.capability === "open_app" || step.capability === "close_app",
    );
    if (!appLifecycleOnly) {
      steps.push({
        id: "step_browser",
        capability: "browser_control",
        description: url ? `${url} adresi açılacak.` : "Tarayıcı bağlamı görev için hazırlanacak.",
        args: url ? { action: "open_url", url } : { action: "search", query: input.summary },
      });
    }
  }
  if (input.capabilities.includes("document_read") && (fileHint || input.capabilities.includes("text_analyze"))) {
    steps.push({
      id: "step_document_read",
      capability: "document_read",
      description: fileHint
        ? "Belge yerel ve izinli çalışma alanında okunacak."
        : "Kullanıcının paylaştığı özel metin/veri bağlamı yerelde okunacak.",
      args: fileHint
        ? { path: fileHint, mode: "read" }
        : { text: semanticBrief, mode: "read" },
    });
  }
  const upstreamStepIds = steps
    .filter((step) => ["step_web_research", "step_math_solve", "step_document_read"].includes(step.id))
    .map((step) => step.id);
  if (analysisRequested) {
    const sourceContext =
      upstreamStepIds.length > 0
        ? [
            upstreamStepIds.includes("step_document_read")
              ? "Okunan bağlam: {{steps.step_document_read.output}}"
              : "",
            upstreamStepIds.includes("step_math_solve")
              ? "Hesap sonucu: {{steps.step_math_solve.output}}"
              : "",
            upstreamStepIds.includes("step_web_research")
              ? "Araştırma bağlamı: {{steps.step_web_research.output}}"
              : "",
          ]
            .filter(Boolean)
            .join("\n\n")
        : semanticBrief;
    steps.push({
      id: "step_text_analyze",
      capability: "text_analyze",
      description: "Toplanan bağlam teslim çıktısı için analiz edilecek.",
      args: {
        prompt: semanticBrief,
        sourceContext,
        mode: inferTextAnalysisMode(`${input.title}\n${input.summary}\n${semanticBrief}`),
      },
      ...(upstreamStepIds.length > 0 ? { dependsOn: upstreamStepIds } : {}),
    });
  }
  for (const capability of ["document_write", "spreadsheet_write", "presentation_write", "canvas_write"] as const) {
    if (!input.capabilities.includes(capability)) continue;
    const args: Record<string, unknown> = {
      title: compactText(input.title, 160),
      prompt: semanticBrief,
    };
    if (!researchRequested) args.sourceContext = semanticBrief;
    if (analysisRequested) {
      args.sourceContext = "Analiz bağlamı: {{steps.step_text_analyze.output}}";
    } else if (researchRequested) {
      args.sourceContext = "Araştırma bağlamı: {{steps.step_web_research.output}}";
    } else if (calculationRequested) {
      args.sourceContext = "Hesap sonucu: {{steps.step_math_solve.output}}";
    }
    if (desktopArtifactTarget) {
      const extension =
        capability === "presentation_write"
          ? "pptx"
          : capability === "spreadsheet_write"
            ? "xlsx"
            : capability === "canvas_write"
              ? input.envelope?.output_contract?.outputFormat === "svg"
                ? "svg"
                : "pdf"
              : input.envelope?.output_contract?.outputFormat === "pdf"
                ? "pdf"
                : "docx";
      args.outputPath = `~/Desktop/${safeArtifactFilename(input.title)}.${extension}`;
    }
    if (capability === "canvas_write") {
      const wantsPdf = input.envelope?.desired_outputs.some((output) => output.kind === "pdf") ?? false;
      if (wantsPdf) args.output_format = "pdf";
    }
    steps.push({
      id: `step_${capability}`,
      capability,
      description: "Tipli kullanıcı gereksinimlerinden deterministik çıktı üretilecek.",
      args,
      ...(analysisRequested
        ? { dependsOn: ["step_text_analyze"] }
        : researchRequested
          ? { dependsOn: ["step_web_research"] }
          : calculationRequested
            ? { dependsOn: ["step_math_solve"] }
            : {}),
    });
  }
  if (input.capabilities.includes("chart_generate") && fileHint) {
    steps.push({
      id: "step_chart_generate",
      capability: "chart_generate",
      description: "Veri kaynağından grafik artifact'i üretilecek.",
      args: {
        path: fileHint,
        chartType: "auto",
      },
      ...(analysisRequested
        ? { dependsOn: ["step_text_analyze"] }
        : {}),
    });
  }
  if (input.capabilities.includes("desktop_operator.run")) {
    steps.push({
      id: "step_desktop_execute",
      capability: "desktop_operator.run",
      description: "Yerel masaüstü bağlamında görev yürütülecek.",
      args: {
        action: "run",
        goal: semanticBrief,
        workOrderKind: input.kind,
      },
    });
  }
  return steps.slice(0, MAX_WORK_ORDER_STEPS);
}

/**
 * Read the unattended envelope out of task metadata, fail-closed.
 *
 * Anything malformed yields `undefined`, which means "attended" — the strict
 * ceiling is simply not applied to a normal user-initiated task. The unsafe
 * direction would be inventing an autonomy envelope, and that cannot happen
 * here: every field must be present and well-formed.
 */
export function readAutonomyEnvelope(
  metadata: Record<string, unknown> | null | undefined,
): DesktopWorkOrder["autonomy"] | undefined {
  const raw = metadata?.autonomy;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  if (record.mode !== "night_watch" || record.unattended !== true) return undefined;
  const jobId = typeof record.jobId === "string" ? record.jobId.trim() : "";
  if (!jobId) return undefined;
  const allowedCapabilities = Array.isArray(record.allowedCapabilities)
    ? record.allowedCapabilities
        .map((value) => String(value ?? "").trim())
        .filter(Boolean)
        .slice(0, 40)
    : [];
  if (allowedCapabilities.length === 0) return undefined;
  const evidenceRaw =
    record.evidence && typeof record.evidence === "object" && !Array.isArray(record.evidence)
      ? (record.evidence as Record<string, unknown>)
      : null;
  const evidence = {
    source: typeof evidenceRaw?.source === "string" ? evidenceRaw.source : "",
    ref: typeof evidenceRaw?.ref === "string" ? evidenceRaw.ref : "",
    note: typeof evidenceRaw?.note === "string" ? evidenceRaw.note : "",
  };
  if (!evidence.source || !evidence.ref) return undefined;
  return {
    mode: "night_watch",
    unattended: true,
    jobId,
    allowedCapabilities,
    evidence,
  };
}

export function buildDesktopWorkOrder(input: {
  message: string;
  title: string;
  routeDecision: CommandRouteDecision;
  requestedCapabilities: string[];
  understandingEnvelope?: UnderstandingEnvelope;
  remoteMcpSelection?: RemoteMcpSelectionMetadata;
  source?: "mobile_chat_dispatch" | "backend_task_route";
  inputRefs?: string[];
  dispatchOptimization?: DesktopWorkOrder["planPreview"]["dispatchOptimization"];
  responsiveExecution?: DesktopWorkOrder["planPreview"]["responsiveExecution"];
  livenessGuard?: DesktopWorkOrder["planPreview"]["livenessGuard"];
  autonomy?: DesktopWorkOrder["autonomy"];
  desktopPlanningEvidence?: NonNullable<
    DesktopWorkOrder["contextPack"]
  >["desktopPlanningEvidence"];
}): DesktopWorkOrder {
  const message = compactText(input.message, 4_000);
  const directRegistryCommand = parseDirectDesktopAppCommand(message);
  const semanticDesktopContract = semanticDesktopContractFromRoute(
    input.routeDecision,
  );
  const kind = inferKind(input.routeDecision, message);
  const capabilities = [
    ...new Set([
      ...inferCapabilities(
        {
          ...input.routeDecision,
          capabilities: [...input.routeDecision.capabilities, ...input.requestedCapabilities],
        },
        message,
        input.understandingEnvelope,
      ),
      // A successfully parsed direct command is a bounded registry fallback,
      // not a free-form model decision. It prevents a low-confidence semantic
      // envelope from dropping the one capability needed for the exact local
      // action while leaving advice/questions outside this path.
      ...(directRegistryCommand ? [directRegistryCommand.capability] : []),
    ]),
  ];
  // MENÜ, HEDEFLE ÇELİŞMEMELİ.
  //
  // Canlı arıza (görev fd3acf73): "masaüstüne kediler hakkında rapor hazırla ve
  // kaydet" isteğinde `goal.kind = document_task` doğru çıktı, ama anlamsal
  // sözleşme `requiredSemanticCapabilities = [desktop_operator.run,
  // desktop_operator_run, document_read]` verdi — hiçbiri belge YAZMIYOR.
  // Menüde yazıcı olmayınca planlayıcı elindeki tek "dış dünya" aracına
  // uzandı: tarayıcıyı sürüp Wikipedia'ya gitmek. Bilgi görevinde en kırılgan
  // yol, çünkü menü başka bir şey sunmuyordu.
  //
  // (`routing-policy` boş kapasite listesinde varsayılan olarak
  // `["desktop_operator.run"]` koyuyor — "hiçbir şey bilmiyorsak ekranı sür".)
  //
  // Burada iki gerçek aynı anda elimizde: hedefin türü ve önerilen yetenekler.
  // Çelişiyorlarsa hedef kazanır.
  const writerForKind =
    kind === "document_task"
      ? "document_write"
      : kind === "presentation_task"
        ? "presentation_write"
        : null;
  if (writerForKind && !capabilities.includes(writerForKind)) {
    capabilities.push(writerForKind);
  }
  // Ekran otomasyonu belge görevinden ÇIKARILIR — ama yalnız istekte ekran,
  // pencere veya tarayıcı bağlamı yoksa. "Ekrandaki tabloyu belgeye aktar"
  // gibi gerçek karma işler bu kapıdan geçmez.
  if (writerForKind) {
    const contexts = inferLocalContext(message, capabilities, semanticDesktopContract);
    const needsScreenSurface =
      contexts.includes("screen") ||
      contexts.includes("browser") ||
      contexts.includes("window");
    if (!needsScreenSurface) {
      for (let index = capabilities.length - 1; index >= 0; index -= 1) {
        const capability = capabilities[index];
        if (
          capability.startsWith("desktop_operator") ||
          capability === "observe_screen" ||
          capability === "analyze_screen" ||
          capability === "browser_control"
        ) {
          capabilities.splice(index, 1);
        }
      }
    }
  }

  const summary = compactText(
    [
      kind === "remote_mcp"
        ? "Bağlı uygulama görevi"
        : kind === "desktop_cowork"
          ? "Masaüstü cowork görevi"
          : "Masaüstü görevi",
      input.title,
      inferLocalContext(message, capabilities, semanticDesktopContract).length > 0 ? `Bağlam: ${inferLocalContext(message, capabilities, semanticDesktopContract).join(", ")}` : "",
    ].filter(Boolean).join(" — "),
    280,
  );
  const entities = extractEntities(message);
  const localContextNeeded = inferLocalContext(
    message,
    capabilities,
    semanticDesktopContract,
  );
  const expectedOutputs = inferExpectedOutputs(
    message,
    capabilities,
    input.understandingEnvelope,
  );
  const semanticExecutionContract = reconcileSemanticExecutionContract(
    input.understandingEnvelope,
    capabilities,
  );
  const executionEnvelope = input.understandingEnvelope
    ? {
        ...input.understandingEnvelope,
        desired_outputs:
          semanticExecutionContract.desiredOutputs ??
          input.understandingEnvelope.desired_outputs,
        output_contract:
          semanticExecutionContract.outputContract ??
          input.understandingEnvelope.output_contract,
        tool_skill_decision:
          semanticExecutionContract.toolSkillDecision ??
          input.understandingEnvelope.tool_skill_decision,
      }
    : undefined;
  const workType: DesktopWorkOrder["workType"] = capabilities.some((capability) => capability.startsWith("quantum_"))
    ? "decision_support"
    : capabilities.some((capability) => capability.startsWith("desktop_operator") || capability === "observe_screen" || capability === "browser_control")
      ? capabilities.some((capability) => ["document_write", "spreadsheet_write", "presentation_write", "text_analyze", "web_research"].includes(capability))
        ? "mixed"
        : "screen_action"
      : "data_workflow";
  const remoteMcpOperation = kind === "remote_mcp"
    ? input.remoteMcpSelection?.operation ?? "unknown"
    : "unknown";
  if (
    kind === "remote_mcp" &&
    remoteMcpOperation === "write" &&
    !expectedOutputs.some((output) => output.kind === "system_state" && output.format === "remote_mcp_state_readback")
  ) {
    expectedOutputs.push({ kind: "system_state", format: "remote_mcp_state_readback", required: true });
  }
  const constraints = [
    "Private/local data stays on the desktop runtime.",
    "Do not claim completion without runtime/tool evidence.",
    "Return user-visible output through existing Elyan block/task result contracts.",
    ...(kind === "remote_mcp"
      ? ["Connected-app access must use the selected remote MCP target metadata; credentials never enter the work order."]
      : []),
  ];
  const verificationRules: DesktopWorkOrder["verificationRules"] = [
    { id: "runtime_completed", description: "Runtime reports a terminal completed status.", evidence: "runtime_status" },
    { id: "tool_or_state_evidence", description: "Any local action is backed by tool result or state read-back.", evidence: "tool_result" },
    { id: "artifact_reference", description: "Generated files/artifacts are returned as artifact references, not local paths.", evidence: "artifact" },
    ...(kind === "remote_mcp"
      ? [
          {
            id: "remote_mcp_tool_result",
            description: "Connected-app operation is backed by a remote MCP tool result.",
            evidence: "tool_result" as const,
          },
        ]
      : []),
  ];
  const successCriteria = semanticSuccessCriteria(
    expectedOutputs,
    verificationRules,
    executionEnvelope,
  );
  const forbiddenCapabilities = forbiddenCapabilitiesForWorkOrder({
    workType,
    capabilities,
    autonomy: input.autonomy,
    envelope: input.understandingEnvelope,
  });
  const steps = buildSteps({
    message,
    title: input.title,
    summary,
    kind,
    capabilities,
    entities,
    envelope: executionEnvelope,
    inputRefs: input.inputRefs,
  });
  for (const step of steps) {
    if (!capabilities.includes(step.capability)) capabilities.push(step.capability);
  }
  const sourceReference = input.understandingEnvelope?.source_reference ?? "current_prompt";
  const deterministicReadOnlyStep =
    steps.length === 1 &&
    steps[0]?.capability === "sys_info" &&
    steps[0]?.args?.query === "all";
  const deterministicRegistryPlan =
    (directRegistryCommand !== null &&
      steps.length === 1 &&
      steps[0]?.capability === directRegistryCommand.capability &&
      Object.keys(steps[0]?.args ?? {}).length === 1 &&
      typeof steps[0]?.args.app_name === "string") ||
    deterministicReadOnlyStep;
  const basePrivacyRouting = executionEnvelope?.privacy_routing ?? {
    mode: localContextNeeded.length > 0 ? "desktop_private" : "server",
    mayUseHostedModels: localContextNeeded.length === 0,
    maySendPrivateContextToServer: false,
    reasons: localContextNeeded.length > 0 ? ["local_private_context"] : ["server_safe_context"],
  };
  const requiresDesktopExecutionContext =
    localContextNeeded.length > 0 ||
    (executionEnvelope?.desired_outputs ?? []).some(
      (output) => output.target === "desktop",
    );
  const privacyRouting =
    requiresDesktopExecutionContext
      ? {
          ...basePrivacyRouting,
          mode: "desktop_private" as const,
          maySendPrivateContextToServer: false,
          reasons: [
            ...new Set([
              ...basePrivacyRouting.reasons,
              "desktop_execution_context",
            ]),
          ],
        }
      : basePrivacyRouting;
  const explicitRoots = [
    ...entities
      .filter((entity) => entity.type === "file_hint")
      .map((entity) => explicitResourceRoot(entity.value)),
    ...(input.inputRefs ?? []).map(explicitResourceRoot),
  ].filter((root): root is string => Boolean(root));
  const stepRoots = steps.flatMap((step) =>
      Object.entries(step.args)
        .filter(
          ([key, value]) =>
            /path$/iu.test(key) && typeof value === "string",
        )
        .map(([, value]) => ({
          root: explicitResourceRoot(String(value)),
          privacyClass: DESKTOP_CAPABILITY_MANIFEST.find(
            (entry) => entry.name === step.capability,
          )?.privacyClass,
        })),
  ).filter(
    (
      item,
    ): item is { root: string; privacyClass: string | undefined } =>
      Boolean(item.root),
  );
  const stepReadRoots = stepRoots
    .filter((item) => item.privacyClass?.includes("_write") !== true)
    .map((item) => item.root);
  const stepWriteRoots = stepRoots
    .filter((item) => item.privacyClass?.includes("_write") === true)
    .map((item) => item.root);
  const desktopOutputRequested = (
    executionEnvelope?.desired_outputs ?? []
  ).some((output) => output.target === "desktop") ||
    steps.some((step) =>
      Object.entries(step.args).some(
        ([key, value]) =>
          /path$/iu.test(key) &&
          typeof value === "string" &&
          (value === "~/Desktop" || value.startsWith("~/Desktop/")),
      ),
    );
  // YAZMA KAPSAMI PLANDAN ÖNCE DONDURULUYOR.
  //
  // Kapsam, iş emri kurulurken belirleniyor; gerçek planı model SONRA üretiyor
  // ve plan bu kapsama karşı yargılanıyor. `~/Desktop` kapsama yalnız
  // `desired_outputs[].target === "desktop"` gelirse ya da başlangıç
  // adımlarında zaten bir `~/Desktop` yolu varsa giriyordu.
  //
  // Anlama zarfı sıklıkla HİÇ GELMİYOR (canlı vaka 2026-08-12: envelope_keys
  // null, desired_outputs null). O zaman kapsam ["workspace"]'e donuyor,
  // kullanıcı "masaüstüme kaydet" dediği için model doğru şekilde
  // `~/Desktop/...` planlıyor ve doğrulayıcı "path is outside the authorized
  // WorkOrder resource scope" ile TÜM görevi reddediyor. Yani en sık istenen
  // şey yapısal olarak imkânsızdı.
  //
  // Çözüm kelime deseni DEĞİL: kullanıcının kendi çıktı klasörleri zaten
  // meşru yazma hedefleri. Bu bir masaüstü ajanı; kullanıcı onu kendi
  // makinesinde çalıştırıyor ve her yazma adımı ayrıca masaüstündeki
  // izin/onay kapısından geçiyor. Kapsamın işi rastgele SİSTEM yollarını
  // engellemek; kullanıcının Masaüstü/Belgeler/İndirilenler klasörünü değil.
  const defaultWriteRoots = ["workspace", "~/Desktop", "~/Documents", "~/Downloads"];
  const resourceScope = {
    contract: "elyan.resource_scope.v1" as const,
    readRoots: [
      ...new Set(["workspace", ...explicitRoots, ...stepReadRoots]),
    ],
    writeRoots: [
      ...new Set([
        ...(desktopOutputRequested ? ["~/Desktop"] : []),
        ...defaultWriteRoots,
        ...stepWriteRoots,
      ]),
    ],
  };
  return {
    schema: "elyan.desktop_work_order.v1",
    source: input.source ?? "mobile_chat_dispatch",
    goal: {
      kind,
      summary,
      language: detectLanguage(message),
      sourceTextHash: sourceHash(message),
    },
    semanticGoal: {
      contract: "elyan.semantic_task_contract.v1",
      objective: compactText(
        input.understandingEnvelope?.intent.topic || message || summary,
        1_000,
      ),
      constraints,
      successCriteria,
      requiredCapabilities: capabilities,
      forbiddenCapabilities,
      ambiguityPolicy: ambiguityPolicyForWorkOrder(
        input.understandingEnvelope,
        workType,
      ),
      risk: {
        localPrivate: Boolean(input.understandingEnvelope?.risk.local_private || localContextNeeded.length > 0),
        sideEffect: Boolean(
          semanticDesktopContract?.sideEffectLevel === "write" ||
            semanticDesktopContract?.sideEffectLevel === "destructive" ||
          input.understandingEnvelope?.risk.side_effect ||
            input.routeDecision.privacyClass === "side_effect",
        ),
        irreversible: semanticDesktopContract?.sideEffectLevel === "destructive",
      },
    },
    entities,
    constraints,
    workType,
    requiredCapabilities: capabilities,
    capabilityAuthorization: {
      source: "semantic_router",
      allowPrivateRead: Boolean(
        input.routeDecision.taskRoute?.needsPrivateDesktopData,
      ),
      sideEffectsRequireApproval: true,
    },
    localContextNeeded,
    resourceScope,
    expectedOutputs,
    verificationRules,
    execution: {
      mode: "cowork_dispatch",
      approvalPolicy: "single_full_access_surface",
      maxSteps: MAX_WORK_ORDER_STEPS,
    },
    contextPack: {
      sourceReference,
      conversationState: input.understandingEnvelope?.conversation_state,
      latestArtifactRef: input.understandingEnvelope?.latest_artifact_ref ?? null,
      toolSkillDecision: semanticExecutionContract.toolSkillDecision ?? null,
      outputContract: semanticExecutionContract.outputContract ?? null,
      privacyRouting,
      ...(semanticDesktopContract ? { semanticDesktopContract } : {}),
      ...(input.desktopPlanningEvidence
        ? { desktopPlanningEvidence: input.desktopPlanningEvidence }
        : {}),
    },
    executionPlan: {
      mode: workType,
      intentGraph: input.understandingEnvelope?.intent_graph,
      planner: "server_brain",
      allowReplan: true,
    },
    verificationPlan: {
      criteria: verificationRules,
      requireEvidence: true,
      noModelClaimCompletion: true,
    },
    failurePolicy: {
      maxReplans: 2,
      retryOnRecoverableToolError: true,
      stopOnIrreversibleRisk: true,
      safeUserMessage: "Görevi tamamlarken bir adım doğrulanamadı; güvenli şekilde yeniden deniyorum.",
      taxonomy: failureTaxonomy(),
    },
    replanContext: {
      includeCompletedOutputs: true,
      includeLastError: true,
      includeScreenObservation: workType === "screen_action" || workType === "mixed",
    },
    permissionEnvelope: input.autonomy
      ? {
          // Unattended work gets a read-shaped envelope: everything that could
          // reach outside the machine needs a human, and there is none.
          mode: "single_full_access_surface",
          coveredPermissions: ["read"],
          separateApprovalFor: [
            "idempotent_write",
            "browser_control",
            "computer_control",
            "delete",
            "overwrite",
            "send_message",
            "send_email",
            "payment",
            "external_side_effect",
          ],
          ttlSeconds: 900,
        }
      : {
          mode: "single_full_access_surface",
          coveredPermissions: ["read", "idempotent_write", "browser_control", "computer_control"],
          separateApprovalFor: ["delete", "overwrite", "send_message", "send_email", "payment", "external_side_effect"],
          ttlSeconds: 900,
        },
    ...(input.autonomy ? { autonomy: input.autonomy } : {}),
    planPreview: {
      summary,
      privacyClass:
        remoteMcpOperation === "write" ||
        input.routeDecision.privacyClass === "side_effect" ||
        input.understandingEnvelope?.risk.side_effect
        ? "side_effect"
        : kind === "remote_mcp" ||
            input.routeDecision.privacyClass === "local_private" ||
            localContextNeeded.length > 0 ||
            input.understandingEnvelope?.risk.local_private
          ? "local_private"
          : "public_text",
      steps,
      // Tek adımlı open/close app planları capability registry tarafından
      // doğrudan doğrulanır. Bunlar model planı beklemeden çalışabilir; safety
      // policy ve state readback kapıları yine desktop runtime'da kalır.
      ...(deterministicRegistryPlan
        ? {
            planSource: "deterministic_registry" as const,
            contract: "elyan.compiled_plan.v1" as const,
            materializationSource: "deterministic_registry" as const,
            planPreparation: {
              status: "ready" as const,
              outcome: "deterministic_materialized" as const,
              preparedAt: new Date().toISOString(),
            },
          }
        : {
            // Varsayılan: heuristik sentez. Dispatch worker karmaşık görevlerde
            // bunu server_materialized ile üzerine yazar.
            planSource: "heuristic" as const,
            planPreparation: { status: "pending" as const },
          }),
      ...(input.dispatchOptimization
        ? { dispatchOptimization: input.dispatchOptimization }
        : {}),
      ...(input.responsiveExecution
        ? { responsiveExecution: input.responsiveExecution }
        : {}),
      ...(input.livenessGuard
        ? { livenessGuard: input.livenessGuard }
        : {}),
      liveNarrationPlan: [
        { phase: "planning", message: "Görevi parçalara ayırıyorum." },
        { phase: "executing", message: "Masaüstünde gerekli adımları yürütüyorum." },
        { phase: "verifying", message: "Çıktıyı ve kanıtı doğruluyorum." },
        { phase: "completed", message: "Sonucu kullanıcıya teslim ediyorum." },
      ],
    },
    ...(kind === "remote_mcp" && input.remoteMcpSelection
      ? { remoteMcp: input.remoteMcpSelection }
      : {}),
    ...(input.understandingEnvelope
      ? {
          understanding: {
            schemaVersion: input.understandingEnvelope.schema_version,
            intent: input.understandingEnvelope.intent,
            entities: input.understandingEnvelope.entities,
            constraints: input.understandingEnvelope.constraints,
            desiredOutputs:
              semanticExecutionContract.desiredOutputs ??
              input.understandingEnvelope.desired_outputs,
            successCriteria: input.understandingEnvelope.success_criteria,
            ambiguities: input.understandingEnvelope.ambiguities,
            risk: input.understandingEnvelope.risk,
            intentGraph: input.understandingEnvelope.intent_graph,
            sourceReference: input.understandingEnvelope.source_reference,
            latestArtifactRef: input.understandingEnvelope.latest_artifact_ref,
            conversationState: input.understandingEnvelope.conversation_state,
            toolSkillDecision:
              semanticExecutionContract.toolSkillDecision ??
              input.understandingEnvelope.tool_skill_decision,
            outputContract:
              semanticExecutionContract.outputContract ??
              input.understandingEnvelope.output_contract,
            privacyRouting: input.understandingEnvelope.privacy_routing,
            ambiguityPolicy: input.understandingEnvelope.ambiguity_policy,
            confidence: input.understandingEnvelope.confidence,
          },
        }
      : {}),
  };
}
