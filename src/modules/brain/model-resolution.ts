import type { FastifyInstance } from "fastify";
import type { SharedBrainRuntimeSnapshot } from "./runtime.js";
import { selectSharedBrainRuntime } from "./runtime.js";
import { resolveSharedBrainSelection, type SharedBrainSelection } from "./selection.js";
import type { SharedBrainWorkload } from "./workloads.js";
import {
  buildGroqModelCatalog,
  resolveGroqModelForWorkload,
  resolveGroqFallbackModel,
} from "./groq-models.js";

export type SharedBrainModelSource = "artifact" | "configured" | "installed_fallback" | "default";

export type SharedBrainModelResolution = {
  configuredBaseModel: string;
  resolvedBaseModel: string | null;
  resolvedFallbackModel: string | null;
  resolvedBaseModelSource: SharedBrainModelSource;
  availableModels: string[];
  runtime: SharedBrainRuntimeSnapshot;
  selection: SharedBrainSelection;
};

const OLLAMA_MODEL_PREFERENCES_BY_WORKLOAD: Record<SharedBrainWorkload, string[]> = {
  intent: [
    "qwen2.5-coder:3b",
    "qwen2.5:7b-instruct-q5_K_M",
    "llama3.2",
    "llama3:8b",
    "llama3.1:8b",
    "qwen2.5:7b",
  ],
  fast_route: [
    "qwen2.5-coder:3b",
    "qwen2.5:7b-instruct-q5_K_M",
    "llama3.2",
    "llama3:8b",
    "llama3.1:8b",
    "qwen2.5:7b",
  ],
  mobile_chat_fast: [
    "qwen2.5:7b-instruct-q5_K_M",
    "qwen2.5:7b-instruct",
    "llama3:8b",
    "llama3.1:8b",
    "deepseek-r1:8b",
    "llama3.2",
    "qwen2.5-coder:3b",
    "qwen2.5:7b",
  ],
  mobile_chat_balanced: [
    "qwen2.5:7b-instruct-q5_K_M",
    "qwen2.5:7b-instruct",
    "deepseek-r1:8b",
    "llama3:8b",
    "llama3.1:8b",
    "qwen2.5-coder:3b",
    "llama3.2",
  ],
  mobile_chat_deep_refine: [
    "qwen2.5:7b-instruct-q5_K_M",
    "qwen2.5:7b-instruct",
    "deepseek-r1:8b",
    "llama3:8b",
    "qwen2.5:7b",
    "llama3.1:8b",
    "qwen2.5-coder:3b",
  ],
  document_analysis: [
    "qwen2.5:7b-instruct-q5_K_M",
    "qwen2.5:7b-instruct",
    "deepseek-r1:8b",
    "llama3:8b",
    "llama3.1:8b",
    "qwen2.5-coder:3b",
    "llama3.2",
  ],
  planning: [
    "qwen2.5:7b-instruct-q5_K_M",
    "qwen2.5:7b-instruct",
    "deepseek-r1:8b",
    "llama3:8b",
    "qwen2.5:7b",
    "llama3.1:8b",
    "qwen2.5-coder:3b",
  ],
  document_generate: [
    "qwen2.5:7b-instruct-q5_K_M",
    "qwen2.5:7b-instruct",
    "deepseek-r1:8b",
    "llama3:8b",
    "llama3.1:8b",
  ],
  table_generate: [
    "qwen2.5:7b-instruct-q5_K_M",
    "qwen2.5:7b-instruct",
    "llama3:8b",
    "llama3.1:8b",
  ],
  image_analyze: [],
  desktop_handoff: [],
  vision_reasoning: [],
};

function normalizeModelName(value: string): string {
  return value.trim().toLowerCase();
}

function uniqueModels(models: string[]): string[] {
  return [...new Set(models.map((model) => model.trim()).filter(Boolean))];
}

function hasHostedSharedBrainProviderConfigured(app: FastifyInstance): boolean {
  return Boolean(
    app.config.OPENAI_API_KEY ||
      app.config.ANTHROPIC_API_KEY ||
      app.config.GROQ_API_KEY ||
      app.config.OPENROUTER_API_KEY,
  );
}

function hasGroqPrimaryConfigured(app: FastifyInstance): boolean {
  return Boolean(app.config.GROQ_API_KEY && app.config.GROQ_API_KEY.trim().length > 0);
}

function getConfiguredModelForWorkload(
  app: FastifyInstance,
  workload: SharedBrainWorkload,
): string {
  const trimOr = (value: unknown, fallback: string) => {
    const trimmed = typeof value === "string" ? value.trim() : "";
    return trimmed || fallback;
  };
  const defaultFastModel = "qwen2.5-coder:3b";
  const defaultBalancedModel = "qwen2.5:7b-instruct-q5_K_M";

  if (workload === "planning" || workload === "mobile_chat_deep_refine") {
    return trimOr(app.config.ELYAN_SHARED_BRAIN_PLANNING_MODEL, defaultBalancedModel);
  }
  if (workload === "mobile_chat_balanced" || workload === "document_analysis") {
    return trimOr(app.config.ELYAN_SHARED_BRAIN_BALANCED_MODEL, defaultBalancedModel);
  }
  if (workload === "mobile_chat_fast" || workload === "fast_route" || workload === "intent") {
    return trimOr(app.config.ELYAN_SHARED_BRAIN_FAST_MODEL, defaultFastModel);
  }
  return trimOr(app.config.ELYAN_SHARED_BRAIN_MODEL, "llama3.2");
}

