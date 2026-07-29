import { createHash } from "node:crypto";
import { and, eq, inArray } from "drizzle-orm";
import { normalizePersonalName } from "./identity-name.js";
import type { FastifyInstance } from "fastify";
import { learningEvents } from "../../db/schema.js";
import { maybeQueueMemoryExtractionJob } from "../../modules/brain/memory.js";
import { cognitiveMemoryRepository } from "../../modules/brain/cognitive-memory-repository.js";
import { isCognitiveFoundationEnabled } from "../../modules/brain/cognitive-foundation-policy.js";
import { recordTurnMemoryOps } from "../../modules/brain/memory-fabric.js";
import type { TurnEnvelope } from "../../modules/brain/turn-envelope.js";
import {
  classifyIntent,
  enhanceIntentWithTransformer,
} from "./intent-classifier.js";
import { buildUserContext } from "./context-builder.js";
import {
  buildEmptyUnderstandingEnvelope,
  buildTypedUnderstandingEnvelope,
} from "./understanding-envelope.js";
import type { UnderstandingEnvelope } from "./types.js";
import { buildModelFallbackUnderstandingEnvelope } from "./understanding-model-fallback.js";
import { extractFeedbackSignals, extractPreferenceSignals } from "./preference-extractor.js";
import { filterLearningSignals } from "./personalization-policy.js";
import { nlpDaemon } from "../../lib/nlp-daemon.js";
import { startStage } from "../../lib/perf-telemetry.js";
import { enhanceIntentWithGeminiFree } from "../../modules/brain/gemini-intent-router.js";
import type {
  ClarificationDiagnostics,
  FeedbackType,
  IntentClassification,
  LearningSignal,
  TaskUnderstandingInput,
  UserUnderstandingResult,
} from "./types.js";
import {
  buildLearningProvenance,
  resolveInteractionContext,
} from "./interaction-context.js";

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
    likelyAnswerShape: "direct answer",
    reasoningMode: "fast",
    shouldClarify: false,
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
  shouldClarify: false,
  ambiguityKind: "none",
  reason: "understanding_unavailable_continue_best_effort",
};

const SYNCHRONOUS_MEMORY_KEYS = new Set([
  "answer_length",
  "brevity_preference",
  "name",
  "preferred_name",
  "preferred_language",
  "preferred_tone",
  "response_style_preference",
  "timezone",
]);

function shouldBuildUnderstandingEnvelope(app: FastifyInstance): boolean {
  return (
    app.config.ELYAN_UNDERSTANDING_ENVELOPE_V2_ENABLED === true ||
    app.config.ELYAN_UNDERSTANDING_ENVELOPE_SHADOW_ENABLED === true ||
    app.config.ELYAN_UNDERSTANDING_ENVELOPE_MODEL_FALLBACK_ENABLED === true
  );
}

