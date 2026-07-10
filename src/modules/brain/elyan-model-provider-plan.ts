import { z } from "zod";
import type { SharedBrainProvider } from "./runtime.js";
import type { SharedBrainWorkload } from "./workloads.js";
import type { ElyanModelLearningPolicy } from "./elyan-model-learning-policy.js";

const sharedBrainProviderSchema = z.enum([
  "ollama",
  "vllm",
  "llamacpp",
  "openai",
  "claude",
  "groq",
  "openrouter",
]);

const lowRiskCanaryWorkloads = new Set<SharedBrainWorkload>([
  "intent",
  "fast_route",
  "mobile_chat_fast",
]);

export type ElyanModelPlanArtifact = {
  id: string;
  scope: "user" | "shared";
  provider: string;
  baseModel: string;
  adapterKind: string;
  storageUri: string | null;
  checksum: string | null;
  metadata: unknown;
};

export type ElyanModelProviderPlan = {
  logicalProvider: "elyan";
  stage: ElyanModelLearningPolicy["stage"];
  servingStrategy: ElyanModelLearningPolicy["servingStrategy"];
  activeModelId: string | null;
  activeModelScope: "user" | "shared" | null;
  activeAdapter: string | null;
  transportProvider: SharedBrainProvider | "unresolved";
  transportReady: boolean;
  liveRoutingEnabled: boolean;
  shadowEvaluationEnabled: boolean;
  canaryEnabled: boolean;
  primaryEnabled: boolean;
  routeReason:
    | "no_ready_elyan_model"
    | "runtime_not_ready"
    | "shadow_eval_only"
    | "canary_disabled"
    | "workload_not_canary_safe"
    | "primary_disabled"
    | "elyan_canary_candidate"
    | "elyan_primary_candidate"
    | "elyan_primary_ready";
  traffic: {
    groqPercent: number;
    elyanShadowPercent: number;
    elyanCanaryPercent: number;
    elyanPrimaryPercent: number;
  };
  safety: {
    requiresOperatorPromotion: boolean;
    requiresGroqFallback: boolean;
    allowedCanaryWorkloads: SharedBrainWorkload[];
  };
};

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function readString(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function isServableModelArtifact(artifact: ElyanModelPlanArtifact | null): boolean {
  if (
    !artifact?.id ||
    !artifact.storageUri ||
    !artifact.checksum ||
    !/^sha256:[a-f0-9]{64}$/i.test(artifact.checksum)
  ) {
    return false;
  }
  const metadata = readRecord(artifact.metadata);
  const trainingMode = readString(metadata, "trainingMode");
  const evaluationState = readString(metadata, "evaluationState");
  const adapterKind = artifact.adapterKind.trim().toLowerCase();
  return (
    !artifact.storageUri.startsWith("elyan://model-artifacts/") &&
    !["eval_adapter", "grounding_eval", "behavior_eval"].includes(adapterKind) &&
    trainingMode !== "bounded_cpu_eval" &&
    evaluationState !== "bounded_offline_eval" &&
    metadata?.servable !== false
  );
}

function normalizeProvider(value: string | null): SharedBrainProvider | null {
  if (!value) {
    return null;
  }

  const normalized = value.trim().toLowerCase().replace(/[_\s.-]+/g, "");
  if (normalized === "llamacpp" || normalized === "llamacppserver") {
    return "llamacpp";
  }
  if (normalized === "anthropic") {
    return "claude";
  }

  const parsed = sharedBrainProviderSchema.safeParse(normalized);
  return parsed.success ? parsed.data : null;
}

function resolveTransportProvider(input: {
  artifact: ElyanModelPlanArtifact | null;
  runtimeProvider: SharedBrainProvider;
}): SharedBrainProvider | "unresolved" {
  const metadata = readRecord(input.artifact?.metadata);
  return (
    normalizeProvider(readString(metadata, "servingProvider")) ??
    normalizeProvider(input.artifact?.provider ?? null) ??
    input.runtimeProvider ??
    "unresolved"
  );
}

export function buildElyanModelProviderPlan(input: {
  policy: ElyanModelLearningPolicy;
  artifact: ElyanModelPlanArtifact | null;
  workload: SharedBrainWorkload;
  runtimeProvider: SharedBrainProvider;
  runtimeReady: boolean;
  canaryEnabled: boolean;
  primaryEnabled: boolean;
}): ElyanModelProviderPlan {
  const transportProvider = resolveTransportProvider({
    artifact: input.artifact,
    runtimeProvider: input.runtimeProvider,
  });
  const hasReadyArtifact = isServableModelArtifact(input.artifact);
  const canaryWorkloadSafe = lowRiskCanaryWorkloads.has(input.workload);
  const base = {
    logicalProvider: "elyan" as const,
    stage: input.policy.stage,
    servingStrategy: input.policy.servingStrategy,
    activeModelId: input.artifact?.id ?? null,
    activeModelScope: input.artifact?.scope ?? null,
    activeAdapter: input.artifact?.adapterKind ?? null,
    transportProvider,
    transportReady: input.runtimeReady && transportProvider !== "unresolved",
    safety: {
      requiresOperatorPromotion: true,
      requiresGroqFallback: input.policy.stage !== "groq_retirement_ready",
      allowedCanaryWorkloads: [...lowRiskCanaryWorkloads],
    },
  };

  if (!hasReadyArtifact) {
    return {
      ...base,
      liveRoutingEnabled: false,
      shadowEvaluationEnabled: false,
      canaryEnabled: false,
      primaryEnabled: false,
      routeReason: "no_ready_elyan_model",
      traffic: {
        groqPercent: 100,
        elyanShadowPercent: 0,
        elyanCanaryPercent: 0,
        elyanPrimaryPercent: 0,
      },
    };
  }

  if (!base.transportReady) {
    return {
      ...base,
      liveRoutingEnabled: false,
      shadowEvaluationEnabled: false,
      canaryEnabled: false,
      primaryEnabled: false,
      routeReason: "runtime_not_ready",
      traffic: {
        groqPercent: 100,
        elyanShadowPercent: 0,
        elyanCanaryPercent: 0,
        elyanPrimaryPercent: 0,
      },
    };
  }

  if (input.policy.stage === "shadow_evaluation") {
    return {
      ...base,
      liveRoutingEnabled: false,
      shadowEvaluationEnabled: true,
      canaryEnabled: false,
      primaryEnabled: false,
      routeReason: "shadow_eval_only",
      traffic: {
        groqPercent: 100,
        elyanShadowPercent: 100,
        elyanCanaryPercent: 0,
        elyanPrimaryPercent: 0,
      },
    };
  }

  if (input.policy.canPromoteLocalPrimary && input.primaryEnabled) {
    return {
      ...base,
      liveRoutingEnabled: true,
      shadowEvaluationEnabled: true,
      canaryEnabled: true,
      primaryEnabled: true,
      routeReason:
        input.policy.stage === "groq_retirement_ready" ? "elyan_primary_ready" : "elyan_primary_candidate",
      traffic: {
        groqPercent: input.policy.stage === "groq_retirement_ready" ? 0 : 20,
        elyanShadowPercent: 0,
        elyanCanaryPercent: 0,
        elyanPrimaryPercent: input.policy.stage === "groq_retirement_ready" ? 100 : 80,
      },
    };
  }

  if (input.policy.canPromoteLocalPrimary && !input.primaryEnabled) {
    return {
      ...base,
      liveRoutingEnabled: false,
      shadowEvaluationEnabled: true,
      canaryEnabled: input.canaryEnabled,
      primaryEnabled: false,
      routeReason: "primary_disabled",
      traffic: {
        groqPercent: 100,
        elyanShadowPercent: 100,
        elyanCanaryPercent: 0,
        elyanPrimaryPercent: 0,
      },
    };
  }

  if (input.policy.canCanary && !canaryWorkloadSafe) {
    return {
      ...base,
      liveRoutingEnabled: false,
      shadowEvaluationEnabled: true,
      canaryEnabled: false,
      primaryEnabled: false,
      routeReason: "workload_not_canary_safe",
      traffic: {
        groqPercent: 100,
        elyanShadowPercent: 100,
        elyanCanaryPercent: 0,
        elyanPrimaryPercent: 0,
      },
    };
  }

  if (input.policy.canCanary && input.canaryEnabled) {
    return {
      ...base,
      liveRoutingEnabled: true,
      shadowEvaluationEnabled: true,
      canaryEnabled: true,
      primaryEnabled: false,
      routeReason: "elyan_canary_candidate",
      traffic: {
        groqPercent: 99,
        elyanShadowPercent: 0,
        elyanCanaryPercent: 1,
        elyanPrimaryPercent: 0,
      },
    };
  }

  return {
    ...base,
    liveRoutingEnabled: false,
    shadowEvaluationEnabled: true,
    canaryEnabled: false,
    primaryEnabled: false,
    routeReason: input.policy.canCanary ? "canary_disabled" : "shadow_eval_only",
    traffic: {
      groqPercent: 100,
      elyanShadowPercent: 100,
      elyanCanaryPercent: 0,
      elyanPrimaryPercent: 0,
    },
  };
}
