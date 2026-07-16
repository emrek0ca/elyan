import { createHash } from "node:crypto";
import type { CommandRouteDecision } from "../routing-policy/service.js";
import type { UnderstandingEnvelope } from "../../core/understanding/types.js";

// Work order adım bütçesi. Eskiden 8'e sabitliydi ve karmaşık (çok-adımlı)
// görevler masaüstünde WORK_ORDER_STEP_BUDGET_EXCEEDED ile reddediliyordu.
// Desktop planner MAX_PLAN_STEPS=16 ile hizalandı (runtime/desktop_work_order.py
// MAX_STEPS ile birlikte güncellenir).
export const MAX_WORK_ORDER_STEPS = 16;

export type DesktopWorkOrderStep = {
  id: string;
  capability: string;
  description: string;
  args: Record<string, unknown>;
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
  entities: Array<{
    type: "url" | "email" | "file_hint" | "app_hint" | "topic";
    value: string;
  }>;
  constraints: string[];
  requiredCapabilities: string[];
  localContextNeeded: string[];
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
    approvalPolicy: "capability_policy";
    maxSteps: number;
  };
  planPreview: {
    summary: string;
    privacyClass: "public_text" | "local_private" | "side_effect";
    steps: DesktopWorkOrderStep[];
  };
  understanding?: {
    schemaVersion: UnderstandingEnvelope["schema_version"];
    intent: UnderstandingEnvelope["intent"];
    entities: UnderstandingEnvelope["entities"];
    constraints: UnderstandingEnvelope["constraints"];
    desiredOutputs: UnderstandingEnvelope["desired_outputs"];
    successCriteria: UnderstandingEnvelope["success_criteria"];
    ambiguities: UnderstandingEnvelope["ambiguities"];
    risk: UnderstandingEnvelope["risk"];
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

export function parseDirectDesktopAppCommand(message: string): DirectDesktopAppCommand | null {
  const compact = compactText(message, 240);
  const match = compact.match(
    /^(?:(?:lütfen|lutfen|şimdi|simdi|bana)\s+)*(?<app>[\p{L}\p{N}][\p{L}\p{N} ._'’+-]{0,79}?)\s+(?:(?:uygulamasını|uygulamasini|uygulamayı|uygulamayi|programını|programini|programı|programi)\s+)?(?<verb>aç|ac|başlat|baslat|çalıştır|calistir|kapat|durdur|sonlandır|sonlandir)[.!?]*$/iu,
  );
  const rawApp = match?.groups?.app?.trim() ?? "";
  const verb = match?.groups?.verb?.toLocaleLowerCase("tr-TR") ?? "";
  if (!rawApp || !verb) return null;
  const appName = rawApp.replace(/['’](?:y?[ıiuü])$/iu, "").trim();
  if (!appName) return null;
  return {
    capability: /^(?:kapat|durdur|sonlandır|sonlandir)$/iu.test(verb) ? "close_app" : "open_app",
    appName,
  };
}

export function parseDirectImageFetchCommand(message: string): DirectImageFetchCommand | null {
  const compact = compactText(message, 400);
  const normalized = compact.toLocaleLowerCase("tr-TR");
  const hasImage = /\b(?:resim|resmi|resmini|görsel|gorsel|görseli|gorseli|foto|fotoğraf|fotograf|image|picture)\b/iu.test(normalized);
  const hasSave = /\b(?:indir|kaydet|download|save)\b/iu.test(normalized);
  const hasGeneration = /\b(?:çiz|ciz|oluştur|olustur|üret|uret|generate|tasarla|yap)\b/iu.test(normalized);
  if (!hasImage || !hasSave || hasGeneration) return null;

  const subjectMatch = compact.match(
    /(.+?)\s+(?:resim|resmi|resmini|görsel|gorsel|görseli|gorseli|foto(?:ğraf|graf)?|image|picture)\b/iu,
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
  else if (/\b(?:resimler|pictures|fotoğraflar|fotograflar)\b/iu.test(normalized)) destination = "~/Pictures";
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

function sourceHash(value: string): string {
  return createHash("sha256").update(value).digest("hex").slice(0, 24);
}

function detectLanguage(value: string): "tr" | "en" | "unknown" {
  if (!value.trim()) return "unknown";
  return /[çğıöşü]/i.test(value) || /\b(bunu|şunu|dosya|masaüstü|bilgisayar|yap|hazırla|özetle)\b/i.test(value)
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
  for (const match of message.matchAll(/\b[\wÇĞİÖŞÜçğıöşü ._-]{1,80}\.(?:pdf|docx|xlsx|csv|txt|png|jpg|jpeg|svg)\b/giu)) {
    add("file_hint", match[0]);
  }
  for (const match of message.matchAll(/\b(vs ?code|visual studio code|chrome|safari|finder|terminal|excel|word|numbers|pages)\b/gi)) {
    add("app_hint", match[0]);
  }
  for (const match of message.matchAll(
    /\b([\p{L}\p{N}][\p{L}\p{N} ._-]{0,60}?)\s+(?:uygulamasını|uygulamasini|uygulamayı|uygulamayi|programını|programini|programı|programi)\s+(?:aç|ac|kapat|başlat|baslat)(?=$|[\s.,!?])/giu,
  )) {
    const appName = match[1]?.replace(/^(?:(?:lütfen|lutfen|şimdi|simdi|bana)\s+)+/i, "").trim();
    if (appName) add("app_hint", appName);
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

function inferLocalContext(message: string, capabilities: string[]): string[] {
  const normalized = message.toLocaleLowerCase("tr-TR");
  const contexts = new Set<string>();
  if (/\b(masaüstü|masaustu|desktop|indirilenler|downloads|klasör|klasor|dosya|belge|pdf)\b/i.test(normalized)) {
    contexts.add("filesystem");
  }
  if (/\b(ekran|screenshot|görüntü|goruntu)\b/i.test(normalized) || capabilities.includes("screen_context")) {
    contexts.add("screen");
  }
  if (/\b(chrome|safari|browser|tarayıcı|tarayici)\b/i.test(normalized) || capabilities.includes("browser_control")) {
    contexts.add("browser");
  }
  if (/\b(terminal|komut|shell)\b/i.test(normalized) || capabilities.includes("shell_run")) {
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
    /\b(düzenle|duzenle|değiştir|degistir|kaldır|kaldir|sil|ekle|düzelt|duzelt|iyileştir|iyilestir|netleştir|netlestir|kırp|kirp|retouch|edit|remove|replace|change|erase|enhance|upscale|crop)\b/iu.test(normalized);
  const visualTarget =
    /\b(görsel|gorsel|resim|fotoğraf|fotograf|image|photo|arka plan|yüz|yuz|saç|sac|kıyafet|kiyafet|renk|ışık|isik|kontrast)\b/iu.test(normalized);
  const explicitEdit = explicitEditVerb && visualTarget;
  const sourceTransform =
    /\b(bunu|şunu|sunu|onu|görseli|gorseli|resmi|fotoğrafı|fotografi|this|it|the image|the photo)\b.{0,80}\b(yap|çevir|cevir|dönüştür|donustur|make|turn|transform)\b/iu.test(normalized) ||
    /\b(anime|çizgi film|cizgi film|sinematik|cinematic|vintage|retro|noir|fotogerçekçi|fotogercekci|photorealistic|3d|sulu boya|watercolor|yağlı boya|yagli boya|tarzında|tarzinda|stilinde)\b.{0,60}\b(yap|çevir|cevir|dönüştür|donustur|make|turn|transform)\b/iu.test(normalized) ||
    /\b(make|turn|transform)\s+(this|it|the image|the photo)\b/iu.test(normalized);
  return explicitEdit || sourceTransform;
}

function inferKind(routeDecision: CommandRouteDecision, message: string): string {
  const normalized = message.toLocaleLowerCase("tr-TR");
  if (routeDecision.capabilities.includes("mcp_call_tool")) return "remote_mcp";
  if (parseDirectImageFetchCommand(message)) return "image_fetch";
  if (
    routeDecision.capabilities.some((capability) =>
      capability === "image_edit" || capability === "image.edit"
    ) ||
    isImageEditCommand(message)
  ) return "image_edit";
  if (/\b(görsel|gorsel|resim|image|illustration|poster|afiş|afis)\b/iu.test(normalized)
    && /\b(üret|uret|oluştur|olustur|çiz|ciz|generate|create|draw)\b/iu.test(normalized)) return "image_generate";
  if (/\b(?:pptx|powerpoint|sunum|slayt|slide|presentation)\b/iu.test(normalized)) return "presentation_task";
  if (routeDecision.capabilities.includes("email_send")) return "email_send";
  if (routeDecision.capabilities.includes("email_draft")) return "email_draft";
  if (/\b(pdf|docx|xlsx|excel|belge|doküman|dokuman|rapor)\b/i.test(normalized)) return "document_task";
  if (/\b(browser|chrome|safari|web|site|url|link)\b/i.test(normalized)) return "browser_task";
  if (/\b(terminal|komut|shell)\b/i.test(normalized)) return "terminal_task";
  if (/\b(ekran|screenshot|uygulama|program|app)\b/i.test(normalized)) return "computer_task";
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

function inferCapabilities(
  routeDecision: CommandRouteDecision,
  message: string,
  envelope?: UnderstandingEnvelope,
): string[] {
  const capabilities = new Set<string>();
  for (const capability of routeDecision.capabilities) {
    const canonical = canonicalRuntimeCapability(capability);
    if (canonical) capabilities.add(canonical);
  }
  for (const capability of envelope?.required_capabilities ?? []) {
    const canonical = canonicalRuntimeCapability(capability.name);
    if (canonical) capabilities.add(canonical);
  }
  const normalized = message.toLocaleLowerCase("tr-TR");
  const researchRequested = /\b(?:araştır|arastir|araştırma|arastirma|research|bilgi\s+topla|kaynak\s+topla)\b/iu.test(normalized);
  const presentationRequested = /\b(?:pptx|powerpoint|sunum|slayt|slide|presentation)\b/iu.test(normalized)
    && /\b(?:hazırla|hazirla|oluştur|olustur|üret|uret|yap|çevir|cevir|kaydet|save|create|prepare)\b/iu.test(normalized);
  const directAppCommand = parseDirectDesktopAppCommand(message);
  const directImageFetch = parseDirectImageFetchCommand(message);
  const imageEditRequested =
    capabilities.has("image_edit") ||
    isImageEditCommand(message);
  const imageGenerateRequested = !imageEditRequested
    && /\b(görsel|gorsel|resim|image|illustration|poster|afiş|afis)\b/iu.test(normalized)
    && /\b(üret|uret|oluştur|olustur|çiz|ciz|generate|create|draw)\b/iu.test(normalized);
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
  if (presentationRequested) {
    capabilities.add("presentation_write");
    capabilities.delete("desktop_operator.run");
  }
  if (/\b(masaüstü|masaustu|desktop|indirilenler|downloads|klasör|klasor|dosya|belge|pdf)\b/i.test(normalized)) {
    capabilities.add("document_read");
  }
  if (/\b(kaydet|save|yaz|oluştur|olustur|düzenle|duzenle|export|dışa aktar|disa aktar)\b/i.test(normalized)) {
    if (presentationRequested) capabilities.add("presentation_write");
    else if (/\b(xlsx|excel|çalışma sayfası|calisma sayfasi)\b/i.test(normalized)) capabilities.add("spreadsheet_write");
    else if (/\b(pdf|svg|canvas|görsel|gorsel)\b/i.test(normalized)) capabilities.add("canvas_write");
    else capabilities.add("document_write");
  }
  if (
    /\b(browser|chrome|safari|site|url|link|tarayıcı|tarayici)\b/iu.test(normalized)
    || (/\bweb\b/iu.test(normalized) && !researchRequested)
    || /https?:\/\//i.test(message)
  ) {
    capabilities.add("browser_control");
  }
  if (/\b(terminal|komut|shell)\b/i.test(normalized)) capabilities.add("shell_run");
  if (/\b(ekran|screenshot|görüntü|goruntu)\b/i.test(normalized)) capabilities.add("desktop_operator.observe_screen");
  return [...capabilities].slice(0, 16);
}

function inferExpectedOutputs(
  message: string,
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
      /\b(görsel|gorsel|resim|fotoğraf|fotograf|image|photo)\b/iu.test(normalized) &&
      /\b(üret|uret|oluştur|olustur|çiz|ciz|generate|create|draw)\b/iu.test(normalized)
    )
  ) {
    addOutput({ kind: "artifact", format: "image", required: true });
    addOutput({ kind: "file_update", format: "state_readback", required: true });
  }
  const presentationRequested = /\b(?:pptx|powerpoint|sunum|slayt|slide|presentation)\b/iu.test(normalized)
    && /\b(?:hazırla|hazirla|oluştur|olustur|üret|uret|yap|çevir|cevir|kaydet|save|create|prepare)\b/iu.test(normalized);
  if (presentationRequested) {
    addOutput({ kind: "artifact", format: "artifact_reference", required: true });
    addOutput({ kind: "file_update", format: "state_readback", required: true });
  }
  const typedArtifactRequested = envelope?.desired_outputs.some(
    (output) => output.target === "artifact" || ["pdf", "docx", "xlsx", "svg", "artifact"].includes(output.kind),
  ) ?? false;
  const explicitArtifactCreation =
    /\b(pdf|docx|xlsx|pptx|csv|svg|dosya|belge|rapor|sunum|slayt|presentation)\b/i.test(normalized) &&
    /\b(oluştur|olustur|hazırla|hazirla|dönüştür|donustur|export|dışa aktar|disa aktar|kaydet|yap)\b/i.test(normalized);
  if (typedArtifactRequested || explicitArtifactCreation) {
    addOutput({ kind: "artifact", format: "artifact_reference", required: true });
  }
  if (/\b(kaydet|save|düzenle|duzenle|yaz|oluştur|olustur|hazırla|hazirla|üret|uret)\b/i.test(normalized)) {
    addOutput({ kind: "file_update", format: "state_readback", required: true });
  }
  if (/\b(browser|chrome|safari|site|url|link|tarayıcı|tarayici)\b/i.test(normalized)) {
    addOutput({ kind: "browser_state", format: "tool_result", required: false });
  }
  return outputs;
}

function buildSteps(input: {
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
  const topic = input.entities.find((entity) => entity.type === "topic")?.value ?? "";
  const directImageFetch = parseDirectImageFetchCommand(topic);
  const researchRequested = input.capabilities.includes("web_research");
  const semanticBrief = compactText([
    input.envelope?.intent.topic,
    ...(input.envelope?.entities ?? []).map((entity) => `${entity.type}: ${entity.normalized ?? entity.value}`),
    ...(input.envelope?.constraints ?? [])
      .filter((constraint) => constraint.explicit)
      .map((constraint) => `${constraint.kind}: ${JSON.stringify(constraint.value)}`),
    ...(input.envelope?.success_criteria ?? []).map((criterion) => criterion.description),
  ].filter(Boolean).join("\n"), 3_000) || topic || input.summary;
  for (const capability of ["open_app", "close_app"] as const) {
    if (!input.capabilities.includes(capability)) continue;
    steps.push({
      id: `step_${capability}`,
      capability,
      description: appHint
        ? `${appHint} ${capability === "open_app" ? "açılacak" : "kapatılacak"}.`
        : `Uygulama ${capability === "open_app" ? "açma" : "kapatma"} isteği yerelde çözümlenecek.`,
      args: appHint ? { app_name: appHint } : {},
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
        ? "Kullanıcının yüksek kaliteli kaynak görseli Gemini ile istenen şekilde düzenlenecek."
        : "Kullanıcının istemi Gemini ile yüksek kaliteli görsele dönüştürülecek.",
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
  if (input.capabilities.includes("document_read") && fileHint) {
    steps.push({
      id: "step_document_read",
      capability: "document_read",
      description: "Belge yerel ve izinli çalışma alanında okunacak.",
      args: { path: fileHint, mode: "read" },
    });
  }
  for (const capability of ["document_write", "spreadsheet_write", "presentation_write", "canvas_write"] as const) {
    if (!input.capabilities.includes(capability)) continue;
    const args: Record<string, unknown> = {
      title: compactText(input.title, 160),
      prompt: semanticBrief,
    };
    if (!researchRequested) args.sourceContext = semanticBrief;
    if (
      capability === "presentation_write"
      && /\b(?:masaüstü|masaustu|desktop)\b/iu.test(topic)
    ) {
      const filename = topic
        .toLocaleLowerCase("tr-TR")
        .replace(/[ıİ]/g, "i")
        .replace(/[ğĞ]/g, "g")
        .replace(/[üÜ]/g, "u")
        .replace(/[şŞ]/g, "s")
        .replace(/[öÖ]/g, "o")
        .replace(/[çÇ]/g, "c")
        .replace(/\b(?:webden|web'den|araştır|arastir|araştırıp|arastirip|sonuçları|sonuclari|sunum|slayt|pptx|powerpoint|hazırla|hazirla|oluştur|olustur|masaüstüne|masaustune|desktop)\b/giu, " ")
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 64) || "elyan-sunum";
      args.outputPath = `~/Desktop/${filename}.pptx`;
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
    });
  }
  if (
    input.capabilities.some((capability) =>
      ["desktop_operator.observe_screen", "shell_run", "desktop_operator.run"].includes(capability),
    )
  ) {
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
  if (steps.length === 0 && !input.capabilities.includes("mcp_call_tool")) {
    steps.push({
      id: "step_desktop_execute",
      capability: "desktop_operator.run",
      description: "Tipli görev yerel masaüstü bağlamında yürütülecek.",
      args: {
        action: "run",
        goal: semanticBrief,
        workOrderKind: input.kind,
      },
    });
  }
  return steps.slice(0, MAX_WORK_ORDER_STEPS);
}

export function buildDesktopWorkOrder(input: {
  message: string;
  title: string;
  routeDecision: CommandRouteDecision;
  requestedCapabilities: string[];
  understandingEnvelope?: UnderstandingEnvelope;
  source?: "mobile_chat_dispatch" | "backend_task_route";
  inputRefs?: string[];
}): DesktopWorkOrder {
  const message = compactText(input.message, 4_000);
  const kind = inferKind(input.routeDecision, message);
  const capabilities = inferCapabilities(
    {
      ...input.routeDecision,
      capabilities: [...input.routeDecision.capabilities, ...input.requestedCapabilities],
    },
    message,
    input.understandingEnvelope,
  );
  const summary = compactText(
    [
      kind === "remote_mcp"
        ? "Bağlı uygulama görevi"
        : kind === "desktop_cowork"
          ? "Masaüstü cowork görevi"
          : "Masaüstü görevi",
      input.title,
      inferLocalContext(message, capabilities).length > 0 ? `Bağlam: ${inferLocalContext(message, capabilities).join(", ")}` : "",
    ].filter(Boolean).join(" — "),
    280,
  );
  const entities = extractEntities(message);
  const localContextNeeded = inferLocalContext(message, capabilities);
  const expectedOutputs = inferExpectedOutputs(message, input.understandingEnvelope);
  const constraints = [
    "Private/local data stays on the desktop runtime.",
    "Do not claim completion without runtime/tool evidence.",
    "Return user-visible output through existing Elyan block/task result contracts.",
  ];
  const verificationRules: DesktopWorkOrder["verificationRules"] = [
    { id: "runtime_completed", description: "Runtime reports a terminal completed status.", evidence: "runtime_status" },
    { id: "tool_or_state_evidence", description: "Any local action is backed by tool result or state read-back.", evidence: "tool_result" },
    { id: "artifact_reference", description: "Generated files/artifacts are returned as artifact references, not local paths.", evidence: "artifact" },
  ];
  const steps = buildSteps({
    title: input.title,
    summary,
    kind,
    capabilities,
    entities,
    envelope: input.understandingEnvelope,
    inputRefs: input.inputRefs,
  });
  for (const step of steps) {
    if (!capabilities.includes(step.capability)) capabilities.push(step.capability);
  }
  return {
    schema: "elyan.desktop_work_order.v1",
    source: input.source ?? "mobile_chat_dispatch",
    goal: {
      kind,
      summary,
      language: detectLanguage(message),
      sourceTextHash: sourceHash(message),
    },
    entities,
    constraints,
    requiredCapabilities: capabilities,
    localContextNeeded,
    expectedOutputs,
    verificationRules,
    execution: {
      mode: "cowork_dispatch",
      approvalPolicy: "capability_policy",
      maxSteps: MAX_WORK_ORDER_STEPS,
    },
    planPreview: {
      summary,
      privacyClass:
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
    },
    ...(input.understandingEnvelope
      ? {
          understanding: {
            schemaVersion: input.understandingEnvelope.schema_version,
            intent: input.understandingEnvelope.intent,
            entities: input.understandingEnvelope.entities,
            constraints: input.understandingEnvelope.constraints,
            desiredOutputs: input.understandingEnvelope.desired_outputs,
            successCriteria: input.understandingEnvelope.success_criteria,
            ambiguities: input.understandingEnvelope.ambiguities,
            risk: input.understandingEnvelope.risk,
            confidence: input.understandingEnvelope.confidence,
          },
        }
      : {}),
  };
}
