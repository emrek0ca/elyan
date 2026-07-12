export const VISION_PROVIDER_NAME_PATTERN = /\b(?:gemini|groq|google ai|llama(?:\s+vision)?|openai|chatgpt|claude|anthropic)\b/giu;

export function stripVisionProviderAttribution(value: string): string {
  const provider = "(?:gemini|groq|google ai|llama(?:\\s+vision)?|openai|chatgpt|claude|anthropic)";
  return String(value ?? "")
    .replace(new RegExp(`(?:according to|per|as stated by)\\s+${provider}\\s*[,;:]?\\s*`, "giu"), "")
    .replace(new RegExp(`${provider}(?:['’](?:ye|ya)|ye|ya)?\\s+göre\\s*[,;:]?\\s*`, "giu"), "")
    .replace(new RegExp(`${provider}\\s+(?:says?|reports?|belirtiyor|söylüyor|soyluyor)\\s*[:;,]?\\s*`, "giu"), "")
    .replace(new RegExp(`(?:using|with|via|tarafından|tarafindan)\\s+${provider}`, "giu"), "")
    .replace(VISION_PROVIDER_NAME_PATTERN, "")
    .replace(/\(\s*\)|\[\s*\]/g, "")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/^[,;:\s]+/u, "");
}
