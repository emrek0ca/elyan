import { createHash } from "node:crypto";
import type {
  IntentClassification,
  UnderstandingIntent,
} from "../../core/understanding/types.js";

export type UnderstandingTargetSurface = "server" | "desktop" | "hybrid";

export type UnderstandingConsensus = {
  contract: "elyan.understanding_consensus.v1";
  status: "agreed" | "fallback" | "clarification_required";
  intent: {
    normalized: string;
    primary: UnderstandingIntent;
    secondary: UnderstandingIntent[];
  };
  goal: {
    objectiveHash: string;
    objectiveKind: UnderstandingIntent;
  };
  targetSurface: UnderstandingTargetSurface;
  selectedCapabilities: string[];
  selectedSkills: string[];
  normalizedArgs: Record<string, unknown>;
  successCriteria: string[];
  approval: {
    required: boolean;
    scope: string[];
  };
  privacy: {
    class: "public" | "local_private" | "side_effect";
    localContextRequired: boolean;
    maySendPrivateContextToServer: boolean;
  };
  confidence: number;
  ambiguity: {
    present: boolean;
    reason: "none" | "low_confidence" | "candidate_conflict";
  };
  conflict: {
    intent: boolean;
    targetSurface: boolean;
    privacy: boolean;
    capabilities: boolean;
  };
  candidates: Array<{
    source: "semantic_transformer" | "structured_model";
    digest: string;
    primaryIntent: UnderstandingIntent;
    targetSurface: UnderstandingTargetSurface;
    confidence: number;
  }>;
};

type ConsensusCandidate = {
  source: "semantic_transformer" | "structured_model";
  classification: IntentClassification;
};

const LOCAL_INTENTS = new Set<UnderstandingIntent>([
  "automation",
  "browser",
  "computer",
]);

function targetSurfaceFor(classification: IntentClassification): UnderstandingTargetSurface {
  if (classification.requiresLocalRuntime || LOCAL_INTENTS.has(classification.primaryIntent)) {
    return "desktop";
  }
  return "server";
}

function privacyClassFor(
  classification: IntentClassification,
  sideEffect: boolean,
): "public" | "local_private" | "side_effect" {
  if (sideEffect) return "side_effect";
  if (classification.requiresLocalRuntime || classification.privacyRisk !== "low") {
    return "local_private";
  }
  return "public";
}

function candidateDigest(candidate: ConsensusCandidate): string {
  const classification = candidate.classification;
  return createHash("sha256")
    .update(
      JSON.stringify({
        source: candidate.source,
        primaryIntent: classification.primaryIntent,
        secondaryIntents: classification.secondaryIntents,
        requiresLocalRuntime: classification.requiresLocalRuntime,
        requiresRetrieval: classification.requiresRetrieval,
        requiresToolUse: classification.requiresToolUse,
        privacyRisk: classification.privacyRisk,
        confidenceBucket: Math.round(classification.confidence * 20) / 20,
      }),
    )
    .digest("hex")
    .slice(0, 24);
}

function normalizedIntentFor(
  classification: IntentClassification,
  targetSurface: UnderstandingTargetSurface,
): string {
  if (classification.primaryIntent === "planning") return "planning_request";
  if (targetSurface === "desktop") return "device_control_request";
  if (classification.primaryIntent === "unknown") return "ambiguous_request";
  return "normal_chat";
}

function normalizedCapabilities(classification: IntentClassification): string[] {
  // routingHints are model/ontology output, not authority. Only carry exact
  // registry-shaped names; the final route validator decides the executable
  // capability set. Generic labels such as "tool_use" are intentionally gone.
  const allowed = new Set([
    "sys_info",
    "retrieve_context",
    "run_skill",
    "browser_search",
    "document_create",
    "image_generate",
    "desktop_operator_run",
    "browser_control",
    "computer_control",
    "open_app",
    "close_app",
  ]);
  return [
    ...new Set(
      (classification.routingHints?.preferredCapabilities ?? []).filter((item) =>
        allowed.has(item),
      ),
    ),
  ];
}

