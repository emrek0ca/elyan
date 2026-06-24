import { and, desc, eq, or } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { modelArtifacts, trainingJobs } from "../../db/schema.js";
import { createAuditLog } from "../audit/service.js";
import { ensureSharedBrainTargetDevice } from "../devices/service.js";

export const SHARED_TRAINING_PLAN = {
  modelName: "Elyan",
  trainingBackend: "pytorch",
  dataSources: [
    "learning_events",
    "task_feedback",
    "chat_summaries",
    "synthetic_examples",
    "runtime_connections",
    "pairing_sessions",
    "task_dispatch_traces",
  ],
  adapterStrategy: "lora",
  adapterMode: "qlora",
  adapterLibrary: "peft",
  baseModelCacheStrategy: "warm_once_then_reuse",
  bridgeStrategy: "mobile_desktop_sync",
  bridgeTargets: ["task_handoff", "session_reconnect", "dispatch_resilience"],
  bridgeLearning: {
    routingSignals: ["task_target", "routing_mode"],
    bridgeSignals: ["routing_outcome", "bridge_readiness"],
    successThreshold: 0.72,
  },
  evaluationPolicy: {
    metrics: [
      "task_success",
      "response_quality",
      "latency",
      "contract_compliance",
      "routing_consistency",
      "handoff_success",
      "reconnect_resilience",
    ],
    minimumCompositeScore: 0.72,
  },
  promotionPolicy: {
    keepPreviousReadyArtifact: true,
    rollbackAllowed: true,
    requiresReadyArtifact: true,
    requiresBridgeReadiness: true,
  },
  privacyPolicy: {
    redactPrivatePaths: true,
    requireSafeEvents: true,
    sharedOnlyPromotion: true,
    redactDeviceIdentifiers: true,
    redactRuntimeAddresses: true,
  },
};

export async function ensureElyanServerBrainBootstrap(app: FastifyInstance) {
  const sharedBrainDevice = await ensureSharedBrainTargetDevice(app);
  if (!sharedBrainDevice) {
    throw new Error("Shared brain device bootstrap failed");
  }

  const [sharedReadyModels, activeSharedJobs, readyUserModels] = await Promise.all([
    app.db
      .select({
        id: modelArtifacts.id,
        scope: modelArtifacts.scope,
      })
      .from(modelArtifacts)
      .where(and(eq(modelArtifacts.status, "ready"), eq(modelArtifacts.scope, "shared")))
      .limit(1),
    app.db
      .select({
        id: trainingJobs.id,
        status: trainingJobs.status,
      })
      .from(trainingJobs)
      .where(
        and(
          eq(trainingJobs.scope, "shared"),
          or(eq(trainingJobs.status, "queued"), eq(trainingJobs.status, "running")),
        ),
      )
      .limit(1),
    app.db
      .select({
        baseModel: modelArtifacts.baseModel,
      })
      .from(modelArtifacts)
      .where(and(eq(modelArtifacts.status, "ready"), eq(modelArtifacts.scope, "user")))
      .orderBy(desc(modelArtifacts.updatedAt))
      .limit(1),
  ]);

  if (sharedReadyModels[0] || activeSharedJobs[0]) {
    return {
      sharedBrainDevice,
      trainingJob: activeSharedJobs[0] ?? null,
      seeded: false,
    };
  }

  const baseModel = readyUserModels[0]?.baseModel?.trim() || "llama3.2";
  const rows = await app.db
    .insert(trainingJobs)
    .values({
      ownerUserId: null,
      scope: "shared",
      name: "Elyan main brain warmup",
      kind: "lora",
      status: "queued",
      baseModel,
      config: {
        bootstrap: true,
        source: "server_bootstrap",
        trainingBackend: "pytorch",
        adapterStrategy: "lora",
        adapterMode: "qlora",
        serverBrainName: "Elyan",
        sharedBrainDeviceId: sharedBrainDevice.id,
        learningTargets: ["chat", "tasks", "personalization", "mobile_desktop_sync"],
        providerStrategy: {
          primary: "groq",
          fallback: [],
        },
        trainingPlan: SHARED_TRAINING_PLAN,
      },
    })
    .returning();

  const trainingJob = rows[0] ?? null;

  if (trainingJob) {
    await createAuditLog(app, {
      actorType: "system",
      actorId: "elyan-bootstrap",
      action: "brain.training_job.bootstrap",
      resourceType: "training_job",
      resourceId: trainingJob.id,
      status: "success",
      payload: {
        baseModel,
        sharedBrainDeviceId: sharedBrainDevice.id,
      },
    });
  }

  return {
    sharedBrainDevice,
    trainingJob,
    seeded: true,
  };
}
