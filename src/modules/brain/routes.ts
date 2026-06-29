import type { FastifyInstance, FastifyPluginAsync } from "fastify";
import { eq } from "drizzle-orm";
import { forbidden } from "../../lib/errors.js";
import { getRequestContext } from "../../lib/http.js";
import { getUserAuth } from "../../lib/request-auth.js";
import { users } from "../../db/schema.js";
import { classifyIntent } from "../../core/understanding/intent-classifier.js";
import { buildUserContext } from "../../core/understanding/context-builder.js";
import {
  brainChatBodySchema,
  approveBrainReviewBodySchema,
  listBrainReviewQuerySchema,
  brainProfileQuerySchema,
  brainMemoryParamsSchema,
  createDatasetManifestBodySchema,
  createKnowledgeDocumentBodySchema,
  createModelArtifactBodySchema,
  createTrainingJobBodySchema,
  datasetParamsSchema,
  knowledgeDocumentParamsSchema,
  listBrainMemoryQuerySchema,
  mutateBrainMemoryBodySchema,
  modelArtifactParamsSchema,
  rejectBrainReviewBodySchema,
  reviewInteractionParamsSchema,
  searchKnowledgeBodySchema,
  trainingJobParamsSchema,
  updateBrainMemoryBodySchema,
  updateDatasetManifestBodySchema,
  updateModelArtifactBodySchema,
} from "./schemas.js";
import {
  cancelTrainingJob,
  createDatasetManifest,
  createKnowledgeDocument,
  createModelArtifact,
  createTrainingJob,
  getBrainMemoryRecord,
  getBrainProfile,
  queueKnowledgeDocumentTrainingJob,
  listBrainMemoryRecords,
  listDatasetManifests,
  listModelArtifacts,
  listTrainingJobs,
  restoreBrainMemoryRecord,
  searchKnowledge,
  setBrainMemoryContestState,
  setBrainMemoryPinState,
  softDeleteBrainMemoryRecord,
  updateBrainMemoryRecord,
  queueContinuousBrainTrainingJob,
  sanitizePublicBrainValue,
  shapePublicBrainProfile,
  updateDatasetManifest,
  updateModelArtifact,
} from "./service.js";
import { decideCommandRoute } from "../routing-policy/service.js";
import { generateGovernedSharedBrainReply } from "./inference.js";
import { buildLocalRenderRecipe } from "../../core/understanding/render-recipe.js";
import {
  approveBrainInteractionCorrection,
  exportApprovedCorrectionsDataset,
  exportSftReadyCorrectionsDataset,
  listPendingBrainInteractionReviews,
  rejectBrainInteractionCorrection,
} from "./review.js";
import { runBrainBenchmark } from "./benchmark.js";

async function assertAdmin(app: FastifyInstance, userId: string): Promise<void> {
  const rows = await app.db.select({ role: users.role }).from(users).where(eq(users.id, userId)).limit(1);
  if (rows[0]?.role !== "admin") {
    throw forbidden("Admin access required");
  }
}

