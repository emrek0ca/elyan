import { distance as levenshteinDistance } from "fastest-levenshtein";
import { isSafeForLearning } from "./personalization-policy.js";
import { formatTurkicLanguageLabel } from "./turkic-language.js";
import type { MemoryProfileFact, MemoryProfileSnapshot, RetrievedMemory } from "./types.js";
import { collapseWhitespace as compactText } from "../../lib/text.js";

const MAX_FACTS_PER_SECTION = 4;
const MAX_SUMMARY_CHARS = 480;

const IDENTITY_LABELS: Record<string, string> = {
  name: "Ad",
  preferred_name: "Tercih edilen ad",
  role: "Rol",
  job_title: "Unvan",
  origin: "Köken",
  location: "Konum",
  timezone: "Saat dilimi",
  language: "Dil",
  pronouns: "Zamir",
  height: "Boy",
  age: "Yaş",
};

const PREFERENCE_LABELS: Record<string, string> = {
  preferred_tone: "Ton",
  response_style_preference: "Cevap stili",
  humor_level: "Mizah",
  answer_length: "Uzunluk",
  brevity_preference: "Kısalık",
  preferred_language: "Dil",
  follow_up_quality: "Takip kalitesi",
};

const PROJECT_LABELS: Record<string, string> = {
  project: "Proje",
  project_constraint: "Kısıt",
  stack: "Yığın",
  routing_mode: "Rota",
  task_target: "Hedef",
  mobile_sync_quality: "Mobil eşitleme",
  task_handoff_helpfulness: "Görev devir",
};

const DERIVED_LABELS: Record<string, string> = {
  self_model_communication_style: "İletişim stili",
  self_model_interests: "İlgi alanları",
  self_model_recent_topics: "Yakın konular",
  energy_rhythm: "Enerji ritmi",
  planning_style: "Planlama stili",
  schedule_pressure_pattern: "Program baskısı",
  mobility_context: "Hareketlilik",
  local_preference_context: "Yerel bağlam",
  notification_attention_pattern: "Dikkat yükü",
  preferred_working_window: "Çalışma penceresi",
  common_city: "Sık şehir",
  preferred_planning_granularity: "Plan yoğunluğu",
};

const SAFETY_KEYS = new Set([
  "implementation_boundary",
  "privacy_boundary",
  "security_boundary",
  "negative_feedback",
  "correction",
  "local_private",
]);

const EPISODE_KEYS = new Set([
  "session_recovered",
  "task_handoff_helpfulness",
  "mobile_sync_quality",
  "positive_feedback",
  "negative_feedback",
  "user_mood",
  "emotional_signal",
  "user_excitement",
  "user_frustration",
  "important_decision",
  "life_event",
  "conversation_highlight",
]);

export const EPISODIC_LABELS: Record<string, string> = {
  user_mood: "Ruh hali",
  emotional_signal: "Duygusal sinyal",
  user_excitement: "Heyecan",
  user_frustration: "Hayal kırıklığı",
  important_decision: "Önemli karar",
  life_event: "Yaşam olayı",
  conversation_highlight: "Konuşma notu",
  positive_feedback: "Olumlu geri bildirim",
  negative_feedback: "Olumsuz geri bildirim",
  task_handoff_helpfulness: "Görev devir kalitesi",
};

const PREFERENCE_VALUE_LABELS: Record<string, Record<string, string>> = {
  preferred_language: {
    turkish: "Türkçe",
    türkçe: "Türkçe",
    turkce: "Türkçe",
    english: "İngilizce",
    ingilizce: "İngilizce",
  },
  language: {
    turkish: "Türkçe",
    türkçe: "Türkçe",
    turkce: "Türkçe",
    english: "İngilizce",
    ingilizce: "İngilizce",
  },
  response_style_preference: {
    formal: "resmi",
    balanced: "dengeli",
    warm: "sıcak",
  },
  preferred_tone: {
    warm_professional: "sıcak ve profesyonel",
    warm: "sıcak",
    formal: "resmi",
    balanced: "dengeli",
  },
  answer_length: {
    concise: "kısa ve öz",
    detailed: "detaylı",
    "detailed when needed": "gerektiğinde detaylı",
  },
  brevity_preference: {
    short: "kısa",
    concise: "kısa ve öz",
    balanced: "dengeli",
  },
  humor_level: {
    restrained: "kısıtlı",
    light: "hafif",
    off: "kapalı",
  },
};

