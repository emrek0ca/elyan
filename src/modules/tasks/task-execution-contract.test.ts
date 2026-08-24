import assert from "node:assert/strict";
import test from "node:test";
import type {
  CommandRouteDecision,
  CommandTurnContract,
} from "../routing-policy/service.js";
import {
  buildTaskExecutionContract,
  syncTaskExecutionContractWithWorkOrder,
  validateTaskExecutionContract,
} from "./task-execution-contract.js";
import type { DesktopWorkOrder } from "./desktop-work-order.js";

function route(overrides: Partial<CommandRouteDecision> = {}): CommandRouteDecision {
  return {
    route: "desktop_runtime",
    mode: "executable_task",
    capabilities: ["sys_info"],
    privacyClass: "local_private",
    requiresApproval: false,
    reason: "test",
    intent: "desktop_cowork",
    confidence: 0.92,
    requiredRuntime: "desktop",
    privacyLevel: "high",
    shouldAskClarification: false,
    failClosedReason: null,
    selectedWorkload: "desktop_handoff",
    ...overrides,
  };
}

function turn(overrides: Partial<CommandTurnContract> = {}): CommandTurnContract {
  return {
    version: "elyan.turn_contract.v1",
    normalizedIntent: "desktop_cowork",
    primaryIntent: "computer",
    secondaryIntents: [],
    intentClassification: {} as CommandTurnContract["intentClassification"],
    selectedWorkload: "desktop_handoff",
    planIntent: false,
    outputContract: {
      operation: "answer",
      sourceReference: "current_prompt",
      outputKind: "chat_reply",
      outputFormat: null,
      pageCount: null,
      requiresArtifact: false,
      confidence: 0.8,
      reasons: ["operation:answer"],
    },
    understandingEnvelope: {
      source: "typed_extractor",
      confidence: 0.92,
      intent: { name: "computer", action: "reply" },
    },
    routeDecision: {
      route: "desktop_runtime",
      mode: "executable_task",
      intent: "desktop_cowork",
      selectedWorkload: "desktop_handoff",
      requiredRuntime: "desktop",
      requiresApproval: false,
    },
    ...overrides,
  };
}

test("buildTaskExecutionContract produces one bounded canonical snapshot", () => {
  const contract = buildTaskExecutionContract({
    taskId: "task-1",
    turnId: "turn-1",
    message: "Sistem bilgilerini getir",
    routeDecision: route(),
    turnContract: turn(),
  });

  assert.equal(contract.contract, "elyan.task_execution_contract.v2");
  assert.equal(contract.taskId, "task-1");
  assert.equal(contract.execution.selectedTools[0]?.id, "sys_info");
  assert.equal(contract.execution.maxSteps, 16);
  assert.equal(contract.execution.mode, "dynamic");
  assert.equal(contract.execution.allowedCapabilities.includes("sys_info"), true);
  assert.match(contract.binding.hash, /^[a-f0-9]{64}$/u);
  assert.equal(contract.privacy.class, "local_private");
  assert.equal(validateTaskExecutionContract(contract).ok, true);
});