export function emptyUnderstanding(
  input: TaskUnderstandingInput,
  options: { includeEnvelope?: boolean } = {},
): UserUnderstandingResult {
  const envelope = options.includeEnvelope
    ? buildEmptyUnderstandingEnvelope(input, fallbackIntent)
    : undefined;
  return {
    intent: fallbackIntent,
    routingHints: fallbackIntent.routingHints,
    ...(envelope
      ? {
          envelope,
          envelopeSource: envelope.source,
          envelopeConfidence: envelope.confidence,
        }
      : {}),
    context: {
      userId: input.userId,
      accountId: input.accountId ?? input.userId,
      intent: "unknown",
      taskFrame: {
        goal: "answer or route safely",
        likelyAnswerShape: "direct answer",
        reasoningMode: "fast",
        shouldClarify: false,
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
      activeGoal: null,
      continuityBoundary: {
        mode: "new_topic",
        reason: "no_prior_context",
        carryContinuity: false,
      },
      relationshipContextDigest: [],
      clarificationDiagnostics: fallbackClarificationDiagnostics,
      memoryEnabled: true,
      interactionContext: resolveInteractionContext(input),
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
      ...(envelope ? { understandingEnvelope: envelope } : {}),
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
  const endStage = startStage("understanding");

  if (!app.config.ELYAN_USER_UNDERSTANDING_ENABLED) {
    endStage();
    return emptyUnderstanding(input, {
      includeEnvelope: shouldBuildUnderstandingEnvelope(app),
    });
  }

  try {
    const baseIntent = classifyIntent(input);
    // Real-semantic upgrade via the same e5-small transformer that powers
    // storage embeddings. Only fires when the sync classifier was unsure
    // (chat/unknown/<0.6 confidence) — keeps the fast path fast.
    const semanticIntent = await enhanceIntentWithTransformer(input.message ?? "", baseIntent);
    const intent = await enhanceIntentWithGeminiFree(app, {
      userId: input.userId,
      message: input.message ?? "",
      current: semanticIntent,
    }).catch(() => semanticIntent);
    app.log.info(
      {
        requestId: input.metadata?.requestId,
        userId: input.userId,
        intent: intent.primaryIntent,
        confidence: intent.confidence,
        privacyRisk: intent.privacyRisk,
        upgradedByTransformer: semanticIntent !== baseIntent,
        upgradedByGeminiFree: intent !== semanticIntent,
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

    let envelope = shouldBuildUnderstandingEnvelope(app)
      ? buildTypedUnderstandingEnvelope({
          ...input,
          intent,
          source: "typed_extractor",
        })
      : undefined;

    if (envelope && app.config.ELYAN_UNDERSTANDING_ENVELOPE_MODEL_FALLBACK_ENABLED) {
      try {
        const modeledEnvelope = await buildModelFallbackUnderstandingEnvelope(app, {
          request: input,
          intent,
          typedEnvelope: envelope,
        });
        if (modeledEnvelope) {
          envelope = modeledEnvelope;
        }
      } catch (fallbackError) {
        app.log.warn(
          {
            requestId: input.metadata?.requestId,
            userId: input.userId,
            reason:
              fallbackError instanceof Error
                ? fallbackError.message
                : "unknown",
          },
          "understanding envelope model fallback failed open",
        );
      }
    }

    if (envelope) {
      context.understandingEnvelope = envelope;
      // ANLAŞILMIŞ BELLEK: modelin çıkardığı açık adaylar artık gerçekten
      // yazılıyor. Önceden yalnız sayılıp atılıyordu; hatırlama sabit bir
      // anahtar listesine (SYNCHRONOUS_MEMORY_KEYS) hapsolmuştu.
      // Fail-open: bellek yazımı anlama akışını asla düşürmez.
      const understoodMemoryOps = buildMemoryOpsFromUnderstandingCandidates(
        envelope.memory_candidates,
      );
      if (understoodMemoryOps.length) {
        void recordTurnMemoryOps(app, {
          userId: input.userId,
          sessionId: input.taskId ?? null,
          envelope: buildMemoryOnlyEnvelope(understoodMemoryOps),
        }).catch((error) => {
          app.log.warn(
            {
              requestId: input.metadata?.requestId,
              userId: input.userId,
              reason: error instanceof Error ? error.message : "unknown",
            },
            "understood memory candidates not persisted",
          );
        });
      }
      app.log.info(
        {
          requestId: input.metadata?.requestId,
          userId: input.userId,
          envelopeSource: envelope.source,
          envelopeConfidence: envelope.confidence,
          desiredOutputCount: envelope.desired_outputs.length,
          constraintCount: envelope.constraints.length,
          ambiguityCount: envelope.ambiguities.length,
          memoryCandidateCount: envelope.memory_candidates.length,
          durationMs: Date.now() - startedAt,
        },
        "understanding envelope built",
      );
    }

    endStage();
    return {
      intent,
      context,
      routingHints: intent.routingHints,
      ...(envelope
        ? {
            envelope,
            envelopeSource: envelope.source,
            envelopeConfidence: envelope.confidence,
          }
        : {}),
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
    endStage();
    return emptyUnderstanding(input, {
      includeEnvelope: shouldBuildUnderstandingEnvelope(app),
    });
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
    source?: string;
    metadata?: Record<string, unknown>;
  },
): Promise<number> {
  if (!app.config.ELYAN_LEARNING_EXTRACTION_ENABLED) {
    return 0;
  }

  const interaction = resolveInteractionContext({
    source: input.source,
    metadata: input.metadata,
  });
  const normalizedSignals = filterLearningSignals(input.signals).map(
    (signal) => ({
      ...signal,
      metadata: {
        ...signal.metadata,
        provenance: buildLearningProvenance({
          interaction,
          evidenceBasis:
            signal.source === "feedback"
              ? "user_feedback"
              : signal.metadata?.explicit === true
                ? "explicit_user"
                : signal.source === "runtime"
                  ? "runtime_observation"
                  : signal.source === "system"
                    ? "system_evaluation"
                    : "behavioral_inference",
        }),
      },
    }),
  );
  const signals = await suppressRepeatedImplicitSignals(
    app,
    input.userId,
    normalizedSignals,
  );

  if (!signals.length) {
    return 0;
  }

  const now = Date.now();

  try {
    if (isCognitiveFoundationEnabled(app, input.userId)) {
      const memoryOps = buildSynchronousMemoryOpsFromLearningSignals(signals);
      await cognitiveMemoryRepository(app).writeTurn({
        userId: input.userId,
        accountId: input.accountId,
        taskId: input.taskId,
        requestId: input.requestId,
        sourceKind: "explicit_signal",
        sourceId: input.taskId ?? input.requestId ?? null,
        envelope: memoryOps.length > 0 ? buildMemoryOnlyEnvelope(memoryOps) : null,
        evidence: signals.map((signal) => ({
          type: signal.type,
          key: signal.key,
          value: signal.value,
          confidence: signal.confidence,
          scope: signal.scope,
          source: signal.source,
          privacyLevel: "safe" as const,
          ttlDays: signal.ttlDays ?? undefined,
          metadata: signal.metadata ?? {},
        })),
      });

      void maybeQueueMemoryExtractionJob(app, {
        userId: input.userId,
        persistedSignals: signals.length,
        trigger: "learning_events_persisted",
        requestId: input.requestId,
      }).catch(() => undefined);
      return signals.length;
    }

    // Identity is single-valued: a new "my name is X" statement *replaces* the
    // old fact, it does not sit beside it. Without this sweep the stale row
    // ("En") stays live indefinitely and competes with the correction at read
    // time — recency scoring only papers over that race, expiry ends it.
    const identityKeysBeingWritten = [
      ...new Set(
        signals
          .filter((signal) => signal.type === "identity")
          .map((signal) => signal.key),
      ),
    ];
    if (identityKeysBeingWritten.length > 0) {
      await app.db
        .update(learningEvents)
        .set({ expiresAt: new Date(now) })
        .where(
          and(
            eq(learningEvents.userId, input.userId),
            eq(learningEvents.type, "identity"),
            inArray(learningEvents.key, identityKeysBeingWritten),
          ),
        )
        .catch(() => undefined);
    }

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

    if (app.config.ELYAN_MEMORY_FABRIC_V2_ENABLED === true) {
      await recordExplicitLearningSignalsAsMemory(app, {
        userId: input.userId,
        taskId: input.taskId,
        signals,
      }).catch((error) => {
        app.log.debug?.(
          {
            userId: input.userId,
            taskId: input.taskId,
            reason: error instanceof Error ? error.message : "unknown",
          },
          "understanding synchronous memory write skipped",
        );
      });
    }

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

async function suppressRepeatedImplicitSignals(
  app: FastifyInstance,
  userId: string,
  signals: LearningSignal[],
): Promise<LearningSignal[]> {
  const store = app.services?.reliability?.store as
    | {
        increment?: (key: string, ttlMs?: number) => Promise<number>;
      }
    | undefined;
  if (!store || typeof store.increment !== "function") {
    return signals;
  }

  const accepted = await Promise.all(
    signals.map(async (signal) => {
      if (
        signal.source !== "interaction" ||
        signal.metadata?.explicit === true
      ) {
        return signal;
      }
      const digest = createHash("sha256")
        .update(
          [
            userId,
            signal.scope,
            signal.type,
            signal.key,
            signal.value.toLocaleLowerCase("tr"),
          ].join("\u001f"),
        )
        .digest("hex")
        .slice(0, 32);
      const count = await store
        .increment!(`learning:implicit:v2:${digest}`, 6 * 60 * 60 * 1_000)
        .catch(() => 1);
      return count === 1 ? signal : null;
    }),
  );

  return accepted.filter((signal): signal is LearningSignal => signal != null);
}

export function buildSynchronousMemoryOpsFromLearningSignals(
  signals: LearningSignal[],
): TurnEnvelope["memory_ops"] {
  const memoryOps: TurnEnvelope["memory_ops"] = [];

  for (const signal of signals) {
    if (!SYNCHRONOUS_MEMORY_KEYS.has(signal.key)) {
      continue;
    }
    if (signal.metadata?.explicit !== true) {
      continue;
    }

    memoryOps.push({
      op: "write",
      kind:
        signal.key === "name" || signal.key === "timezone"
          ? "fact"
          : "preference",
      key: signal.key,
      value: signal.value,
      confidence: signal.confidence,
      ttl_days: signal.ttlDays ?? undefined,
    });
  }

  return memoryOps;
}

/**
 * Anlama zarfının `memory_candidates` alanını gerçek bellek yazımına çevirir.
 *
 * NEDEN: iki ayrı çıkarım yolu vardı ve yalnız zayıf olanı yazıyordu.
 *  - Öğrenme sinyalleri → `SYNCHRONOUS_MEMORY_KEYS` adlı SABİT ANAHTAR
 *    LİSTESİnden geçenler kaydediliyordu. Liste dışındaki her şey (kullanıcının
 *    açıkça söylediği alerjisi, çalıştığı şirket, kullandığı editör…) düşüyordu.
 *  - `memory_candidates` → model tarafından ANLAŞILARAK çıkarılıyor, şemada
 *    tipli (op/kind/key/value/confidence/explicit/source/ttlDays) ve zarfla
 *    birlikte taşınıyordu — ama yalnız SAYILIP loglanıyor, hiçbir yere
 *    yazılmıyordu. Yazıcı (`recordTurnMemoryOps`) zaten mevcuttu.
 *
 * Yani hatırlama yeteneği bir kelime listesine hapsedilmişti. Bu adaptör,
 * anlaşılmış adayları var olan lavaboya bağlar; anahtar listesi bir sonraki
 * sürümde tamamen kaldırılabilir hale gelir.
 *
 * DEĞİŞMEZ: yalnız `explicit` adaylar yazılır — çıkarım/tahmin hatırlanmaz.
 * Bu, sinyal yolundaki `metadata.explicit !== true` kuralının aynısıdır.
 */
export function buildMemoryOpsFromUnderstandingCandidates(
  candidates: UnderstandingEnvelope["memory_candidates"],
): TurnEnvelope["memory_ops"] {
  const memoryOps: TurnEnvelope["memory_ops"] = [];
  const seen = new Set<string>();
  for (const candidate of candidates ?? []) {
    if (candidate.op === "none") continue;
    // Kullanıcı açıkça söylemediyse hatırlama: çıkarılmış "tercih" uydurmadır.
    if (!candidate.explicit) continue;
    const key = candidate.key.trim();
    let value = candidate.value.trim();
    if (!key || !value) continue;
    // Kimlik anahtarları TEK kapıdan doğrulanır — aday ister zarfın
    // deterministik çıkarıcısından, ister modelin kendi anlayışından gelsin.
    // "bundan" bir gün adın kendisi olarak yazıldı; hangi yol yazdıysa yazsın,
    // fonksiyon kelimesi içeren bir "ad" burada düşer. Çıkarıcılar yer bulur,
    // adın ne olduğuna yalnız identity-name.ts karar verir.
    if (key === "name" || key === "preferred_name") {
      const normalized = normalizePersonalName(value);
      if (!normalized) continue;
      value = normalized;
    }
    // Aynı anahtar için tek yazım: aday listesi kendi içinde çelişirse ilki kazanır.
    if (seen.has(key)) continue;
    seen.add(key);
    memoryOps.push({
      op: candidate.op,
      kind: candidate.kind,
      key,
      value,
      confidence: candidate.confidence,
      ...(candidate.ttlDays ? { ttl_days: candidate.ttlDays } : {}),
    });
    if (memoryOps.length >= 20) break;
  }
  return memoryOps;
}

function buildMemoryOnlyEnvelope(
  memoryOps: TurnEnvelope["memory_ops"],
): TurnEnvelope {
  return {
    reply: { text: "", lang: "tr", tone: "neutral" },
    blocks: [],
    memory_ops: memoryOps,
    goal_ops: [],
    follow_ups: [],
    tool_requests: [],
    affect: { user_mood_guess: "unknown", energy: "mid", register: "neutral" },
  };
}

async function recordExplicitLearningSignalsAsMemory(
  app: FastifyInstance,
  input: {
    userId: string;
    taskId?: string;
    signals: LearningSignal[];
  },
): Promise<void> {
  const memoryOps = buildSynchronousMemoryOpsFromLearningSignals(input.signals);
  if (!memoryOps.length) {
    return;
  }

  await recordTurnMemoryOps(app, {
    userId: input.userId,
    sessionId: input.taskId ?? null,
    envelope: buildMemoryOnlyEnvelope(memoryOps),
  });
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
    source: input.source,
    metadata: input.metadata,
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
    volatileExternalData?: boolean;
    source?: string;
    metadata?: Record<string, unknown>;
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
  // Identity stated in plain conversation.
  //
  // This used to run only in `recordTaskLearningFromCreation`, i.e. only when
  // the turn produced a *task*. But people introduce themselves while chatting
  // ("benim adım Emre"), not while filing work, so the single most important
  // durable fact about a user was the one path that never captured it — the
  // name was never written, and every later turn correctly reported that it
  // knew of none.
  const identityExtraction = extractPreferenceSignals({
    userId: input.userId,
    accountId: input.accountId,
    taskId: input.taskId,
    message: input.userMessage,
  } as never);
  for (const signal of identityExtraction.signals) {
    if (signal.type === "identity") {
      signals.push(signal);
    }
  }

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
      confidence: 0.7,
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
      confidence: 0.72,
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
      confidence: 0.7,
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
  if (!input.volatileExternalData && keywordsResult && keywordsResult.length >= 3) {
    signals.push({
      type: "project_context",
      key: "message_keywords",
      value: keywordsResult.slice(0, 5).join(", "),
      confidence: 0.7,
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
    source: input.source,
    metadata: input.metadata,
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

/**
 * Başarısız görevden yapısal öğrenme sinyali kaydeder — sonucu (hata kodu,
 * patlayan araç, görev tipi/yetenekler) öğrenme deposuna bağlar. İmza türetimi
 * çağıran (tasks modülü) tarafında yapılır; burada döngüsel bağımlılık olmasın
 * diye yalnız ilkel değerler alınır.
 */
export async function recordTaskFailureLearning(
  app: FastifyInstance,
  input: {
    userId: string;
    accountId?: string;
    taskId: string;
    errorCode: string;
    failedTool?: string | null;
    capabilities?: string[];
    requestId?: string;
  },
): Promise<number> {
  const errorCode = String(input.errorCode ?? "").trim() || "unknown";
  const capabilities = Array.isArray(input.capabilities)
    ? input.capabilities.map((value) => String(value ?? "").trim().toLowerCase()).filter(Boolean).slice(0, 8)
    : [];
  const failedTool = String(input.failedTool ?? "").trim().toLowerCase() || null;
  const signal: LearningSignal = {
    type: "workflow",
    key: "task_failure",
    value: errorCode,
    confidence: 0.7,
    scope: "account",
    source: "runtime",
    ttlDays: 60,
    metadata: {
      errorCode,
      failedTool,
      capabilities,
    },
  };
  return persistLearningSignals(app, {
    userId: input.userId,
    accountId: input.accountId,
    taskId: input.taskId,
    signals: [signal],
    requestId: input.requestId,
  });
}

export async function recordBlockQualityLearning(
  app: FastifyInstance,
  input: {
    userId: string;
    accountId?: string;
    taskId?: string;
    quality: {
      version: string;
      score: number;
      feedbackSignals: string[];
      blockTypes: string[];
      metrics: Record<string, unknown>;
    };
    requestId?: string;
  },
): Promise<number> {
  const feedbackSignals = input.quality.feedbackSignals
    .map((signal) => signal.trim().toLowerCase())
    .filter((signal) =>
      [
        "unrequested_table_block",
        "duplicate_table_block",
        "duplicate_block",
        "malformed_structured_json",
        "raw_json_leak_prevented",
        "fallback_to_text",
      ].includes(signal),
    );
  if (feedbackSignals.length === 0 && input.quality.score >= 95) {
    return 0;
  }

  const scoreBucket =
    input.quality.score >= 95
      ? "excellent"
      : input.quality.score >= 80
        ? "needs_watch"
        : input.quality.score >= 60
          ? "needs_repair"
          : "bad";
  const baseMetadata = {
    qualityVersion: input.quality.version,
    score: Math.round(input.quality.score),
    scoreBucket,
    blockTypes: input.quality.blockTypes.slice(0, 12),
    metrics: input.quality.metrics,
  };
  const signals: LearningSignal[] = [
    {
      type: "workflow",
      key: "block_output_quality",
      value: scoreBucket,
      confidence: 0.74,
      scope: "user",
      source: "system",
      ttlDays: 30,
      metadata: baseMetadata,
    },
    ...feedbackSignals.map(
      (signal): LearningSignal => ({
        type: "workflow",
        key: "block_output_quality",
        value: signal,
        confidence: 0.78,
        scope: "user",
        source: "system",
        ttlDays: 30,
        metadata: baseMetadata,
      }),
    ),
  ];

  return persistLearningSignals(app, {
    userId: input.userId,
    accountId: input.accountId,
    taskId: input.taskId,
    signals,
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
    source?: string;
    metadata?: Record<string, unknown>;
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
    source: input.source,
    metadata: input.metadata,
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
