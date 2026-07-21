import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import {
  assertOwnedDesktopTaskTarget,
  createInvalidTargetDeviceError,
  createStaleRuntimeConnectionError,
  createTaskRuntimeOwnershipConflictError,
  extractSharedBrainConversation,
  extractTaskRouteDecision,
  getSharedBrainFallbackMessage,
  resolveSafeChatContinuityReply,
  resolveIdempotentTaskMatch,
  shapeTaskArtifact,
  shapeTaskFeedItem,
  sanitizePublicInferenceValue,
  sanitizePublicTaskEventPayload,
} from "./service-helpers.js";
import { normalizeAssistantMessageBlocks } from "../chat/message-blocks.js";

test("hosted image chat requests bypass text inference and streaming prose", () => {
  const serviceSource = readFileSync(path.join(process.cwd(), "src/modules/tasks/service.ts"), "utf8");
  const processStart = serviceSource.indexOf("async function processSharedBrainChatTask");
  assert.notEqual(processStart, -1);
  const imageBranchStart = serviceSource.indexOf(
    "const imageGenerationRequested =",
    processStart,
  );
  const inferenceStart = serviceSource.indexOf(
    "const inference = await generateGovernedSharedBrainReply(app, {",
    processStart,
  );
  assert.ok(imageBranchStart > processStart);
  assert.ok(inferenceStart > imageBranchStart);

  const imageBranchEnd = serviceSource.indexOf("\n    // Deterministik hedef komutu", imageBranchStart);
  assert.ok(imageBranchEnd > imageBranchStart);
  const imageBranch = serviceSource.slice(imageBranchStart, imageBranchEnd);
  assert.ok(imageBranch.includes("isHostedImageGenerationRequest(input.prompt)"));
  assert.ok(imageBranch.includes("imageEditIntent"));
  assert.equal(imageBranch.includes("generateGovernedSharedBrainReply"), false);
  assert.ok(imageBranch.includes('event: "message.delta"'));
  assert.ok(imageBranch.includes('delta: ""'));
  assert.ok(imageBranch.includes('reset: true'));
  assert.ok(imageBranch.includes('event: "heartbeat"'));
  assert.ok(imageBranch.includes('event: "message.completed"'));
  assert.ok(imageBranch.includes('const visibleText = imageResultBlocks.length > 0 ? "" : completedResultText;'));
  assert.equal(imageBranch.includes('title: ""'), false);
  assert.equal(imageBranch.includes('summary: ""'), false);
  assert.equal(imageBranch.includes('preview: ""'), false);
  assert.equal(imageBranch.includes('answerSource: "image_generation"'), false);
  assert.equal(imageBranch.includes('answerSource: "model"'), false);
  assert.equal(imageBranch.includes("selectedProfile"), false);
  assert.equal(serviceSource.includes('answerSource: "backend_ack"'), false);

});

test("generated image artifact blocks survive assistant block normalization", () => {
  const blocks = normalizeAssistantMessageBlocks({
    blocks: [
      {
        type: "artifact",
        artifactType: "image",
        artifactId: "artifact-image-1",
        title: "Görsel",
        url: "https://api.elyan.dev/v1/tasks/task-1/artifacts/artifact-image-1/content/raw?token=signed",
        mime: "image/jpeg",
        viewerHint: "image",
        contentFamily: "image",
        loadStrategy: "remote_url",
      },
    ],
  });

  assert.equal(blocks.length, 1);
  assert.equal(blocks[0]?.type, "artifact");
  assert.equal((blocks[0] as { url?: string }).url?.includes("/content/raw?token="), true);
});

test("createInvalidTargetDeviceError keeps the target-device validation contract", () => {
  const error = createInvalidTargetDeviceError("device-1");

  assert.equal(error.statusCode, 422);
  assert.equal(error.code, "invalid_target");
  assert.match(error.message, /valid desktop runtime/i);
});

test("assertOwnedDesktopTaskTarget rejects inactive desktop runtimes", () => {
  assert.throws(
    () =>
      assertOwnedDesktopTaskTarget(
        {
          type: "desktop",
          isActive: false,
          canReceiveTasks: false,
          isOnline: false,
          targetStatus: "inactive",
          runtime: {
            lastHeartbeatAt: null,
          },
        },
        "device-1",
      ),
    (error: unknown) => {
      assert.equal((error as { statusCode?: number }).statusCode, 409);
      assert.equal((error as { code?: string }).code, "device_inactive");
      return true;
    },
  );
});

