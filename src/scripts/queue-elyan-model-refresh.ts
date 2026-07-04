import { buildApp } from "../app/build-app.js";
import { loadEnv } from "../config/env.js";
import { fileURLToPath } from "node:url";
import {
  getBrainProfile,
  queueContinuousBrainTrainingJob,
} from "../modules/brain/service.js";

type CliOptions = {
  userId: string | null;
  execute: boolean;
};

function parseOptions(argv: string[]): CliOptions {
  let userId: string | null = null;
  let execute = false;

  for (const arg of argv) {
    if (arg.startsWith("--user-id=")) {
      userId = arg.slice("--user-id=".length).trim() || null;
      continue;
    }
    if (arg === "--execute") {
      execute = true;
      continue;
    }
    if (arg === "--help" || arg === "-h") {
      console.log(
        [
          "Usage: npm run brain:queue-elyan-refresh -- --user-id=<uuid> [--execute]",
          "",
          "Runs a safe preflight for the Elyan model refresh queue.",
          "Without --execute it only prints gate status and writes nothing.",
          "With --execute it delegates to queueContinuousBrainTrainingJob.",
        ].join("\n"),
      );
      process.exit(0);
    }
  }

  return {
    userId,
    execute,
  };
}

function readRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

export function shapeRefreshQueuePreflight(profile: Awaited<ReturnType<typeof getBrainProfile>>) {
  const training = readRecord(profile.training);
  const learning = readRecord(profile.learning);
  const chat = readRecord(profile.chat);
  const benchmark = readRecord(profile.benchmark);
  const pipeline = readRecord(training.pipeline);
  const queueEligibility = readRecord(training.queueEligibility);
  const trainingEligibility = readRecord(training.trainingEligibility);
  const correctionDatasetStatus = readRecord(learning.correctionDatasetStatus);
  const elyanModel = readRecord(training.elyanModel ?? learning.elyanModel);
  const elyanProviderPlan = readRecord(training.elyanProviderPlan ?? learning.elyanProviderPlan ?? chat.elyanProviderPlan);
  const activeSharedJobId =
    pipeline.activeJobId ??
    readRecord(pipeline.continuousImprovement).activeSharedJobId ??
    null;
  const qualityGateReady = queueEligibility.status === "ready_for_queue";
  const datasetReady = trainingEligibility.approvedCorrectionDatasetReady === true;
  const compactDatasetEligible = trainingEligibility.compactDatasetEligible !== false;
  const benchmarkReady =
    trainingEligibility.benchmarkBaselineReady === true &&
    trainingEligibility.benchmarkScoreAttached === true;
  const canQueue =
    !activeSharedJobId &&
    qualityGateReady &&
    datasetReady &&
    compactDatasetEligible &&
    benchmarkReady;

  return {
    canQueue,
    nextAction: canQueue ? "queue_elyan_model_refresh" : "resolve_blockers",
    blockers: [
      activeSharedJobId ? "active_shared_training_job_exists" : null,
      qualityGateReady ? null : "quality_gate_not_ready",
      datasetReady ? null : "sft_ready_dataset_missing",
      compactDatasetEligible ? null : "compact_dataset_not_eligible",
      benchmarkReady ? null : "benchmark_baseline_missing",
    ].filter((item): item is string => Boolean(item)),
    gates: {
      activeSharedJobId,
      activeSharedJobStatus: pipeline.activeJobStatus ?? null,
      qualityGateStatus: queueEligibility.status ?? null,
      qualityGateReasons: Array.isArray(queueEligibility.reasons) ? queueEligibility.reasons : [],
      approvedCorrectionDatasetReady: datasetReady,
      correctionDatasetId: correctionDatasetStatus.datasetId ?? null,
      compactDatasetEligible,
      compactDatasetQualityScore: trainingEligibility.compactDatasetQualityScore ?? null,
      benchmarkBaselineReady: benchmarkReady,
      benchmarkLatestRunAt: benchmark.latestRunAt ?? null,
      benchmarkLatestOverallScore: benchmark.latestOverallScore ?? null,
    },
    elyanModel: {
      stage: elyanModel.stage ?? null,
      elyanRole: elyanModel.elyanRole ?? null,
      groqRole: elyanModel.groqRole ?? null,
      servingStrategy: elyanModel.servingStrategy ?? null,
      policyNextAction: elyanModel.nextAction ?? null,
    },
    providerPlan: {
      logicalProvider: elyanProviderPlan.logicalProvider ?? null,
      routeReason: elyanProviderPlan.routeReason ?? null,
      liveRoutingEnabled: elyanProviderPlan.liveRoutingEnabled ?? false,
      traffic: elyanProviderPlan.traffic ?? null,
    },
  };
}

export async function runQueueElyanModelRefreshCli(argv = process.argv.slice(2)): Promise<number> {
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
    const preflight = shapeRefreshQueuePreflight(profile);

    if (!options.execute) {
      console.log(
        JSON.stringify(
          {
            mode: "preflight",
            wrote: false,
            ...preflight,
          },
          null,
          2,
        ),
      );
    } else {
      const result = await queueContinuousBrainTrainingJob(app, {
        userId: options.userId,
        requestId: `cli:${Date.now()}`,
        userAgent: "elyan-queue-refresh-cli",
      });
      console.log(
        JSON.stringify(
          {
            mode: "execute",
            wrote: result.created,
            reason: result.reason,
            job: result.job
              ? {
                  id: result.job.id,
                  status: result.job.status,
                  kind: result.job.kind,
                  baseModel: result.job.baseModel,
                  datasetManifestId: result.job.datasetManifestId ?? null,
                }
              : null,
            preflight,
          },
          null,
          2,
        ),
      );
    }
    return 0;
  } catch (error) {
    console.error("Elyan model refresh queue failed:", error instanceof Error ? error.message : error);
    return 1;
  } finally {
    await app.close();
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  process.exitCode = await runQueueElyanModelRefreshCli();
}
