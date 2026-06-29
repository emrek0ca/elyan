import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_SCRIPT = path.resolve(__dirname, "../scripts/python/continuity_enrich.py");
const DEFAULT_PYTHON_BIN = process.env.ELYAN_CONTINUITY_ENRICH_PYTHON_BIN?.trim() || "python3";
const REQUEST_TIMEOUT_MS = 1_200;
const MAX_FACTS = 20;
const MAX_EPISODES = 12;

const STOP_WORDS = new Set([
  "the", "and", "for", "with", "that", "this", "from", "into", "over", "then", "when", "while",
  "bir", "ve", "ile", "için", "icin", "gibi", "daha", "sonra", "gore", "göre", "olan", "olarak",
  "user", "kullanici", "kullanıcı", "elyan", "günlük", "gunluk", "haftalık", "haftalik",
]);

export type ContinuityFactSeed = {
  key: string;
  value: string;
  factType?: string;
};

export type ContinuityEpisodeSeed = {
  episodeType: string;
  summary: string;
};

export type ContinuityEnrichmentInput = {
  facts: ContinuityFactSeed[];
  episodes: ContinuityEpisodeSeed[];
};

export type ContinuityEnrichmentResult = {
  recentTopics: string | null;
  continuityStyle: string | null;
  reasoningStyle: string | null;
  topicTokens: string[];
  evidenceCount: number;
  source: "typescript_baseline" | "python_refined";
};

function compactText(value: string, maxLength = 240): string {
  return value.replace(/\s+/g, " ").trim().slice(0, maxLength);
}

function tokenize(value: string): string[] {
  return compactText(value)
    .toLowerCase()
    .replace(/[^a-z0-9çğıöşü_\s.-]/gi, " ")
    .split(/\s+/)
    .filter((token) => token.length >= 3 && !STOP_WORDS.has(token))
    .slice(0, 80);
}

function countTokens(input: string[]): string[] {
  const counts = new Map<string, number>();
  for (const token of input) {
    counts.set(token, (counts.get(token) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .map(([token]) => token)
    .slice(0, 6);
}

function hasFollowupPattern(value: string): boolean {
  return /\b(devam|follow up|next step|sonraki|yarın|yarin|pending|bekliyor|açık|acik|sürdür|surdur)\b/i.test(value);
}

export function buildContinuityEnrichmentBaseline(input: ContinuityEnrichmentInput): ContinuityEnrichmentResult | null {
  const facts = input.facts.slice(0, MAX_FACTS);
  const episodes = input.episodes.slice(0, MAX_EPISODES);
  const combinedTokens = countTokens([
    ...facts.flatMap((item) => tokenize(`${item.key} ${item.value}`)),
    ...episodes.flatMap((item) => tokenize(`${item.episodeType} ${item.summary}`)),
  ]);

  const recentTopics =
    combinedTokens.length > 0
      ? compactText(`Recent recurring topics: ${combinedTokens.slice(0, 4).join(", ")}`, 180)
      : null;

  const followupCount = episodes.filter((item) => hasFollowupPattern(item.summary)).length;
  const technicalCount = facts.filter((item) =>
    /(technical_stack|project_context|routing|bridge)/.test(String(item.factType ?? "")) ||
    /\b(auth|backend|api|debug|fix|plan|architecture|flutter|server|memory)\b/i.test(`${item.key} ${item.value}`),
  ).length;

  const continuityStyle =
    followupCount >= 2
      ? "When work spans multiple turns, restate the carried goal and the next unresolved step explicitly."
      : technicalCount >= 2
        ? "For ongoing work, preserve architecture and prior constraints unless the user clearly changes direction."
        : null;

  const reasoningStyle =
    technicalCount >= 3
      ? "Ongoing implementation work benefits from stepwise, architecture-preserving reasoning instead of broad rewrites."
      : followupCount >= 2
        ? "Multi-turn work benefits from checking whether the user is continuing the same thread before answering."
        : null;

  if (!recentTopics && !continuityStyle && !reasoningStyle) {
    return null;
  }

  return {
    recentTopics,
    continuityStyle,
    reasoningStyle,
    topicTokens: combinedTokens,
    evidenceCount: facts.length + episodes.length,
    source: "typescript_baseline",
  };
}

function normalizePythonResult(value: unknown): ContinuityEnrichmentResult | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const recentTopics = typeof record.recentTopics === "string" ? compactText(record.recentTopics, 180) : null;
  const continuityStyle = typeof record.continuityStyle === "string" ? compactText(record.continuityStyle, 220) : null;
  const reasoningStyle = typeof record.reasoningStyle === "string" ? compactText(record.reasoningStyle, 220) : null;
  const topicTokens = Array.isArray(record.topicTokens)
    ? record.topicTokens.map((item) => compactText(String(item), 40)).filter(Boolean).slice(0, 6)
    : [];
  const evidenceCount = Number(record.evidenceCount ?? 0);

  if (!recentTopics && !continuityStyle && !reasoningStyle) {
    return null;
  }

  return {
    recentTopics,
    continuityStyle,
    reasoningStyle,
    topicTokens,
    evidenceCount: Number.isFinite(evidenceCount) ? evidenceCount : 0,
    source: "python_refined",
  };
}

export async function refineContinuityEnrichmentWithPython(
  input: ContinuityEnrichmentInput,
): Promise<ContinuityEnrichmentResult | null> {
  if (process.env.ELYAN_CONTINUITY_ENRICHER_ENABLED === "false") {
    return null;
  }

  const scriptPath = process.env.ELYAN_CONTINUITY_ENRICH_SCRIPT?.trim() || DEFAULT_SCRIPT;
  if (!existsSync(scriptPath)) {
    return null;
  }

  return new Promise((resolve) => {
    const child = spawn(DEFAULT_PYTHON_BIN, [scriptPath], {
      stdio: ["pipe", "pipe", "ignore"],
    });

    let stdout = "";
    let settled = false;
    const timer = setTimeout(() => {
      settled = true;
      child.kill("SIGKILL");
      resolve(null);
    }, REQUEST_TIMEOUT_MS);

    child.stdout?.on("data", (chunk) => {
      stdout += String(chunk ?? "");
      if (stdout.length > 24_000) {
        stdout = stdout.slice(0, 24_000);
      }
    });

    child.on("error", () => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      resolve(null);
    });

    child.on("exit", (code) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      if (code !== 0) {
        resolve(null);
        return;
      }
      try {
        resolve(normalizePythonResult(JSON.parse(stdout)));
      } catch {
        resolve(null);
      }
    });

    child.stdin?.end(
      JSON.stringify({
        facts: input.facts.slice(0, MAX_FACTS),
        episodes: input.episodes.slice(0, MAX_EPISODES),
      }),
    );
  });
}
