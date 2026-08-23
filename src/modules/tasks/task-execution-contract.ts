import { z } from "zod";
import type { UnderstandingEnvelope } from "../../core/understanding/types.js";
import type { SharedBrainWorkload } from "../brain/workloads.js";
import type {
  CommandRouteDecision,
  CommandTurnContract,
} from "../routing-policy/service.js";
import {
  DESKTOP_CAPABILITY_MANIFEST,
  type DesktopCapabilityManifestEntry,
} from "./desktop-capability-manifest.js";
import {
  DESKTOP_SKILL_MANIFEST,
  type DesktopSkillManifestEntry,
} from "./desktop-skill-manifest.js";
import type {
  DesktopWorkOrder,
  DesktopWorkOrderStep,
} from "./desktop-work-order.js";
import type { ExecutionStep } from "./execution-step.js";

/**
 * Tek görev otoritesi.
 *
 * Route/task/inference/desktop katmanları bu snapshot'ı tüketir; ham kullanıcı
 * metni tekrar sınıflandırmak için downstream katmanlara taşınmaz. Eski task
 * kayıtları için bu alan additive'tir ve contract yokluğu legacy adapter ile
 * desteklenmeye devam eder.
 */
export const TASK_EXECUTION_CONTRACT = "elyan.task_execution_contract.v1" as const;
export const TASK_EXECUTION_CONTRACT_VERSION = 1 as const;
export const TASK_EXECUTION_MAX_STEPS = 16;

const SERVER_CAPABILITY_IDS = new Set([
  "sys_info",
  "retrieve_context",
  "run_skill",
  "browser_search",
  "document_create",
  "image_generate",
  "desktop_operator_run",
  "chat.reply",
  "memory.query",
  "goal.update",
  "desktop.runtime",
  "filesystem.write",
]);

const capabilityManifestById = new Map(
  DESKTOP_CAPABILITY_MANIFEST.map((entry) => [entry.name, entry] as const),
);
const skillManifestById = new Map(
  DESKTOP_SKILL_MANIFEST.map((entry) => [entry.id, entry] as const),
);

export const taskExecutionToolSchema = z.object({
  id: z.string().min(1).max(120),
  args: z.record(z.string(), z.unknown()).default({}),
  reason: z.string().max(240).optional(),
  confidence: z.number().min(0).max(1).optional(),
});

export const taskExecutionSkillSchema = z.object({
  id: z.string().min(1).max(160),
  args: z.record(z.string(), z.unknown()).default({}),
  confidence: z.number().min(0).max(1).optional(),
});

export const taskExecutionStepSchema = z.object({
  id: z.string().min(1).max(100),
  device: z.enum(["desktop", "mobile", "control-plane"]).optional(),
  capability: z.string().min(1).max(120),
  args: z.record(z.string(), z.unknown()).default({}),
  dependsOn: z.array(z.string().min(1).max(100)).max(TASK_EXECUTION_MAX_STEPS).default([]),
  resourceScope: z.array(z.string().min(1).max(160)).max(16).default([]),
  forEach: z.string().max(240).optional(),
});

export const taskExecutionContractSchema = z.object({
  contract: z.literal(TASK_EXECUTION_CONTRACT),
  taskId: z.string().min(1).max(160),
  goalId: z.string().max(160).nullable().default(null),
  turnId: z.string().min(1).max(160),
  planRevision: z.number().int().positive(),
  intent: z.object({
    normalized: z.string().min(1).max(120),
    primary: z.string().min(1).max(120),
    secondary: z.array(z.string().min(1).max(120)).max(12).default([]),
  }),
  goal: z.object({
    objective: z.string().min(1).max(1_000),
    constraints: z.array(z.string().max(240)).max(48).default([]),
    successCriteria: z.array(z.string().max(300)).max(16).default([]),
    ambiguityPolicy: z.enum(["ask", "safe_assumption", "fail_closed"]),
  }),
  execution: z.object({
    workload: z.string().min(1).max(100),
    requiredRuntime: z.enum(["server", "desktop", "both"]),
    selectedTools: z.array(taskExecutionToolSchema).max(32),
    selectedSkills: z.array(taskExecutionSkillSchema).max(16),
    steps: z.array(taskExecutionStepSchema).max(TASK_EXECUTION_MAX_STEPS),
    maxSteps: z.number().int().min(1).max(TASK_EXECUTION_MAX_STEPS),
  }),
  approval: z.object({
    required: z.boolean(),
    scope: z.array(z.string().max(120)).max(32).default([]),
    separateApprovalFor: z.array(z.string().max(120)).max(32).default([]),
    ttlSeconds: z.number().int().min(1).max(86_400),
  }),
  privacy: z.object({
    class: z.enum(["public", "local_private", "side_effect"]),
    localContextRequired: z.boolean(),
    maySendPrivateContextToServer: z.boolean(),
  }),
  desktopWorkOrder: z.record(z.string(), z.unknown()).nullable().default(null),
  selectionAudit: z.object({
    rejectedToolIds: z.array(z.string().max(120)).max(16).default([]),
    rejectedSkillIds: z.array(z.string().max(160)).max(16).default([]),
  }).default({}),
}).passthrough();

