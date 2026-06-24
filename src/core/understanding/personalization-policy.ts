import type { LearningSignal, RetrievedMemory } from "./types.js";

const MIN_CONFIDENCE = 0.68;
const MAX_VALUE_LENGTH = 240;

const sensitivePatterns = [
  /\b(password|passwd|secret|token|api[_ -]?key|bearer|credential|private[_ -]?key|otp|2fa|mfa|recovery[_ -]?code)\b/i,
  /\b(şifre|sifre|gizli|anahtar|erişim[_ -]?anahtarı|erisim[_ -]?anahtari|tek[_ -]?kullanımlık[_ -]?kod|tek[_ -]?kullanimlik[_ -]?kod)\b/i,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/i,
  /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/,
  /\b(?:sk|pk|ghp|github_pat|xox[baprs])_[A-Za-z0-9_=-]{12,}\b/i,
  /\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/,
  /(?:\/Users\/|\/home\/|C:\\Users\\)[^\s]+/i,
  /\bTR\d{2}(?:\s?\d{4}){5}\s?\d{2}\b/i,
  /\b(?:T\.?C\.?\s*)?(?:kimlik|identity)\s*(?:no|numarası|numarasi)?\s*[:=]?\s*\d{11}\b/i,
  /\b\d{3}-\d{2}-\d{4}\b/,
  /\b\d{13,19}\b/,
];

function isSensitiveText(value: string): boolean {
  return sensitivePatterns.some((pattern) => pattern.test(value));
}

function compactText(value: string, maxLength = MAX_VALUE_LENGTH): string {
  return value.replace(/\s+/g, " ").trim().slice(0, maxLength);
}

function verificationFreshnessScore(lastVerifiedAt: Date | null | undefined, now: Date): number {
  if (!lastVerifiedAt) {
    return 0;
  }

  const ageDays = Math.max(0, (now.getTime() - lastVerifiedAt.getTime()) / 86_400_000);
  if (ageDays <= 7) {
    return 0.22;
  }
  if (ageDays <= 30) {
    return 0.16;
  }
  if (ageDays <= 90) {
    return 0.08;
  }
  return 0.03;
}

function rankRetrievedMemoryForPrompt(item: RetrievedMemory, now: Date): number {
  const confidence = Math.max(0, Math.min(1, item.confidence));
  const importance = Math.max(0, Math.min(1, Number(item.importanceScore ?? 0) / 100));
  const freshness = item.staleness === "fresh" ? 1 : item.staleness === "stale" ? 0.35 : 0.05;
  const verifiedBoost = verificationFreshnessScore(item.lastVerifiedAt ?? null, now);
  const pinnedBoost = item.isPinned ? 0.28 : 0;
  const activeBoost = item.conflictStatus === "active" ? 0.12 : 0;
  const contestedPenalty =
    item.staleness === "contested" || item.conflictStatus === "contested" ? -0.9 : 0;
  const supersededPenalty = item.conflictStatus === "superseded" ? -1.2 : 0;
  const createdAt = item.createdAt instanceof Date ? item.createdAt.getTime() : new Date(item.createdAt).getTime();
  const recency = Number.isFinite(createdAt) ? Math.max(0, Math.min(1, createdAt / 10_000_000_000_000)) : 0;

  return (
    confidence * 0.34 +
    importance * 0.2 +
    freshness * 0.18 +
    verifiedBoost +
    pinnedBoost +
    activeBoost +
    contestedPenalty +
    supersededPenalty +
    recency * 0.04
  );
}

export function isSafeForLearning(value: string): boolean {
  const compact = compactText(value);
  return compact.length > 0 && !isSensitiveText(compact);
}

export function normalizeLearningSignal(signal: LearningSignal): LearningSignal | null {
  const value = compactText(signal.value);
  const key = compactText(signal.key, 120).toLowerCase().replace(/[^a-z0-9_.-]/g, "_");

  if (!key || signal.confidence < MIN_CONFIDENCE || !isSafeForLearning(value)) {
    return null;
  }

  return {
    ...signal,
    key,
    value,
    confidence: Math.min(0.99, Math.max(0, signal.confidence)),
  };
}

export function filterLearningSignals(signals: LearningSignal[]): LearningSignal[] {
  const seen = new Set<string>();
  const filtered: LearningSignal[] = [];

  for (const signal of signals) {
    const normalized = normalizeLearningSignal(signal);

    if (!normalized) {
      continue;
    }

    const dedupeKey = `${normalized.scope}:${normalized.type}:${normalized.key}:${normalized.value.toLowerCase()}`;

    if (seen.has(dedupeKey)) {
      continue;
    }

    seen.add(dedupeKey);
    filtered.push(normalized);
  }

  return filtered;
}

export function filterRetrievedMemory(items: RetrievedMemory[], now = new Date()): RetrievedMemory[] {
  const ordered = [...items].sort((left, right) => rankRetrievedMemoryForPrompt(right, now) - rankRetrievedMemoryForPrompt(left, now));
  const seen = new Set<string>();
  const filtered: RetrievedMemory[] = [];
  let correctionHintIncluded = false;

  for (const item of ordered) {
    if (item.confidence < MIN_CONFIDENCE || !isSafeForLearning(item.value)) {
      continue;
    }

    if (item.conflictStatus === "superseded" || item.conflictStatus === "contested") {
      continue;
    }

    if (item.staleness === "contested") {
      continue;
    }

    if (item.staleness === "stale" && !item.lastVerifiedAt && !item.isPinned) {
      continue;
    }

    const dedupeKey = `${item.scope}:${item.type}:${item.key}:${item.value.toLowerCase()}`;

    if (seen.has(dedupeKey)) {
      continue;
    }

    const isCorrection = item.type === "correction" || item.key === "negative_feedback";
    if (isCorrection && correctionHintIncluded) {
      continue;
    }

    seen.add(dedupeKey);
    correctionHintIncluded ||= isCorrection;
    filtered.push({
      ...item,
      value: compactText(item.value),
      createdAt: item.createdAt > now ? now : item.createdAt,
    });
  }

  return filtered;
}