function sentenceCase(value: string): string {
  const compact = compactText(value);
  if (!compact) {
    return compact;
  }
  return compact.charAt(0).toUpperCase() + compact.slice(1);
}

function normalizeKey(value: string): string {
  return compactText(value)
    .toLowerCase()
    .replace(/[^a-z0-9çğıöşü_.-]+/gi, "_")
    .replace(/^_+|_+$/g, "");
}

function verificationFreshnessScore(lastVerifiedAt: Date | null | undefined, now: Date): number {
  if (!lastVerifiedAt) {
    return 0;
  }

  const ageDays = Math.max(0, (now.getTime() - lastVerifiedAt.getTime()) / 86_400_000);
  if (ageDays <= 7) {
    return 0.26;
  }
  if (ageDays <= 30) {
    return 0.18;
  }
  if (ageDays <= 90) {
    return 0.09;
  }
  return 0.04;
}

function toFact(
  item: RetrievedMemory,
  labelMap: Record<string, string>,
): MemoryProfileFact | null {
  const key = normalizeKey(item.key);
  const value = compactText(item.value);
  if (!key || !value || !isSafeForLearning(value)) {
    return null;
  }
  if (item.conflictStatus === "superseded" || item.conflictStatus === "contested") {
    return null;
  }
  if (item.staleness === "contested") {
    return null;
  }
  if (item.staleness === "stale" && !item.lastVerifiedAt && !item.isPinned) {
    return null;
  }

  return {
    key,
    label: labelMap[key] ?? key.replace(/_/g, " "),
    value,
    confidence: Math.max(0, Math.min(1, item.confidence)),
    source: item.source,
    staleness: item.staleness ?? "unknown",
    updatedAt: item.createdAt.toISOString(),
  };
}

function dedupeFacts(items: MemoryProfileFact[]): MemoryProfileFact[] {
  const seen = new Set<string>();
  const filtered: MemoryProfileFact[] = [];

  for (const item of items) {
    const normalizedValue = compactText(item.value).toLowerCase();
    const key = `${item.key}:${normalizedValue}`;
    const hasNearDuplicate = filtered.some((existing) => {
      if (existing.key !== item.key) {
        return false;
      }
      const existingValue = compactText(existing.value).toLowerCase();
      if (existingValue === normalizedValue) {
        return true;
      }
      return levenshteinDistance(existingValue, normalizedValue) <= 2;
    });

    if (seen.has(key) || hasNearDuplicate) {
      continue;
    }
    seen.add(key);
    filtered.push(item);
  }

  return filtered;
}

function sortFactsByStrength(items: MemoryProfileFact[]): MemoryProfileFact[] {
  return [...items].sort((left, right) => {
    const confidenceDelta = right.confidence - left.confidence;
    if (confidenceDelta !== 0) {
      return confidenceDelta;
    }
    return right.updatedAt.localeCompare(left.updatedAt);
  });
}

function rankMemoryItem(item: RetrievedMemory, now = new Date()): number {
  const confidence = Math.max(0, Math.min(1, item.confidence));
  const importance = Math.max(0, Math.min(1, Number(item.importanceScore ?? 0) / 100));
  const freshness = item.staleness === "fresh" ? 1 : item.staleness === "stale" ? 0.42 : 0.08;
  const pinnedBoost = item.isPinned ? 0.24 : 0;
  const verifiedBoost = verificationFreshnessScore(item.lastVerifiedAt ?? null, now);
  const conflictPenalty = item.conflictStatus === "contested" ? -0.7 : item.conflictStatus === "superseded" ? -0.95 : 0.08;
  const updatedSource = item.lastVerifiedAt ?? item.createdAt;
  const updatedAt =
    updatedSource instanceof Date ? updatedSource.getTime() : new Date(updatedSource).getTime();
  const recency = Number.isFinite(updatedAt) ? Math.max(0, Math.min(1, updatedAt / 10_000_000_000_000)) : 0;

  return confidence * 0.4 + importance * 0.2 + freshness * 0.15 + verifiedBoost + pinnedBoost + conflictPenalty + recency * 0.05;
}

