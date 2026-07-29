const SINGLE_VALUE_MEMORY_KEYS = new Set([
  "name",
  "preferred_name",
  "preferred_language",
  "preferred_tone",
  "response_style_preference",
  "timezone",
  "job_title",
  "company",
  "location",
  "project",
  "active_project",
  "primary_repo",
  "working_boundary",
  "implementation_boundary",
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
  ["display_name", "preferred_name"],
  ["language", "preferred_language"],
  ["response_style", "response_style_preference"],
  ["current_project", "active_project"],
  ["repo", "primary_repo"],
  ["repository", "primary_repo"],
]);

export function resolveCanonicalMemoryKey(key: string): string {
  return MEMORY_KEY_ALIASES.get(key) ?? key;
}

export function isSingleValueMemoryKey(key: string): boolean {
  return SINGLE_VALUE_MEMORY_KEYS.has(resolveCanonicalMemoryKey(key));
}
