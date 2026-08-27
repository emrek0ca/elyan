import { and, desc, eq, or } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { modelArtifacts, trainingJobs } from "../../db/schema.js";
import {
  asRecord as readRecord,
  recordString as readString,
} from "../../lib/record.js";

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

// Model artifacts change through explicit mutation paths, which invalidate
// this cache. A longer TTL keeps ordinary turns from reopening the same two
// artifact queries for every user while preserving mutation freshness.
const SHARED_BRAIN_SELECTION_CACHE_TTL_MS = 30_000;
const SHARED_BRAIN_SELECTION_CACHE_MAX_ENTRIES = 4_096;

type SelectionCacheEntry = {
  value?: SharedBrainSelection;
  expiresAt: number;
  pending?: Promise<SharedBrainSelection>;
};

const selectionCache = new WeakMap<
  FastifyInstance,
  Map<string, SelectionCacheEntry>
>();

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

export function invalidateSharedBrainSelection(
  app: FastifyInstance,
  userId?: string,
): void {
  if (userId) {
    selectionCache.get(app)?.delete(userId);
  } else {
    selectionCache.delete(app);
  }
}

export async function resolveSharedBrainSelection(
  app: FastifyInstance,
  userId: string,
): Promise<SharedBrainSelection> {
  let cache = selectionCache.get(app);
  if (!cache) {
    cache = new Map();
    selectionCache.set(app, cache);
  }
  const now = Date.now();
  const cached = cache.get(userId);
  if (cached?.value && cached.expiresAt > now) {
    return cached.value;
  }
  if (cached?.pending) {
    return cached.pending;
  }

  if (!cached && cache.size >= SHARED_BRAIN_SELECTION_CACHE_MAX_ENTRIES) {
    const oldestKey = cache.keys().next().value;
    if (typeof oldestKey === "string") cache.delete(oldestKey);
  }
  const pending = querySharedBrainSelection(app, userId);
  cache.set(userId, { expiresAt: 0, pending });
  try {
    const value = await pending;
    cache.set(userId, {
      value,
      expiresAt: Date.now() + SHARED_BRAIN_SELECTION_CACHE_TTL_MS,
    });
    return value;
  } catch (error) {
    cache.delete(userId);
    throw error;
  }
}

async function querySharedBrainSelection(
  app: FastifyInstance,
  userId: string,
): Promise<SharedBrainSelection> {
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