test("assertOwnedDesktopTaskTarget rejects backend reachability failures", () => {
  assert.throws(
    () =>
      assertOwnedDesktopTaskTarget(
        {
          type: "desktop",
          isActive: true,
          canReceiveTasks: false,
          isOnline: true,
          targetStatus: "backend_unreachable",
          runtime: {
            lastHeartbeatAt: new Date("2030-01-01T00:00:00.000Z"),
          },
        },
        "device-2",
      ),
    (error: unknown) => {
      assert.equal((error as { statusCode?: number }).statusCode, 409);
      assert.equal((error as { code?: string }).code, "runtime_unreachable");
      return true;
    },
  );
});

test("assertOwnedDesktopTaskTarget rejects plan restricted desktop targets", () => {
  assert.throws(
    () =>
      assertOwnedDesktopTaskTarget(
        {
          type: "desktop",
          isActive: true,
          canReceiveTasks: false,
          isOnline: true,
          targetStatus: "plan_restricted",
          runtime: {
            lastHeartbeatAt: new Date("2030-01-01T00:00:00.000Z"),
          },
        },
        "device-2b",
      ),
    (error: unknown) => {
      assert.equal((error as { statusCode?: number }).statusCode, 409);
      assert.equal((error as { code?: string }).code, "desktop_plan_required");
      return true;
    },
  );
});

test("assertOwnedDesktopTaskTarget rejects offline runtimes", () => {
  assert.throws(
    () =>
      assertOwnedDesktopTaskTarget(
        {
          type: "desktop",
          isActive: true,
          canReceiveTasks: false,
          isOnline: false,
          targetStatus: "offline",
          runtime: {
            lastHeartbeatAt: new Date("2030-01-01T00:00:00.000Z"),
          },
        },
        "device-3",
      ),
    (error: unknown) => {
      assert.equal((error as { statusCode?: number }).statusCode, 409);
      assert.equal((error as { code?: string }).code, "device_offline");
      return true;
    },
  );
});

test("assertOwnedDesktopTaskTarget rejects stale runtimes with a safe unavailable code", () => {
  assert.throws(
    () =>
      assertOwnedDesktopTaskTarget(
        {
          type: "desktop",
          isActive: true,
          canReceiveTasks: false,
          isOnline: false,
          targetStatus: "runtime_stale",
          runtime: {
            lastHeartbeatAt: new Date("2030-01-01T00:00:00.000Z"),
          },
        },
        "device-4",
      ),
    (error: unknown) => {
      assert.equal((error as { statusCode?: number }).statusCode, 409);
      assert.equal((error as { code?: string }).code, "runtime_unavailable");
      assert.equal((error as { details?: { targetStatus?: string } }).details?.targetStatus, "runtime_stale");
      return true;
    },
  );
});


test("resolveIdempotentTaskMatch reuses matching payloads", () => {
  const existingTask = {
    id: "task-1",
    idempotencyFingerprint: "fingerprint-123",
  };

  const resolved = resolveIdempotentTaskMatch(existingTask, {
    idempotencyKey: "idempotency-key",
    fingerprint: "fingerprint-123",
  });

  assert.equal(resolved, existingTask);
});

test("resolveIdempotentTaskMatch raises idempotency_conflict on payload drift", () => {
  assert.throws(
    () =>
      resolveIdempotentTaskMatch(
        {
          id: "task-1",
          idempotencyFingerprint: "fingerprint-abc",
        },
        {
          idempotencyKey: "idempotency-key",
          fingerprint: "fingerprint-def",
        },
      ),
    (error: unknown) => {
      assert.equal((error as { statusCode?: number }).statusCode, 409);
      assert.equal((error as { code?: string }).code, "idempotency_conflict");
      return true;
    },
  );
});

test("createStaleRuntimeConnectionError and runtime ownership conflict keep explicit codes", () => {
  const stale = createStaleRuntimeConnectionError();
  const conflict = createTaskRuntimeOwnershipConflictError({
    taskId: "task-1",
    activeConnectionId: "runtime-2",
    owningConnectionId: "runtime-1",
  });

  assert.equal(stale.statusCode, 401);
  assert.equal(stale.code, "unauthorized");
  assert.equal(conflict.statusCode, 409);
  assert.equal(conflict.code, "task_runtime_owner_conflict");
});