function pickPreferredInstalledModel(
  availableModels: string[],
  workload: SharedBrainWorkload,
  exclude: string[] = [],
): string | null {
  const normalizedAvailable = new Map(
    availableModels.map((model) => [normalizeModelName(model), model] as const),
  );
  const excluded = new Set(exclude.map((model) => normalizeModelName(model)));

  for (const preferredModel of OLLAMA_MODEL_PREFERENCES_BY_WORKLOAD[workload]) {
    const normalizedPreferred = normalizeModelName(preferredModel);
    if (excluded.has(normalizedPreferred)) {
      continue;
    }
    const resolved = normalizedAvailable.get(normalizedPreferred);
    if (resolved) {
      return resolved;
    }
  }

  return availableModels.find((model) => !excluded.has(normalizeModelName(model))) ?? null;
}

async function loadOllamaModelNames(baseUrl: string): Promise<string[]> {
  const response = await fetch(`${baseUrl}/api/tags`, {
    signal: AbortSignal.timeout(4_000),
  });
  if (!response.ok) {
    return [];
  }

  const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  const models = Array.isArray(payload.models) ? payload.models : [];
  const names = models
    .map((model) => {
      if (!model || typeof model !== "object" || Array.isArray(model)) {
        return "";
      }

      const record = model as Record<string, unknown>;
      const name = typeof record.name === "string" ? record.name : "";
      const fallback = typeof record.model === "string" ? record.model : "";
      return (name || fallback).trim();
    })
    .filter(Boolean);

  return uniqueModels(names);
}

function getResolvedArtifactModel(selection: SharedBrainSelection): string | null {
  return (
    selection.activeSharedModel?.baseModel?.trim() ||
    selection.warmupJob?.baseModel?.trim() ||
    selection.activeUserModel?.baseModel?.trim() ||
    null
  );
}

export async function resolveSharedBrainModel(
  app: FastifyInstance,
  input: {
    userId: string;
    workload?: SharedBrainWorkload;
    selection?: SharedBrainSelection;
    runtime?: SharedBrainRuntimeSnapshot;
  },
): Promise<SharedBrainModelResolution> {
  const workload = input.workload ?? "mobile_chat_fast";
  const selection = input.selection ?? (await resolveSharedBrainSelection(app, input.userId));
  const runtime = input.runtime ?? (await selectSharedBrainRuntime(app));
  const groqPrimaryConfigured = hasGroqPrimaryConfigured(app);
  if (groqPrimaryConfigured) {
    const catalog = buildGroqModelCatalog(app.config);
    const resolvedBaseModel = resolveGroqModelForWorkload(app.config, workload);
    return {
      configuredBaseModel: catalog.reasoningModel,
      resolvedBaseModel,
      resolvedFallbackModel:
        resolveGroqFallbackModel(app.config, resolvedBaseModel, workload) ?? catalog.fallbackModel,
      resolvedBaseModelSource: "configured",
      availableModels: catalog.models,
      runtime,
      selection,
    };
  }
  const configuredBaseModel = app.config.ELYAN_SHARED_BRAIN_MODEL.trim();
  const configuredWorkloadModel = getConfiguredModelForWorkload(app, workload);
  const localOnlyServing = !hasHostedSharedBrainProviderConfigured(app);
  const availableModels =
    runtime.ready && runtime.provider === "ollama" ? await loadOllamaModelNames(runtime.baseUrl) : [];
  const artifactModel = getResolvedArtifactModel(selection);
  const warmupBaseModel = selection.warmupJob?.baseModel?.trim() ?? "";
  const preferredCandidates =
    workload === "mobile_chat_fast" || workload === "fast_route" || workload === "intent"
      ? uniqueModels(
          [
            configuredWorkloadModel,
            ...(localOnlyServing ? [artifactModel ?? ""] : []),
            configuredBaseModel,
            warmupBaseModel,
          ].filter((candidate): candidate is string => Boolean(candidate)),
        )
      : uniqueModels(
          [artifactModel, configuredWorkloadModel, configuredBaseModel, warmupBaseModel].filter(
            (candidate): candidate is string => Boolean(candidate),
          ),
        );

  for (const candidate of preferredCandidates) {
    if (availableModels.some((model) => normalizeModelName(model) === normalizeModelName(candidate))) {
      const fallbackModel = pickPreferredInstalledModel(availableModels, workload, [candidate]);
      return {
        configuredBaseModel,
        resolvedBaseModel: candidate,
        resolvedFallbackModel: fallbackModel,
        resolvedBaseModelSource: candidate === artifactModel ? "artifact" : "configured",
        availableModels,
        runtime,
        selection,
      };
    }
  }

  if (availableModels.length > 0) {
    const resolvedBaseModel = pickPreferredInstalledModel(availableModels, workload);
    const fallbackModel = pickPreferredInstalledModel(
      availableModels,
      workload,
      resolvedBaseModel ? [resolvedBaseModel] : [],
    );
    return {
      configuredBaseModel,
      resolvedBaseModel,
      resolvedFallbackModel: fallbackModel,
      resolvedBaseModelSource: resolvedBaseModel ? "installed_fallback" : "default",
      availableModels,
      runtime,
      selection,
    };
  }

  if (artifactModel) {
    return {
      configuredBaseModel,
      resolvedBaseModel: artifactModel,
      resolvedFallbackModel: null,
      resolvedBaseModelSource: "artifact",
      availableModels,
      runtime,
      selection,
    };
  }

  if (configuredBaseModel) {
    return {
      configuredBaseModel,
      resolvedBaseModel: configuredBaseModel,
      resolvedFallbackModel: null,
      resolvedBaseModelSource: "configured",
      availableModels,
      runtime,
      selection,
    };
  }

  return {
    configuredBaseModel,
    resolvedBaseModel: null,
    resolvedFallbackModel: null,
    resolvedBaseModelSource: "default",
    availableModels,
    runtime,
    selection,
  };
}