function selectBestMemoryItems(items: RetrievedMemory[], now = new Date()): RetrievedMemory[] {
  const byKey = new Map<string, RetrievedMemory>();

  for (const item of items) {
    const key = normalizeKey(item.key);
    if (!key) {
      continue;
    }

    const current = byKey.get(key);
    if (!current) {
      byKey.set(key, item);
      continue;
    }

    const currentRank = rankMemoryItem(current, now);
    const nextRank = rankMemoryItem(item, now);
    if (nextRank > currentRank) {
      byKey.set(key, item);
      continue;
    }

    if (nextRank === currentRank) {
      const currentAt = current.createdAt instanceof Date ? current.createdAt.getTime() : new Date(current.createdAt).getTime();
      const nextAt = item.createdAt instanceof Date ? item.createdAt.getTime() : new Date(item.createdAt).getTime();
      if (Number.isFinite(nextAt) && nextAt > currentAt) {
        byKey.set(key, item);
      }
    }
  }

  return [...byKey.values()];
}

function formatProperNounPredicate(value: string): string {
  const compact = compactText(value);
  if (!compact) {
    return compact;
  }
  return compact.endsWith("'") ? `${compact}dır` : `${compact}'dır`;
}

function formatPreferenceValue(item: MemoryProfileFact): string {
  const normalizedKey = item.key.toLowerCase();
  const normalizedValue = compactText(item.value).toLowerCase();
  if (normalizedKey === "preferred_language" || normalizedKey === "language") {
    return sentenceCase(formatTurkicLanguageLabel(item.value));
  }
  const mapped = PREFERENCE_VALUE_LABELS[normalizedKey]?.[normalizedValue];

  if (mapped) {
    return sentenceCase(mapped);
  }

  return sentenceCase(item.value);
}

function formatHeightSentence(value: string): string {
  const compact = compactText(value);
  if (!compact) {
    return compact;
  }
  const unitMatch = compact.match(/^(.*?)(?:\s*(cm|m|metre))$/i);
  if (unitMatch?.[1]) {
    const number = compactText(unitMatch[1]);
    const unit = (unitMatch[2] ?? "").toLowerCase();
    if (unit === "cm") {
      return `${number} santimetredir`;
    }
    return `${number} metredir`;
  }
  return `${compact} metredir`;
}

function formatMemoryFactSentence(item: MemoryProfileFact): string {
  if (item.label === "Ad" || item.key === "name" || item.key === "preferred_name") {
    return `Kullanıcının adı ${formatProperNounPredicate(item.value)}.`;
  }

  if (item.label === "Rol" || item.key === "role" || item.key === "job_title") {
    const roleValue = sentenceCase(item.value);
    if (roleValue.toLowerCase() === "geliştirici") {
      return "Kullanıcı, Elyan'ın geliştiricisidir.";
    }
    if (roleValue.toLowerCase() === "öğrenci") {
      return "Kullanıcı öğrencidir.";
    }
    if (roleValue.toLowerCase() === "mühendis") {
      return "Kullanıcı mühendistir.";
    }
    return `Kullanıcının rolü ${roleValue.toLowerCase()}dir.`;
  }

  if (item.label === "Köken" || item.key === "origin" || item.key === "location") {
    return `Kullanıcının kökeni ${formatProperNounPredicate(item.value)}.`;
  }

  if (item.label === "Boy" || item.key === "height") {
    return `Kullanıcının boyu ${formatHeightSentence(item.value)}.`;
  }

  if (item.label === "Dil" || item.key === "language" || item.key === "preferred_language") {
    return `Tercih edilen dil ${formatPreferenceValue(item)}.`;
  }

  if (
    item.key === "response_style_preference" ||
    item.key === "preferred_tone" ||
    item.key === "answer_length" ||
    item.key === "brevity_preference" ||
    item.key === "humor_level"
  ) {
    return `${sentenceCase(item.label)}: ${formatPreferenceValue(item)}.`;
  }

  return `${sentenceCase(item.label)}: ${sentenceCase(item.value)}.`;
}