test("extractSharedBrainConversation keeps only valid conversation items", () => {
  const conversation = extractSharedBrainConversation({
    brainContext: {
      conversation: [
        { role: "system", content: "  Session state  " },
        { role: "assistant", content: "" },
        { role: "user", content: "Hello" },
        { role: "tool", content: "ignored" },
        null,
      ],
    },
  });

  assert.deepEqual(conversation, [
    { role: "system", content: "  Session state  " },
    { role: "user", content: "Hello" },
  ]);
});

test("getSharedBrainFallbackMessage preserves explicit error text and default fallback", () => {
  const fallback = "Buradayım. Bunu birlikte ilerletelim; beklediğin sonucu bir cümleyle netleştirir misin?";
  assert.equal(
    getSharedBrainFallbackMessage(new Error("  Shared brain failed  ")),
    "Shared brain failed",
  );
  assert.equal(
    getSharedBrainFallbackMessage(new Error("Provider endpoint http://127.0.0.1:11434 failed")),
    fallback,
  );
  assert.equal(
    getSharedBrainFallbackMessage(new Error("fetch failed")),
    fallback,
  );
  assert.equal(
    getSharedBrainFallbackMessage({}),
    fallback,
  );
});

test("resolveSafeChatContinuityReply keeps public chat alive after provider exhaustion", () => {
  const reply = resolveSafeChatContinuityReply({
    prompt: "Bunu nasıl düzenleyebilirim?",
    channel: "chat",
    route: "server_brain",
    mode: "chat",
    privacyClass: "public_text",
    requiresApproval: false,
    intent: "normal_chat",
    requiredRuntime: "server",
    shouldAskClarification: false,
    failClosedReason: null,
    workload: "mobile_chat_fast",
    taskRoute: null,
    routeCapabilities: [],
    requestedCapabilities: [],
    metadata: { channel: "chat" },
    understandingEnvelope: null,
    errorCode: "server_brain_unavailable",
    failureClass: "invalid_output",
  });

  assert.match(reply ?? "", /^Buradayım\./u);
  assert.doesNotMatch(reply ?? "", /yanıt servisi|yeniden dene/iu);
});

test("resolveSafeChatContinuityReply never bypasses tools, private context, approvals, or policy", () => {
  const base = {
    prompt: "Devam et",
    channel: "chat",
    route: "server_brain",
    mode: "chat",
    privacyClass: "public_text",
    requiresApproval: false,
    intent: "normal_chat",
    requiredRuntime: "server",
    shouldAskClarification: false,
    failClosedReason: null,
    workload: "mobile_chat_fast",
    taskRoute: null,
    routeCapabilities: [] as unknown[],
    requestedCapabilities: [] as unknown[],
    metadata: { channel: "chat" } as Record<string, unknown>,
    understandingEnvelope: null,
    errorCode: "server_brain_unavailable",
    failureClass: "unavailable",
  };

  assert.equal(
    resolveSafeChatContinuityReply({ ...base, routeCapabilities: ["drive.search"] }),
    null,
  );
  assert.equal(
    resolveSafeChatContinuityReply({ ...base, privacyClass: "private_context" }),
    null,
  );
  assert.equal(
    resolveSafeChatContinuityReply({ ...base, requiresApproval: true }),
    null,
  );
  assert.equal(
    resolveSafeChatContinuityReply({ ...base, failureClass: "policy_blocked" }),
    null,
  );
  assert.equal(
    resolveSafeChatContinuityReply({
      ...base,
      metadata: { channel: "chat", mediaInputRefs: [{ inputRef: "private" }] },
    }),
    null,
  );
  assert.equal(
    resolveSafeChatContinuityReply({
      ...base,
      taskRoute: {
        needsPrivateDesktopData: true,
        requiredCapabilities: [],
      },
    }),
    null,
  );
  assert.equal(
    resolveSafeChatContinuityReply({
      ...base,
      understandingEnvelope: {
        risk: { local_private: false, side_effect: true },
        required_capabilities: [],
      },
    }),
    null,
  );
  assert.equal(
    resolveSafeChatContinuityReply({
      ...base,
      metadata: {
        channel: "chat",
        clientAttachments: [{ documentId: "private" }],
      },
    }),
    null,
  );
});