export function buildUnderstandingConsensus(input: {
  message: string;
  primary: IntentClassification;
  verifier?: IntentClassification | null;
  verifierInvoked: boolean;
  sideEffect?: boolean;
  selectedCapabilities?: string[];
  selectedSkills?: string[];
  normalizedArgs?: Record<string, unknown>;
  successCriteria?: string[];
  approvalRequired?: boolean;
  /**
   * Kullanıcı hedefi AÇIKÇA söylediyse ("masaüstüne … kaydet") burada gelir.
   *
   * Canlı arıza (görev dbc7352e, 2026-08-22 17:22): "masaüstüne zürafalar
   * hakkında bir pdf hazırla ve kaydet" isteğinde anlama katmanları yüzey
   * konusunda ayrıştı, `clarification_required` çıktı ve tur sunucu sohbetine
   * düştü. Model de kullanıcıya "Netleştireyim: tam olarak neyi yapmamı
   * istiyorsun?" diye sordu — oysa kullanıcı NEREYE ve NE yapılacağını zaten
   * söylemişti.
   *
   * Katmanların birbiriyle anlaşamaması, kullanıcının açık talimatını
   * geçersiz kılmaz. Açık hedef varsa yüzey çatışması netleştirme sebebi
   * DEĞİLDİR; hedef kullanıcının dediğidir.
   */
  explicitTargetSurface?: "desktop" | null;
}): UnderstandingConsensus {
  const primaryCandidate: ConsensusCandidate = {
    source: "semantic_transformer",
    classification: input.primary,
  };
  const verifierCandidate = input.verifier
    ? {
        source: "structured_model" as const,
        classification: input.verifier,
      }
    : null;
  const selected = verifierCandidate?.classification ?? primaryCandidate.classification;
  const primarySurface = targetSurfaceFor(primaryCandidate.classification);
  const selectedSurface = targetSurfaceFor(selected);
  const primaryPrivacy = privacyClassFor(
    primaryCandidate.classification,
    input.sideEffect === true,
  );
  const selectedPrivacy = privacyClassFor(selected, input.sideEffect === true);
  const primaryCapabilities = normalizedCapabilities(primaryCandidate.classification);
  const selectedCapabilities = normalizedCapabilities(selected);
  const capabilityConflict =
    primaryCapabilities.length > 0 &&
    selectedCapabilities.length > 0 &&
    primaryCapabilities.join(",") !== selectedCapabilities.join(",");
  const conflict = {
    intent:
      verifierCandidate !== null &&
      primaryCandidate.classification.primaryIntent !== selected.primaryIntent,
    targetSurface: verifierCandidate !== null && primarySurface !== selectedSurface,
    privacy: verifierCandidate !== null && primaryPrivacy !== selectedPrivacy,
    capabilities: verifierCandidate !== null && capabilityConflict,
  };
  const highRisk =
    input.sideEffect === true ||
    primarySurface === "desktop" ||
    selectedSurface === "desktop" ||
    primaryCandidate.classification.privacyRisk !== "low" ||
    selected.privacyRisk !== "low";
  // Açık hedef, yüzey/gizlilik çatışmasını çözer: kullanıcı zaten söyledi.
  // Niyet çatışması (ör. "bu gerçekten bir iş mi, sohbet mi") hâlâ geçerlidir.
  const explicitDesktop = input.explicitTargetSurface === "desktop";
  const hardConflict = explicitDesktop
    ? highRisk && conflict.intent
    : conflict.targetSurface || conflict.privacy || (highRisk && conflict.intent);
  const lowConfidence = Math.min(
    primaryCandidate.classification.confidence,
    selected.confidence,
  ) < 0.55;
  const status: UnderstandingConsensus["status"] = hardConflict
    ? "clarification_required"
    : input.verifierInvoked
      ? "agreed"
      : "fallback";
  const targetSurface = hardConflict
    ? "server"
    : explicitDesktop
      ? "desktop"
      : selectedSurface;
  const normalizedIntent = normalizedIntentFor(selected, targetSurface);
  const objectiveHash = createHash("sha256")
    .update(String(input.message ?? "").replace(/\s+/g, " ").trim())
    .digest("hex")
    .slice(0, 24);

  return {
    contract: "elyan.understanding_consensus.v1",
    status,
    intent: {
      normalized: normalizedIntent,
      primary: selected.primaryIntent,
      secondary: selected.secondaryIntents,
    },
    goal: {
      objectiveHash,
      objectiveKind: selected.primaryIntent,
    },
    targetSurface,
    selectedCapabilities: [
      ...new Set([...(input.selectedCapabilities ?? []), ...selectedCapabilities]),
    ],
    selectedSkills: [...new Set(input.selectedSkills ?? [])],
    normalizedArgs: input.normalizedArgs ?? {},
    successCriteria: [...new Set(input.successCriteria ?? [])].slice(0, 8),
    approval: {
      required: input.approvalRequired === true || input.sideEffect === true,
      scope: input.sideEffect === true ? ["validated_capability"] : [],
    },
    privacy: {
      class: selectedPrivacy,
      localContextRequired: targetSurface !== "server",
      maySendPrivateContextToServer: selectedPrivacy === "public",
    },
    confidence: Number(
      Math.min(primaryCandidate.classification.confidence, selected.confidence).toFixed(3),
    ),
    ambiguity: {
      present: lowConfidence || hardConflict,
      reason: hardConflict
        ? "candidate_conflict"
        : lowConfidence
          ? "low_confidence"
          : "none",
    },
    conflict,
    candidates: [
      {
        source: primaryCandidate.source,
        digest: candidateDigest(primaryCandidate),
        primaryIntent: primaryCandidate.classification.primaryIntent,
        targetSurface: primarySurface,
        confidence: Number(primaryCandidate.classification.confidence.toFixed(3)),
      },
      ...(verifierCandidate
        ? [
            {
              source: verifierCandidate.source,
              digest: candidateDigest(verifierCandidate),
              primaryIntent: verifierCandidate.classification.primaryIntent,
              targetSurface: selectedSurface,
              confidence: Number(verifierCandidate.classification.confidence.toFixed(3)),
            },
          ]
        : []),
    ],
  };
}

