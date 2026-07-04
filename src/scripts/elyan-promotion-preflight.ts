import { fileURLToPath } from "node:url";
import { buildApp } from "../app/build-app.js";
import { loadEnv } from "../config/env.js";
import { getBrainProfile } from "../modules/brain/service.js";

type CliOptions = {
  userId: string | null;
};

function parseOptions(argv: string[]): CliOptions {
  let userId: string | null = null;

  for (const arg of argv) {
    if (arg.startsWith("--user-id=")) {
      userId = arg.slice("--user-id=".length).trim() || null;
      continue;
    }
    if (arg === "--help" || arg === "-h") {
      console.log(
        [
          "Usage: npm run brain:elyan-promotion-preflight -- --user-id=<uuid>",
          "",
          "Prints a safe promotion preflight for the Elyan model provider plan.",
          "This command never changes routing flags, model artifacts, or live traffic.",
        ].join("\n"),
      );
      process.exit(0);
    }
  }

  return { userId };
}

function readRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readBoolean(value: unknown): boolean {
  return value === true;
}

function readArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function shapeElyanPromotionPreflight(profile: Awaited<ReturnType<typeof getBrainProfile>>) {
  const chat = readRecord(profile.chat);
  const learning = readRecord(profile.learning);
  const training = readRecord(profile.training);
  const benchmark = readRecord(profile.benchmark);
  const latency = readRecord(readRecord(training.brainLatency).recentBrainTimeoutCount !== undefined ? training.brainLatency : chat.latencySummary);
  const elyanModel = readRecord(training.elyanModel ?? learning.elyanModel);
  const providerPlan = readRecord(training.elyanProviderPlan ?? learning.elyanProviderPlan ?? chat.elyanProviderPlan);
  const activeArtifact = readRecord(chat.activeArtifact ?? chat.activeSharedModel ?? chat.activeUserModel);
  const traffic = readRecord(providerPlan.traffic);
  const safety = readRecord(providerPlan.safety);
  const gates = readRecord(elyanModel.gates);
  const blockers = [
    readString(activeArtifact.id) ? null : "ready_elyan_model_missing",
    readBoolean(providerPlan.transportReady) ? null : "transport_not_ready",
    readBoolean(providerPlan.shadowEvaluationEnabled) ? null : "shadow_evaluation_not_enabled",
    providerPlan.routeReason === "canary_disabled" ? "canary_flag_disabled" : null,
    providerPlan.routeReason === "primary_disabled" ? "primary_flag_disabled" : null,
    providerPlan.routeReason === "workload_not_canary_safe" ? "workload_not_canary_safe" : null,
    providerPlan.routeReason === "runtime_not_ready" ? "runtime_not_ready" : null,
    providerPlan.routeReason === "no_ready_elyan_model" ? "no_ready_elyan_model" : null,
    readNumber(elyanModel.evaluationScore) !== null &&
    readNumber(gates.minimumEvaluationScoreForCanary) !== null &&
    (readNumber(elyanModel.evaluationScore) ?? 0) < (readNumber(gates.minimumEvaluationScoreForCanary) ?? 0)
      ? "evaluation_score_below_canary_gate"
      : null,
    readNumber(benchmark.latestOverallScore) !== null &&
    readNumber(gates.minimumBenchmarkScoreForPrimary) !== null &&
    (readNumber(benchmark.latestOverallScore) ?? 0) < (readNumber(gates.minimumBenchmarkScoreForPrimary) ?? 0)
      ? "benchmark_score_below_primary_gate"
      : null,
  ].filter((item): item is string => Boolean(item));
  const liveRoutingEnabled = readBoolean(providerPlan.liveRoutingEnabled);
  const nextAction =
    providerPlan.routeReason === "elyan_primary_ready"
      ? "operator_can_retire_groq_after_final_review"
      : providerPlan.routeReason === "elyan_primary_candidate"
        ? "operator_can_enable_primary_after_review"
        : providerPlan.routeReason === "elyan_canary_candidate"
          ? "monitor_canary_before_primary"
          : providerPlan.routeReason === "shadow_eval_only" || readBoolean(providerPlan.shadowEvaluationEnabled)
            ? "run_or_review_shadow_evaluation"
            : "resolve_promotion_blockers";

  return {
    canChangeLiveTraffic: liveRoutingEnabled,
    nextAction,
    blockers,
    artifact: {
      id: readString(activeArtifact.id),
      scope: readString(activeArtifact.scope),
      provider: readString(activeArtifact.provider),
      baseModel: readString(activeArtifact.baseModel),
      adapterKind: readString(activeArtifact.adapterKind),
      hasStorageUri: Boolean(readString(activeArtifact.storageUri)),
      hasChecksum: Boolean(readString(activeArtifact.checksum)),
    },
    modelPolicy: {
      stage: readString(elyanModel.stage),
      elyanRole: readString(elyanModel.elyanRole),
      groqRole: readString(elyanModel.groqRole),
      servingStrategy: readString(elyanModel.servingStrategy),
      canShadowEvaluate: readBoolean(elyanModel.canShadowEvaluate),
      canCanary: readBoolean(elyanModel.canCanary),
      canPromoteLocalPrimary: readBoolean(elyanModel.canPromoteLocalPrimary),
      canRetireGroq: readBoolean(elyanModel.canRetireGroq),
      policyNextAction: readString(elyanModel.nextAction),
      policyBlockers: readArray(elyanModel.blockers).map(String),
      gates,
    },
    providerPlan: {
      routeReason: readString(providerPlan.routeReason),
      liveRoutingEnabled,
      shadowEvaluationEnabled: readBoolean(providerPlan.shadowEvaluationEnabled),
      canaryEnabled: readBoolean(providerPlan.canaryEnabled),
      primaryEnabled: readBoolean(providerPlan.primaryEnabled),
      transportProvider: readString(providerPlan.transportProvider),
      transportReady: readBoolean(providerPlan.transportReady),
      traffic,
      safety,
    },
    latestEvidence: {
      benchmarkRunAt: readString(benchmark.latestRunAt),
      benchmarkOverallScore: readNumber(benchmark.latestOverallScore),
      recentBrainTimeoutCount: readNumber(latency.recentBrainTimeoutCount),
    },
  };
}

export async function runElyanPromotionPreflightCli(argv = process.argv.slice(2)): Promise<number> {
  try {
    process.loadEnvFile();
  } catch (error) {
    const code = typeof error === "object" && error && "code" in error ? String((error as { code?: string }).code) : "";
    if (code !== "ENOENT") {
      throw error;
    }
  }

  const options = parseOptions(argv);
  if (!options.userId) {
    console.error("Missing required --user-id=<uuid>. Use --help for usage.");
    return 1;
  }

  const app = await buildApp(loadEnv());
  try {
    const profile = await getBrainProfile(app, options.userId);
    console.log(
      JSON.stringify(
        {
          mode: "preflight",
          wrote: false,
          ...shapeElyanPromotionPreflight(profile),
        },
        null,
        2,
      ),
    );
    return 0;
  } catch (error) {
    console.error("Elyan promotion preflight failed:", error instanceof Error ? error.message : error);
    return 1;
  } finally {
    await app.close();
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  process.exitCode = await runElyanPromotionPreflightCli();
}
