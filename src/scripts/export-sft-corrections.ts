import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { buildApp } from "../app/build-app.js";
import { loadEnv } from "../config/env.js";
import { exportSftReadyCorrectionsDataset } from "../modules/brain/review.js";
import { asRecordOrEmpty as readRecord } from "../lib/record.js";

type CliOptions = {
  actorUserId: string;
  writeJsonlPath: string | null;
};

function parseOptions(argv: string[]): CliOptions {
  let actorUserId = "system:elyan-sft-exporter";
  let writeJsonlPath: string | null = null;

  for (const arg of argv) {
    if (arg.startsWith("--actor-user-id=")) {
      actorUserId = arg.slice("--actor-user-id=".length).trim() || actorUserId;
      continue;
    }
    if (arg.startsWith("--write-jsonl=")) {
      writeJsonlPath = arg.slice("--write-jsonl=".length).trim() || null;
      continue;
    }
    if (arg === "--help" || arg === "-h") {
      console.log(
        [
          "Usage: npm run brain:export-sft-corrections -- [--actor-user-id=<id>] [--write-jsonl=<path>]",
          "",
          "Exports a shared SFT-ready dataset manifest from human-approved correction reviews.",
          "The command prints only safe manifest metadata by default. Use --write-jsonl to persist the JSONL artifact locally.",
        ].join("\n"),
      );
      process.exit(0);
    }
  }

  return {
    actorUserId,
    writeJsonlPath,
  };
}

function shapeSafeExportSummary(result: Awaited<ReturnType<typeof exportSftReadyCorrectionsDataset>>, jsonlWrittenTo: string | null) {
  const manifest = result.manifest;
  const metadata = readRecord(manifest?.metadata);
  return {
    ok: Boolean(manifest),
    dataset: {
      id: manifest?.id ?? null,
      name: manifest?.name ?? null,
      status: manifest?.status ?? null,
      scope: manifest?.scope ?? null,
      source: manifest?.source ?? null,
      format: manifest?.format ?? null,
      locator: manifest?.locator ?? null,
      recordCount: manifest?.recordCount ?? 0,
      tokenEstimate: manifest?.tokenEstimate ?? 0,
      datasetVersion: result.datasetVersion,
      jsonlWrittenTo,
    },
    quality: {
      datasetRole: metadata.datasetRole ?? null,
      approvedCorrectionsOnly: metadata.approvedCorrectionsOnly === true,
      sourceLineage: metadata.sourceLineage ?? null,
      compactionMode: metadata.compactionMode ?? null,
      approvedCorrectionCount: metadata.approvedCorrectionCount ?? null,
      compactedRecordCount: metadata.compactedRecordCount ?? null,
      freshSignalCount: metadata.freshSignalCount ?? null,
      correctionDensity: metadata.correctionDensity ?? null,
      freshSignalRatio: metadata.freshSignalRatio ?? null,
      signalFreshnessScore: metadata.signalFreshnessScore ?? null,
      lineageScore: metadata.lineageScore ?? null,
      compactionQualityScore: metadata.compactionQualityScore ?? null,
      compactDatasetEligible: metadata.compactDatasetEligible ?? null,
      latestApprovedAt: metadata.latestApprovedAt ?? null,
      oldestApprovedAt: metadata.oldestApprovedAt ?? null,
    },
    nextAction:
      manifest && metadata.compactDatasetEligible === true
        ? "queue_elyan_model_refresh"
        : "approve_more_recent_corrections_before_training",
  };
}

try {
  process.loadEnvFile();
} catch (error) {
  const code = typeof error === "object" && error && "code" in error ? String((error as { code?: string }).code) : "";
  if (code !== "ENOENT") {
    throw error;
  }
}

const options = parseOptions(process.argv.slice(2));
const app = await buildApp(loadEnv());

try {
  const result = await exportSftReadyCorrectionsDataset(app, {
    actorUserId: options.actorUserId,
    requestId: `cli:${Date.now()}`,
  });

  let writtenPath: string | null = null;
  if (options.writeJsonlPath) {
    const resolved = path.resolve(process.cwd(), options.writeJsonlPath);
    await mkdir(path.dirname(resolved), { recursive: true });
    await writeFile(resolved, `${result.jsonl}\n`, { encoding: "utf8", mode: 0o600 });
    writtenPath = resolved;
  }

  console.log(JSON.stringify(shapeSafeExportSummary(result, writtenPath), null, 2));
} catch (error) {
  console.error("SFT correction dataset export failed:", error instanceof Error ? error.message : error);
  process.exitCode = 1;
} finally {
  await app.close();
}
