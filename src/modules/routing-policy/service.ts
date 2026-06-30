import type { FastifyInstance } from "fastify";
import { classifyIntent } from "../../core/understanding/intent-classifier.js";
import {
  isExplicitChartRequest,
  isExplicitMathSurface3DRequest,
  isExplicitMathOrLatexRequest,
  isExplicitTableRequest,
} from "../../core/understanding/structured-output-policy.js";
import type { UnderstandingIntent } from "../../core/understanding/types.js";
import { isMateriallyAmbiguousUserPrompt, selectHybridMobileChatWorkload } from "../brain/chat-heuristics.js";
import { normalizePlanBrainProfile, type PlanBrainProfile } from "../billing/catalog.js";
import type { SharedBrainWorkload } from "../brain/workloads.js";
import { generateSharedBrainReply } from "../brain/inference.js";
import { getSharedBrainTargetDevice, getUserDevice, listUserDevices } from "../devices/service.js";
import {
  assertOwnedDesktopTaskTarget,
  createInvalidTargetDeviceError,
  createRuntimeCapabilityMismatchError,
} from "../tasks/service-helpers.js";
import {
  missingRuntimeCapabilities,
  normalizeRuntimeCapabilities,
  supportsRequestedCapabilities,
} from "../runtime/capabilities.js";

export type RoutingPurpose = "task" | "chat";

export type CommandRoute = "server_brain" | "desktop_runtime" | "pairing_required" | "unavailable";
export type ExecutionTarget = "server_brain" | "mobile_local" | "desktop_runtime" | "hybrid";

export type TaskRoute = {
  target: ExecutionTarget;
  operationalRoute: "server_brain" | "desktop_runtime";
  executionPlan: Array<"mobile_local" | "server_brain" | "desktop_runtime">;
  reason: string;
  needsDesktop: boolean;
  needsPrivateDesktopData: boolean;
  needsUserApproval: boolean;
  requiredCapabilities: string[];
};

export type CommandMode = "chat" | "executable_task" | "mixed_task";

export type CommandPrivacyClass = "public_text" | "local_private" | "side_effect";

export type NormalizedCommandIntent =
  | "normal_chat"
  | "planning_request"
  | "desktop_required"
  | "local_file_request"
  | "private_data_request"
  | "device_control_request"
  | "ambiguous_request"
  | "unsupported_request";

export type CommandRequiredRuntime = "server" | "desktop" | "both";

export type CommandRouteDecision = {
  route: CommandRoute;
  taskRoute?: TaskRoute;
  mode: CommandMode;
  capabilities: string[];
  privacyClass: CommandPrivacyClass;
  requiresApproval: boolean;
  reason: string;
  userFacingMessage?: string;
  intent: NormalizedCommandIntent;
  confidence: number;
  requiredRuntime: CommandRequiredRuntime;
  privacyLevel: "low" | "medium" | "high";
  shouldAskClarification: boolean;
  failClosedReason: string | null;
  selectedWorkload: SharedBrainWorkload;
};

export type CommandRouteInput = {
  userId: string;
  message: string;
  source: "mobile" | "desktop";
  activeChatSessionId?: string;
  selectedDeviceId?: string;
  metadata?: Record<string, unknown>;
  desktopAllowed?: boolean;
  requestedCapabilities?: string[];
  bootstrap?: unknown;
  brainProfile?: unknown;
  quota?: unknown;
};

export type ResolvedCommandTarget = {
  device: NonNullable<Awaited<ReturnType<typeof getUserDevice>>>;
  isSharedBrain: boolean;
};

