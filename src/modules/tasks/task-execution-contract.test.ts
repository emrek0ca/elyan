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
    outputContract: {} as CommandTurnContract["outputContract"],
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

  assert.equal(contract.contract, "elyan.task_execution_contract.v1");
  assert.equal(contract.taskId, "task-1");
  assert.equal(contract.execution.selectedTools[0]?.id, "sys_info");
  assert.equal(contract.execution.maxSteps, 16);
  assert.equal(contract.privacy.class, "local_private");
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
      steps: [{ id: "close_chrome", capability: "close_app", description: "Chrome'u kapat", args: { app_name: "Google Chrome" } }],
      executionSteps: [{
        stepId: "close_chrome",
        device: "desktop" as const,
        capability: "close_app",
        input: { app_name: "Google Chrome" },
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
  assert.equal(synced.execution.steps[0]?.capability, "close_app");
  assert.equal(synced.execution.steps[0]?.device, "desktop");
  assert.deepEqual(synced.execution.steps[0]?.args, { app_name: "Google Chrome" });
  assert.equal(synced.execution.selectedTools[0]?.reason, "server_plan_step");
  assert.equal(validateTaskExecutionContract(synced).ok, true);
});
