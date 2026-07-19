import type { SharedBrainConversationMessage } from "./provider-request.js";
import { sanitizeAssistantVisibleText } from "../chat/message-blocks.js";

type MobileLocalExportShortcutInput = {
  prompt: string;
  conversation?: SharedBrainConversationMessage[];
  requestMetadata?: Record<string, unknown>;
  attachmentContextUsed?: boolean;
};

function compactText(value: unknown): string {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeMetadataValue(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s.-]+/g, "_");
}

const EXPORT_FORMAT_TOKENS = new Set([
  "pdf",
  "docx",
  "word",
  "xlsx",
  "excel",
  "csv",
  "svg",
  "png",
  "jpg",
  "jpeg",
  "webp",
]);

const PURE_EXPORT_TOKENS = new Set([
  ...EXPORT_FORMAT_TOKENS,
  "bu",
  "bunu",
  "şu",
  "şunu",
  "onu",
  "önceki",
  "onceki",
  "yukarıdaki",
  "yukaridaki",
  "cevap",
  "cevabı",
  "cevabi",
  "yanıt",
  "yanit",
  "yanıtı",
  "yaniti",
  "metin",
  "metni",
  "içerik",
  "icerik",
  "içeriği",
  "icerigi",
  "belge",
  "belgeyi",
  "doküman",
  "dokuman",
  "dokümanı",
  "dokumani",
  "dosya",
  "dosyası",
  "dosyasi",
  "tablo",
  "tabloyu",
  "çizelge",
  "cizelge",
  "çizelgeyi",
  "cizelgeyi",
  "olarak",
  "formatında",
  "formatinda",
  "formatına",
  "formatina",
  "ver",
  "hazırla",
  "hazirla",
  "oluştur",
  "olustur",
  "dönüştür",
  "donustur",
  "çevir",
  "cevir",
  "kaydet",
  "yap",
  "üret",
  "uret",
  "dışa",
  "disa",
  "aktar",
  "export",
  "save",
  "convert",
  "create",
  "make",
  "please",
  "lütfen",
  "lutfen",
  "ve",
  "de",
  "da",
]);

const EXPORT_ENRICHMENT_PATTERN =
  /\b(araştır|arastir|research|incele|analiz|analyze|karşılaştır|karsilastir|compare|doğrula|dogrula|verify|kaynak|source|internetten|webden|online|özetle|ozetle|summarize|yeniden yaz|rewrite|revize|güncelle|guncelle|update|profesyonel|professional|detaylandır|detaylandir|genişlet|genislet|expand)\b/iu;

function exportPromptTokens(prompt: string): string[] {
  return compactText(prompt)
    .toLocaleLowerCase("tr-TR")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
}

function isPureExistingContentExportPrompt(
  prompt: string,
  acceptedFormats: ReadonlySet<string>,
): boolean {
  const normalizedPrompt = compactText(prompt);
  if (!normalizedPrompt || EXPORT_ENRICHMENT_PATTERN.test(normalizedPrompt)) {
    return false;
  }
  const tokens = exportPromptTokens(normalizedPrompt);
  return (
    tokens.some((token) => acceptedFormats.has(token)) &&
    tokens.every((token) => PURE_EXPORT_TOKENS.has(token))
  );
}

function requestsCurrentTurnArtifact(
  metadata: Record<string, unknown> | undefined,
): boolean {
  const intent = normalizeMetadataValue(metadata?.documentExportIntent);
  const source = normalizeMetadataValue(metadata?.artifactContentSource);
  return (
    intent === "generate_and_export" ||
    intent === "research_then_export" ||
    intent === "new_content" ||
    source === "current_turn"
  );
}

export function isMobileLocalExportMode(
  metadata: Record<string, unknown> | undefined,
): boolean {
  if (!metadata) {
    return false;
  }

  if (
    metadata.mobileDocumentExport === true ||
    metadata.mobileLocalExport === true ||
    metadata.documentExportReady === true
  ) {
    return true;
  }

  const mode = normalizeMetadataValue(
    metadata.documentExportMode ??
      metadata.outputMode ??
      metadata.localExportMode ??
      metadata.documentOutputMode,
  );
  return (
    mode === "mobile_local" ||
    mode === "local" ||
    mode === "mobile_export" ||
    mode === "on_device" ||
    mode === "on_device_export"
  );
}

export function isLikelyPureDocumentExportPrompt(prompt: string): boolean {
  return isPureExistingContentExportPrompt(
    prompt,
    new Set(["pdf", "docx", "word", "xlsx", "excel", "csv"]),
  );
}

function isLikelyPureMobileLocalExportPrompt(prompt: string): boolean {
  return isPureExistingContentExportPrompt(
    prompt,
    EXPORT_FORMAT_TOKENS,
  );
}

function looksLikeDesktopHandoffMessage(text: string): boolean {
  return /\b(masaüstü|masaustu|desktop|pairing|eşleştir|eslestir|runtime)\b/i.test(
    compactText(text).toLowerCase(),
  );
}

// Hardcoded so legacy ack strings already stored in DB sessions are still
// filtered after buildSharedBrainAckText was changed to return "".
const TRANSIENT_ASSISTANT_ACKS = new Set([
  "bir saniye, bakıyorum",
  "anladım, planı çıkarıyorum",
  "anladım, biraz daha derin bakıyorum",
  "belge hazırlanıyor, birkaç saniye",
  "rapor hazırlanıyor, birkaç saniye",
  "hazırlanıyor",
  "yanıt hazırlanıyor",
  "yanıt sıraya alındı",
  "yanıt yeniden deneniyor",
]);

function isLikelyTransientAssistantAck(text: string): boolean {
  const normalized = compactText(text)
    .toLocaleLowerCase("tr-TR")
    .replace(/[.!…]+$/u, "")
    .trim();
  return TRANSIENT_ASSISTANT_ACKS.has(normalized);
}

export function getMostRecentAssistantMessage(
  conversation: SharedBrainConversationMessage[] | undefined,
): string | null {
  if (!conversation?.length) {
    return null;
  }

  for (let index = conversation.length - 1; index >= 0; index -= 1) {
    const item = conversation[index];
    if (
      item?.role === "assistant" &&
      compactText(item.content) &&
      !isLikelyTransientAssistantAck(item.content)
    ) {
      const sanitized = sanitizeAssistantVisibleText(item.content, {
        fallback: "",
      });
      if (sanitized.trim()) {
        return sanitized;
      }
    }
  }

  return null;
}

export function buildMobileLocalExportShortcutReply(
  input: MobileLocalExportShortcutInput,
): string | null {
  if (!isMobileLocalExportMode(input.requestMetadata)) {
    return null;
  }
  if (input.attachmentContextUsed === true) {
    return null;
  }
  if (requestsCurrentTurnArtifact(input.requestMetadata)) {
    return null;
  }
  if (!isLikelyPureMobileLocalExportPrompt(input.prompt)) {
    return null;
  }

  const assistantMessage = getMostRecentAssistantMessage(input.conversation);
  if (!assistantMessage || looksLikeDesktopHandoffMessage(assistantMessage)) {
    return null;
  }

  return assistantMessage;
}