const EMAIL_ADDRESS_PATTERN = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi;
const EMAIL_SIDE_EFFECT_PATTERNS = [
  /\b(mail|email|e-?posta)\b.*\b(gönder|gonder|yolla|at|send)\b/i,
  /\b(gönder|gonder|yolla|at|send)\b.*\b(mail|email|e-?posta)\b/i,
  /\bmail gönder\b/i,
  /\bemail gönder\b/i,
];
const EMAIL_DRAFT_PATTERNS = [
  /\b(mail|email|e-?posta)\b.*\b(taslak|taslağı|taslagi|hazırla|hazirla|yaz|compose|draft)\b/i,
  /\b(taslak|taslağı|taslagi|hazırla|hazirla|yaz|compose|draft)\b.*\b(mail|email|e-?posta)\b/i,
];
const LOCAL_PRIVATE_PATTERNS = [
  /\b(downloads?|indirilenler|desktop|klasör|klasor|folder|workspace|local file|yerel dosya|file system|dosya sistemi|path)\b/i,
  /\b(takvim|calendar|ajanda|hatırlatıcı|reminder|ekran görüntüsü|screenshot|ekran)\b/i,
  /\b(open_app|browser|computer|terminal|shell)\b/i,
  /\b(bilgisayar(?:ım|im|ımda|imde|umda|unda)?|son çalıştığımız belge|son calistigimiz belge|masaüstündeki dosya|masaustundeki dosya|indirilenlerdeki dosya|indirilenlerdeki rapor)\b/i,
  /\b(masaüstü|masaustu|desktop)\b.*\b(dosya|belge|rapor|klasör|klasor)\b/i,
  /\b(dosya|belge|rapor|klasör|klasor)\b.*\b(masaüstü|masaustu|desktop|indirilenler|downloads?)\b/i,
];
const LOCAL_FILE_DESTRUCTIVE_PATTERNS = [
  /\b(dosyaya yaz|file write|write to file|overwrite|üzerine yaz|uzerine yaz|append|sil dosya|delete file|güncelle dosya|guncelle dosya)\b/i,
  /\b(sil|delete|overwrite|append|güncelle|guncelle)\b.*\b(dosya|file|klasör|klasor|workspace|folder|path)\b/i,
  /\b(dosya|file|klasör|klasor|workspace|folder|path)\b.*\b(sil|delete|overwrite|append|güncelle|guncelle)\b/i,
];
const LOCAL_FILE_BENIGN_SAVE_PATTERNS = [
  /\b(masaüstüne|masaustune|desktop(?:a|e)?|bilgisayara|downloads?a?|indirilenlere)\b.*\b(kaydet|save|gönder|gonder|indir|export|dışa aktar|disa aktar)\b/i,
  /\b(kaydet|save|gönder|gonder|indir|export|dışa aktar|disa aktar)\b.*\b(masaüstü|masaustu|desktop|bilgisayar|downloads?|indirilenler)\b/i,
];
const PACKAGED_WORLD_CONTEXT_SUBJECT_PATTERNS = [
  /\b(sağlık|saglik|health|uyku|sleep|stres|stress|enerji|energy)\b/i,
  /\b(takvim|calendar|ajanda|saat|zaman|time|timezone)\b/i,
  /\b(cihaz durumu|device status|pil|battery|ağ|ag|network|odak|focus)\b/i,
  /\b(bildirim|notification|notification load|dikkat|attention)\b/i,
];
const PACKAGED_WORLD_CONTEXT_MODE_PATTERNS = [
  /\b(bağlam|baglam|context|sinyal|signal|özet|ozet|durum|state|paket|packaged)\b/i,
  /\b(tanıyarak|taniyarak|kişisel|kisisel|hafıza|hafiza|memory|profil|profile)\b/i,
];
const PACKAGED_WORLD_CONTEXT_UNSAFE_ACTION_PATTERNS = [
  /\b(aç|ac|open|oku|read|listele|list|tara|scan|çek|cek|fetch|getir)\b.*\b(takvim|calendar|bildirim|notification|ekran|screen|dosya|file|klasör|klasor|folder)\b/i,
  /\b(takvim|calendar|bildirim|notification|ekran|screen|dosya|file|klasör|klasor|folder)\b.*\b(aç|ac|open|oku|read|listele|list|tara|scan|çek|cek|fetch|getir)\b/i,
];
const ATTACHMENT_ANALYSIS_PATTERNS = [
  /\b(özetle|ozetle|summarize|summary|özeti|ozeti|çıkar|cikar|extract|önemli maddeler|onemli maddeler|ana maddeler|sor|soruyu|ask about|question about|ne yazıyor|ne yaziyo|içinde ne var|icinde ne var|what's in|what is in)\b/i,
  /\b(bu|şu|söz konusu|attached|ekli|ek) (pdf|belge|doküman|dokuman|dosya|foto|görsel|gorsel|resim|image)\b/i,
];
const ROUTER_SEMANTIC_CAPABILITIES = {
  mobile: ["document_parse", "image_ocr", "file_transform", "camera_input"],
  server: ["summarize", "reason", "rag", "transform_chunks", "generate_response"],
  desktop: ["filesystem_read", "filesystem_write", "app_control", "screen_context", "terminal", "recent_files"],
} as const;
const LOCAL_FILE_SIDE_EFFECT_PATTERNS = [
  /\b(dosyaya yaz|file write|write to file|overwrite|üzerine yaz|uzerine yaz|append|sil dosya|delete file|güncelle dosya|guncelle dosya)\b/i,
  /\b(kaydet|save|export|dışa aktar|disa aktar|dosyaya yaz|write to file|overwrite|üzerine yaz|uzerine yaz|append|sil|delete|güncelle|guncelle)\b.*\b(desktop|downloads?|indirilenler|local file|yerel dosya|file system|dosya sistemi|workspace|folder|klasör|klasor|path)\b/i,
  /\b(desktop|downloads?|indirilenler|local file|yerel dosya|file system|dosya sistemi|workspace|folder|klasör|klasor|path)\b.*\b(kaydet|save|export|dışa aktar|disa aktar|dosyaya yaz|write to file|overwrite|üzerine yaz|uzerine yaz|append|sil|delete|güncelle|guncelle)\b/i,
];
const MOBILE_DOCUMENT_EXPORT_PATTERNS = [
  /\b(metni|yazıyı|yaziyi|içeriği|icerigi|notları|notlari|özeti|ozeti|taslağı|taslagi|görseli|gorseli|resmi|image)\b.*\b(pdf|word|docx|doc|belge|png|jpg|jpeg|webp|afiş|afis|poster|banner|kapak|thumbnail|screenshot)\b/i,
  /\b(pdf|word|docx|doc|belge|png|jpg|jpeg|webp|afiş|afis|poster|banner|kapak|thumbnail|screenshot|görsel|gorsel|resim|image)\b.*\b(ver|hazırla|hazirla|oluştur|olustur|dönüştür|donustur|çevir|cevir|kaydet|düzenle|duzenle|yap|üret|uret)\b/i,
  /\b(ver|hazırla|hazirla|oluştur|olustur|dönüştür|donustur|çevir|cevir|kaydet|düzenle|duzenle|yap|üret|uret)\b.*\b(pdf|word|docx|doc|belge|png|jpg|jpeg|webp|afiş|afis|poster|banner|kapak|thumbnail|screenshot|görsel|gorsel|resim|image)\b/i,
  /\b(pdf olarak ver|pdf'e çevir|pdfe çevir|pdf yap|pdf oluştur|pdf üret|word olarak ver|word olarak hazırla|word yap|word oluştur|word üret|docx olarak hazırla|docx yap|docx oluştur|docx üret|görsel üret|görsel yap|görsel oluştur|resim üret|resim yap|image üret|image yap|png oluştur|png üret|jpg oluştur|jpg üret|jpeg oluştur|jpeg üret|webp oluştur|webp üret|afiş oluştur|afiş üret|afis oluştur|afis üret|poster oluştur|poster üret|banner oluştur|banner üret|kapak oluştur|kapak üret|thumbnail oluştur|thumbnail üret|screenshot oluştur|screenshot üret)\b/i,
];
// Yeni bir çok bölümlü belge/rapor ÜRETME niyeti (mevcut içeriği export değil).
// document_generate workload'unu tetikler → model {"type":"document_block"} üretir.
// NOT: Türkçe karakterler JS `\b` (ASCII word-boundary) ile çalışmadığından
// Unicode-aware lookaround (?<!\p{L})...(?!\p{L}) kullanılıyor (bkz. memory:
// "TÜRKÇE \b REGEX TUZAĞI"). "raporla"/"yazılım" gibi kelimelerin yanlış
// eşleşmesini engeller.
const DOC_NOUN = String.raw`(?:rapor|makale|belge|d[öo]k[üu]man|deneme|kompozisyon|dilek[çc]e|mektup|essay|article|report|bülten|bulten|kılavuz|kilavuz|sunum metni|köşe yaz[ıi]s[ıi]|kose yaz[ıi]s[ıi]|blog yaz[ıi]s[ıi]|blog post|taslak)`;
const DOC_VERB = String.raw`(?:yaz|haz[ıi]rla|olu[şs]tur|[üu]ret|d[üu]zenle|kaleme al|derle|haz[ıi]rlay)`;
const DOCUMENT_GENERATE_PATTERNS = [
  new RegExp(`(?<!\\p{L})${DOC_NOUN}(?!\\p{L})[\\s\\S]{0,48}?(?<!\\p{L})${DOC_VERB}`, "iu"),
  new RegExp(`(?<!\\p{L})${DOC_VERB}(?!\\p{L})[\\s\\S]{0,48}?(?<!\\p{L})${DOC_NOUN}(?!\\p{L})`, "iu"),
];
const DOCUMENT_OUTPUT_GENERATE_PATTERNS = [
  /\b(pdf|docx|word|belge|doküman|dokuman|rapor)\b.*\b(hazırla|hazirla|oluştur|olustur|üret|uret|tasarla|düzenle|duzenle|yap)\b/i,
  /\b(hazırla|hazirla|oluştur|olustur|üret|uret|tasarla|düzenle|duzenle|yap)\b.*\b(pdf|docx|word|belge|doküman|dokuman|rapor)\b/i,
  /\b(tasarım|tasarim|layout|şablon|sablon)\b.*\b(pdf|docx|word|belge|doküman|dokuman|rapor|sunum metni)\b/i,
  /\b(pdf olarak|word olarak|docx olarak)\b.*\b(ver|hazırla|hazirla|oluştur|olustur|üret|uret|tasarla|düzenle|duzenle)\b/i,
];
const QUANTUM_TOPIC_PATTERNS = [
  /\b(quantum|kuantum|qubo|ising|qaoa|vqe|qiskit|ocean sdk|dwave|d-wave|hamiltonian)\b/i,
];
const QUANTUM_EXECUTION_PATTERNS = [
  /\b(çalıştır|calistir|koştur|kostur|simüle|simule|simulate|run|execute|deney|experiment|devre|circuit)\b/i,
  /\b(modelle|formüle|formule|formulation|oluştur|olustur|kur|çöz|coz|solve|karşılaştır|karsilastir|benchmark|raporla|report)\b/i,
  /\b(qaoa|vqe|qiskit|ocean sdk|qubo|ising)\b.*\b(çalıştır|calistir|simüle|simule|çöz|coz|solve|raporla|report)\b/i,
];
const QUANTUM_CAPABILITIES = [
  "quantum_model_problem",
  "quantum_run_experiment",
  "quantum_compare_classical",
  "quantum_generate_report",
];

function normalizeMessage(value: string): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

function extractEmailAddresses(message: string): string[] {
  return [...new Set((message.match(EMAIL_ADDRESS_PATTERN) ?? []).map((value) => value.trim()))];
}

function matchesAny(message: string, patterns: RegExp[]): boolean {
  return patterns.some((pattern) => pattern.test(message));
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function readString(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readBoolean(record: Record<string, unknown> | null, key: string): boolean | null {
  const value = record?.[key];
  return typeof value === "boolean" ? value : null;
}

function normalizeFlag(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s.-]+/g, "_");
}

function normalizeExportMode(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s.-]+/g, "_");
}

