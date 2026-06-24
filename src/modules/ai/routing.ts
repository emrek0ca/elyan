import type { AiProvider } from "../../contracts/domain.js";
import type { SharedBrainWorkload } from "../brain/workloads.js";
import { supportedAiProviders } from "./provider-registry.js";

export type AiWorkload = SharedBrainWorkload;

export function resolveAiRoute(input: {
  workload: AiWorkload;
  preferredProvider?: AiProvider;
  preferredModel?: string;
  allowHosted?: boolean;
  allowLocal?: boolean;
}) {
  const primary = supportedAiProviders[0];

  const selectedModel =
    input.preferredModel && primary.models.includes(input.preferredModel)
      ? input.preferredModel
      : primary.defaultModelByWorkload[input.workload];
  const fallbackModel =
    primary.models.find((model) => model === "qwen/qwen3.6-27b" && model !== selectedModel) ??
    primary.models.find((model) => model !== selectedModel) ??
    null;

  return {
    provider: primary.code,
    model: selectedModel,
    timeoutMs: primary.timeoutMsByWorkload[input.workload],
    fallbacks: fallbackModel ? [fallbackModel] : [],
  };
}
