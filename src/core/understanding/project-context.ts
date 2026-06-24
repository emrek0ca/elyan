import { isSafeForLearning } from "./personalization-policy.js";

function normalizeProjectName(value: string): string | null {
  const compact = value.replace(/\s+/g, " ").trim().slice(0, 80);

  if (!/^[\p{L}\p{N}_. -]{2,80}$/u.test(compact) || !isSafeForLearning(compact)) {
    return null;
  }

  return compact;
}

export function extractProjectHints(input: {
  title?: string;
  message?: string;
  metadata?: Record<string, unknown>;
}): string[] {
  const hints: string[] = [];
  const metadataProject = input.metadata?.projectName ?? input.metadata?.project ?? input.metadata?.workspaceName;

  if (typeof metadataProject === "string") {
    const normalized = normalizeProjectName(metadataProject);

    if (normalized) {
      hints.push(`project:${normalized}`);
    }
  }

  const text = `${input.title ?? ""}\n${input.message ?? ""}`;
  const explicitMatches = text.matchAll(/\b(?:project|repo|workspace|proje)\s*[:=]\s*([A-Za-z0-9_. -]{2,80})/gi);

  for (const match of explicitMatches) {
    const normalized = normalizeProjectName(match[1] ?? "");

    if (normalized) {
      hints.push(`project:${normalized}`);
    }
  }

  return [...new Set(hints)].slice(0, 4);
}