function hasMobileLocalDocumentExportHint(metadata: unknown): boolean {
  const record = readRecord(metadata);
  if (!record) {
    return false;
  }

  if (
    readBoolean(record, "mobileDocumentExport") === true ||
    readBoolean(record, "mobileLocalExport") === true ||
    readBoolean(record, "mobileExport") === true ||
    readBoolean(record, "documentExportReady") === true
  ) {
    return true;
  }

  const exportMode = normalizeExportMode(
    readString(record, "documentExportMode") ??
      readString(record, "exportMode") ??
      readString(record, "localExportMode") ??
      readString(record, "documentOutputMode") ??
      readString(record, "outputMode"),
  );

  return (
    exportMode === "mobile_local" ||
    exportMode === "mobile" ||
    exportMode === "local" ||
    exportMode === "on_device" ||
    exportMode === "on_device_export" ||
    exportMode === "mobile_export"
  );
}

function readArray(record: Record<string, unknown> | null, key: string): unknown[] {
  const value = record?.[key];
  return Array.isArray(value) ? value : [];
}

function hasDocumentEnvelopePayload(value: unknown, depth = 0): boolean {
  if (depth > 8) {
    return false;
  }

  const record = readRecord(value);
  if (!record) {
    return false;
  }

  const hasEnvelopeShape =
    Boolean(readString(record, "sourceHash") || readString(record, "source_hash")) &&
    Boolean(
      readString(record, "mimeType") ||
        readString(record, "mime_type") ||
        readString(record, "type") ||
        readArray(record, "blocks").length > 0 ||
        readRecord(record.blocks) != null,
    );
  if (hasEnvelopeShape) {
    return true;
  }

  const envelopeCandidates = [
    record.deepContext,
    record.fastPreview,
    record.envelope,
    record.documentEnvelope,
    record.document_envelope,
    record.documentPayload,
    record.document_payload,
    record.compactDocument,
    record.document_analysis,
    record.documentAnalysis,
  ];

  return envelopeCandidates.some((candidate) => {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) {
      return false;
    }
    return hasDocumentEnvelopePayload(candidate, depth + 1);
  });
}

function hasReadableDocumentPayload(value: unknown, depth = 0): boolean {
  if (depth > 8) {
    return false;
  }

  const record = readRecord(value);
  if (!record) {
    return false;
  }

  if (
    readString(record, "content") ||
    readString(record, "text") ||
    readString(record, "summary") ||
    readString(record, "ocrText") ||
    readString(record, "extractedText") ||
    readString(record, "visualSummary")
  ) {
    return true;
  }

  if (hasDocumentEnvelopePayload(record, depth + 1)) {
    return true;
  }

  const chunks = Array.isArray(record.chunks) ? record.chunks : [];
  if (chunks.some((chunk) => hasReadableDocumentPayload(chunk, depth + 1))) {
    return true;
  }

  const blockCandidates = [
    record.deepContext,
    record.fastPreview,
    ...readArray(record, "blocks"),
    ...readArray(record, "pages"),
    ...readArray(record, "paragraphs"),
    ...readArray(record, "lines"),
    ...readArray(record, "tables"),
    ...readArray(record, "attachments"),
  ];
  return blockCandidates.some((candidate) => hasReadableDocumentPayload(candidate, depth + 1));
}

function hasLocalDerivedDocumentContext(metadata: unknown, depth = 0): boolean {
  if (depth > 8) {
    return false;
  }

  const record = readRecord(metadata);
  if (!record) {
    return false;
  }

  const rawFileUploaded = readBoolean(record, "raw_file_uploaded");
  const dataOrigin = normalizeFlag(
    readString(record, "data_origin") ??
      readString(record, "dataOrigin") ??
      readString(record, "origin"),
  );
  const privacyLevel = normalizeFlag(
    readString(record, "privacy_level") ??
      readString(record, "privacyLevel"),
  );
  if (
    rawFileUploaded === false &&
    (dataOrigin === "local_derived" || privacyLevel === "local_derived")
  ) {
    return true;
  }

  const candidates = [
    record.document_analysis,
    record.documentAnalysis,
    record.deepContext,
    record.fastPreview,
    record.image_analysis,
    record.imageAnalysis,
    record.vision_analysis,
    record.visionAnalysis,
    record.visual_analysis,
    record.visualAnalysis,
    record.analysis,
    ...readArray(record, "attachments"),
    ...readArray(record, "documents"),
    ...readArray(record, "files"),
    ...readArray(record, "items"),
  ];

  return candidates.some((candidate) => {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) {
      return false;
    }
    return (
      hasLocalDerivedDocumentContext(candidate, depth + 1) ||
      hasReadableDocumentPayload(candidate)
    );
  });
}

function hasMobileReadableDocumentHint(metadata: unknown): boolean {
  const record = readRecord(metadata);
  if (!record) {
    return false;
  }

  const candidates = [
    record.compactDocument,
    record.deepContext,
    record.fastPreview,
    record.document,
    record.documentPayload,
    record.documentEnvelope,
    record.document_envelope,
    record.document_analysis,
    record.documentAnalysis,
    record.knowledgeDocument,
    record.attachment,
    record.image_analysis,
    record.imageAnalysis,
    record.vision_analysis,
    record.visionAnalysis,
    record.visual_analysis,
    record.visualAnalysis,
    record.analysis,
    ...readArray(record, "attachments"),
    ...readArray(record, "documents"),
    ...readArray(record, "files"),
    ...readArray(record, "items"),
  ];

  return candidates.some((candidate) => hasReadableDocumentPayload(candidate));
}