test("explicit Turkish research save compiles to a two-tool desktop grant contract", () => {
  const message = "Kedilerin yaşamı hakkında araştırma yapıp masaüstüne kaydet";
  const workOrder: DesktopWorkOrder = {
    schema: "elyan.desktop_work_order.v1",
    source: "mobile_chat_dispatch",
    goal: {
      kind: "document_task",
      summary: message,
      language: "tr",
      sourceTextHash: "abcdef1234567890abcdef12",
    },
    semanticGoal: {
      contract: "elyan.semantic_task_contract.v1",
      objective: message,
      constraints: [],
      successCriteria: ["DOCX artifact masaüstünde oluşturuldu."],
      requiredCapabilities: ["web_research", "document_write"],
      forbiddenCapabilities: ["desktop_operator.run"],
      ambiguityPolicy: "safe_assumption",
      risk: { localPrivate: true, sideEffect: true, irreversible: false },
    },
    entities: [],
    constraints: [],
    workType: "data_workflow",
    requiredCapabilities: ["web_research", "document_write"],
    materializedCapabilityScope: ["web_research", "document_write"],
    requiresApproval: true,
    approvalCapabilities: ["document_write"],
    capabilityAuthorization: {
      source: "semantic_router",
      allowPrivateRead: false,
      sideEffectsRequireApproval: true,
    },
    localContextNeeded: ["filesystem"],
    resourceScope: {
      contract: "elyan.resource_scope.v1",
      readRoots: ["workspace"],
      writeRoots: ["~/Desktop"],
    },
    expectedOutputs: [
      { kind: "artifact", format: "docx", required: true },
      { kind: "file_update", format: "state_readback", required: true },
    ],
    verificationRules: [
      { id: "artifact", description: "DOCX var.", evidence: "artifact" },
      { id: "readback", description: "Dosya okunabildi.", evidence: "state_readback" },
    ],
    execution: {
      mode: "cowork_dispatch",
      approvalPolicy: "single_full_access_surface",
      maxSteps: 16,
    },
    planPreview: {
      summary: message,
      privacyClass: "side_effect",
      contract: "elyan.compiled_plan.v1",
      planSource: "server_materialized",
      materializationSource: "semantic_compiler",
      planPreparation: { status: "ready", outcome: "materialized" },
      steps: [
        {
          id: "research",
          capability: "web_research",
          description: "Kedilerin yaşamını araştır.",
          args: { query: "kedilerin yaşamı" },
        },
        {
          id: "write",
          capability: "document_write",
          description: "Araştırmayı DOCX olarak yaz.",
          args: {
            title: "Kedilerin Yaşamı",
            sourceContext: "{{steps.research.output}}",
            outputPath: "~/Desktop/Kedilerin Yaşamı.docx",
          },
          dependsOn: ["research"],
          resourceScope: ["~/Desktop"],
        },
      ],
    },
  };
  const contract = buildTaskExecutionContract({
    taskId: "task-cats",
    turnId: "turn-cats",
    message,
    routeDecision: route({
      capabilities: ["web_research", "document_write", "desktop_operator.run"],
      privacyClass: "side_effect",
      requiresApproval: true,
    }),
    turnContract: turn({
      outputContract: {
        operation: "analyze_then_export",
        sourceReference: "current_prompt",
        outputKind: "document",
        outputFormat: "docx",
        pageCount: null,
        requiresArtifact: true,
        confidence: 0.96,
        reasons: ["explicit_local_save"],
      },
    }),
    workOrder,
  });

  assert.equal(contract.execution.mode, "compiled");
  assert.deepEqual(contract.execution.allowedCapabilities, [
    "web_research",
    "document_write",
  ]);
  assert.deepEqual(
    contract.execution.steps.map((step) => step.capability),
    ["web_research", "document_write"],
  );
  assert.equal(
    contract.execution.selectedTools.some(
      (tool) => tool.id === "desktop_operator.run",
    ),
    false,
  );
  assert.deepEqual(contract.output, {
    operation: "analyze_then_export",
    kind: "document",
    format: "docx",
    target: "desktop",
    artifactRequired: true,
  });
  assert.equal(contract.approval.required, false);
  assert.deepEqual(contract.approval.grants, [
    {
      id: "grant_task-cats_1",
      taskId: "task-cats",
      turnId: "turn-cats",
      capability: "document_write",
      effect: "write",
      resourceScope: ["~/Desktop"],
      source: "explicit_user_request",
    },
  ]);
  assert.equal(contract.verification.artifactRequired, true);
  assert.equal(contract.verification.stateReadbackRequired, true);
  assert.equal(validateTaskExecutionContract(contract).ok, true);
});

test("contract validation rejects unknown tools and skills", () => {
  const result = validateTaskExecutionContract({
    contract: "elyan.task_execution_contract.v1",
    taskId: "task-1",
    turnId: "turn-1",
    planRevision: 1,
    intent: { normalized: "desktop_cowork", primary: "computer", secondary: [] },
    goal: {
      objective: "Bir görevi tamamla",
      constraints: [],
      successCriteria: [],
      ambiguityPolicy: "safe_assumption",
    },
    execution: {
      workload: "desktop_handoff",
      requiredRuntime: "desktop",
      selectedTools: [{ id: "invented_tool", args: {} }],
      selectedSkills: [{ id: "invented.skill", args: {} }],
      steps: [],
      maxSteps: 1,
    },
    approval: { required: false, scope: [], separateApprovalFor: [], ttlSeconds: 900 },
    privacy: { class: "local_private", localContextRequired: true, maySendPrivateContextToServer: false },
    desktopWorkOrder: null,
  });

  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.errors.some((error) => error.code === "TASK_CONTRACT_UNKNOWN_TOOL"), true);
    assert.equal(result.errors.some((error) => error.code === "TASK_CONTRACT_UNKNOWN_SKILL"), true);
  }
});

test("server-only capabilities cannot become desktop execution steps", () => {
  const contract = buildTaskExecutionContract({
    taskId: "task-1",
    turnId: "turn-1",
    message: "Bir belge oluştur",
    routeDecision: route({ capabilities: ["document_create"], requiredRuntime: "desktop" }),
    turnContract: turn(),
    workOrder: {
      schema: "elyan.desktop_work_order.v1",
      source: "backend_task_route",
      goal: { kind: "desktop", summary: "Bir belge oluştur", language: "tr", sourceTextHash: "abcdef1234567890abcdef12" },
      entities: [],
      constraints: [],
      requiredCapabilities: ["document_create"],
      localContextNeeded: [],
      expectedOutputs: [{ kind: "chat_result", format: "text", required: true }],
      verificationRules: [{ id: "result", description: "Sonuç", evidence: "tool_result" }],
      execution: { mode: "cowork_dispatch", approvalPolicy: "capability_policy", maxSteps: 1 },
      planPreview: {
        summary: "Bir belge oluştur",
        privacyClass: "local_private",
        contract: "elyan.compiled_plan.v1",
        planSource: "deterministic_registry",
        steps: [{ id: "create", capability: "document_create", description: "Bir belge oluştur", args: {} }],
      },
    },
  });
  const result = validateTaskExecutionContract(contract);
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.errors.some((error) => error.code === "TASK_CONTRACT_NON_LOCAL_STEP_CAPABILITY"), true);
  }
});