function describeMemoryFactForSummary(item: MemoryProfileFact): string {
  if (item.label === "Ad" || item.key === "name" || item.key === "preferred_name") {
    return `Kullanıcının adı ${item.value}`;
  }

  if (item.label === "Rol" || item.key === "role" || item.key === "job_title") {
    const roleValue = sentenceCase(item.value);
    if (roleValue.toLowerCase() === "geliştirici") {
      return "Kullanıcı, Elyan'ın geliştiricisidir";
    }
    if (roleValue.toLowerCase() === "öğrenci") {
      return "Kullanıcı öğrencidir";
    }
    if (roleValue.toLowerCase() === "mühendis") {
      return "Kullanıcı mühendistir";
    }
    return `Kullanıcının rolü ${roleValue.toLowerCase()}`;
  }

  if (item.label === "Köken" || item.key === "origin" || item.key === "location") {
    return `Kullanıcının kökeni ${formatProperNounPredicate(item.value)}`;
  }

  if (item.label === "Boy" || item.key === "height") {
    return `Kullanıcının boyu ${formatHeightSentence(item.value)}`;
  }

  if (item.label === "Dil" || item.key === "language" || item.key === "preferred_language") {
    return `Tercih edilen dil ${formatPreferenceValue(item)}`;
  }

  if (
    item.key === "response_style_preference" ||
    item.key === "preferred_tone" ||
    item.key === "answer_length" ||
    item.key === "brevity_preference" ||
    item.key === "humor_level"
  ) {
    return `${sentenceCase(item.label)}: ${formatPreferenceValue(item)}`;
  }

  return `${sentenceCase(item.label)}: ${sentenceCase(item.value)}`;
}

export function buildMemoryProfileSnapshot(items: RetrievedMemory[]): MemoryProfileSnapshot {
  const now = new Date();
  const identityItems: RetrievedMemory[] = [];
  const preferenceItems: RetrievedMemory[] = [];
  const projectItems: RetrievedMemory[] = [];
  const derivedItems: RetrievedMemory[] = [];
  const episodeItems: RetrievedMemory[] = [];
  const safetyNotes: string[] = [];
  let lastUpdatedAt: string | null = null;

  for (const item of items) {
    const updatedAt = item.createdAt instanceof Date ? item.createdAt : new Date(item.createdAt);
    if (!Number.isNaN(updatedAt.getTime()) && (!lastUpdatedAt || updatedAt.toISOString() > lastUpdatedAt)) {
      lastUpdatedAt = updatedAt.toISOString();
    }

    const normalizedKey = normalizeKey(item.key);
    const fact = toFact(item, {
      ...IDENTITY_LABELS,
      ...PREFERENCE_LABELS,
      ...PROJECT_LABELS,
    });
    if (!fact) {
      continue;
    }

    if (IDENTITY_LABELS[normalizedKey]) {
      identityItems.push(item);
      continue;
    }

    if (PREFERENCE_LABELS[normalizedKey]) {
      preferenceItems.push(item);
      continue;
    }

    if (PROJECT_LABELS[normalizedKey]) {
      projectItems.push(item);
      continue;
    }

    if (
      DERIVED_LABELS[normalizedKey] ||
      (typeof item.metadata === "object" &&
        item.metadata != null &&
        (item.metadata as Record<string, unknown>).sourceCategory === "world_signal_derived")
    ) {
      derivedItems.push(item);
      continue;
    }

    if (SAFETY_KEYS.has(normalizedKey) || item.type === "correction") {
      safetyNotes.push(`${fact.label}: ${fact.value}`);
      continue;
    }

    if (EPISODE_KEYS.has(normalizedKey) || item.type === "reflective" || item.type === "episode") {
      episodeItems.push(item);
      continue;
    }
  }

  const cappedIdentity = sortFactsByStrength(
    dedupeFacts(
    selectBestMemoryItems(identityItems, now).flatMap((item) => {
      const fact = toFact(item, {
        ...IDENTITY_LABELS,
        ...PREFERENCE_LABELS,
        ...PROJECT_LABELS,
      });
      return fact ? [fact] : [];
    }),
  ),
  ).slice(0, MAX_FACTS_PER_SECTION);
  const cappedPreferences = sortFactsByStrength(
    dedupeFacts(
    selectBestMemoryItems(preferenceItems, now).flatMap((item) => {
      const fact = toFact(item, {
        ...IDENTITY_LABELS,
        ...PREFERENCE_LABELS,
        ...PROJECT_LABELS,
      });
      return fact ? [fact] : [];
    }),
  ),
  ).slice(0, MAX_FACTS_PER_SECTION);
  const cappedProjects = sortFactsByStrength(
    dedupeFacts(
    selectBestMemoryItems(projectItems, now).flatMap((item) => {
      const fact = toFact(item, {
        ...IDENTITY_LABELS,
        ...PREFERENCE_LABELS,
        ...PROJECT_LABELS,
      });
      return fact ? [fact] : [];
    }),
  ),
  ).slice(0, MAX_FACTS_PER_SECTION);
  const cappedDerived = sortFactsByStrength(
    dedupeFacts(
    selectBestMemoryItems(derivedItems, now).flatMap((item) => {
      const fact = toFact(item, {
        ...DERIVED_LABELS,
        ...PROJECT_LABELS,
      });
      return fact ? [fact] : [];
    }),
  ),
  ).slice(0, MAX_FACTS_PER_SECTION);
  const cappedEpisodes = sortFactsByStrength(
    dedupeFacts(
    selectBestMemoryItems(episodeItems, now).flatMap((item) => {
      const fact = toFact(item, {
        ...IDENTITY_LABELS,
        ...PREFERENCE_LABELS,
        ...PROJECT_LABELS,
      });
      return fact ? [{ ...fact, source: String(item.source ?? item.type ?? "memory") }] : [];
    }),
  ),
  ).slice(0, MAX_FACTS_PER_SECTION);
  const selectedCount =
    cappedIdentity.length +
    cappedPreferences.length +
    cappedProjects.length +
    cappedDerived.length +
    cappedEpisodes.length;

  const summaryParts = [
    cappedIdentity.length ? `kimlik: ${cappedIdentity.map(describeMemoryFactForSummary).join(" · ")}` : null,
    cappedPreferences.length
      ? `tercih: ${cappedPreferences.map(describeMemoryFactForSummary).join(" · ")}`
      : null,
    cappedProjects.length ? `proje: ${cappedProjects.map(describeMemoryFactForSummary).join(" · ")}` : null,
    cappedDerived.length ? `durumsal: ${cappedDerived.map(describeMemoryFactForSummary).join(" · ")}` : null,
    cappedEpisodes.length ? `son olay: ${cappedEpisodes[0]?.value ?? ""}` : null,
  ].filter(Boolean);

  const summary = summaryParts.length
    ? compactText(`Hatırlanan çekirdek: ${summaryParts.join(" | ")}`).slice(0, MAX_SUMMARY_CHARS)
    : null;

  return {
    summary,
    identityFacts: cappedIdentity,
    preferenceFacts: cappedPreferences,
    projectFacts: cappedProjects,
    derivedFacts: cappedDerived,
    recentEpisodes: cappedEpisodes,
    safetyNotes: safetyNotes.slice(0, MAX_FACTS_PER_SECTION),
    memoryCount: items.length,
    compactedCount: Math.max(0, items.length - selectedCount),
    lastUpdatedAt,
  };
}