function hasAttachmentPayload(metadata: unknown): boolean {
  const record = readRecord(metadata);
  if (!record) {
    return false;
  }

  if (readRecord(record.attachment) || readRecord(record.file) || readRecord(record.document)) {
    return true;
  }

  return [
    ...readArray(record, "blocks"),
    ...readArray(record, "attachments"),
    ...readArray(record, "documents"),
    ...readArray(record, "files"),
    ...readArray(record, "items"),
  ].some((candidate) => {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) {
      return false;
    }
    const attachment = candidate as Record<string, unknown>;
    return Boolean(
      readString(attachment, "name") ||
        readString(attachment, "filename") ||
        readString(attachment, "type") ||
        readString(attachment, "contentType") ||
        readString(attachment, "text") ||
        readString(attachment, "content") ||
      readString(attachment, "summary") ||
      readString(attachment, "extractedText") ||
        readString(attachment, "ocrText") ||
        readString(attachment, "mimeType") ||
        readString(attachment, "mime_type") ||
        readString(attachment, "sourceHash") ||
        readString(attachment, "source_hash") ||
        readRecord(attachment.envelope) ||
        readRecord(attachment.deepContext) ||
        readRecord(attachment.fastPreview) ||
        readRecord(attachment.documentEnvelope) ||
        readRecord(attachment.document_envelope),
    );
  });
}

function normalizeSemanticCapabilityName(value: string): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s.-]+/g, "_");
}

function uniqueSemanticCapabilities(values: string[]): string[] {
  return [...new Set(values.map((value) => normalizeSemanticCapabilityName(value)).filter(Boolean))];
}

function hasAttachmentAnalysisSignal(message: string, metadata: unknown): boolean {
  return hasAttachmentPayload(metadata) && matchesAny(message, ATTACHMENT_ANALYSIS_PATTERNS);
}

function hasDesktopPrivateDataSignal(message: string): boolean {
  return matchesAny(message, LOCAL_PRIVATE_PATTERNS);
}

function hasPackagedWorldContextSignal(message: string): boolean {
  return (
    matchesAny(message, PACKAGED_WORLD_CONTEXT_SUBJECT_PATTERNS) &&
    matchesAny(message, PACKAGED_WORLD_CONTEXT_MODE_PATTERNS) &&
    !matchesAny(message, PACKAGED_WORLD_CONTEXT_UNSAFE_ACTION_PATTERNS)
  );
}

function hasDesktopSaveExportSignal(message: string): boolean {
  return matchesAny(message, LOCAL_FILE_BENIGN_SAVE_PATTERNS);
}

function hasDesktopWriteSideEffectSignal(message: string): boolean {
  return matchesAny(message, LOCAL_FILE_SIDE_EFFECT_PATTERNS) || matchesAny(message, LOCAL_FILE_DESTRUCTIVE_PATTERNS);
}

function hasDesktopActionSignal(message: string): boolean {
  return hasDesktopPrivateDataSignal(message) || hasDesktopSaveExportSignal(message) || hasDesktopWriteSideEffectSignal(message);
}

// Capabilities that can ONLY be satisfied on the user's desktop runtime.
// Cloud-doable capabilities (document_write, web_research, document_read for
// in-message attachments, data_analyze, generate_response, reason, summarize,
// transform_chunks, image_ocr, file_transform, document_parse, email_draft)
// are intentionally excluded — the server brain handles them inline.
const DESKTOP_ONLY_CAPABILITIES = new Set<string>([
  "shell_run",
  "filesystem_read",
  "filesystem_write",
  "app_control",
  "open_app",
  "close_app",
  "screen_context",
  "analyze_screen",
  "terminal",
  "recent_files",
  "browser_control",
  "computer_control",
  "add_calendar_event",
  "add_reminder",
  "email_send",
]);

function isDesktopOnlyCapability(capability: string): boolean {
  const normalized = String(capability ?? "").trim().toLowerCase().replace(/[\s.]+/g, "_");
  return DESKTOP_ONLY_CAPABILITIES.has(normalized);
}

function buildSemanticCapabilitiesForRoute(input: {
  target: ExecutionTarget;
  executionPlan: Array<"mobile_local" | "server_brain" | "desktop_runtime">;
  hasAttachment: boolean;
  hasDesktopPrivateData: boolean;
  hasDesktopSaveExport: boolean;
  hasDesktopWriteSideEffect: boolean;
  primaryIntent: UnderstandingIntent;
}): string[] {
  const capabilities: string[] = [];

  if (input.executionPlan.includes("mobile_local")) {
    capabilities.push(...ROUTER_SEMANTIC_CAPABILITIES.mobile);
    capabilities.push("file_transform");
  }

  if (input.executionPlan.includes("server_brain")) {
    capabilities.push(...ROUTER_SEMANTIC_CAPABILITIES.server);
  }

  if (input.executionPlan.includes("desktop_runtime")) {
    capabilities.push(...ROUTER_SEMANTIC_CAPABILITIES.desktop);
  }

  if (input.hasAttachment) {
    capabilities.push("document_parse", "transform_chunks");
  }

  if (input.hasDesktopPrivateData) {
    capabilities.push("filesystem_read", "recent_files");
  }

  if (input.hasDesktopSaveExport || input.hasDesktopWriteSideEffect) {
    capabilities.push("filesystem_write", "file_transform");
  }

  if (input.primaryIntent === "image") {
    capabilities.push("image_ocr");
  }

  if (input.target === "server_brain") {
    capabilities.push("reason", "generate_response");
  } else if (input.target === "desktop_runtime") {
    capabilities.push("screen_context");
  } else if (input.target === "hybrid") {
    capabilities.push("reason", "generate_response");
  }

  return uniqueSemanticCapabilities(capabilities);
}

function buildDefaultExecutionPlan(input: {
  target: ExecutionTarget;
  hasAttachment: boolean;
  hasDesktopPrivateData: boolean;
  hasDesktopSaveExport: boolean;
}): Array<"mobile_local" | "server_brain" | "desktop_runtime"> {
  if (input.target === "server_brain") {
    return ["server_brain"];
  }

  if (input.target === "desktop_runtime") {
    return input.hasDesktopPrivateData ? ["desktop_runtime", "server_brain"] : ["desktop_runtime"];
  }

  if (input.target === "hybrid") {
    if (input.hasDesktopSaveExport) {
      return ["mobile_local", "desktop_runtime"];
    }
    if (input.hasAttachment || input.hasDesktopPrivateData) {
      return ["mobile_local", "server_brain"];
    }
    return ["mobile_local", "server_brain"];
  }

  return input.hasAttachment ? ["mobile_local", "server_brain"] : ["mobile_local"];
}