test("shapeTaskFeedItem preserves chat session truth from task payload", () => {
  const item = shapeTaskFeedItem({
    id: "task-chat",
    title: "Selam",
    status: "completed",
    targetDeviceId: "shared-brain-device",
    queuePosition: 0,
    runtimeConnectionId: "runtime-1",
    dispatchLeaseId: null,
    dispatchLeaseIssuedAt: new Date("2030-01-01T00:00:00.000Z"),
    dispatchLeaseExpiresAt: null,
    dispatchAckAt: new Date("2030-01-01T00:00:01.000Z"),
    requestedCapabilities: [],
    payload: {
      metadata: {
        routeDecision: { route: "server_brain", mode: "chat", privacyClass: "public_text" },
        chat: { sessionId: "chat-session-1" },
      },
    },
    summary: "Merhaba",
    error: null,
    approvalRequest: null,
    createdAt: new Date("2030-01-01T00:00:00.000Z"),
    updatedAt: new Date("2030-01-01T00:00:01.000Z"),
  });

  assert.equal(item.chatSessionId, "chat-session-1");
  assert.equal(item.presentation, "chat");
  assert.equal(item.deliveryState, "acked");
  assert.equal(item.runtimeConnectionId, "runtime-1");
  assert.equal(item.routeDecision?.route, "server_brain");
  assert.equal(item.lastDispatchAttemptAt?.toISOString(), "2030-01-01T00:00:00.000Z");
});

test("shapeTaskFeedItem exposes render recipe from completed task result", () => {
  const item = shapeTaskFeedItem({
    id: "task-render",
    title: "PDF",
    status: "completed",
    targetDeviceId: "shared-brain-device",
    queuePosition: 0,
    runtimeConnectionId: null,
    dispatchLeaseId: null,
    dispatchLeaseIssuedAt: null,
    dispatchLeaseExpiresAt: null,
    dispatchAckAt: null,
    requestedCapabilities: [],
    payload: {
      metadata: {
        presentation: "chat",
        chat: { sessionId: "chat-session-1" },
      },
    },
    result: {
      text: "PDF hazır",
      renderRecipe: {
        output_type: "document_render_recipe",
        format: "pdf",
        render_on: "mobile",
      },
    },
    summary: "PDF hazır",
    error: null,
    approvalRequest: null,
    createdAt: new Date("2030-01-01T00:00:00.000Z"),
    updatedAt: new Date("2030-01-01T00:00:01.000Z"),
    completedAt: new Date("2030-01-01T00:00:01.000Z"),
  });

  assert.deepEqual(item.renderRecipe, {
    output_type: "document_render_recipe",
    format: "pdf",
    render_on: "mobile",
  });
});

test("shapeTaskFeedItem exposes public-safe quality metadata from server brain results", () => {
  const item = shapeTaskFeedItem({
    id: "task-quality",
    title: "Düzelt",
    status: "completed",
    targetDeviceId: "shared-brain-device",
    queuePosition: 0,
    runtimeConnectionId: null,
    dispatchLeaseId: null,
    dispatchLeaseIssuedAt: null,
    dispatchLeaseExpiresAt: null,
    dispatchAckAt: null,
    requestedCapabilities: [],
    payload: {
      metadata: {
        presentation: "chat",
      },
    },
    result: {
      text: "Merhaba, ben geldim. Nasılsın?",
      skillUsed: true,
      skillId: "research-report",
      retrievalResultCount: 6,
      qualityPolicyApplied: true,
      dataGroundingLevel: "request_only",
      personalizationScope: "none",
      responseLanguage: "tr",
      evidenceSufficiency: "weak",
      dataConfidence: "low",
      dataQualityWarnings: ["insufficient_external_evidence"],
      responseBudgetState: "normal",
      responseBudgetReason: "standard",
      contextPacketCount: 5,
      contextPacketKinds: ["health_context", "calendar_context"],
      healthContextUsed: true,
    },
    summary: "Merhaba",
    error: null,
    approvalRequest: null,
    createdAt: new Date("2030-01-01T00:00:00.000Z"),
    updatedAt: new Date("2030-01-01T00:00:01.000Z"),
    completedAt: new Date("2030-01-01T00:00:01.000Z"),
  });

  assert.equal(item.brain?.qualityPolicyApplied, true);
  assert.equal(item.brain?.skillUsed, true);
  assert.equal(item.brain?.skillId, "research-report");
  assert.equal(item.brain?.retrievalResultCount, 6);
  assert.equal(item.brain?.dataGroundingLevel, "request_only");
  assert.equal(item.brain?.personalizationScope, "none");
  assert.equal(item.brain?.responseLanguage, "tr");
  assert.equal(item.brain?.evidenceSufficiency, "weak");
  assert.equal(item.brain?.dataConfidence, "low");
  assert.deepEqual(item.brain?.dataQualityWarnings, ["insufficient_external_evidence"]);
  assert.equal(item.brain?.responseBudgetState, "normal");
  assert.equal(item.brain?.responseBudgetReason, "standard");
  assert.equal(item.brain?.contextPacketCount, 5);
  assert.deepEqual(item.brain?.contextPacketKinds, ["health_context", "calendar_context"]);
  assert.equal(item.brain?.healthContextUsed, true);
});

