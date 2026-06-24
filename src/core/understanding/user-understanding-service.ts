import type { FastifyInstance } from "fastify";
import { learningEvents } from "../../db/schema.js";
import { maybeQueueMemoryExtractionJob } from "../../modules/brain/memory.js";
import { classifyIntent } from "./intent-classifier.js";
import { buildUserContext } from "./context-builder.js";
import { extractFeedbackSignals, extractPreferenceSignals } from "./preference-extractor.js";
import { filterLearningSignals } from "./personalization-policy.js";
import type {
  FeedbackType,
  IntentClassification,
  LearningSignal,
  TaskUnderstandingInput,
  UserUnderstandingResult,
} from "./types.js";

const fallbackIntent: IntentClassification = {
  primaryIntent: "unknown",
  secondaryIntents: [],
  requiresLocalRuntime: false,
  requiresRetrieval: false,
  requiresToolUse: false,
  requiresCitation: false,
  requiresLongRunningTask: false,
  privacyRisk: "low",
  confidence: 0,
  reason: "understanding_disabled_or_failed",
  taskFrame: {
    goal: "answer or route safely",
    likelyAnswerShape: "direct answer with caution",
    reasoningMode: "fast",
    shouldClarify: true,
  },
  ecosystemHints: [],
  routingHints: {
    mode: "fast",
    preferredCapabilities: [],
    avoidCloud: false,
    requiresLocalRuntime: false,
  },
};

export function emptyUnderstanding(input: TaskUnderstandingInput): UserUnderstandingResult {
  return {
    intent: fallbackIntent,
    routingHints: fallbackIntent.routingHints,
    context: {
      userId: input.userId,
      accountId: input.accountId ?? input.userId,
      intent: "unknown",
      taskFrame: {
        goal: "answer or route safely",
        likelyAnswerShape: "direct answer with caution",
        reasoningMode: "fast",
        shouldClarify: true,
      },
      ecosystemHints: [],
      personalizationHints: [],
      projectHints: [],
      styleHints: [],
      technicalHints: [],
      safetyHints: [],
      contextPackets: [],
      healthContextUsed: false,
      packetKinds: [],
      freshness: {
        newestContextAt: null,
        oldestContextAt: null,
        maxAgeHours: null,
        stalePacketCount: 0,
      },
      retrievedMemory: [],
      tokenBudget: {
        maxHints: 12,
        maxChars: 4000,
      },
    },
  };
}

export async function buildTaskUnderstanding(
  app: FastifyInstance,
  input: TaskUnderstandingInput,
): Promise<UserUnderstandingResult> {
  const startedAt = Date.now();

  if (!app.config.ELYAN_USER_UNDERSTANDING_ENABLED) {
    return emptyUnderstanding(input);
  }

  try {
    const intent = classifyIntent(input);
    app.log.info(
      {
        requestId: input.metadata?.requestId,
        userId: input.userId,
        intent: intent.primaryIntent,
        confidence: intent.confidence,
        privacyRisk: intent.privacyRisk,
      },
      "understanding intent classified",
    );

    const context = app.config.ELYAN_PERSONALIZATION_ENABLED
      ? await buildUserContext(app, {
          ...input,
          intent,
        })
      : emptyUnderstanding(input).context;

    app.log.info(
      {
        requestId: input.metadata?.requestId,
        userId: input.userId,
        intent: intent.primaryIntent,
        hintCount:
          context.personalizationHints.length +
          context.projectHints.length +
          context.styleHints.length +
          context.technicalHints.length +
          context.safetyHints.length,
        contextPacketCount: context.contextPackets.length,
        healthContextUsed: context.healthContextUsed,
        memoryCount: context.retrievedMemory.length,
        durationMs: Date.now() - startedAt,
      },
      "understanding context built",
    );

    return {
      intent,
      context,
      routingHints: intent.routingHints,
    };
  } catch (error) {
    app.log.warn(
      {
        userId: input.userId,
        reason: error instanceof Error ? error.message : "unknown",
        durationMs: Date.now() - startedAt,
      },
      "understanding failed open",
    );
    return emptyUnderstanding(input);
  }
}