test("older plan revisions are rejected at the contract boundary", () => {
  const contract = buildTaskExecutionContract({
    taskId: "task-1",
    turnId: "turn-1",
    routeDecision: route(),
    turnContract: turn(),
    planRevision: 1,
  });

  const result = validateTaskExecutionContract(contract, {
    taskId: "task-1",
    planRevision: 2,
  });
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.errors[0]?.code, "TASK_CONTRACT_PLAN_REVISION_STALE");
  }
});

test("materialized work order refreshes the canonical contract steps and tools", () => {
  const contract = buildTaskExecutionContract({
    taskId: "task-1",
    turnId: "turn-1",
    message: "Chrome'u kapat",
    routeDecision: route({ capabilities: ["close_app"] }),
    turnContract: turn({ primaryIntent: "computer" }),
    workOrder: {
      schema: "elyan.desktop_work_order.v1",
      source: "backend_task_route",
      goal: { kind: "desktop", summary: "Chrome'u kapat", language: "tr", sourceTextHash: "abcdef1234567890abcdef12" },
      entities: [],
      constraints: [],
      requiredCapabilities: ["close_app"],
      localContextNeeded: [],
      expectedOutputs: [{ kind: "system_state", format: "app_closed", required: true }],
      verificationRules: [{ id: "closed", description: "Uygulama kapalı", evidence: "state_readback" }],
      execution: { mode: "cowork_dispatch", approvalPolicy: "capability_policy", maxSteps: 4 },
      planPreview: { summary: "Chrome kapanacak", privacyClass: "side_effect", steps: [] },
    },
  });
  const workOrder = {
    schema: "elyan.desktop_work_order.v1" as const,
    source: "backend_task_route" as const,
    goal: { kind: "desktop", summary: "Chrome'u kapat", language: "tr" as const, sourceTextHash: "abcdef1234567890abcdef12" },
    entities: [],
    constraints: [],
    requiredCapabilities: ["close_app"],
    localContextNeeded: [],
    expectedOutputs: [{ kind: "system_state" as const, format: "app_closed", required: true }],
    verificationRules: [{ id: "closed", description: "Uygulama kapalı", evidence: "state_readback" as const }],
    execution: { mode: "cowork_dispatch" as const, approvalPolicy: "capability_policy" as const, maxSteps: 4 },
    planPreview: {
      summary: "Chrome kapanacak",
      privacyClass: "side_effect" as const,
      steps: [{
        id: "close_chrome",
        capability: "close_app",
        description: "Chrome'u kapat",
        args: { app_name: "Google Chrome" },
        resourceScope: ["app:chrome"],
        forEach: "steps.targets",
      }],
      executionSteps: [{
        stepId: "close_chrome",
        device: "desktop" as const,
        capability: "close_app",
        input: { app_name: "Google Chrome" },
        resourceScope: ["app:chrome"],
        forEach: "steps.targets",
      }],
      executionPlacement: {
        mode: "bound" as const,
        resolvedAt: "2030-01-01T00:00:00.000Z",
        summary: {
          total: 1,
          resolved: 1,
          unresolved: 0,
          offline: 0,
          byDevice: { desktop: 1 },
        },
        unresolvedCapabilities: [],
      },
    },
  };
  const synced = syncTaskExecutionContractWithWorkOrder({ contract, workOrder });
  assert.ok(synced);
  assert.equal(contract.approval.required, true);
  assert.equal(contract.approval.scope.includes("close_app"), true);
  assert.equal(synced.execution.steps[0]?.capability, "close_app");
  assert.equal(synced.execution.steps[0]?.device, "desktop");
  assert.deepEqual(synced.execution.steps[0]?.args, { app_name: "Google Chrome" });
  assert.deepEqual(synced.execution.steps[0]?.resourceScope, ["app:chrome"]);
  assert.equal(synced.execution.steps[0]?.forEach, "steps.targets");
  assert.equal(synced.execution.selectedTools[0]?.reason, "server_plan_step");
  assert.equal(validateTaskExecutionContract(synced).ok, true);
});

test("desktop contract rejects an explicitly remote execution step", () => {
  const contract = buildTaskExecutionContract({
    taskId: "task-1",
    turnId: "turn-1",
    routeDecision: route(),
    turnContract: turn(),
  });
  contract.execution.steps = [{
    id: "remote_step",
    device: "mobile",
    capability: "sys_info",
    args: {},
    dependsOn: [],
    resourceScope: [],
  }];

  const result = validateTaskExecutionContract(contract);

  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(
      result.errors.some((error) => error.code === "TASK_CONTRACT_REMOTE_STEP_DEVICE"),
      true,
    );
  }
});