test("extractTaskRouteDecision round-trips the richer taskRoute metadata", () => {
  const routeDecision = {
    route: "server_brain",
    taskRoute: {
      target: "hybrid",
      operationalRoute: "server_brain",
      executionPlan: ["mobile_local", "server_brain"],
      reason: "Belge önce mobilde hazırlanıp sonra beyin tarafında çözülebilir.",
      needsDesktop: false,
      needsPrivateDesktopData: false,
      needsUserApproval: false,
      requiredCapabilities: ["document_parse", "transform_chunks", "summarize", "reason"],
    },
    mode: "chat",
    intent: "normal_chat",
    confidence: 0.98,
    privacyClass: "public_text",
    privacyLevel: "low",
    requiresApproval: false,
    requiredRuntime: "server",
    shouldAskClarification: false,
    failClosedReason: null,
    selectedWorkload: "mobile_chat_balanced",
    reason: "Belge özetleme",
    capabilities: ["document_read"],
  };
  const item = shapeTaskFeedItem({
    id: "task-route",
    title: "Route",
    status: "completed",
    targetDeviceId: "shared-brain-device",
    queuePosition: 0,
    runtimeConnectionId: null,
    dispatchLeaseId: null,
    dispatchLeaseIssuedAt: null,
    dispatchLeaseExpiresAt: null,
    dispatchAckAt: null,
    requestedCapabilities: [],
    payload: {
      metadata: {
        routeDecision,
      },
    },
    summary: null,
    error: null,
    approvalRequest: null,
    createdAt: new Date("2030-01-01T00:00:00.000Z"),
    updatedAt: new Date("2030-01-01T00:00:00.000Z"),
  });

  assert.deepEqual(item.routeDecision?.taskRoute, routeDecision.taskRoute);
  assert.deepEqual(extractTaskRouteDecision({
    metadata: {
      routeDecision,
    },
  })?.taskRoute, routeDecision.taskRoute);
});

test("shapeTaskArtifact adds viewer hints and compact previews", () => {
  const longText = "Bu belge özeti çok uzundur. ".repeat(20).trim();
  const artifact = shapeTaskArtifact({
    id: "artifact-1",
    taskId: "task-1",
    kind: "file",
    name: "Product Brief.pdf",
    contentType: "application/pdf",
    storageKey: "elyan://artifacts/artifact-1",
    textContent: longText,
    payload: {
      previewText: "fallback preview",
    },
    metadata: {
      sourceType: "task_artifact",
    },
    createdAt: new Date("2030-01-01T00:00:00.000Z"),
  });

  assert.equal(artifact.viewerHint, "pdf");
  assert.equal(artifact.contentFamily, "document");
  assert.equal(artifact.downloadable, true);
  assert.equal(artifact.downloadName, "Product Brief.pdf");
  assert.equal(artifact.previewText?.endsWith("…"), true);
  assert.equal((artifact.previewText ?? "").length <= 320, true);
});