function buildTaskRoute(input: {
  target: ExecutionTarget;
  operationalRoute: "server_brain" | "desktop_runtime";
  executionPlan?: Array<"mobile_local" | "server_brain" | "desktop_runtime">;
  reason: string;
  needsDesktop: boolean;
  needsPrivateDesktopData: boolean;
  needsUserApproval: boolean;
  requiredCapabilities: string[];
}): TaskRoute {
  return {
    target: input.target,
    operationalRoute: input.operationalRoute,
    executionPlan: input.executionPlan ?? buildDefaultExecutionPlan({
      target: input.target,
      hasAttachment: input.requiredCapabilities.includes("document_parse"),
      hasDesktopPrivateData: input.needsPrivateDesktopData,
      hasDesktopSaveExport: input.requiredCapabilities.includes("filesystem_write"),
    }),
    reason: input.reason,
    needsDesktop: input.needsDesktop,
    needsPrivateDesktopData: input.needsPrivateDesktopData,
    needsUserApproval: input.needsUserApproval,
    requiredCapabilities: uniqueSemanticCapabilities(input.requiredCapabilities),
  };
}

function deriveRequiredRuntime(input: {
  route: CommandRoute;
  taskRoute?: TaskRoute | null;
  requiresLocalRuntime: boolean;
  capabilities: string[];
}): CommandRequiredRuntime {
  if (input.route === "desktop_runtime" || input.route === "pairing_required") {
    return "desktop";
  }
  if (input.taskRoute?.target === "hybrid") {
    return input.taskRoute.operationalRoute === "desktop_runtime" ? "desktop" : "both";
  }
  if (input.taskRoute?.target === "desktop_runtime") {
    return "desktop";
  }
  if (input.taskRoute?.target === "mobile_local") {
    return "both";
  }
  if (input.requiresLocalRuntime || input.capabilities.length > 0) {
    return "both";
  }
  return "server";
}

function deriveNormalizedIntent(input: {
  primaryIntent: UnderstandingIntent;
  route: CommandRoute;
  privacyClass: CommandPrivacyClass;
  capabilities: string[];
  message: string;
  confidence: number;
}): NormalizedCommandIntent {
  if (isMateriallyAmbiguousUserPrompt(input.message) || input.confidence < 0.55) {
    return "ambiguous_request";
  }
  if (input.route === "pairing_required" || input.route === "desktop_runtime") {
    if (input.privacyClass === "local_private") {
      return "local_file_request";
    }
    if (
      input.capabilities.includes("browser_control") ||
      input.capabilities.includes("computer_control") ||
      input.capabilities.includes("shell_run")
    ) {
      return "device_control_request";
    }
    if (input.capabilities.includes("document_read")) {
      return "private_data_request";
    }
    return "desktop_required";
  }
  if (input.primaryIntent === "planning") {
    return "planning_request";
  }
  if (input.route === "unavailable") {
    return "unsupported_request";
  }
  return "normal_chat";
}

function deriveSelectedWorkload(input: {
  route: CommandRoute;
  intent: NormalizedCommandIntent;
  message: string;
  primaryIntent: UnderstandingIntent;
  brainProfile?: PlanBrainProfile | null;
}): SharedBrainWorkload {
  if (input.route === "desktop_runtime" || input.route === "pairing_required" || input.route === "unavailable") {
    return "desktop_handoff";
  }
  if (input.intent === "planning_request") {
    return "planning";
  }
  if (isExplicitTableRequest(input.message)) {
    return "table_generate";
  }
  // Belge/rapor ÜRETME isteği → document_generate workload (model document_block
  // üretir). Bu olmadan mobildeki document_block / pdf kartları HİÇ veri almıyordu
  // çünkü hiçbir kod bu workload'u seçmiyordu. Mevcut içeriği export eden istekler
  // (MOBILE_DOCUMENT_EXPORT) ve ek-okuma istekleri buraya düşmez; sadece açık
  // üretme fiilleri (yaz/hazırla/oluştur/üret) + belge-türü isim eşleşince tetiklenir.
  if (matchesAny(input.message, DOCUMENT_GENERATE_PATTERNS) || matchesAny(input.message, DOCUMENT_OUTPUT_GENERATE_PATTERNS)) {
    return "document_generate";
  }
  if (isExplicitMathSurface3DRequest(input.message) || isExplicitChartRequest(input.message) || isExplicitMathOrLatexRequest(input.message)) {
    return "mobile_chat_balanced";
  }
  return selectHybridMobileChatWorkload({
    message: input.message,
    primaryIntent: input.primaryIntent,
    brainProfile: input.brainProfile ?? undefined,
  });
}

function buildDecision(input: {
  route: CommandRoute;
  taskRoute?: TaskRoute | null;
  mode: CommandMode;
  capabilities: string[];
  privacyClass: CommandPrivacyClass;
  requiresApproval: boolean;
  reason: string;
  userFacingMessage?: string;
  primaryIntent: UnderstandingIntent;
  confidence: number;
  requiresLocalRuntime: boolean;
  message: string;
  brainProfile?: unknown;
  failClosedReason?: string | null;
  selectedWorkloadOverride?: SharedBrainWorkload;
}): CommandRouteDecision {
  const intent = deriveNormalizedIntent({
    primaryIntent: input.primaryIntent,
    route: input.route,
    privacyClass: input.privacyClass,
    capabilities: input.capabilities,
    message: input.message,
    confidence: input.confidence,
  });

  return {
    route: input.route,
    taskRoute: input.taskRoute ?? undefined,
    mode: input.mode,
    capabilities: input.capabilities,
    privacyClass: input.privacyClass,
    requiresApproval: input.requiresApproval,
    reason: input.reason,
    userFacingMessage: input.userFacingMessage,
    intent,
    confidence: Number(input.confidence.toFixed(2)),
    requiredRuntime: deriveRequiredRuntime({
      route: input.route,
      taskRoute: input.taskRoute ?? null,
      requiresLocalRuntime: input.requiresLocalRuntime,
      capabilities: input.capabilities,
    }),
    privacyLevel:
      input.privacyClass === "local_private"
        ? "high"
        : input.privacyClass === "side_effect"
          ? "medium"
          : "low",
    shouldAskClarification: intent === "ambiguous_request",
    failClosedReason:
      input.failClosedReason ??
      (input.route === "pairing_required" || input.route === "unavailable"
        ? input.reason
        : null),
    selectedWorkload:
      input.selectedWorkloadOverride ??
      deriveSelectedWorkload({
        route: input.route,
        intent,
        message: input.message,
        primaryIntent: input.primaryIntent,
        brainProfile: normalizePlanBrainProfile(input.brainProfile),
      }),
  };
}

function intentToCapabilities(intent: UnderstandingIntent, message: string, isResearchLike: boolean): string[] {
  const capabilities = new Set<string>();
  if (isResearchLike) {
    capabilities.add("web_research");
  }
  if (matchesAny(message, EMAIL_SIDE_EFFECT_PATTERNS) || extractEmailAddresses(message).length > 0) {
    capabilities.add("email_draft");
    capabilities.add("email_send");
  }
  if (matchesAny(message, EMAIL_DRAFT_PATTERNS)) {
    capabilities.add("email_draft");
  }
  if (matchesAny(message, LOCAL_PRIVATE_PATTERNS)) {
    capabilities.add("document_read");
  }
  if (matchesAny(message, LOCAL_FILE_SIDE_EFFECT_PATTERNS)) {
    capabilities.add("document_write");
  }
  if (intent === "browser") {
    capabilities.add("browser_control");
  }
  if (intent === "computer") {
    capabilities.add("computer_control");
  }
  if (intent === "automation") {
    capabilities.add("shell_run");
  }
  if (matchesAny(message, QUANTUM_TOPIC_PATTERNS) && matchesAny(message, QUANTUM_EXECUTION_PATTERNS)) {
    for (const capability of QUANTUM_CAPABILITIES) {
      capabilities.add(capability);
    }
  }
  return [...capabilities];
}

