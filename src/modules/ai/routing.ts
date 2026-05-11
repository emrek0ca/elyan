import type { AiProvider } from "../../contracts/domain.js";
import { supportedAiProviders } from "./provider-registry.js";

export type AiWorkload = "intent" | "planning" | "fast_route";

export function resolveAiRoute(input: {
  workload: AiWorkload;
  preferredProvider?: AiProvider;
  preferredModel?: string;
  allowHosted?: boolean;
  allowLocal?: boolean;
}) {
  const providers = supportedAiProviders.filter((provider) => {
    if (input.preferredProvider && provider.code === input.preferredProvider) {
      return true;
    }

    if (input.allowHosted === false && provider.hosted) {
      return false;
    }

    if (input.allowLocal === false && !provider.hosted) {
      return false;
    }

    return provider.workloads.includes(input.workload);
  });

  const primary =
    providers.find((provider) => provider.code === input.preferredProvider) ??
    providers.find((provider) => provider.workloads.includes(input.workload)) ??
    supportedAiProviders.find((provider) => provider.code === "openrouter") ??
    supportedAiProviders[0];

  const selectedModel =
    input.preferredModel && primary.models.includes(input.preferredModel)
      ? input.preferredModel
      : primary.defaultModelByWorkload[input.workload];

  return {
    provider: primary.code,
    model: selectedModel,
    timeoutMs: primary.timeoutMsByWorkload[input.workload],
    fallbacks: supportedAiProviders
      .filter((provider) => provider.code !== primary.code && provider.workloads.includes(input.workload))
      .map((provider) => ({
        provider: provider.code,
        model: provider.defaultModelByWorkload[input.workload],
        timeoutMs: provider.timeoutMsByWorkload[input.workload],
      })),
  };
}