test("sanitizePublicInferenceValue removes nested provider and model metadata", () => {
  const sanitized = sanitizePublicInferenceValue({
    text: "Yanıt",
    provider: "private-provider",
    model: "private-model",
    renderRecipe: {
      format: "pdf",
    },
    nested: {
      fallbackState: "private-fallback",
      runtimeProvider: "private-runtime",
      latencyMs: 42,
    },
    visionBlock: {
      type: "vision",
      summary_for_answer: "internal visual reference",
    },
  });

  assert.deepEqual(sanitized, {
    text: "Yanıt",
    renderRecipe: {
      format: "pdf",
    },
    nested: {
      latencyMs: 42,
    },
  });
});

test("sanitizePublicInferenceValue removes compound provider and engine keys", () => {
  const sanitized = sanitizePublicInferenceValue({
    text: "Görselde bir uyarı var.",
    toolRefinementProvider: "gemini",
    toolRefinementModel: "private-vision-model",
    secondaryVisionEngine: "groq",
    selectedProfile: "vision_reasoning",
    answerSource: "model",
    modelCallCount: 2,
    reasoningPasses: 2,
    fallbackUsed: true,
    cloudVisionOptIn: true,
    visionEscalationReasons: ["secondary_unavailable"],
    agentEngineVersion: "internal-v2",
    nested: {
      selectedProvider: "gemini",
      fallbackModel: "private-model",
      latencyMs: 42,
    },
  });
  assert.deepEqual(sanitized, {
    text: "Görselde bir uyarı var.",
    nested: { latencyMs: 42 },
  });
});

test("sanitizePublicTaskEventPayload removes compound provider keys from SSE data", () => {
  const sanitized = sanitizePublicTaskEventPayload({
    status: "completed",
    task: {
      summary: "Hazır",
      visionProvider: "gemini",
      servingModel: "private-model",
    },
    secondaryEngine: "groq",
    selectedProfile: "vision_reasoning",
    answerSource: "model",
    fallbackUsed: true,
    cloudVisionOptIn: true,
    visionEscalationUsed: true,
  });
  assert.deepEqual(sanitized, {
    status: "completed",
    task: { summary: "Hazır" },
  });
});

test("sanitizePublicInferenceValue bounds public JSON and strips internal variants", () => {
  const sanitized = sanitizePublicInferenceValue({
    text: "x".repeat(9_000),
    createdAt: new Date("2030-01-01T00:00:00.000Z"),
    selected_workload: "planning",
    toolTrace: { raw: "secret" },
    blocks: Array.from({ length: 250 }, (_, index) => ({ type: "text", markdown: `row-${index}` })),
    public: {
      ok: true,
      nested: {
        value: "kept",
      },
    },
  }) as Record<string, unknown>;

  assert.equal(String(sanitized.text).endsWith("…"), true);
  assert.equal(sanitized.createdAt, "2030-01-01T00:00:00.000Z");
  assert.equal("selected_workload" in sanitized, false);
  assert.equal("toolTrace" in sanitized, false);
  assert.equal((sanitized.blocks as unknown[]).length, 200);
  assert.deepEqual(sanitized.public, {
    ok: true,
    nested: {
      value: "kept",
    },
  });
});

test("sanitizePublicTaskEventPayload preserves public routing contract while stripping internals", () => {
  const sanitized = sanitizePublicTaskEventPayload({
    task: {
      id: "task-1",
      routeDecision: {
        route: "server_brain",
        selectedWorkload: "mobile_chat_fast",
      },
      provider: "private-provider",
      toolTrace: "secret",
    },
    artifacts: Array.from({ length: 250 }, (_, index) => ({
      id: `artifact-${index}`,
      previewText: "p".repeat(9_000),
      rawProviderResponse: "secret",
    })),
    reasoning: "hidden",
  }) as Record<string, unknown>;

  const task = sanitized.task as Record<string, unknown>;
  const routeDecision = task.routeDecision as Record<string, unknown>;
  assert.equal(routeDecision.route, "server_brain");
  assert.equal(routeDecision.selectedWorkload, "mobile_chat_fast");
  assert.equal("provider" in task, false);
  assert.equal("toolTrace" in task, false);
  assert.equal("reasoning" in sanitized, false);
  const artifacts = sanitized.artifacts as Array<Record<string, unknown>>;
  assert.equal(artifacts.length, 200);
  assert.equal(String(artifacts[0]?.previewText).endsWith("…"), true);
  assert.equal("rawProviderResponse" in artifacts[0]!, false);
});