function determinePrivacyClass(
  capabilities: string[],
  message: string,
  options: { packagedWorldContext?: boolean } = {},
): CommandPrivacyClass {
  if (capabilities.includes("email_send") || capabilities.includes("shell_run") || capabilities.includes("document_write")) {
    return "side_effect";
  }
  if (capabilities.includes("email_draft")) {
    return "public_text";
  }
  if (options.packagedWorldContext) {
    return "public_text";
  }
  if (capabilities.includes("document_read") || matchesAny(message, LOCAL_PRIVATE_PATTERNS)) {
    return "local_private";
  }
  return "public_text";
}

function determineMode(capabilities: string[], intent: UnderstandingIntent): CommandMode {
  if (capabilities.includes("email_send")) {
    return capabilities.includes("web_research") || intent === "research" ? "mixed_task" : "executable_task";
  }
  if (capabilities.includes("email_draft")) {
    return capabilities.includes("web_research") || intent === "research" ? "mixed_task" : "executable_task";
  }
  if (capabilities.some((capability) => capability !== "web_research")) {
    return "executable_task";
  }
  return intent === "research" || capabilities.includes("web_research") ? "chat" : "chat";
}

function isServerBrainPublicCapability(capability: string): boolean {
  const normalized = String(capability ?? "").trim().toLowerCase().replace(/[\s.]+/g, "_");
  return normalized === "web_research";
}

function resolveDesktopUnavailableMessage(candidates: {
  selectedDevice: { canReceiveTasks: boolean } | null;
  canUseSelectedDevice: boolean;
}): string {
  if (candidates.selectedDevice && !candidates.canUseSelectedDevice) {
    return "PC çevrimdışı, döndüğünde çalıştırılacak.";
  }
  return "Bu görev için önce bir masaüstü eşleştirmen gerekiyor.";
}

async function resolveDesktopCandidates(
  app: FastifyInstance,
  userId: string,
  requestedCapabilities: string[],
  selectedDeviceId?: string,
) {
  const normalizedRequestedCapabilities = normalizeRuntimeCapabilities(requestedCapabilities);
  const normalizedSelectedDeviceId = selectedDeviceId?.trim() ?? "";
  if (normalizedSelectedDeviceId) {
    const ownedDevice = await getUserDevice(app, userId, normalizedSelectedDeviceId);
    if (ownedDevice?.type === "desktop") {
      const availableCapabilities = normalizeRuntimeCapabilities(ownedDevice.runtime.capabilities);
      const supportsRequested = supportsRequestedCapabilities(availableCapabilities, normalizedRequestedCapabilities);
      return {
        selectedDevice: ownedDevice,
        canUseSelectedDevice: ownedDevice.canReceiveTasks && supportsRequested,
        missingCapabilities: supportsRequested
          ? []
          : missingRuntimeCapabilities(ownedDevice.runtime.capabilities, normalizedRequestedCapabilities),
      };
    }
  }

  const devices = await listUserDevices(app, userId);
  const desktop = devices.find(
    (device) =>
      device.type === "desktop" &&
      device.canReceiveTasks &&
      supportsRequestedCapabilities(device.runtime.capabilities, normalizedRequestedCapabilities),
  );

  return {
    selectedDevice: desktop ?? null,
    canUseSelectedDevice: Boolean(desktop),
    missingCapabilities: desktop ? [] : normalizedRequestedCapabilities,
  };
}

function stripDocumentPayload(message: string): string {
  const documentRegex = /---\s+(.+?)\s+---\n.*?--- BELGE SONU: \1 ---[\n]?/gs;
  const summaryRegex = /\n?Ekler: (.+)$/m;
  let stripped = message.replace(documentRegex, "").trim();
  stripped = stripped.replace(summaryRegex, "").trim();
  return stripped;
}

function parseTaskRouteFallbackResponse(rawText: string): TaskRoute | null {
  const compact = String(rawText ?? "").trim();
  if (!compact) {
    return null;
  }

  const startIndex = compact.indexOf("{");
  const endIndex = compact.lastIndexOf("}");
  if (startIndex < 0 || endIndex <= startIndex) {
    return null;
  }

  try {
    const parsed = JSON.parse(compact.slice(startIndex, endIndex + 1)) as Record<string, unknown>;
    const target = typeof parsed.target === "string" ? parsed.target.trim() : "";
    const operationalRoute =
      typeof parsed.operationalRoute === "string" ? parsed.operationalRoute.trim() : "";
    const executionPlan = Array.isArray(parsed.executionPlan)
      ? uniqueSemanticCapabilities(parsed.executionPlan.map((value) => String(value ?? "").trim()))
          .filter((value) => value === "mobile_local" || value === "server_brain" || value === "desktop_runtime")
      : [];
    const reason = typeof parsed.reason === "string" ? parsed.reason.trim() : "";
    const needsDesktop = Boolean(parsed.needsDesktop);
    const needsPrivateDesktopData = Boolean(parsed.needsPrivateDesktopData);
    const needsUserApproval = Boolean(parsed.needsUserApproval);
    const requiredCapabilities = Array.isArray(parsed.requiredCapabilities)
      ? uniqueSemanticCapabilities(parsed.requiredCapabilities.map((value) => String(value ?? "").trim()))
      : [];

    if (
      (target !== "server_brain" &&
        target !== "mobile_local" &&
        target !== "desktop_runtime" &&
        target !== "hybrid") ||
      (operationalRoute !== "server_brain" && operationalRoute !== "desktop_runtime") ||
      !reason
    ) {
      return null;
    }

    if (target === "desktop_runtime") {
      return null;
    }

    if (operationalRoute === "server_brain" && !executionPlan.includes("server_brain")) {
      return null;
    }

    if (operationalRoute === "desktop_runtime" && !needsDesktop) {
      return null;
    }

    if (executionPlan.includes("desktop_runtime") && !needsDesktop) {
      return null;
    }

    return {
      target: target as TaskRoute["target"],
      operationalRoute: operationalRoute as TaskRoute["operationalRoute"],
      executionPlan:
        executionPlan.length > 0
          ? executionPlan
          : operationalRoute === "desktop_runtime"
            ? ["desktop_runtime"]
            : ["server_brain"],
      reason,
      needsDesktop,
      needsPrivateDesktopData,
      needsUserApproval,
      requiredCapabilities,
    };
  } catch {
    return null;
  }
}

