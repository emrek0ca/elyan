import { and, eq, inArray, isNull, lt, ne, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import type { AppEnv } from "../../config/env.js";
import { getBaseUrlReachability, getDatabaseReachability } from "../../config/env.js";
import { devices, runtimeConnections, tasks } from "../../db/schema.js";
import { getNeuralBrainReadiness } from "../brain/neural-readiness.js";
import { getBrainLatencySummary } from "../brain/latency-summary.js";
import { getRetrievalStatus } from "../brain/retrieval.js";
import { getSharedBrainProviderCircuitState, warmSharedBrainRuntime } from "../brain/runtime.js";
import { ELYAN_CONSTITUTION_GATE_READY, ELYAN_CONSTITUTION_VERSION, constitutionRuleCount } from "../brain/constitution.js";
import { getApprovedCorrectionDatasetState, getLatestBrainBenchmarkSummary } from "../brain/review.js";
import { getSharedBrainWorkloadProfile } from "../brain/workloads.js";
import { RUNTIME_CONNECTION_STALE_AFTER_MS } from "../devices/service.js";
import { activeTaskStatuses } from "../tasks/queue.js";

const coreSurfaces = [
  "ai",
  "auth",
  "billing",
  "brain",
  "chat",
  "devices",
  "mobile",
  "pairing",
  "realtime",
  "runtime",
  "tasks",
] as const;

export function getBillingDependencyStatus(
  env: Partial<
    Pick<
    AppEnv,
    | "APPLE_APP_STORE_ISSUER_ID"
    | "APPLE_APP_STORE_KEY_ID"
    | "APPLE_APP_STORE_PRIVATE_KEY"
    | "APPLE_APP_STORE_PRIVATE_KEY_PATH"
    | "APPLE_APP_BUNDLE_ID"
    | "APPLE_APP_ID"
    | "APPLE_SOLO_PRODUCT_ID"
    | "APPLE_PRO_PRODUCT_ID"
    | "GOOGLE_PLAY_PACKAGE_NAME"
    | "GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL"
    | "GOOGLE_PLAY_PRIVATE_KEY"
    | "IYZICO_API_KEY"
    | "IYZICO_SECRET_KEY"
    | "IYZICO_MERCHANT_ID"
    >
  >,
) {
  const appleMissing = [
    !env.APPLE_APP_STORE_ISSUER_ID ? "APPLE_APP_STORE_ISSUER_ID" : null,
    !env.APPLE_APP_STORE_KEY_ID ? "APPLE_APP_STORE_KEY_ID" : null,
    !env.APPLE_APP_STORE_PRIVATE_KEY && !env.APPLE_APP_STORE_PRIVATE_KEY_PATH
      ? "APPLE_APP_STORE_PRIVATE_KEY_OR_PATH"
      : null,
    !env.APPLE_APP_BUNDLE_ID ? "APPLE_APP_BUNDLE_ID" : null,
    !env.APPLE_APP_ID ? "APPLE_APP_ID" : null,
    !env.APPLE_SOLO_PRODUCT_ID ? "APPLE_SOLO_PRODUCT_ID" : null,
    !env.APPLE_PRO_PRODUCT_ID ? "APPLE_PRO_PRODUCT_ID" : null,
  ].filter((value): value is string => Boolean(value));

  const googleMissing = [
    !env.GOOGLE_PLAY_PACKAGE_NAME ? "GOOGLE_PLAY_PACKAGE_NAME" : null,
    !env.GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL ? "GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL" : null,
    !env.GOOGLE_PLAY_PRIVATE_KEY ? "GOOGLE_PLAY_PRIVATE_KEY" : null,
  ].filter((value): value is string => Boolean(value));

  const iyzicoMissing = [
    !env.IYZICO_API_KEY ? "IYZICO_API_KEY" : null,
    !env.IYZICO_SECRET_KEY ? "IYZICO_SECRET_KEY" : null,
    !env.IYZICO_MERCHANT_ID ? "IYZICO_MERCHANT_ID" : null,
  ].filter((value): value is string => Boolean(value));

  const appleReady = appleMissing.length === 0;
  const googleReady = googleMissing.length === 0;
  const legacyCheckoutReady = iyzicoMissing.length === 0;
  const storeVerificationEnabled = appleReady || googleReady;
  const availableProviders = [
    ...(appleReady ? ["apple_store"] : []),
    ...(googleReady ? ["google_play"] : []),
    ...(legacyCheckoutReady ? ["iyzico"] : []),
  ];

  return {
    provider: storeVerificationEnabled && legacyCheckoutReady ? "mixed" : storeVerificationEnabled ? "store_first" : "iyzico",
    checkoutEnabled: storeVerificationEnabled || legacyCheckoutReady,
    storeVerificationEnabled,
    legacyCheckoutEnabled: legacyCheckoutReady,
    availableProviders,
    status: storeVerificationEnabled || legacyCheckoutReady ? ("ready" as const) : ("degraded" as const),
    missingEnv: [...appleMissing, ...googleMissing, ...iyzicoMissing],
  };
}

type AgentReadiness = {
  chatReady: boolean;
  serverBrainReady: boolean;
  runtimeDispatchReady: boolean;
  realtimeReady: boolean;
  databaseReady: boolean;
  redisReady: boolean;
  providerCircuitState: "closed" | "open" | "half_open";
  queueHealthy: boolean;
  activeRuntimeConnections: number;
  staleRuntimeConnections: number;
  desktopReadyCount: number;
  desktopTaskReady: boolean;
  latestDesktopHeartbeatAgeSeconds: number | null;
  quantumReady: boolean;
  quantumDesktopReady: boolean;
  quantumCapabilitiesReady: boolean;
  quantumSupportedProblemClasses: string[];
  quantumBlockingReasons: string[];
  neuralReady: boolean;
  trainingWorkerReady: boolean;
  embeddingReady: boolean;
  evaluationReady: boolean;
  quantumLearningReady: boolean;
  activeTrainingJobs: number;
  latestEvaluationScore: number | null;
  latestQuantumBenchmarkScore: number | null;
  lastChatLatencyMs: number | null;
  lastStreamingFirstDeltaMs: number | null;
  completionLatencyP50Ms: number | null;
  completionLatencyP95Ms: number | null;
  firstDeltaP50Ms: number | null;
  firstDeltaP95Ms: number | null;
  attachmentCacheHitRate: number | null;
  recentResponseBytesAverage: number | null;
  sessionPageLatencyP50Ms: number | null;
  sessionPageLatencyP95Ms: number | null;
  sessionPageBytesP50: number | null;
  sessionPageBytesP95: number | null;
  recentBrainTimeoutCount: number;
  mlWorkerMode: string | null;
  mlWorkerLastJobAt: string | null;
  mlWorkerLastErrorCode: string | null;
  optionalLibraries: Record<string, boolean>;
  runnerBacklog: number | null;
  brainBlockingReasons: string[];
  staleActiveTaskCount: number;
  staleBlockingTaskCount: number;
  staleApprovalTaskCount: number;
  requestBudgetReady: boolean;
  blockingReasons: string[];
};

type RuntimeOperationalRow = {
  status: "online" | "busy" | "idle" | "offline";
  deviceType: "mobile" | "desktop";
  deviceIsActive: boolean;
  deviceUserId: string | null;
  lastHeartbeatAt: Date;
  capabilities?: unknown;
};

const REQUIRED_QUANTUM_CAPABILITIES = [
  "quantum.model.problem",
  "quantum.run.experiment",
  "quantum.compare.classical",
  "quantum.generate.report",
] as const;

function normalizeCapabilityList(input: unknown): string[] {
  if (!Array.isArray(input)) {
    return [];
  }
  return [
    ...new Set(
      input
        .map((capability) => String(capability ?? "").trim().toLowerCase().replace(/[\s_]+/g, "."))
        .filter(Boolean),
    ),
  ];
}

export function summarizeRuntimeOperationalRows(rows: RuntimeOperationalRow[], now = Date.now()) {
  let activeRuntimeConnections = 0;
  let staleRuntimeConnections = 0;
  let desktopReadyCount = 0;
  let latestDesktopHeartbeatAt: Date | null = null;
  let quantumDesktopReady = false;
  const supportedProblemClasses = new Set<string>();

  for (const row of rows) {
    const ageMs = now - row.lastHeartbeatAt.getTime();
    const fresh = row.status !== "offline" && ageMs <= RUNTIME_CONNECTION_STALE_AFTER_MS;
    const stale = row.status !== "offline" && ageMs > RUNTIME_CONNECTION_STALE_AFTER_MS;
    const userDesktop = row.deviceType === "desktop" && row.deviceIsActive && Boolean(row.deviceUserId);

    if (fresh) {
      activeRuntimeConnections += 1;
    }
    if (stale) {
      staleRuntimeConnections += 1;
    }
    if (userDesktop) {
      latestDesktopHeartbeatAt =
        !latestDesktopHeartbeatAt || row.lastHeartbeatAt.getTime() > latestDesktopHeartbeatAt.getTime()
          ? row.lastHeartbeatAt
          : latestDesktopHeartbeatAt;
      if (fresh) {
        desktopReadyCount += 1;
        const capabilities = normalizeCapabilityList(row.capabilities);
        const hasQuantumCapabilities = REQUIRED_QUANTUM_CAPABILITIES.every((capability) =>
          capabilities.includes(capability),
        );
        if (hasQuantumCapabilities) {
          quantumDesktopReady = true;
          supportedProblemClasses.add("qubo");
          supportedProblemClasses.add("ising");
          supportedProblemClasses.add("qaoa");
          supportedProblemClasses.add("vqe");
        }
      }
    }
  }

  const quantumSupportedProblemClasses = [...supportedProblemClasses];
  const quantumCapabilitiesReady = quantumSupportedProblemClasses.length > 0;
  const quantumBlockingReasons = [
    desktopReadyCount === 0 ? "desktop_runtime_unavailable" : null,
    !quantumCapabilitiesReady ? "quantum_capabilities_unavailable" : null,
  ].filter((value): value is string => Boolean(value));

  return {
    activeRuntimeConnections,
    staleRuntimeConnections,
    desktopReadyCount,
    desktopTaskReady: desktopReadyCount > 0,
    latestDesktopHeartbeatAgeSeconds: latestDesktopHeartbeatAt
      ? Math.max(0, Math.floor((now - latestDesktopHeartbeatAt.getTime()) / 1000))
      : null,
    quantumReady: quantumDesktopReady && quantumCapabilitiesReady,
    quantumDesktopReady,
    quantumCapabilitiesReady,
    quantumSupportedProblemClasses,
    quantumBlockingReasons,
  };
}

async function reconcileStaleOpenRuntimeConnections(app: FastifyInstance, now = new Date()): Promise<void> {
  const cutoff = new Date(now.getTime() - RUNTIME_CONNECTION_STALE_AFTER_MS);
  const run = async () => {
    await app.db
      .update(runtimeConnections)
      .set({
        status: "offline",
        disconnectedAt: now,
      })
      .where(
        and(
          isNull(runtimeConnections.disconnectedAt),
          ne(runtimeConnections.status, "offline"),
          lt(runtimeConnections.lastHeartbeatAt, cutoff),
        ),
      );
  };

  const reliability = app.services?.reliability;
  if (reliability) {
    await reliability.withLock("runtime-stale-cleanup", 30_000, run);
    return;
  }

  await run();
}

async function getOperationalCounts(app: FastifyInstance) {
  await reconcileStaleOpenRuntimeConnections(app);
  const runtimeRows = await app.db
    .select({
      status: runtimeConnections.status,
      deviceType: devices.type,
      deviceIsActive: devices.isActive,
      deviceUserId: devices.userId,
      lastHeartbeatAt: runtimeConnections.lastHeartbeatAt,
      capabilities: runtimeConnections.capabilities,
    })
    .from(runtimeConnections)
    .innerJoin(devices, eq(runtimeConnections.deviceId, devices.id))
    .where(isNull(runtimeConnections.disconnectedAt));
  const runtimeCounts = summarizeRuntimeOperationalRows(runtimeRows);
  const cutoff = new Date(Date.now() - RUNTIME_CONNECTION_STALE_AFTER_MS);
  const staleTaskRows = await app.db
    .select({
      staleActiveTaskCount: sql<number>`count(*) filter (where ${tasks.status} in ('queued', 'planning', 'running', 'waiting_approval'))::int`,
      staleBlockingTaskCount: sql<number>`count(*) filter (where ${tasks.status} in ('planning', 'running'))::int`,
      staleApprovalTaskCount: sql<number>`count(*) filter (where ${tasks.status} = 'waiting_approval')::int`,
    })
    .from(tasks)
    .where(and(inArray(tasks.status, activeTaskStatuses), lt(tasks.updatedAt, cutoff)));

  return {
    ...runtimeCounts,
    staleActiveTaskCount: Number(staleTaskRows[0]?.staleActiveTaskCount ?? 0),
    staleBlockingTaskCount: Number(staleTaskRows[0]?.staleBlockingTaskCount ?? 0),
    staleApprovalTaskCount: Number(staleTaskRows[0]?.staleApprovalTaskCount ?? 0),
  };
}

async function getAgentReadiness(
  app: FastifyInstance,
  input: {
    databaseReady: boolean;
    externalClientsCanReachAdvertisedBaseUrl: boolean;
    realtimeReady: boolean;
  },
): Promise<AgentReadiness> {
  const blockingReasons: string[] = [];
  let serverBrainReady = false;
  const reliability = app.services?.reliability;
  const redisReady = reliability ? await reliability.store.ping() : true;
  const requestBudgetReady = reliability ? reliability.requestBudgetReady() : true;
  const providerCircuitState = await getSharedBrainProviderCircuitState(app);
  const counts = input.databaseReady
      ? await getOperationalCounts(app).catch(() => ({
        activeRuntimeConnections: 0,
        staleRuntimeConnections: 0,
        desktopReadyCount: 0,
        desktopTaskReady: false,
        latestDesktopHeartbeatAgeSeconds: null,
        quantumReady: false,
        quantumDesktopReady: false,
        quantumCapabilitiesReady: false,
        quantumSupportedProblemClasses: [],
        quantumBlockingReasons: ["desktop_runtime_unavailable", "quantum_capabilities_unavailable"],
        staleActiveTaskCount: 0,
        staleBlockingTaskCount: 0,
        staleApprovalTaskCount: 0,
      }))
    : {
        activeRuntimeConnections: 0,
        staleRuntimeConnections: 0,
        desktopReadyCount: 0,
        desktopTaskReady: false,
        latestDesktopHeartbeatAgeSeconds: null,
        quantumReady: false,
        quantumDesktopReady: false,
        quantumCapabilitiesReady: false,
        quantumSupportedProblemClasses: [],
        quantumBlockingReasons: ["desktop_runtime_unavailable", "quantum_capabilities_unavailable"],
        staleActiveTaskCount: 0,
        staleBlockingTaskCount: 0,
        staleApprovalTaskCount: 0,
      };
  const brainLatency = input.databaseReady
    ? await getBrainLatencySummary(app).catch(() => ({
        lastChatLatencyMs: null,
        lastStreamingFirstDeltaMs: null,
        completionLatencyP50Ms: null,
        completionLatencyP95Ms: null,
        firstDeltaP50Ms: null,
        firstDeltaP95Ms: null,
        attachmentCacheHitRate: null,
        recentResponseBytesAverage: null,
        sessionPageLatencyP50Ms: null,
        sessionPageLatencyP95Ms: null,
        sessionPageBytesP50: null,
        sessionPageBytesP95: null,
        recentBrainTimeoutCount: 0,
      }))
    : {
        lastChatLatencyMs: null,
        lastStreamingFirstDeltaMs: null,
        completionLatencyP50Ms: null,
        completionLatencyP95Ms: null,
        firstDeltaP50Ms: null,
        firstDeltaP95Ms: null,
        attachmentCacheHitRate: null,
        recentResponseBytesAverage: null,
        sessionPageLatencyP50Ms: null,
        sessionPageLatencyP95Ms: null,
        sessionPageBytesP50: null,
        sessionPageBytesP95: null,
        recentBrainTimeoutCount: 0,
      };
  const queueHealthy = input.databaseReady && counts.staleBlockingTaskCount === 0;
  const neural = input.databaseReady
      ? await getNeuralBrainReadiness(app).catch(() => ({
        neuralReady: false,
        trainingWorkerReady: false,
        embeddingReady: false,
        evaluationReady: false,
        quantumLearningReady: false,
        activeTrainingJobs: 0,
        latestEvaluationScore: null,
        latestQualityCompositeScore: null,
        latestQuantumBenchmarkScore: null,
        mlWorkerMode: null,
        mlWorkerLastJobAt: null,
        mlWorkerLastErrorCode: null,
        optionalLibraries: {},
        runnerBacklog: null,
        brainBlockingReasons: ["neural_readiness_unavailable"],
      }))
    : {
        neuralReady: false,
        trainingWorkerReady: false,
        embeddingReady: false,
        evaluationReady: false,
        quantumLearningReady: false,
        activeTrainingJobs: 0,
        latestEvaluationScore: null,
        latestQualityCompositeScore: null,
        latestQuantumBenchmarkScore: null,
        mlWorkerMode: null,
        mlWorkerLastJobAt: null,
        mlWorkerLastErrorCode: null,
        optionalLibraries: {},
        runnerBacklog: null,
        brainBlockingReasons: ["database_unavailable"],
      };

  if (input.databaseReady) {
    try {
      const runtime = await warmSharedBrainRuntime(app);
      serverBrainReady = runtime.ready;
    } catch {
      serverBrainReady = false;
    }
  }

  if (!input.databaseReady) {
    blockingReasons.push("database_unavailable");
  }
  if (!input.externalClientsCanReachAdvertisedBaseUrl) {
    blockingReasons.push("backend_unreachable_for_external_clients");
  }
  if (!input.realtimeReady) {
    blockingReasons.push("realtime_unavailable");
  }
  if (!serverBrainReady) {
    blockingReasons.push("server_brain_unavailable");
  }
  if (app.config.RELIABILITY_REDIS_REQUIRED && !redisReady) {
    blockingReasons.push("redis_unavailable");
  }
  if (!requestBudgetReady) {
    blockingReasons.push("request_budget_unavailable");
  }

  const runtimeDispatchReady =
    input.databaseReady &&
    input.externalClientsCanReachAdvertisedBaseUrl &&
    input.realtimeReady &&
    (!app.config.RELIABILITY_REDIS_REQUIRED || redisReady);

  return {
    chatReady:
      input.databaseReady &&
      input.externalClientsCanReachAdvertisedBaseUrl &&
      input.realtimeReady &&
      serverBrainReady &&
      (!app.config.RELIABILITY_REDIS_REQUIRED || redisReady) &&
      requestBudgetReady,
    serverBrainReady,
    runtimeDispatchReady,
    realtimeReady: input.realtimeReady,
    databaseReady: input.databaseReady,
    redisReady,
    providerCircuitState,
    queueHealthy,
    activeRuntimeConnections: counts.activeRuntimeConnections,
    staleRuntimeConnections: counts.staleRuntimeConnections,
    desktopReadyCount: counts.desktopReadyCount,
    desktopTaskReady: counts.desktopTaskReady,
    latestDesktopHeartbeatAgeSeconds: counts.latestDesktopHeartbeatAgeSeconds,
    quantumReady: counts.quantumReady,
    quantumDesktopReady: counts.quantumDesktopReady,
    quantumCapabilitiesReady: counts.quantumCapabilitiesReady,
    quantumSupportedProblemClasses: counts.quantumSupportedProblemClasses,
    quantumBlockingReasons: counts.quantumBlockingReasons,
    neuralReady: neural.neuralReady,
    trainingWorkerReady: neural.trainingWorkerReady,
    embeddingReady: neural.embeddingReady,
    evaluationReady: neural.evaluationReady,
    quantumLearningReady: neural.quantumLearningReady,
    activeTrainingJobs: neural.activeTrainingJobs,
    latestEvaluationScore: neural.latestEvaluationScore,
    latestQuantumBenchmarkScore: neural.latestQuantumBenchmarkScore,
    lastChatLatencyMs: brainLatency.lastChatLatencyMs,
    lastStreamingFirstDeltaMs: brainLatency.lastStreamingFirstDeltaMs,
    completionLatencyP50Ms: brainLatency.completionLatencyP50Ms,
    completionLatencyP95Ms: brainLatency.completionLatencyP95Ms,
    firstDeltaP50Ms: brainLatency.firstDeltaP50Ms,
    firstDeltaP95Ms: brainLatency.firstDeltaP95Ms,
    attachmentCacheHitRate: brainLatency.attachmentCacheHitRate,
    recentResponseBytesAverage: brainLatency.recentResponseBytesAverage,
    sessionPageLatencyP50Ms: brainLatency.sessionPageLatencyP50Ms,
    sessionPageLatencyP95Ms: brainLatency.sessionPageLatencyP95Ms,
    sessionPageBytesP50: brainLatency.sessionPageBytesP50,
    sessionPageBytesP95: brainLatency.sessionPageBytesP95,
    recentBrainTimeoutCount: brainLatency.recentBrainTimeoutCount,
    mlWorkerMode: neural.mlWorkerMode,
    mlWorkerLastJobAt: neural.mlWorkerLastJobAt,
    mlWorkerLastErrorCode: neural.mlWorkerLastErrorCode,
    optionalLibraries: neural.optionalLibraries,
    runnerBacklog: neural.runnerBacklog,
    brainBlockingReasons: neural.brainBlockingReasons,
    staleActiveTaskCount: counts.staleActiveTaskCount,
    staleBlockingTaskCount: counts.staleBlockingTaskCount,
    staleApprovalTaskCount: counts.staleApprovalTaskCount,
    requestBudgetReady,
    blockingReasons,
  };
}

export async function getReadiness(app: FastifyInstance): Promise<{
  ok: boolean;
  database: {
    status: "up" | "down";
    reachability: ReturnType<typeof getDatabaseReachability>;
  };
  dependencies: {
    billing: ReturnType<typeof getBillingDependencyStatus>;
  };
  commercialReadiness: {
    billing: ReturnType<typeof getBillingDependencyStatus>;
  };
  agent: AgentReadiness;
  mode: "control_plane";
  coreSurfaces: readonly string[];
  network: ReturnType<typeof getBaseUrlReachability>;
  realtime: {
    sseEnabled: boolean;
    websocketEnabled: boolean;
    heartbeatSeconds: number;
  };
  retrieval: {
    mode: "hybrid" | "lexical_fallback";
    embeddingCoverage: number;
    pendingIndexJobs: number;
    lastIndexedAt: string | null;
  };
  brainControl: {
    constitutionVersion: string;
    constitutionRuleCount: number;
    boundaryGateReady: boolean;
    activeMobileDefaultProfile: string;
    latestBenchmarkStatus: string | null;
    latestBenchmarkOverallScore: number | null;
    latestBenchmarkBoundaryScore: number | null;
    correctionDatasetReady: boolean;
    correctionDatasetId: string | null;
    latestLatencyWarning: string | null;
    mobileChatFastReady: boolean;
    latestFirstDeltaP50Ms: number | null;
    latestFirstDeltaP95Ms: number | null;
    latestCompletionP50Ms: number | null;
    latestCompletionP95Ms: number | null;
    attachmentCacheHitRate: number | null;
    sessionPageLatencyP50Ms: number | null;
    sessionPageLatencyP95Ms: number | null;
    fallbackPressure: string;
  };
  mobile: {
    statusSummary: "ready" | "backend_unavailable" | "runtime_unreachable";
    safeForExternalClients: boolean;
  };
}> {
  const network = getBaseUrlReachability(app.config);
  const databaseReachability = getDatabaseReachability(app.config);
  const billing = getBillingDependencyStatus(app.config);
  const realtime = {
    sseEnabled: true,
    websocketEnabled: true,
    heartbeatSeconds: 15,
  } as const;

  try {
    await app.db.execute(sql`select 1`);
    const agent = await getAgentReadiness(app, {
      databaseReady: true,
      externalClientsCanReachAdvertisedBaseUrl: network.externalClientsCanReachAdvertisedBaseUrl,
      realtimeReady: realtime.sseEnabled && realtime.websocketEnabled,
    });
    const retrieval = await getRetrievalStatus(app, "__health__");
    const benchmarkSummary = await getLatestBrainBenchmarkSummary(app).catch(() => ({
      latestRunAt: null,
      latestStatus: null,
      latestOverallScore: null,
      latestBoundaryScore: null,
      latestReasoningScore: null,
      latestClarificationScore: null,
      latestToolUseScore: null,
      latestLatencyScore: null,
      caseCount: 0,
      constitutionVersion: ELYAN_CONSTITUTION_VERSION,
    }));
    const correctionDataset = await getApprovedCorrectionDatasetState(app).catch(() => ({
      ready: false,
      datasetId: null,
      datasetVersion: null,
      compactionMode: null,
      approvedCorrectionCount: null,
      compactedRecordCount: null,
      freshSignalCount: null,
      correctionDensity: null,
      freshSignalRatio: null,
      signalFreshnessScore: null,
      lineageScore: null,
      compactionQualityScore: null,
      compactDatasetEligible: null,
      sourceLineage: null,
      freshnessWindowDays: null,
      highSignalThreshold: null,
      latestApprovedAt: null,
      oldestApprovedAt: null,
    }));
    const latestLatencyWarning =
      agent.recentBrainTimeoutCount > 0
        ? "recent_timeouts_detected"
        : (agent.lastChatLatencyMs ?? 0) > getSharedBrainWorkloadProfile("mobile_chat_fast").timeoutMs
          ? "mobile_chat_latency_high"
          : null;

    return {
      ok: agent.databaseReady && network.externalClientsCanReachAdvertisedBaseUrl && agent.chatReady,
      database: {
        status: "up",
        reachability: databaseReachability,
      },
      dependencies: {
        billing,
      },
      commercialReadiness: {
        billing,
      },
      agent,
      mode: "control_plane",
      coreSurfaces,
      network,
      realtime,
      retrieval: {
        mode: retrieval.mode,
        embeddingCoverage: retrieval.embeddingCoverage,
        pendingIndexJobs: retrieval.pendingIndexJobs,
        lastIndexedAt: retrieval.lastIndexedAt,
      },
      brainControl: {
        constitutionVersion: ELYAN_CONSTITUTION_VERSION,
        constitutionRuleCount: constitutionRuleCount(),
        boundaryGateReady: ELYAN_CONSTITUTION_GATE_READY,
        activeMobileDefaultProfile: "mobile_chat_fast",
        latestBenchmarkStatus: benchmarkSummary.latestStatus,
        latestBenchmarkOverallScore: benchmarkSummary.latestOverallScore,
        latestBenchmarkBoundaryScore: benchmarkSummary.latestBoundaryScore,
        correctionDatasetReady: correctionDataset.ready,
        correctionDatasetId: correctionDataset.datasetId,
        latestLatencyWarning,
        mobileChatFastReady: agent.chatReady,
        latestFirstDeltaP50Ms: agent.firstDeltaP50Ms,
        latestFirstDeltaP95Ms: agent.firstDeltaP95Ms,
        latestCompletionP50Ms: agent.completionLatencyP50Ms,
        latestCompletionP95Ms: agent.completionLatencyP95Ms,
        attachmentCacheHitRate: agent.attachmentCacheHitRate,
        sessionPageLatencyP50Ms: agent.sessionPageLatencyP50Ms,
        sessionPageLatencyP95Ms: agent.sessionPageLatencyP95Ms,
        fallbackPressure: agent.recentBrainTimeoutCount > 0 ? "elevated" : "normal",
      },
      mobile: {
        statusSummary: network.externalClientsCanReachAdvertisedBaseUrl
          ? "ready"
          : "runtime_unreachable",
        safeForExternalClients:
          network.externalClientsCanReachAdvertisedBaseUrl,
      },
    };
  } catch {
    const agent = await getAgentReadiness(app, {
      databaseReady: false,
      externalClientsCanReachAdvertisedBaseUrl: network.externalClientsCanReachAdvertisedBaseUrl,
      realtimeReady: realtime.sseEnabled && realtime.websocketEnabled,
    });

    return {
      ok: false,
      database: {
        status: "down",
        reachability: databaseReachability,
      },
      dependencies: {
        billing,
      },
      commercialReadiness: {
        billing,
      },
      agent,
      mode: "control_plane",
      coreSurfaces,
      network,
      realtime,
      retrieval: {
        mode: "lexical_fallback",
        embeddingCoverage: 0,
        pendingIndexJobs: 0,
        lastIndexedAt: null,
      },
      brainControl: {
        constitutionVersion: ELYAN_CONSTITUTION_VERSION,
        constitutionRuleCount: constitutionRuleCount(),
        boundaryGateReady: ELYAN_CONSTITUTION_GATE_READY,
        activeMobileDefaultProfile: "mobile_chat_fast",
        latestBenchmarkStatus: null,
        latestBenchmarkOverallScore: null,
        latestBenchmarkBoundaryScore: null,
        correctionDatasetReady: false,
        correctionDatasetId: null,
        latestLatencyWarning: null,
        mobileChatFastReady: false,
        latestFirstDeltaP50Ms: null,
        latestFirstDeltaP95Ms: null,
        latestCompletionP50Ms: null,
        latestCompletionP95Ms: null,
        attachmentCacheHitRate: null,
        sessionPageLatencyP50Ms: null,
        sessionPageLatencyP95Ms: null,
        fallbackPressure: "unknown",
      },
      mobile: {
        statusSummary: "backend_unavailable",
        safeForExternalClients:
          network.externalClientsCanReachAdvertisedBaseUrl,
      },
    };
  }
}
