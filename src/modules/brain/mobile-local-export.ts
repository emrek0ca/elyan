import type { SharedBrainConversationMessage } from "./provider-request.js";
import { sanitizeAssistantVisibleText } from "../chat/message-blocks.js";

type MobileLocalExportShortcutInput = {
  prompt: string;
  conversation?: SharedBrainConversationMessage[];
  requestMetadata?: Record<string, unknown>;
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
  const normalizedPrompt = compactText(prompt).toLowerCase();
  if (!normalizedPrompt) {
    return false;
  }

  return (
    /\b(pdf|docx|word|belge|doküman|dokuman|rapor|sunum)\b.*\b(ver|hazırla|hazirla|oluştur|olustur|dönüştür|donustur|çevir|cevir|kaydet|düzenle|duzenle|yap|üret|uret)\b/i.test(
      normalizedPrompt,
    ) ||
    /\b(ver|hazırla|hazirla|oluştur|olustur|dönüştür|donustur|çevir|cevir|kaydet|düzenle|duzenle|yap|üret|uret)\b.*\b(pdf|docx|word|belge|doküman|dokuman|rapor|sunum)\b/i.test(
      normalizedPrompt,
    )
  );
}

function isLikelyPureMobileLocalExportPrompt(prompt: string): boolean {
  const normalizedPrompt = compactText(prompt).toLowerCase();
  if (!normalizedPrompt) {
    return false;
  }

  if (isLikelyPureDocumentExportPrompt(normalizedPrompt)) {
    return true;
  }

  return (
    /\b(görsel|gorsel|resim|image|png|jpg|jpeg|webp|svg|afiş|afis|poster|banner|kapak|thumbnail|screenshot)\b.*\b(ver|hazırla|hazirla|oluştur|olustur|dönüştür|donustur|çevir|cevir|kaydet|düzenle|duzenle|yap|üret|uret)\b/i.test(
      normalizedPrompt,
    ) ||
    /\b(ver|hazırla|hazirla|oluştur|olustur|dönüştür|donustur|çevir|cevir|kaydet|düzenle|duzenle|yap|üret|uret)\b.*\b(görsel|gorsel|resim|image|png|jpg|jpeg|webp|svg|afiş|afis|poster|banner|kapak|thumbnail|screenshot)\b/i.test(
      normalizedPrompt,
    )
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
  "bir saniye, bakıyorum.",
  "anladım, planı çıkarıyorum.",
  "anladım, biraz daha derin bakıyorum.",
  "belge hazırlanıyor, birkaç saniye...",
  "rapor hazırlanıyor, birkaç saniye...",
]);

function isLikelyTransientAssistantAck(text: string): boolean {
  return TRANSIENT_ASSISTANT_ACKS.has(compactText(text).toLowerCase());
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
  if (!isLikelyPureMobileLocalExportPrompt(input.prompt)) {
    return null;
  }

  const assistantMessage = getMostRecentAssistantMessage(input.conversation);
  if (!assistantMessage || looksLikeDesktopHandoffMessage(assistantMessage)) {
    return null;
  }

  return assistantMessage;
}