async function resolveAmbiguousTaskRouteFallback(
  app: FastifyInstance,
  input: {
    userId: string;
    message: string;
    brainProfile?: unknown;
    promptSummary: string;
  },
): Promise<TaskRoute | null> {
  let responseText = "";
  try {
    const response = await generateSharedBrainReply(app, {
      userId: input.userId,
      prompt: [
        "Route this Elyan request. Return only JSON with no extra text.",
        "Allowed target values: server_brain, mobile_local, desktop_runtime, hybrid.",
        "Allowed operationalRoute values: server_brain, desktop_runtime.",
        'Allowed executionPlan values: ["mobile_local"], ["server_brain"], ["desktop_runtime"], ["mobile_local","server_brain"], ["mobile_local","desktop_runtime"], ["desktop_runtime","server_brain"].',
        "Set needsDesktop=true and operationalRoute=desktop_runtime ONLY when the request requires: local file read/write, browser control (click/navigate/scrape), computer control (screenshot/keyboard/mouse/window), app launch/quit, terminal/shell commands, screen recording, or local notifications/calendar.",
        "The server brain handles: writing, reasoning, math, research, code generation, document summarization, image analysis, memory recall, and any cloud-solvable task.",
        "Never set needsDesktop true for tasks the server brain can do without local OS access.",
        "If uncertain and no desktop is needed, choose server_brain.",
        `User request: ${input.message}`,
        `Router summary: ${input.promptSummary}`,
      ].join("\n"),
      workload: "fast_route",
      brainProfile: input.brainProfile,
      internalEvaluation: {
        skipUsageValidation: true,
        skipInvocationLogging: true,
        skipReviewLogging: true,
      },
    });
    responseText = response.text;
  } catch {
    return null;
  }

  const parsed = parseTaskRouteFallbackResponse(responseText);
  if (!parsed) {
    return null;
  }

  if (parsed.needsDesktop && parsed.operationalRoute !== "desktop_runtime") {
    return null;
  }

  if (!parsed.needsDesktop && parsed.operationalRoute === "desktop_runtime") {
    return null;
  }

  if (!parsed.needsDesktop && parsed.executionPlan.includes("desktop_runtime")) {
    return null;
  }

  return parsed;
}

// Strong, explicit signals that a message needs the LOCAL desktop machine.
// Used ONLY to decide, when the dispatch toggle is on, whether to hand a message
// off to desktop vs answer it normally on the server. Intentionally conservative
// — it looks for possessive/local markers (bilgisayarım, masaüstüm, yerel),
// screen/terminal/shell, or explicit app/device control, not generic words.
const DESKTOP_TASK_PATTERNS: RegExp[] = [
  /(bilgisayar[ıi]m|masa[üu]st[üu]|yerel|local\b|finder|explorer)/i,
  /(klas[öo]r|indirilenler|belgelerim|downloads folder|my files?)/i,
  /(ekran g[öo]r[üu]nt[üu]s[üu]|screenshot|ekran[ıi]m)/i,
  /(terminal|komut sat[ıi]r|\bshell\b|command line|komut[ıi]? [çc]al[ıi][şs]t[ıi]r|run a command)/i,
  /(uygulamay[ıi]|program[ıi]|vs ?code|visual studio code|chrome'?u|safari'?yi)\s*\w*\s*(a[çc]|ba[şs]lat|kapat)/i,
  /(ekran parlakl[ıi]|sistem ayar|wifi|bluetooth)/i,
  /(open|read|list|delete|index|move|rename)\b.{0,24}\b(file|folder|directory|app|screenshot|terminal)/i,
];

function messageLikelyNeedsDesktop(message: string): boolean {
  const normalized = String(message ?? "").toLocaleLowerCase("tr-TR");
  if (!normalized.trim()) {
    return false;
  }
  return DESKTOP_TASK_PATTERNS.some((pattern) => pattern.test(normalized));
}

export async function decideCommandRoute(
  app: FastifyInstance,
  input: CommandRouteInput,
): Promise<CommandRouteDecision> {
  // SINGLE source of truth: the mobile user toggles a "dispatch to desktop"
  // button. Every prior keyword/intent heuristic is gone — they produced more
  // wrong decisions than right ones. If the toggle says desktop and a ready
  // desktop is available, route there. Otherwise the server brain handles it.
  const message = normalizeMessage(stripDocumentPayload(input.message));
  const metadata = readRecord(input.metadata) ?? {};
  const desktopAllowed = input.desktopAllowed ?? true;
  const classification = classifyIntent({
    userId: input.userId,
    accountId: input.userId,
    message: input.message,
    routeContext: "command_route",
    source: input.source,
    metadata: {
      selectedDeviceId: input.selectedDeviceId,
      requestedCapabilities: input.requestedCapabilities ?? [],
    },
  });

  // `desktopDispatch` (the laptop toggle) means "I have a desktop available for
  // tasks that need it" — NOT "send literally everything to the desktop". With
  // the toggle on we still answer normal chat / knowledge questions on the
  // server brain, and only hand off messages that genuinely need the local
  // machine (files, screen, terminal, app control). Otherwise toggling the
  // button silently broke ordinary conversation. The check is conservative:
  // bias toward answering normally, since blocking chat is worse than running a
  // clearly-local task on the server (which will just say it lacks local access).
  const userWantsDesktop = metadata.desktopDispatch === true;
  const dispatchToDesktop = userWantsDesktop && messageLikelyNeedsDesktop(message);

  if (dispatchToDesktop) {
    if (!desktopAllowed) {
      const taskRoute = buildTaskRoute({
        target: "desktop_runtime",
        operationalRoute: "desktop_runtime",
        executionPlan: ["desktop_runtime"],
        reason: "Masaüstü bağlantısı yalnızca Pro planında kullanılabilir.",
        needsDesktop: true,
        needsPrivateDesktopData: false,
        needsUserApproval: false,
        requiredCapabilities: [],
      });
      return buildDecision({
        route: "pairing_required",
        taskRoute,
        mode: "executable_task",
        capabilities: [],
        privacyClass: "local_private",
        requiresApproval: false,
        reason: "Masaüstü dispatch açık ama plan izin vermiyor.",
        userFacingMessage: "Masaüstü bağlantısı yalnızca Pro planında kullanılabilir.",
        primaryIntent: classification.primaryIntent,
        confidence: classification.confidence,
        requiresLocalRuntime: true,
        message,
        failClosedReason: "desktop_plan_required",
      });
    }

    const candidates = await resolveDesktopCandidates(
      app,
      input.userId,
      input.requestedCapabilities ?? [],
      input.selectedDeviceId,
    );
    if (candidates.selectedDevice && candidates.canUseSelectedDevice) {
      const taskRoute = buildTaskRoute({
        target: "desktop_runtime",
        operationalRoute: "desktop_runtime",
        executionPlan: ["desktop_runtime"],
        reason: "Kullanıcı dispatch butonu ile bu görevi masaüstüne yönlendirdi.",
        needsDesktop: true,
        needsPrivateDesktopData: false,
        needsUserApproval: false,
        requiredCapabilities: input.requestedCapabilities ?? [],
      });
      return buildDecision({
        route: "desktop_runtime",
        taskRoute,
        mode: "executable_task",
        capabilities: input.requestedCapabilities ?? [],
        privacyClass: "local_private",
        requiresApproval: false,
        reason: "Kullanıcı dispatch butonu ile bu görevi masaüstüne yönlendirdi.",
        userFacingMessage: "Bu görev masaüstünde çalışacak.",
        primaryIntent: classification.primaryIntent,
        confidence: classification.confidence,
        requiresLocalRuntime: true,
        message,
        failClosedReason: "desktop_runtime_selected_target",
      });
    }

    // Toggle ON but no ready desktop — surface a friendly pairing prompt.
    const taskRoute = buildTaskRoute({
      target: "desktop_runtime",
      operationalRoute: "desktop_runtime",
      executionPlan: ["desktop_runtime"],
      reason: "Dispatch açık ama bağlı bir masaüstü bulunamadı.",
      needsDesktop: true,
      needsPrivateDesktopData: false,
      needsUserApproval: false,
      requiredCapabilities: input.requestedCapabilities ?? [],
    });
    return buildDecision({
      route: "pairing_required",
      taskRoute,
      mode: "executable_task",
      capabilities: input.requestedCapabilities ?? [],
      privacyClass: "local_private",
      requiresApproval: false,
      reason: "Dispatch açık ama bağlı bir masaüstü bulunamadı.",
      userFacingMessage: resolveDesktopUnavailableMessage(candidates),
      primaryIntent: classification.primaryIntent,
      confidence: classification.confidence,
      requiresLocalRuntime: true,
      message,
      failClosedReason: "pairing_required",
    });
  }

  // Default path: server brain answers everything else.
  return buildDecision({
    route: "server_brain",
    taskRoute: buildTaskRoute({
      target: "server_brain",
      operationalRoute: "server_brain",
      executionPlan: ["server_brain"],
      reason: "Sohbet veya bilgi isteği sunucu beyninde çözülecek.",
      needsDesktop: false,
      needsPrivateDesktopData: false,
      needsUserApproval: false,
      requiredCapabilities: [],
    }),
    mode: "chat",
    capabilities: [],
    privacyClass: "public_text",
    requiresApproval: false,
    reason: "Sohbet veya bilgi isteği sunucu beyninde çözülecek.",
    userFacingMessage: "Bu istek sohbet olarak işlenecek.",
    primaryIntent: classification.primaryIntent,
    confidence: classification.confidence,
    requiresLocalRuntime: false,
    message,
    brainProfile: input.brainProfile,
  });
}


