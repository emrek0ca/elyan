import type { FastifyInstance } from "fastify";
import { learningEvents } from "../../db/schema.js";
import { maybeQueueMemoryExtractionJob } from "../../modules/brain/memory.js";
import {
  classifyIntent,
  enhanceIntentWithTransformer,
} from "./intent-classifier.js";
import { buildUserContext } from "./context-builder.js";
import { extractFeedbackSignals, extractPreferenceSignals } from "./preference-extractor.js";
import { filterLearningSignals } from "./personalization-policy.js";
import { nlpDaemon } from "../../lib/nlp-daemon.js";
import type {
  ClarificationDiagnostics,
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

const fallbackClarificationDiagnostics: ClarificationDiagnostics = {
  shouldClarify: true,
  ambiguityKind: "insufficient_evidence",
  reason: "understanding_disabled_or_failed",
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
      speakingStyleDirectives: [],
      reasoningDirectives: [],
      technicalHints: [],
      safetyHints: [],
      situationalHints: [],
      behavioralHints: [],
      environmentHints: [],
      continuitySummary: {
        userGoal: null,
        assistantState: null,
        openLoops: [],
      },
      continuityBoundary: {
        mode: "new_topic",
        reason: "no_prior_context",
        carryContinuity: false,
      },
      relationshipContextDigest: [],
      clarificationDiagnostics: fallbackClarificationDiagnostics,
      memoryEnabled: true,
      personalizationPrompt: null,
      memoryRelevanceSummary: [],
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
    const baseIntent = classifyIntent(input);
    // Real-semantic upgrade via the same e5-small transformer that powers
    // storage embeddings. Only fires when the sync classifier was unsure
    // (chat/unknown/<0.6 confidence) — keeps the fast path fast.
    const intent = await enhanceIntentWithTransformer(input.message ?? "", baseIntent);
    app.log.info(
      {
        requestId: input.metadata?.requestId,
        userId: input.userId,
        intent: intent.primaryIntent,
        confidence: intent.confidence,
        privacyRisk: intent.privacyRisk,
        upgradedByTransformer: intent !== baseIntent,
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

// Konuşma değişiminden gerçek zamanlı sinyal çıkarma
// Hem kullanıcı mesajından hem asistan cevabından öğrenir
export async function recordConversationExchangeLearning(
  app: FastifyInstance,
  input: {
    userId: string;
    accountId?: string;
    taskId?: string;
    userMessage: string;
    assistantReply: string;
    intent: string;
    requestId?: string;
  },
): Promise<number> {
  const signals: LearningSignal[] = [];
  const replyText = input.assistantReply.toLowerCase();

  // C NLP daemon çağrıları (paralel) — regex fallback ile
  const [langResult, sentimentResult, complexityResult, keywordsResult] = await Promise.all([
    nlpDaemon.detectLanguage(input.userMessage).catch(() => null),
    nlpDaemon.scoreSentiment(input.userMessage).catch(() => null),
    nlpDaemon.scoreComplexity(input.userMessage).catch(() => null),
    nlpDaemon.extractKeywords(input.userMessage, 6).catch(() => [] as string[]),
  ]);

  // Dil tercihi: C daemon veya regex fallback
  const isTurkish = langResult
    ? langResult.lang === "tr" && langResult.confidence >= 0.6
    : /[çğıöşü]/i.test(input.userMessage) || /\b(ve|ile|için|bu|şu|merhaba|tamam|evet|hayır)\b/.test(input.userMessage.toLowerCase());

  if (isTurkish) {
    signals.push({
      type: "preference",
      key: "preferred_language",
      value: "turkish",
      confidence: langResult ? Math.min(0.95, langResult.confidence * 0.9) : 0.82,
      scope: "user",
      source: "interaction",
      ttlDays: 180,
    });
  }

  // Cevap uzunluğu tercihi: C complexity veya char length fallback
  const tokenCount = complexityResult?.tokenCount ?? 0;
  const msgLen = input.userMessage.trim().length;
  const isShort = tokenCount > 0 ? tokenCount < 12 : msgLen < 60;
  const isLong  = tokenCount > 0 ? tokenCount > 60  : msgLen > 300;
  const cProfileMetadata = {
    tokenCount: complexityResult?.tokenCount,
    sentenceCount: complexityResult?.sentenceCount,
    vocabRichness: complexityResult?.vocabRichness,
    avgSentenceLen: complexityResult?.avgSentenceLen,
    sentimentLabel: sentimentResult?.label,
    sentimentScore: sentimentResult?.score,
    keywordCount: keywordsResult?.length ?? 0,
  };

  if (isShort) {
    signals.push({
      type: "preference",
      key: "answer_length",
      value: "concise",
      confidence: 0.55,
      scope: "user",
      source: "interaction",
      ttlDays: 60,
      metadata: { ...cProfileMetadata, intent: input.intent },
    });
  } else if (isLong) {
    signals.push({
      type: "preference",
      key: "answer_length",
      value: "detailed",
      confidence: 0.6,
      scope: "user",
      source: "interaction",
      ttlDays: 60,
      metadata: { ...cProfileMetadata, intent: input.intent },
    });
  }

  // Vocab richness → kullanıcı karmaşık dil kullanıyorsa "expert" sinyali
  if (complexityResult && complexityResult.vocabRichness > 0.75 && complexityResult.tokenCount >= 10) {
    signals.push({
      type: "style",
      key: "vocabulary_richness",
      value: "high",
      confidence: 0.58,
      scope: "user",
      source: "interaction",
      ttlDays: 90,
      metadata: { ...cProfileMetadata, intent: input.intent },
    });
  }

  if (/\b(hatırla|hatirla|beni tanı|beni tani|kişiselleştir|kisisellestir|derin bağ|derin bag|yakın hisset|yakin hisset|devamlılık|devamlilik|süreklilik|sureklilik|remember me|personalize|continuity)\b/i.test(input.userMessage)) {
    signals.push({
      type: "style",
      key: "response_style_preference",
      value: "warm_contextual",
      confidence: 0.78,
      scope: "user",
      source: "interaction",
      ttlDays: 180,
      metadata: {
        ...cProfileMetadata,
        intent: input.intent,
        explicit: true,
        reason: "user_requested_deeper_personalization",
      },
    });
    signals.push({
      type: "episodic",
      key: "conversation_highlight",
      value: "user wants Elyan to remember only useful context and build deeper continuity",
      confidence: 0.82,
      scope: "user",
      source: "interaction",
      ttlDays: 90,
      metadata: {
        ...cProfileMetadata,
        intent: input.intent,
        explicit: true,
        reason: "relationship_continuity_request",
      },
    });
  }

  // Teknik stack sinyali: mesajda spesifik teknoloji geçiyor mu?
  const techPatterns: Array<[RegExp, string]> = [
    [/\b(flutter|dart)\b/i, "flutter"],
    [/\b(typescript|ts)\b/i, "typescript"],
    [/\b(python)\b/i, "python"],
    [/\b(swift|swiftui|ios)\b/i, "swift/ios"],
    [/\b(fastify|node\.?js)\b/i, "fastify/nodejs"],
    [/\b(postgres|postgresql)\b/i, "postgresql"],
    [/\b(react|next\.?js)\b/i, "react"],
  ];
  for (const [pattern, stack] of techPatterns) {
    if (pattern.test(input.userMessage)) {
      signals.push({
        type: "technical_stack",
        key: "stack",
        value: stack,
        confidence: 0.72,
        scope: "user",
      source: "interaction",
      ttlDays: 120,
        metadata: { ...cProfileMetadata, detectedIn: "user_message", intent: input.intent },
      });
    }
  }

  // Duygusal sinyal: C sentiment veya regex fallback
  const sentLabel = sentimentResult?.label;
  if (sentLabel === "positive" && (sentimentResult?.positive ?? 0) >= 1) {
    signals.push({
      type: "episodic",
      key: "emotional_signal",
      value: "positive",
      confidence: Math.min(0.85, 0.55 + (sentimentResult?.score ?? 0.5) * 0.3),
      scope: "user",
      source: "interaction",
      ttlDays: 30,
      metadata: { ...cProfileMetadata, intent: input.intent, taskId: input.taskId },
    });
  } else if (sentLabel === "negative" && (sentimentResult?.negative ?? 0) >= 1) {
    signals.push({
      type: "episodic",
      key: "emotional_signal",
      value: "frustrated",
      confidence: Math.min(0.80, 0.50 + (sentimentResult?.score ?? 0.5) * 0.3),
      scope: "user",
      source: "interaction",
      ttlDays: 14,
      metadata: { ...cProfileMetadata, intent: input.intent, taskId: input.taskId },
    });
  } else if (!sentimentResult) {
    // regex fallback if C daemon unavailable
    if (/\b(harika|mükemmel|süper|amazing|perfect|great|excellent|teşekkür|thanks)\b/i.test(input.userMessage)) {
      signals.push({ type: "episodic", key: "emotional_signal", value: "positive", confidence: 0.65, scope: "user", source: "interaction", ttlDays: 30, metadata: { intent: input.intent, taskId: input.taskId } });
    }
    if (/\b(olmadı|çalışmıyor|hata|bug|sorun|problem|yanlış|wrong|broken)\b/i.test(input.userMessage)) {
      signals.push({ type: "episodic", key: "emotional_signal", value: "frustrated", confidence: 0.62, scope: "user", source: "interaction", ttlDays: 14, metadata: { intent: input.intent, taskId: input.taskId } });
    }
  }

  // Keyword-based memory tag: C'den gelen keyword'lar varsa project_context olarak kaydet
  if (keywordsResult && keywordsResult.length >= 3) {
    signals.push({
      type: "project_context",
      key: "message_keywords",
      value: keywordsResult.slice(0, 5).join(", "),
      confidence: 0.50,
      scope: "user",
      source: "interaction",
      ttlDays: 14,
      metadata: { ...cProfileMetadata, intent: input.intent, taskId: input.taskId },
    });
  }

  // Pozitif feedback: asistan cevabı kısa + kullanıcı devam ediyor = kaliteli etkileşim
  if (replyText.length < 600 && input.userMessage.length > 10) {
    signals.push({
      type: "workflow",
      key: "positive_feedback",
      value: "interaction_continued",
      confidence: 0.52,
      scope: "user",
      source: "interaction",
      ttlDays: 30,
    });
  }

  if (signals.length === 0) return 0;

  return persistLearningSignals(app, {
    userId: input.userId,
    accountId: input.accountId,
    taskId: input.taskId,
    signals,
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
