import type { FastifyInstance } from "fastify";
import { z } from "zod";
import {
  buildGeminiFreePublicOperationFrame,
  hasPrivateGeminiFreeDataLineage,
  shouldSampleGeminiUtility,
  type GeminiFreeDataLineage,
} from "./gemini-free-tier-guard.js";
import { callGeminiFreeStructured } from "./gemini-utility-client.js";

/**
 * Pre-synthesize public web grounding results with the free Gemini tier.
 *
 * The raw grounding block dumps every source's snippet and page content into
 * the main prompt, leaving a small fast model to both read and reason. Gemini
 * distills it first: the main model then answers from a compact, source-indexed
 * digest instead of raw scrape text.
 *
 * Only public web content and a redacted question frame are sent — never
 * connected-account data. Free-tier input is training data for the provider, so
 * the private-lineage gate here is a hard requirement, not an optimization.
 * Fail-open: a null result leaves the existing raw grounding block untouched.
 */

const synthesisSchema = z.object({
  summary: z.string().max(1_200),
  keyPoints: z.array(z.string().max(240)).max(5),
  citedSourceNumbers: z.array(z.number().int().min(1).max(10)).max(10),
  evidenceSufficient: z.boolean(),
  conflictNote: z.string().max(300),
});

export type GeminiWebSynthesis = z.infer<typeof synthesisSchema>;

const synthesisJsonSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "summary",
    "keyPoints",
    "citedSourceNumbers",
    "evidenceSufficient",
    "conflictNote",
  ],
  properties: {
    summary: { type: "string" },
    keyPoints: { type: "array", maxItems: 5, items: { type: "string" } },
    citedSourceNumbers: {
      type: "array",
      maxItems: 10,
      items: { type: "integer", minimum: 1, maximum: 10 },
    },
    evidenceSufficient: { type: "boolean" },
    conflictNote: { type: "string" },
  },
};

export type WebSynthesisSource = {
  title: string;
  host: string;
  snippet: string;
  publishedAt: string | null;
  pageContent?: string | null;
};

export async function synthesizeWebGroundingWithGeminiFree(
  app: FastifyInstance,
  input: {
    userId: string;
    stableId: string;
    question: string;
    sources: WebSynthesisSource[];
    dataLineage?: GeminiFreeDataLineage;
  },
): Promise<GeminiWebSynthesis | null> {
  if (input.sources.length === 0) return null;
  if (!shouldSampleGeminiUtility(app, `${input.stableId}:web_synth`)) return null;
  if (input.question.length > 2_000) return null;
  // Connected-account turns never reach the free tier.
  if (hasPrivateGeminiFreeDataLineage(input.dataLineage)) return null;
  const publicQuestion = buildGeminiFreePublicOperationFrame(input.question);
  if (!publicQuestion) return null;

  const sources = input.sources.slice(0, 6).map((source, index) => ({
    n: index + 1,
    title: source.title.slice(0, 200),
    host: source.host.slice(0, 120),
    publishedAt: source.publishedAt ?? "unknown",
    // Page content is the highest-signal field; keep the top entries richer.
    text: `${source.snippet} ${index < 2 ? (source.pageContent ?? "") : ""}`
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, index < 2 ? 1_200 : 400),
  }));

  return callGeminiFreeStructured(app, {
    feature: "web_synthesize",
    userId: input.userId,
    system: [
      "You distill public web search results into a compact, factual digest for another assistant.",
      "Use ONLY the supplied sources. Never add outside knowledge and never invent numbers, dates, or names.",
      "Cite sources by their number. If sources disagree, say so in conflictNote.",
      "Set evidenceSufficient=false when the sources do not actually answer the question.",
      "Write summary and keyPoints in the same language as the question. Return bounded JSON only.",
    ].join(" "),
    payload: { question: publicQuestion, sources },
    schema: synthesisSchema,
    jsonSchema: synthesisJsonSchema,
    sensitivity: "none",
    dataLineage: input.dataLineage,
    maxOutputTokens: 600,
    timeoutMs: 4_000,
  });
}

/** Render the digest as a prompt block placed ahead of the raw source dump. */
export function buildGeminiWebSynthesisPromptBlock(
  synthesis: GeminiWebSynthesis | null,
): string | null {
  if (!synthesis) return null;
  const summary = synthesis.summary.trim();
  if (!summary) return null;
  const lines = [
    "WEB EVIDENCE DIGEST (pre-synthesized from the public sources below)",
    `Summary: ${summary}`,
  ];
  if (synthesis.keyPoints.length > 0) {
    lines.push(
      ...synthesis.keyPoints
        .map((point) => point.trim())
        .filter(Boolean)
        .map((point) => `- ${point}`),
    );
  }
  if (synthesis.citedSourceNumbers.length > 0) {
    lines.push(`Supported by sources: ${synthesis.citedSourceNumbers.join(", ")}`);
  }
  if (synthesis.conflictNote.trim()) {
    lines.push(`Conflicting evidence: ${synthesis.conflictNote.trim()}`);
  }
  if (!synthesis.evidenceSufficient) {
    lines.push(
      "DIGEST GUARD: these sources do not sufficiently answer the question. Say briefly that current evidence could not be established instead of asserting an answer.",
    );
  }
  lines.push(
    "This digest is a reading aid over the same sources — it never overrides the freshness and evidence guards below.",
  );
  return lines.join("\n");
}