async function getDefaultDesktopTaskTarget(
  app: FastifyInstance,
  userId: string,
  requestedCapabilities: string[] = [],
) {
  const devices = await listUserDevices(app, userId);
  return (
    devices.find(
      (device) =>
        device.type === "desktop" &&
        device.canReceiveTasks &&
        supportsRequestedCapabilities(device.runtime.capabilities, requestedCapabilities),
    ) ?? null
  );
}

export async function resolvePendingDesktopQueueTarget(
  app: FastifyInstance,
  userId: string,
  targetDeviceId?: string,
  requestedCapabilities: string[] = [],
): Promise<ResolvedCommandTarget | null> {
  const normalizedRequestedCapabilities = normalizeRuntimeCapabilities(requestedCapabilities);
  const normalizedTargetDeviceId = targetDeviceId?.trim() ?? "";

  if (normalizedTargetDeviceId) {
    const ownedDevice = await getUserDevice(app, userId, normalizedTargetDeviceId);
    if (
      !ownedDevice ||
      ownedDevice.type !== "desktop" ||
      !ownedDevice.isActive ||
      ownedDevice.targetStatus === "plan_restricted"
    ) {
      return null;
    }
    return {
      device: ownedDevice,
      isSharedBrain: false,
    };
  }

  const userDevices = await listUserDevices(app, userId);
  const activeDesktops = userDevices.filter(
    (device) => device.type === "desktop" && device.isActive && device.targetStatus !== "plan_restricted",
  );
  const capableDesktop = activeDesktops.find((device) =>
    supportsRequestedCapabilities(device.runtime.capabilities, normalizedRequestedCapabilities),
  );
  const unknownCapabilityDesktop = activeDesktops.find(
    (device) => normalizeRuntimeCapabilities(device.runtime.capabilities).length === 0,
  );
  const desktopTarget = capableDesktop ?? unknownCapabilityDesktop ?? activeDesktops[0] ?? null;

  return desktopTarget
    ? {
        device: desktopTarget,
        isSharedBrain: false,
      }
    : null;
}

export async function resolveCommandTarget(
  app: FastifyInstance,
  userId: string,
  targetDeviceId?: string,
  purpose: RoutingPurpose = "task",
  requestedCapabilities: string[] = [],
): Promise<ResolvedCommandTarget> {
  const normalizedRequestedCapabilities = normalizeRuntimeCapabilities(requestedCapabilities);
  const normalizedTargetDeviceId = targetDeviceId?.trim() ?? "";
  if (normalizedTargetDeviceId) {
    const ownedDevice = await getUserDevice(app, userId, normalizedTargetDeviceId);

    if (ownedDevice?.type === "desktop") {
      assertOwnedDesktopTaskTarget(ownedDevice, normalizedTargetDeviceId);
      if (
        purpose === "task" &&
        normalizedRequestedCapabilities.length > 0 &&
        !supportsRequestedCapabilities(ownedDevice.runtime.capabilities, normalizedRequestedCapabilities)
      ) {
        throw createRuntimeCapabilityMismatchError({
          targetDeviceId: normalizedTargetDeviceId,
          requestedCapabilities: normalizedRequestedCapabilities,
          availableCapabilities: normalizeRuntimeCapabilities(ownedDevice.runtime.capabilities),
          missingCapabilities: missingRuntimeCapabilities(
            ownedDevice.runtime.capabilities,
            normalizedRequestedCapabilities,
          ),
        });
      }
      return {
        device: ownedDevice,
        isSharedBrain: false,
      };
    }

    const sharedBrainDevice = await getSharedBrainTargetDevice(app);
    if (sharedBrainDevice && sharedBrainDevice.id === normalizedTargetDeviceId) {
      if (purpose === "task") {
        throw createInvalidTargetDeviceError(normalizedTargetDeviceId);
      }
      return {
        device: sharedBrainDevice,
        isSharedBrain: true,
      };
    }

    throw createInvalidTargetDeviceError(normalizedTargetDeviceId);
  }

  if (purpose === "task") {
    const desktopTarget = await getDefaultDesktopTaskTarget(app, userId, normalizedRequestedCapabilities);

    if (desktopTarget) {
      return {
        device: desktopTarget,
        isSharedBrain: false,
      };
    }

    if (normalizedRequestedCapabilities.length > 0) {
      throw createRuntimeCapabilityMismatchError({
        targetDeviceId: "desktop",
        requestedCapabilities: normalizedRequestedCapabilities,
        availableCapabilities: [],
        missingCapabilities: normalizedRequestedCapabilities,
      });
    }
  }

  const sharedBrainDevice = await getSharedBrainTargetDevice(app);
  if (!sharedBrainDevice) {
    throw createInvalidTargetDeviceError("shared-brain");
  }

  return {
    device: sharedBrainDevice,
    isSharedBrain: true,
  };
}

export async function routeChatTurn(
  app: FastifyInstance,
  input: Parameters<typeof decideCommandRoute>[1],
): Promise<CommandRouteDecision> {
  return decideCommandRoute(app, input);
}
