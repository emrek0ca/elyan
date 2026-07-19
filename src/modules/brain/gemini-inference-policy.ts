import type { FastifyInstance } from "fastify";
import {
  acquireGeminiFreePermit,
  estimateGeminiTokens,
  type GeminiDataSensitivity,
  type GeminiFreeDataLineage,
  type GeminiFreeFeature,
} from "./gemini-free-tier-guard.js";

export type GeminiInferencePermit = {
  allowed: boolean;
  mode: "free" | "paid";
  reason:
    | "allowed"
    | "disabled"
    | "missing_key"
    | "data_usage_not_attested"
    | "model_not_allowlisted"
    | "private_data_blocked"
    | "provider_cooldown"
    | "global_request_limit"
    | "user_request_limit"
    | "feature_request_limit"
    | "input_token_limit"
    | "feature_input_token_limit"
    | "output_token_limit"
    | "feature_output_token_limit"
    | "budget_store_unavailable"
    | "paid_fallback_disabled"
    | "paid_data_processing_not_attested"
    | "data_sharing_consent_required";
  model: string;
  estimatedInputTokens: number;
};

type GeminiInferencePermitInput = {
  feature: GeminiFreeFeature;
  userId: string;
  model?: string;
  requestPayload: unknown;
  estimatedInputTokensOverride?: number;
  sensitivity?: GeminiDataSensitivity;
  userAuthorizedCloud?: boolean;
  dataLineage?: GeminiFreeDataLineage;
  dataSharingConsentValidated?: boolean;
};

function paidPrivateLineageBlocked(
  lineage: GeminiFreeDataLineage | null | undefined,
): boolean {
  return Boolean(
    lineage?.mcp ||
      lineage?.connector ||
      lineage?.accountData ||
      lineage?.toolResult,
  );
}

export async function acquireGeminiInferencePermit(
  app: FastifyInstance,
  input: GeminiInferencePermitInput,
): Promise<GeminiInferencePermit> {
  if (app.config.GEMINI_FREE_ONLY === true) {
    const permit = await acquireGeminiFreePermit(app, input);
    return { ...permit, mode: "free" };
  }

  const model = String(input.model || app.config.GEMINI_FAST_MODEL || "").trim();
  const estimatedInputTokens = Math.max(
    1,
    Math.trunc(
      input.estimatedInputTokensOverride ??
        estimateGeminiTokens(input.requestPayload),
    ),
  );
  const denied = (reason: GeminiInferencePermit["reason"]): GeminiInferencePermit => ({
    allowed: false,
    mode: "paid",
    reason,
    model,
    estimatedInputTokens,
  });

  if (!String(app.config.GEMINI_API_KEY || "").trim()) {
    return denied("missing_key");
  }
  if (app.config.GEMINI_PAID_FALLBACK_ENABLED !== true) {
    return denied("paid_fallback_disabled");
  }
  if (app.config.GEMINI_PAID_DATA_PROCESSING_ATTESTED !== true) {
    return denied("paid_data_processing_not_attested");
  }
  if (input.dataSharingConsentValidated !== true) {
    return denied("data_sharing_consent_required");
  }
  if (
    input.sensitivity === "restricted" ||
    input.sensitivity === "sensitive" ||
    paidPrivateLineageBlocked(input.dataLineage) ||
    (input.dataLineage?.attachment === true &&
      input.userAuthorizedCloud !== true)
  ) {
    return denied("private_data_blocked");
  }

  return {
    allowed: true,
    mode: "paid",
    reason: "allowed",
    model,
    estimatedInputTokens,
  };
}