export const brainRoutes: FastifyPluginAsync = async (app) => {
  app.get("/profile", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    brainProfileQuerySchema.parse(request.query ?? {});
    const auth = getUserAuth(request);

    return shapePublicBrainProfile(await getBrainProfile(app, auth.sub));
  });

  app.post("/chat", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const body = brainChatBodySchema.parse(request.body);
    const auth = getUserAuth(request);
    await assertAdmin(app, auth.sub);

    const understandingContext = await buildUserContext(app, {
      userId: auth.sub,
      message: body.prompt,
      title: body.title,
      source: "mobile",
      intent: classifyIntent({
        userId: auth.sub,
        message: body.prompt,
        title: body.title,
        source: "mobile",
      }),
    });

    const routeDecision = await decideCommandRoute(app, {
      userId: auth.sub,
      message: body.prompt,
      source: "mobile",
      activeChatSessionId: undefined,
      selectedDeviceId: undefined,
      requestedCapabilities: [],
      bootstrap: undefined,
      brainProfile: undefined,
      quota: undefined,
    });

    const replyResult = await generateGovernedSharedBrainReply(app, {
      userId: auth.sub,
      prompt: body.prompt,
      title: body.title,
      conversation: body.conversation,
      route: "shared_brain",
      routeDecision,
      workload: routeDecision.selectedWorkload,
      understandingContext,
      internalEvaluation: {
        skipUsageValidation: true,
        skipInvocationLogging: true,
        skipReviewLogging: true,
      },
    });
    const renderRecipe = buildLocalRenderRecipe({
      prompt: body.prompt,
      responseText: replyResult.text,
      assistantBlocks: Array.isArray(replyResult.metadata.blocks) ? replyResult.metadata.blocks : [],
      metadata: {
        routeDecision,
        workload: routeDecision.selectedWorkload,
        source: "brain_chat",
        title: body.title,
        latencyMs: replyResult.latencyMs,
      },
      renderOn: routeDecision.route === "desktop_runtime" ? "desktop" : "mobile",
      taskId: undefined,
    });

    return {
      reply: {
        text: replyResult.text,
        latencyMs: replyResult.latencyMs,
        answerSource: replyResult.answerSource,
        boundaryOutcome: replyResult.boundaryOutcome,
        failureType: replyResult.failureType,
        metadata: sanitizePublicBrainValue(replyResult.metadata),
        renderRecipe: renderRecipe ?? null,
      },
      routeDecision,
    };
  });

  app.get("/datasets", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    return {
      datasets: await listDatasetManifests(app, auth.sub),
    };
  });

  app.post("/datasets", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const body = createDatasetManifestBodySchema.parse(request.body);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);

    return createDatasetManifest(app, {
      userId: auth.sub,
      name: body.name,
      source: body.source,
      format: body.format,
      scope: body.scope,
      description: body.description,
      locator: body.locator,
      languageTags: body.languageTags,
      recordCount: body.recordCount,
      tokenEstimate: body.tokenEstimate,
      metadata: body.metadata,
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.put("/datasets/:datasetId", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = datasetParamsSchema.parse(request.params);
    const body = updateDatasetManifestBodySchema.parse(request.body);
    const auth = getUserAuth(request);

    return updateDatasetManifest(app, {
      userId: auth.sub,
      datasetId: params.datasetId,
      name: body.name,
      description: body.description,
      locator: body.locator,
      status: body.status,
      languageTags: body.languageTags,
      recordCount: body.recordCount,
      tokenEstimate: body.tokenEstimate,
      metadata: body.metadata,
    });
  });

  app.get("/training-jobs", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    return {
      jobs: await listTrainingJobs(app, auth.sub),
    };
  });

  app.post("/training-jobs", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const body = createTrainingJobBodySchema.parse(request.body);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);

    return createTrainingJob(app, {
      userId: auth.sub,
      name: body.name,
      kind: body.kind,
      scope: body.scope,
      baseModel: body.baseModel,
      datasetManifestId: body.datasetManifestId,
      config: body.config,
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.post("/training-jobs/:jobId/cancel", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = trainingJobParamsSchema.parse(request.params);
    const auth = getUserAuth(request);

    return cancelTrainingJob(app, {
      userId: auth.sub,
      jobId: params.jobId,
    });
  });

  app.post("/training-jobs/continuous", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const context = getRequestContext(request);

    return queueContinuousBrainTrainingJob(app, {
      userId: auth.sub,
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.get("/models", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    return {
      models: await listModelArtifacts(app, auth.sub),
    };
  });

  app.post("/models", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const body = createModelArtifactBodySchema.parse(request.body);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);

    return createModelArtifact(app, {
      userId: auth.sub,
      name: body.name,
      scope: body.scope,
      trainingJobId: body.trainingJobId,
      provider: body.provider,
      baseModel: body.baseModel,
      adapterKind: body.adapterKind,
      status: body.status,
      storageUri: body.storageUri,
      checksum: body.checksum,
      metadata: body.metadata,
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.put("/models/:artifactId", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = modelArtifactParamsSchema.parse(request.params);
    const body = updateModelArtifactBodySchema.parse(request.body);
    const auth = getUserAuth(request);

    return updateModelArtifact(app, {
      userId: auth.sub,
      artifactId: params.artifactId,
      status: body.status,
      storageUri: body.storageUri,
      checksum: body.checksum,
      metadata: body.metadata,
    });
  });

  app.post("/knowledge/documents", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const body = createKnowledgeDocumentBodySchema.parse(request.body);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);
    const sharedLearningRequested = body.scope === "shared" || body.learningMode === "shared_corpus_train";

    if (sharedLearningRequested) {
      await assertAdmin(app, auth.sub);
    }

    return createKnowledgeDocument(app, {
      userId: auth.sub,
      title: body.title,
      scope: body.scope,
      sourceType: body.sourceType,
      sourceUri: body.sourceUri,
      text: body.text,
      chunks: body.chunks,
      learningMode: body.learningMode,
      languageTags: body.languageTags,
      autoQueueTraining: body.autoQueueTraining,
      isAdmin: sharedLearningRequested,
      metadata: body.metadata,
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.post("/knowledge/documents/:documentId/train", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = knowledgeDocumentParamsSchema.parse(request.params);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);

    await assertAdmin(app, auth.sub);

    return queueKnowledgeDocumentTrainingJob(app, {
      userId: auth.sub,
      documentId: params.documentId,
      isAdmin: true,
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.post("/retrieval/search", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const body = searchKnowledgeBodySchema.parse(request.body);
    const auth = getUserAuth(request);

    return await searchKnowledge(app, {
      userId: auth.sub,
      query: body.query,
      limit: body.limit,
    });
  });

  app.get("/review/interactions", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) {
      return;
    }
    const auth = getUserAuth(request);
    await assertAdmin(app, auth.sub);
    const query = listBrainReviewQuerySchema.parse(request.query ?? {});
    return {
      interactions: await listPendingBrainInteractionReviews(app, {
        limit: query.limit,
      }),
    };
  });

  app.post("/review/interactions/:interactionId/approve", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) {
      return;
    }
    const auth = getUserAuth(request);
    await assertAdmin(app, auth.sub);
    const params = reviewInteractionParamsSchema.parse(request.params);
    const body = approveBrainReviewBodySchema.parse(request.body ?? {});
    const context = getRequestContext(request);
    return approveBrainInteractionCorrection(app, {
      interactionId: params.interactionId,
      actorUserId: auth.sub,
      correctedAnswer: body.correctedAnswer,
      reason: body.reason ?? null,
      requestId: context.requestId,
    });
  });

  app.post("/review/interactions/:interactionId/reject", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) {
      return;
    }
    const auth = getUserAuth(request);
    await assertAdmin(app, auth.sub);
    const params = reviewInteractionParamsSchema.parse(request.params);
    const body = rejectBrainReviewBodySchema.parse(request.body ?? {});
    const context = getRequestContext(request);
    return rejectBrainInteractionCorrection(app, {
      interactionId: params.interactionId,
      actorUserId: auth.sub,
      reason: body.reason ?? null,
      requestId: context.requestId,
    });
  });

  app.post("/review/export/approved-corrections", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) {
      return;
    }
    const auth = getUserAuth(request);
    await assertAdmin(app, auth.sub);
    const context = getRequestContext(request);
    return exportApprovedCorrectionsDataset(app, {
      actorUserId: auth.sub,
      requestId: context.requestId,
    });
  });

  app.post("/review/export/sft-ready-corrections", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) {
      return;
    }
    const auth = getUserAuth(request);
    await assertAdmin(app, auth.sub);
    const context = getRequestContext(request);
    return exportSftReadyCorrectionsDataset(app, {
      actorUserId: auth.sub,
      requestId: context.requestId,
    });
  });

  app.post("/benchmark/run", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) {
      return;
    }
    const auth = getUserAuth(request);
    await assertAdmin(app, auth.sub);
    const context = getRequestContext(request);
    return runBrainBenchmark(app, {
      actorUserId: auth.sub,
      persistSummary: true,
      requestId: context.requestId,
    });
  });

  app.get("/memory", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const query = listBrainMemoryQuerySchema.parse(request.query ?? {});
    const auth = getUserAuth(request);
    const actingAsAdmin = Boolean(query.userId && query.userId !== auth.sub);
    if (actingAsAdmin) {
      await assertAdmin(app, auth.sub);
    }

    return listBrainMemoryRecords(app, {
      actorUserId: auth.sub,
      targetUserId: actingAsAdmin ? query.userId ?? auth.sub : auth.sub,
      isAdmin: actingAsAdmin,
      includeSoftDeleted: query.includeSoftDeleted,
      limit: query.limit,
      surface: query.surface,
      lifecycle: query.lifecycle,
    });
  });

  app.get("/memory/:memoryId", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = brainMemoryParamsSchema.parse(request.params);
    const query = listBrainMemoryQuerySchema.pick({ userId: true }).parse(request.query ?? {});
    const auth = getUserAuth(request);
    const actingAsAdmin = Boolean(query.userId && query.userId !== auth.sub);
    if (actingAsAdmin) {
      await assertAdmin(app, auth.sub);
    }

    return getBrainMemoryRecord(app, {
      actorUserId: auth.sub,
      targetUserId: actingAsAdmin ? query.userId ?? auth.sub : auth.sub,
      isAdmin: actingAsAdmin,
      memoryId: params.memoryId,
    });
  });

  app.post("/memory/:memoryId/pin", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) {
      return;
    }

    const params = brainMemoryParamsSchema.parse(request.params);
    const body = mutateBrainMemoryBodySchema.parse(request.body ?? {});
    const auth = getUserAuth(request);
    const actingAsAdmin = Boolean(body.userId && body.userId !== auth.sub);
    if (actingAsAdmin) {
      await assertAdmin(app, auth.sub);
    }
    const context = getRequestContext(request);

    return setBrainMemoryPinState(app, {
      actorUserId: auth.sub,
      targetUserId: actingAsAdmin ? body.userId ?? auth.sub : auth.sub,
      isAdmin: actingAsAdmin,
      memoryId: params.memoryId,
      pinned: true,
      reason: body.reason ?? null,
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.post("/memory/:memoryId/unpin", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) {
      return;
    }

    const params = brainMemoryParamsSchema.parse(request.params);
    const body = mutateBrainMemoryBodySchema.parse(request.body ?? {});
    const auth = getUserAuth(request);
    const actingAsAdmin = Boolean(body.userId && body.userId !== auth.sub);
    if (actingAsAdmin) {
      await assertAdmin(app, auth.sub);
    }
    const context = getRequestContext(request);

    return setBrainMemoryPinState(app, {
      actorUserId: auth.sub,
      targetUserId: actingAsAdmin ? body.userId ?? auth.sub : auth.sub,
      isAdmin: actingAsAdmin,
      memoryId: params.memoryId,
      pinned: false,
      reason: body.reason ?? null,
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.post("/memory/:memoryId/contest", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) {
      return;
    }

    const params = brainMemoryParamsSchema.parse(request.params);
    const body = mutateBrainMemoryBodySchema.parse(request.body ?? {});
    const auth = getUserAuth(request);
    const actingAsAdmin = Boolean(body.userId && body.userId !== auth.sub);
    if (actingAsAdmin) {
      await assertAdmin(app, auth.sub);
    }
    const context = getRequestContext(request);

    return setBrainMemoryContestState(app, {
      actorUserId: auth.sub,
      targetUserId: actingAsAdmin ? body.userId ?? auth.sub : auth.sub,
      isAdmin: actingAsAdmin,
      memoryId: params.memoryId,
      supersedesMemoryId: body.supersedesMemoryId ?? null,
      reason: body.reason ?? null,
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.post("/memory/:memoryId/soft-delete", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) {
      return;
    }

    const params = brainMemoryParamsSchema.parse(request.params);
    const body = mutateBrainMemoryBodySchema.parse(request.body ?? {});
    const auth = getUserAuth(request);
    const actingAsAdmin = Boolean(body.userId && body.userId !== auth.sub);
    if (actingAsAdmin) {
      await assertAdmin(app, auth.sub);
    }
    const context = getRequestContext(request);

    return softDeleteBrainMemoryRecord(app, {
      actorUserId: auth.sub,
      targetUserId: actingAsAdmin ? body.userId ?? auth.sub : auth.sub,
      isAdmin: actingAsAdmin,
      memoryId: params.memoryId,
      reason: body.reason ?? "user_requested_soft_delete",
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.post("/memory/:memoryId/update", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) {
      return;
    }

    const params = brainMemoryParamsSchema.parse(request.params);
    const body = updateBrainMemoryBodySchema.parse(request.body ?? {});
    const auth = getUserAuth(request);
    const actingAsAdmin = Boolean(body.userId && body.userId !== auth.sub);
    if (actingAsAdmin) {
      await assertAdmin(app, auth.sub);
    }
    const context = getRequestContext(request);

    return updateBrainMemoryRecord(app, {
      actorUserId: auth.sub,
      targetUserId: actingAsAdmin ? body.userId ?? auth.sub : auth.sub,
      isAdmin: actingAsAdmin,
      memoryId: params.memoryId,
      title: body.title ?? null,
      content: body.content,
      reason: body.reason ?? null,
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.post("/memory/:memoryId/restore", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) {
      return;
    }

    const params = brainMemoryParamsSchema.parse(request.params);
    const body = mutateBrainMemoryBodySchema.parse(request.body ?? {});
    const auth = getUserAuth(request);
    const actingAsAdmin = Boolean(body.userId && body.userId !== auth.sub);
    if (actingAsAdmin) {
      await assertAdmin(app, auth.sub);
    }
    const context = getRequestContext(request);

    return restoreBrainMemoryRecord(app, {
      actorUserId: auth.sub,
      targetUserId: actingAsAdmin ? body.userId ?? auth.sub : auth.sub,
      isAdmin: actingAsAdmin,
      memoryId: params.memoryId,
      reason: body.reason ?? null,
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });
};
