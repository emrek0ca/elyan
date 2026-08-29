import {
  buildFreshDataEnvelope,
  resolveFreshDataPolicy,
  sourceFreshnessStatus,
  sourceTrustScore,
} from "./fresh-data-policy.js";
import type { GroqCompoundEvidence } from "./groq-compound.js";
import type {
  WebGroundingResult,
  WebGroundingSearchResult,
} from "./web-grounding.js";
import { applyDomainEvidenceGuards } from "./web-grounding.js";
import { collapseWhitespace as compactText } from "../../lib/text.js";

function sourceMetadata(host: string, prompt: string): {
  authority: WebGroundingSearchResult["sourceAuthority"];
  trust: number;
} {
  const policy = resolveFreshDataPolicy(prompt);
  const normalized = host.replace(/^www\./iu, "").toLowerCase();
  const official =
    /(?:^|\.)(?:gov|gov\.tr|edu|edu\.tr)$/iu.test(normalized) ||
    policy.preferredHosts.some(
      (preferred) => normalized === preferred || normalized.endsWith(`.${preferred}`),
    );
  const authority = official ? "official" : "standard";
  return {
    authority,
    trust: sourceTrustScore({ host, authority, policy }),
  };
}

export function compoundEvidenceToWebGrounding(input: {
  evidence: GroqCompoundEvidence;
  prompt: string;
  existing: WebGroundingResult;
  retrievedAt?: string;
}): WebGroundingResult | null {
  const retrievedAt = input.retrievedAt ?? new Date().toISOString();
  const requestedAt = new Date(retrievedAt);
  const policy = resolveFreshDataPolicy(input.prompt);
  const seen = new Set<string>();
  const results = input.evidence.citations.flatMap((citation) => {
    try {
      const parsed = new URL(citation.url);
      if (!["http:", "https:"].includes(parsed.protocol) || seen.has(parsed.href)) {
        return [];
      }
      seen.add(parsed.href);
      const { authority, trust } = sourceMetadata(parsed.hostname, input.prompt);
      const verified =
        Boolean(citation.snippet) &&
        (citation.toolType === "visit_website" || authority === "official");
      const freshnessStatus = sourceFreshnessStatus({
        ...(citation.observedAt
          ? {
              publishedAt: citation.observedAt,
              observedAt: citation.observedAt,
            }
          : {}),
        policy,
        now: requestedAt,
      });
      return [{
        title: compactText(citation.title) || parsed.hostname,
        url: parsed.href,
        snippet: compactText(citation.snippet).slice(0, 700),
        sourceHost: parsed.hostname,
        sourceAuthority: authority,
        verificationState: verified ? "verified" as const : "partial" as const,
        queryHits: 1,
        score: trust,
        sourceTrustScore: trust,
        ...(citation.observedAt ? { publishedAt: citation.observedAt } : {}),
        observedAt: citation.observedAt ?? retrievedAt,
        freshnessStatus,
        searchProvider: "groq_compound" as const,
      }];
    } catch {
      return [];
    }
  });
  if (results.length === 0) return null;

  const hostCount = new Set(results.map((result) => result.sourceHost)).size;
  const isFresh = (result: WebGroundingSearchResult) =>
    result.freshnessStatus === "fresh" ||
    result.freshnessStatus === "aging" ||
    (!policy.freshnessRequired && result.freshnessStatus === "undated");
  const freshResults = results.filter(isFresh);
  const verifiedResults = results.filter(
    (result) => result.verificationState === "verified",
  );
  const freshVerifiedResults = verifiedResults.filter(isFresh);
  const datedResults = results.filter((result) => Boolean(result.publishedAt));
  const freshDatedResults = datedResults.filter(isFresh);
  const freshData = buildFreshDataEnvelope({
    policy,
    requestedAt,
    retrievedAt,
    cacheState: "miss",
    sourceCount: results.length,
    freshSourceCount: freshResults.length,
    verifiedSourceCount: verifiedResults.length,
    freshVerifiedSourceCount: freshVerifiedResults.length,
    datedSourceCount: datedResults.length,
    freshDatedSourceCount: freshDatedResults.length,
    independentHostCount: hostCount,
    reasons: ["groq_compound", ...input.evidence.toolsUsed.slice(0, 3)],
  });

  return applyDomainEvidenceGuards({
    ...input.existing,
    enabled: true,
    used: freshData.evidence.sufficient,
    query: input.evidence.searchQueries[0] ?? compactText(input.prompt).slice(0, 320),
    queries: input.evidence.searchQueries.slice(0, 4),
    source: "groq_compound",
    results,
    degradedReason: freshData.evidence.sufficient ? null : "compound_evidence_insufficient",
    confidence: results.length >= 2 ? "medium" : "low",
    retrievedAt,
    decisionReasons: [
      ...(input.existing.decisionReasons ?? []),
      "groq_compound_evidence",
    ],
    freshData,
  });
}
