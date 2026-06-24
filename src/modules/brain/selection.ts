import { and, desc, eq, or } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { modelArtifacts, trainingJobs } from "../../db/schema.js";

type BrainModelRow = {
  id: string;
  name: string;
  scope: "user" | "shared";
  provider: string;
  baseModel: string;
  adapterKind: string;
  status: string;
  storageUri: string | null;
  checksum: string | null;
  updatedAt: Date;
  metadata: unknown;
};

type BrainTrainingJobRow = {
  id: string;
  baseModel: string;
  kind: string;
  status: string;
  config: unknown;
  updatedAt: Date;
};

export type SharedBrainSelection = {
  readyModels: BrainModelRow[];
  activeSharedModel: BrainModelRow | null;
  rollbackSharedModel: BrainModelRow | null;
  activeUserModel: BrainModelRow | null;
  warmupJob: BrainTrainingJobRow | null;
  baseModel: string;
  activeAdapter: string;
  trainingPlan: Record<string, unknown> | null;
};

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function readString(record: Record<string, unknown> | null, key: string): string | null {
  if (!record) {
    return null;
  }

  const value = record[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readAdapterStrategy(model: BrainModelRow | null, warmupJob: BrainTrainingJobRow | null): string {
  const modelMetadata = readRecord(model?.metadata);
  const jobConfig = readRecord(warmupJob?.config);

  return (
    readString(modelMetadata, "adapterStrategy") ??
    readString(modelMetadata, "adapter_kind") ??
    readString(jobConfig, "adapterStrategy") ??
    readString(jobConfig, "adapterKind") ??
    model?.adapterKind?.trim() ??
    warmupJob?.kind?.trim() ??
    "base"
  );
}

export function isCompleteReadyBrainModelArtifact(model: BrainModelRow | null | undefined): model is BrainModelRow {
  if (!model || model.status !== "ready") {
    return false;
  }

  return (
    typeof model.storageUri === "string" &&
    model.storageUri.trim().length > 0 &&
    typeof model.checksum === "string" &&
    model.checksum.trim().length > 0 &&
    typeof model.baseModel === "string" &&
    model.baseModel.trim().length > 0 &&
    typeof model.adapterKind === "string" &&
    model.adapterKind.trim().length > 0
  );
}

export async function resolveSharedBrainSelection(app: FastifyInstance, userId: string): Promise<SharedBrainSelection> {
  const [models, warmupJobs] = await Promise.all([
    app.db
      .select({
        id: modelArtifacts.id,
        name: modelArtifacts.name,
        scope: modelArtifacts.scope,
        provider: modelArtifacts.provider,
        baseModel: modelArtifacts.baseModel,
        adapterKind: modelArtifacts.adapterKind,
        status: modelArtifacts.status,
        storageUri: modelArtifacts.storageUri,
        checksum: modelArtifacts.checksum,
        updatedAt: modelArtifacts.updatedAt,
        metadata: modelArtifacts.metadata,
      })
      .from(modelArtifacts)
      .where(
        and(
          eq(modelArtifacts.status, "ready"),
          or(eq(modelArtifacts.scope, "shared"), eq(modelArtifacts.ownerUserId, userId)),
        ),
      )
      .orderBy(desc(modelArtifacts.scope), desc(modelArtifacts.updatedAt))
      .limit(10),
    app.db
      .select({
        id: trainingJobs.id,
        baseModel: trainingJobs.baseModel,
        kind: trainingJobs.kind,
        status: trainingJobs.status,
        config: trainingJobs.config,
        updatedAt: trainingJobs.updatedAt,
      })
      .from(trainingJobs)
      .where(
        and(
          eq(trainingJobs.scope, "shared"),
          or(eq(trainingJobs.status, "queued"), eq(trainingJobs.status, "running")),
        ),
      )
      .orderBy(desc(trainingJobs.updatedAt))
      .limit(1),
  ]);

  const readyModels = (models as BrainModelRow[]).filter(isCompleteReadyBrainModelArtifact);
  const activeSharedModel = readyModels.find((model) => model.scope === "shared") ?? null;
  const activeUserModel = readyModels.find((model) => model.scope === "user") ?? null;
  const rollbackSharedModel = readyModels.filter((model) => model.scope === "shared")[1] ?? null;
  const warmupJob = (warmupJobs[0] ?? null) as BrainTrainingJobRow | null;
  const baseModel =
    activeSharedModel?.baseModel?.trim() ||
    warmupJob?.baseModel?.trim() ||
    activeUserModel?.baseModel?.trim() ||
    "llama3.2";

  return {
    readyModels,
    activeSharedModel,
    rollbackSharedModel,
    activeUserModel,
    warmupJob,
    baseModel,
    activeAdapter: readAdapterStrategy(activeSharedModel, warmupJob),
    trainingPlan: readRecord(warmupJob?.config),
  };
}
