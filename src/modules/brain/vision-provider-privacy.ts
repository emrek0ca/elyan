export const VISION_PROVIDER_NAME_PATTERN =
  /(?<!\p{L})(?:(?:according to|per|as stated by)\s+(?:gemini|groq|google ai|llama(?:\s+vision)?|openai|chatgpt|claude|anthropic)|(?:gemini|groq|google ai|llama(?:\s+vision)?|openai|chatgpt|claude|anthropic)(?:['’](?:ye|ya)|ye|ya)?\s+göre|(?:gemini|groq|google ai|llama(?:\s+vision)?|openai|chatgpt|claude|anthropic)\s+(?:says?|reports?|belirtiyor|söylüyor|soyluyor)|(?:gemini|groq|google ai|llama(?:\s+vision)?|openai|chatgpt|claude|anthropic)\s+ile\s+(?:bunu|şunu|sunu|görüntüyü|goruntuyu|gördü\p{L}*|gordu\p{L}*|analiz\p{L}*)(?:\s+\p{L}+){0,4}|(?:using|with|via|tarafından|tarafindan)\s+(?:gemini|groq|google ai|llama(?:\s+vision)?|openai|chatgpt|claude|anthropic))(?!\p{L})/giu;

export function stripVisionProviderAttribution(value: string): string {
  const provider = "(?:gemini|groq|google ai|llama(?:\\s+vision)?|openai|chatgpt|claude|anthropic)";
  return String(value ?? "")
    .replace(new RegExp(`(?:according to|per|as stated by)\\s+${provider}\\s*[,;:]?\\s*`, "giu"), "")
    .replace(new RegExp(`${provider}(?:['’](?:ye|ya)|ye|ya)?\\s+göre\\s*[,;:]?\\s*`, "giu"), "")
    .replace(new RegExp(`${provider}\\s+(?:says?|reports?|belirtiyor|söylüyor|soyluyor)\\s*[:;,]?\\s*`, "giu"), "")
    .replace(new RegExp(`${provider}\\s+ile\\s+(?:bunu|şunu|sunu|görüntüyü|goruntuyu|gördü\\p{L}*|gordu\\p{L}*|analiz\\p{L}*)(?:\\s+\\p{L}+){0,4}\\s*`, "giu"), "")
    .replace(new RegExp(`(?:using|with|via|tarafından|tarafindan)\\s+${provider}`, "giu"), "")
    .replace(/\(\s*\)|\[\s*\]/g, "")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/^[,;:\s]+/u, "");
}
