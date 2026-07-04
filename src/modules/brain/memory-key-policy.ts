const SINGLE_VALUE_MEMORY_KEYS = new Set([
  "name",
  "preferred_name",
  "preferred_language",
  "preferred_tone",
  "response_style_preference",
  "timezone",
]);

const MEMORY_KEY_ALIASES = new Map<string, string>([
  ["address_name", "preferred_name"],
  ["form_of_address", "preferred_name"],
  ["hitap_adı", "preferred_name"],
  ["hitap_adi", "preferred_name"],
  ["hitap_şekli", "preferred_name"],
  ["hitap_sekli", "preferred_name"],
  ["preferred_address", "preferred_name"],
  ["preferred_address_name", "preferred_name"],
]);

export function resolveCanonicalMemoryKey(key: string): string {
  return MEMORY_KEY_ALIASES.get(key) ?? key;
}

export function isSingleValueMemoryKey(key: string): boolean {
  return SINGLE_VALUE_MEMORY_KEYS.has(resolveCanonicalMemoryKey(key));
}