export async function persistLearningSignals(
  app: FastifyInstance,
  input: {
    userId: string;
    accountId?: string;
    taskId?: string;
    signals: LearningSignal[];
    requestId?: string;
  },
): Promise<number> {
  if (!app.config.ELYAN_LEARNING_EXTRACTION_ENABLED) {
    return 0;
  }

  const signals = filterLearningSignals(input.signals);

  if (!signals.length) {
    return 0;
  }

  const now = Date.now();

  try {
    await app.db.insert(learningEvents).values(
      signals.map((signal) => ({
        userId: input.userId,
        accountId: input.accountId ?? input.userId,
        taskId: input.taskId,
        type: signal.type,
        key: signal.key,
        value: signal.value,
        confidence: Math.round(signal.confidence * 100),
        scope: signal.scope,
        source: signal.source,
        privacyLevel: "safe",
        metadata: {
          ...signal.metadata,
          requestId: input.requestId,
        },
        expiresAt: signal.ttlDays ? new Date(now + signal.ttlDays * 86_400_000) : null,
      })),
    );

    app.log.info(
      {
        userId: input.userId,
        taskId: input.taskId,
        persistedCount: signals.length,
      },
      "understanding learning persisted",
    );

    void maybeQueueMemoryExtractionJob(app, {
      userId: input.userId,
      persistedSignals: signals.length,
      trigger: "learning_events_persisted",
      requestId: input.requestId,
    }).catch((error) => {
      app.log.debug?.(
        {
          userId: input.userId,
          taskId: input.taskId,
          reason: error instanceof Error ? error.message : "unknown",
        },
        "understanding memory extraction queue skipped",
      );
    });
    return signals.length;
  } catch (error) {
    app.log.warn(
      {
        userId: input.userId,
        taskId: input.taskId,
        reason: error instanceof Error ? error.message : "unknown",
      },
      "understanding learning persistence failed closed",
    );
    return 0;
  }
}

export async function recordTaskLearningFromCreation(
  app: FastifyInstance,
  input: TaskUnderstandingInput & { intent: IntentClassification; requestId?: string },
): Promise<number> {
  const extracted = extractPreferenceSignals({
    ...input,
    intent: input.intent.primaryIntent,
  });

  return persistLearningSignals(app, {
    userId: input.userId,
    accountId: input.accountId,
    taskId: input.taskId,
    signals: extracted.signals,
    requestId: input.requestId,
  });
}

export async function recordTaskLearningFromCompletion(
  app: FastifyInstance,
  input: {
    userId: string;
    accountId?: string;
    taskId: string;
    title?: string;
    message: string;
    status: "completed" | "failed" | "canceled";
    requestId?: string;
  },
): Promise<number> {
  const extracted = extractPreferenceSignals({
    userId: input.userId,
    accountId: input.accountId,
    taskId: input.taskId,
    title: input.title,
    message: input.message,
  });
  const terminalSignal: LearningSignal = {
    type: "workflow",
    key: input.status === "completed" ? "task_completed" : "task_not_completed",
    value: input.status,
    confidence: input.status === "completed" ? 0.72 : 0.7,
    scope: "user",
    source: "runtime",
    ttlDays: 30,
  };
  const completionStateSignal: LearningSignal = {
    type: "workflow",
    key: "task_completion_state",
    value: input.status,
    confidence: input.status === "completed" ? 0.8 : 0.76,
    scope: "user",
    source: "runtime",
    ttlDays: 30,
  };

  return persistLearningSignals(app, {
    userId: input.userId,
    accountId: input.accountId,
    taskId: input.taskId,
    signals: [...extracted.signals, terminalSignal, completionStateSignal],
    requestId: input.requestId,
  });
}