export type TaskExecutionTool = z.output<typeof taskExecutionToolSchema>;
export type TaskExecutionSkill = z.output<typeof taskExecutionSkillSchema>;
export type TaskExecutionStep = z.output<typeof taskExecutionStepSchema>;
export type TaskExecutionContract = z.output<typeof taskExecutionContractSchema>;

export type TaskExecutionContractValidation =
  | { ok: true; value: TaskExecutionContract; errors: [] }
  | { ok: false; value: null; errors: Array<{ code: string; path: string; message: string }> };

export function knownTaskCapabilityIds(): Set<string> {
  return new Set([...capabilityManifestById.keys(), ...SERVER_CAPABILITY_IDS]);
}

export function knownTaskLocalCapabilityIds(): Set<string> {
  return new Set(capabilityManifestById.keys());
}

export function knownTaskSkillIds(): Set<string> {
  return new Set(skillManifestById.keys());
}

function compact(value: unknown, max = 300): string {
  const text = typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}

function uniqueStrings(values: readonly unknown[], max: number): string[] {
  const output: string[] = [];
  for (const value of values) {
    const normalized = compact(value, 240);
    if (normalized && !output.includes(normalized)) output.push(normalized);
    if (output.length >= max) break;
  }
  return output;
}

function recordOf(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function knownCapability(id: string): DesktopCapabilityManifestEntry | null {
  return capabilityManifestById.get(id) ?? null;
}

function knownSkill(id: string): DesktopSkillManifestEntry | null {
  return skillManifestById.get(id) ?? null;
}

function stepSnapshot(step: DesktopWorkOrderStep | ExecutionStep): TaskExecutionStep {
  const executionStep = "stepId" in step;
  return {
    id: compact(executionStep ? step.stepId : step.id, 100),
    ...(executionStep && step.device ? { device: step.device } : {}),
    capability: compact(step.capability, 120),
    args: recordOf(executionStep ? step.input : step.args) ?? {},
    dependsOn: uniqueStrings(step.dependsOn ?? [], TASK_EXECUTION_MAX_STEPS),
    resourceScope: uniqueStrings(step.resourceScope ?? [], 16),
    ...(step.forEach ? { forEach: compact(step.forEach, 240) } : {}),
  };
}

function executionStepsForWorkOrder(
  workOrder: DesktopWorkOrder | null | undefined,
): Array<DesktopWorkOrderStep | ExecutionStep> {
  const boundSteps = workOrder?.planPreview?.executionSteps;
  const placementMode = workOrder?.planPreview?.executionPlacement?.mode;
  return placementMode === "bound" && boundSteps && boundSteps.length > 0
    ? boundSteps
    : workOrder?.planPreview?.steps ?? [];
}

function safeWorkOrderSnapshot(
  workOrder: DesktopWorkOrder | null | undefined,
): Record<string, unknown> | null {
  if (!workOrder) return null;
  const snapshot = { ...(workOrder as unknown as Record<string, unknown>) };
  // Never allow a future nested copy to recursively grow the contract.
  delete snapshot.taskExecutionContract;
  delete snapshot.contract;
  return snapshot;
}

function selectedToolsForInput(input: {
  routeDecision: CommandRouteDecision;
  workOrder?: DesktopWorkOrder | null;
  confidence: number;
}): { selectedTools: TaskExecutionTool[]; rejectedToolIds: string[] } {
  const selectedTools: TaskExecutionTool[] = [];
  const rejectedToolIds: string[] = [];
  const seen = new Set<string>();
  const steps = executionStepsForWorkOrder(input.workOrder);
  const candidates = [
    ...steps.map((step) => ({
      id: step.capability,
      args: "stepId" in step ? step.input : step.args,
      reason: "server_plan_step",
    })),
    ...input.routeDecision.capabilities.map((id) => ({ id, args: {}, reason: "route_capability" })),
  ];
  for (const candidate of candidates) {
    const id = compact(candidate.id, 120);
    if (!id || seen.has(id)) continue;
    seen.add(id);
    if (!knownCapability(id) && !SERVER_CAPABILITY_IDS.has(id)) {
      rejectedToolIds.push(id);
      continue;
    }
    selectedTools.push({
      id,
      args: recordOf(candidate.args) ?? {},
      reason: candidate.reason,
      confidence: Math.max(0, Math.min(1, input.confidence)),
    });
  }
  return { selectedTools, rejectedToolIds: rejectedToolIds.slice(0, 16) };
}

function selectedSkillsForInput(
  envelope: UnderstandingEnvelope | null | undefined,
  confidence: number,
): { selectedSkills: TaskExecutionSkill[]; rejectedSkillIds: string[] } {
  const selected = envelope?.tool_skill_decision?.selected;
  if (!selected) return { selectedSkills: [], rejectedSkillIds: [] };
  const id = compact(selected, 160);
  const skill = knownSkill(id);
  if (!skill) {
    // A capability name in this legacy field is not promoted to a skill. It is
    // handled by the capability/step path instead of being silently invented.
    return { selectedSkills: [], rejectedSkillIds: [id] };
  }
  return {
    selectedSkills: [{ id: skill.id, args: {}, confidence: Math.max(0, Math.min(1, confidence)) }],
    rejectedSkillIds: [],
  };
}

function deriveGoal(input: {
  message?: string;
  workOrder?: DesktopWorkOrder | null;
  envelope?: UnderstandingEnvelope | null;
}): TaskExecutionContract["goal"] {
  const semanticGoal = input.workOrder?.semanticGoal;
  const objective = compact(
    semanticGoal?.objective || input.envelope?.intent.topic || input.workOrder?.goal.summary || input.message,
    1_000,
  ) || "Görevi güvenli şekilde tamamla";
  const constraints = uniqueStrings([
    ...(semanticGoal?.constraints ?? []),
    ...(input.workOrder?.constraints ?? []),
    ...(input.envelope?.constraints ?? []).map((item) =>
      typeof item.value === "string" ? item.value : "",
    ),
  ], 48);
  const successCriteria = uniqueStrings([
    ...(semanticGoal?.successCriteria ?? []),
    ...(input.envelope?.success_criteria ?? []).map((item) => item.description),
    ...(input.workOrder?.verificationRules ?? []).map((item) => item.description),
  ], 16);
  const ambiguity = input.envelope?.ambiguity_policy?.action;
  const ambiguityPolicy =
    semanticGoal?.ambiguityPolicy ??
    (ambiguity === "ask_clarifying_question"
      ? "ask"
      : ambiguity === "fail_safe"
        ? "fail_closed"
        : "safe_assumption");
  return { objective, constraints, successCriteria, ambiguityPolicy };
}

export function buildTaskExecutionContract(input: {
  taskId: string;
  turnId: string;
  goalId?: string | null;
  message?: string;
  routeDecision: CommandRouteDecision;
  turnContract: CommandTurnContract;
  understandingEnvelope?: UnderstandingEnvelope | null;
  workOrder?: DesktopWorkOrder | null;
  planRevision?: number;
}): TaskExecutionContract {
  const workOrder = input.workOrder ?? null;
  const confidence = Math.max(0, Math.min(1, input.routeDecision.confidence));
  const toolSelection = selectedToolsForInput({
    routeDecision: input.routeDecision,
    workOrder,
    confidence,
  });
  const skillSelection = selectedSkillsForInput(
    input.understandingEnvelope,
    confidence,
  );
  const steps = executionStepsForWorkOrder(workOrder)
    .slice(0, TASK_EXECUTION_MAX_STEPS)
    .map(stepSnapshot);
  const risk = workOrder?.semanticGoal?.risk;
  const requiredRuntime = input.routeDecision.requiredRuntime;
  const privacyClass =
    risk?.sideEffect || input.routeDecision.privacyClass === "side_effect"
      ? "side_effect"
      : risk?.localPrivate || input.routeDecision.privacyClass === "local_private"
        ? "local_private"
        : "public";
  const approvalScope = uniqueStrings([
    ...toolSelection.selectedTools
      .filter((tool) => knownCapability(tool.id)?.requiresApproval === true)
      .map((tool) => tool.id),
    ...(workOrder?.capabilityAuthorization?.sideEffectsRequireApproval ? ["side_effect"] : []),
  ], 32);
  const selectedWorkload: SharedBrainWorkload | string = input.turnContract.selectedWorkload;
  return {
    contract: TASK_EXECUTION_CONTRACT,
    taskId: compact(input.taskId, 160),
    goalId: input.goalId ? compact(input.goalId, 160) : null,
    turnId: compact(input.turnId, 160),
    planRevision: Math.max(1, Math.floor(input.planRevision ?? 1)),
    intent: {
      normalized: input.turnContract.normalizedIntent,
      primary: input.turnContract.primaryIntent,
      secondary: uniqueStrings(input.turnContract.secondaryIntents, 12),
    },
    goal: deriveGoal({
      message: input.message,
      workOrder,
      envelope: input.understandingEnvelope,
    }),
    execution: {
      workload: selectedWorkload,
      requiredRuntime,
      selectedTools: toolSelection.selectedTools,
      selectedSkills: skillSelection.selectedSkills,
      steps,
      maxSteps: Math.min(
        TASK_EXECUTION_MAX_STEPS,
        Math.max(1, workOrder?.execution.maxSteps ?? TASK_EXECUTION_MAX_STEPS),
      ),
    },
    approval: {
      required: input.routeDecision.requiresApproval || approvalScope.length > 0,
      scope: approvalScope,
      separateApprovalFor: approvalScope,
      ttlSeconds: 900,
    },
    privacy: {
      class: privacyClass,
      localContextRequired:
        requiredRuntime !== "server" || (workOrder?.localContextNeeded.length ?? 0) > 0,
      maySendPrivateContextToServer:
        input.understandingEnvelope?.privacy_routing.maySendPrivateContextToServer === true,
    },
    desktopWorkOrder: safeWorkOrderSnapshot(workOrder),
    selectionAudit: {
      rejectedToolIds: toolSelection.rejectedToolIds,
      rejectedSkillIds: skillSelection.rejectedSkillIds,
    },
  };
}

/**
 * Plan hazırlığı task oluşturulduktan sonra tamamlanabildiği için ilk yazılan
 * contract boş `execution.steps` taşıyabilir. Materializer yeni WorkOrder'ı
 * persist ederken contract'ın da aynı step grafiğine bağlanması gerekir; aksi
 * halde task payload'ında iki farklı plan otoritesi kalır.
 */
export function syncTaskExecutionContractWithWorkOrder(input: {
  contract: unknown;
  workOrder: DesktopWorkOrder;
  planRevision?: number;
}): TaskExecutionContract | null {
  const parsed = taskExecutionContractSchema.safeParse(input.contract);
  if (!parsed.success) return null;

  const contract = parsed.data;
  const steps = executionStepsForWorkOrder(input.workOrder)
    .slice(0, TASK_EXECUTION_MAX_STEPS)
    .map(stepSnapshot);
  if (steps.length > contract.execution.maxSteps) return null;

  const stepCapabilities = new Set(steps.map((step) => step.capability));
  const existingToolsById = new Map(
    contract.execution.selectedTools.map((tool) => [tool.id, tool] as const),
  );
  const selectedTools: TaskExecutionTool[] = [];
  for (const step of steps) {
    const existing = existingToolsById.get(step.capability);
    selectedTools.push({
      id: step.capability,
      args: step.args,
      reason: "server_plan_step",
      ...(typeof existing?.confidence === "number"
        ? { confidence: existing.confidence }
        : {}),
    });
  }
  // Route-level tools that are not concrete desktop steps remain useful as
  // server-side context, but a materialized step always wins its args/order.
  for (const tool of contract.execution.selectedTools) {
    if (!stepCapabilities.has(tool.id)) selectedTools.push(tool);
  }

  const planRevision =
    input.planRevision == null
      ? contract.planRevision
      : Math.max(1, Math.floor(input.planRevision));
  return {
    ...contract,
    planRevision,
    execution: {
      ...contract.execution,
      selectedTools,
      steps,
    },
    desktopWorkOrder: safeWorkOrderSnapshot(input.workOrder),
  };
}

export function validateTaskExecutionContract(
  value: unknown,
  options: { taskId?: string; planRevision?: number } = {},
): TaskExecutionContractValidation {
  const parsed = taskExecutionContractSchema.safeParse(value);
  if (!parsed.success) {
    return {
      ok: false,
      value: null,
      errors: parsed.error.issues.map((issue) => ({
        code: "TASK_CONTRACT_SCHEMA_INVALID",
        path: issue.path.join("."),
        message: issue.message,
      })),
    };
  }
  const contract = parsed.data;
  const errors: Array<{ code: string; path: string; message: string }> = [];
  if (options.taskId && contract.taskId !== options.taskId) {
    errors.push({
      code: "TASK_CONTRACT_TASK_ID_MISMATCH",
      path: "taskId",
      message: "Task contract taskId ile yürütülen görev taskId eşleşmiyor.",
    });
  }
  if (
    options.planRevision != null &&
    contract.planRevision < Math.max(1, Math.floor(options.planRevision))
  ) {
    errors.push({
      code: "TASK_CONTRACT_PLAN_REVISION_STALE",
      path: "planRevision",
      message: "Task contract eski bir plan revision taşıyor.",
    });
  }
  const knownCapabilities = knownTaskCapabilityIds();
  const localCapabilities = knownTaskLocalCapabilityIds();
  const knownSkills = knownTaskSkillIds();
  for (const [index, tool] of contract.execution.selectedTools.entries()) {
    if (!knownCapabilities.has(tool.id)) {
      errors.push({
        code: "TASK_CONTRACT_UNKNOWN_TOOL",
        path: `execution.selectedTools.${index}.id`,
        message: "Capability registry dışında bir tool seçildi.",
      });
    }
  }
  for (const [index, skill] of contract.execution.selectedSkills.entries()) {
    if (!knownSkills.has(skill.id)) {
      errors.push({
        code: "TASK_CONTRACT_UNKNOWN_SKILL",
        path: `execution.selectedSkills.${index}.id`,
        message: "Skill registry dışında bir skill seçildi.",
      });
    }
  }
  const stepIds = new Set<string>();
  for (const [index, step] of contract.execution.steps.entries()) {
    if (stepIds.has(step.id)) {
      errors.push({
        code: "TASK_CONTRACT_DUPLICATE_STEP",
        path: `execution.steps.${index}.id`,
        message: "Plan step id tekrarlı.",
      });
    }
    stepIds.add(step.id);
    if (!localCapabilities.has(step.capability)) {
      errors.push({
        code: knownCapabilities.has(step.capability)
          ? "TASK_CONTRACT_NON_LOCAL_STEP_CAPABILITY"
          : "TASK_CONTRACT_UNKNOWN_STEP_CAPABILITY",
        path: `execution.steps.${index}.capability`,
        message: knownCapabilities.has(step.capability)
          ? "Server-only capability desktop plan step'i olarak çalıştırılamaz."
          : "Plan step capability registry dışında.",
      });
    }
  }
  if (contract.execution.steps.length > contract.execution.maxSteps) {
    errors.push({
      code: "TASK_CONTRACT_STEP_BUDGET_EXCEEDED",
      path: "execution.steps",
      message: "Plan step sayısı maxSteps sınırını aşıyor.",
    });
  }
  return errors.length > 0
    ? { ok: false, value: null, errors }
    : { ok: true, value: contract, errors: [] };
}

export function readTaskExecutionContract(value: unknown): TaskExecutionContract | null {
  const result = validateTaskExecutionContract(value);
  return result.ok ? result.value : null;
}