export function formatMemoryProfilePromptBlock(profile: MemoryProfileSnapshot | null | undefined): string | null {
  if (!profile) {
    return null;
  }

  const lines: string[] = ["User memory profile:"];
  if (profile.summary) {
    lines.push(`- Summary: ${profile.summary}`);
  }
  if (profile.identityFacts.length) {
    lines.push("- Identity:");
    for (const item of profile.identityFacts) {
      lines.push(`  - ${formatMemoryFactSentence(item)}`);
    }
  }
  if (profile.preferenceFacts.length) {
    lines.push("- Preferences:");
    for (const item of profile.preferenceFacts) {
      lines.push(`  - ${formatMemoryFactSentence(item)}`);
    }
  }
  if (profile.projectFacts.length) {
    lines.push("- Project context:");
    for (const item of profile.projectFacts) {
      lines.push(`  - ${formatMemoryFactSentence(item)}`);
    }
  }
  if (profile.derivedFacts.length) {
    lines.push("- Derived context:");
    for (const item of profile.derivedFacts) {
      lines.push(`  - ${formatMemoryFactSentence(item)}`);
    }
  }
  if (profile.safetyNotes.length) {
    lines.push("- Safety notes:");
    for (const note of profile.safetyNotes) {
      lines.push(`  - ${sentenceCase(note)}.`);
    }
  }

  return lines.length > 1 ? lines.join("\n") : null;
}