export async function recordTaskFeedback(
  app: FastifyInstance,
  input: {
    userId: string;
    accountId?: string;
    taskId: string;
    feedbackType: FeedbackType;
    reasonTags?: string[];
    correction?: string;
    preferredAnswer?: string;
    requestId?: string;
  },
): Promise<number> {
  const extracted = extractFeedbackSignals(input);
  const feedbackOutcomeSignal: LearningSignal = {
    type: "workflow",
    key: "feedback_outcome",
    value: input.feedbackType,
    confidence: 0.74,
    scope: "user",
    source: "feedback",
    ttlDays: 45,
  };

  return persistLearningSignals(app, {
    userId: input.userId,
    accountId: input.accountId,
    taskId: input.taskId,
    signals: [...extracted.signals, feedbackOutcomeSignal],
    requestId: input.requestId,
  });
}

export async function recordBridgeLearningSignals(
  app: FastifyInstance,
  input: {
    userId: string;
    accountId?: string;
    taskId?: string;
    target: "desktop" | "server_brain";
    outcome: "created" | "dispatched" | "completed" | "failed" | "unavailable";
    readiness: "ready" | "degraded" | "unavailable";
    routingMode?: "desktop_first_when_available" | "server_brain_first";
    requestId?: string;
  },
): Promise<number> {
  const signals: LearningSignal[] = [
    {
      type: "routing",
      key: "task_target",
      value: input.target,
      confidence: 0.78,
      scope: "user",
      source: "runtime",
      ttlDays: 30,
    },
    {
      type: "bridge",
      key: "routing_outcome",
      value: input.outcome,
      confidence: 0.82,
      scope: "user",
      source: "runtime",
      ttlDays: 30,
    },
    {
      type: "bridge",
      key: "bridge_readiness",
      value: input.readiness,
      confidence: 0.76,
      scope: "user",
      source: "system",
      ttlDays: 30,
    },
  ];

  if (input.routingMode) {
    signals.push({
      type: "routing",
      key: "routing_mode",
      value: input.routingMode,
      confidence: 0.74,
      scope: "user",
      source: "runtime",
      ttlDays: 30,
    });
  }

  signals.push({
    type: "workflow",
    key: "task_handoff_state",
    value: `${input.target}:${input.outcome}`,
    confidence: 0.79,
    scope: "user",
    source: "runtime",
    ttlDays: 30,
  });

  signals.push({
    type: "correction",
    key: "task_handoff_helpfulness",
    value:
      input.outcome === "completed" || input.outcome === "dispatched"
        ? "helpful"
        : input.outcome === "failed" || input.outcome === "unavailable"
          ? "needs_improvement"
          : "pending",
    confidence: 0.7,
    scope: "user",
    source: "runtime",
    ttlDays: 30,
  });

  return persistLearningSignals(app, {
    userId: input.userId,
    accountId: input.accountId,
    taskId: input.taskId,
    signals,
    requestId: input.requestId,
  });
}

export async function recordMobileSyncRecoverySignals(
  app: FastifyInstance,
  input: {
    userId: string;
    accountId?: string;
    cursorProvided: boolean;
    outcome: "recovered" | "resync_required";
    requestId?: string;
  },
): Promise<number> {
  const signals: LearningSignal[] = [
    {
      type: "bridge",
      key: "session_recovered",
      value: input.outcome,
      confidence: input.outcome === "recovered" ? 0.76 : 0.68,
      scope: "user",
      source: "system",
      ttlDays: 21,
      metadata: {
        cursorProvided: input.cursorProvided,
      },
    },
    {
      type: "bridge",
      key: "mobile_sync_quality",
      value: input.outcome === "recovered" ? "healthy" : "needs_resync",
      confidence: 0.72,
      scope: "user",
      source: "system",
      ttlDays: 21,
      metadata: {
        cursorProvided: input.cursorProvided,
      },
    },
  ];

  return persistLearningSignals(app, {
    userId: input.userId,
    accountId: input.accountId,
    signals,
    requestId: input.requestId,
  });
}
