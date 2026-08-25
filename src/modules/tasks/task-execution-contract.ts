import { z } from "zod";
import { createHash } from "node:crypto";
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
import { collectStepLocalPaths, resolveOutputTarget } from "./output-target.js";
import {
  ELEVATED_RISK_ARGUMENT_PATTERN,
  GENERIC_EXECUTOR_CAPABILITY_PATTERN,
  SEPARATE_APPROVAL_CAPABILITY_PATTERN,
} from "./capability-risk.js";

/**
 * Tek görev otoritesi.
 *
 * Route/task/inference/desktop katmanları bu snapshot'ı tüketir; ham kullanıcı
 * metni tekrar sınıflandırmak için downstream katmanlara taşınmaz. Eski task
 * kayıtları için bu alan additive'tir ve contract yokluğu legacy adapter ile
 * desteklenmeye devam eder.
 */
export const TASK_EXECUTION_CONTRACT_V1 = "elyan.task_execution_contract.v1" as const;
export const TASK_EXECUTION_CONTRACT = "elyan.task_execution_contract.v2" as const;
export const TASK_EXECUTION_CONTRACT_VERSION = 2 as const;
export const TASK_EXECUTION_MAX_STEPS = 16;
export const TASK_EXECUTION_DIRECT_TOOL_LIMIT = 12;
export const TASK_EXECUTION_DYNAMIC_MAX_STEPS = 12;

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

const taskExecutionContractV1Schema = z.object({
  contract: z.literal(TASK_EXECUTION_CONTRACT_V1),
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

export const taskExecutionGrantSchema = z.object({
  id: z.string().min(1).max(160),
  taskId: z.string().min(1).max(160),
  turnId: z.string().min(1).max(160),
  capability: z.string().min(1).max(120),
  effect: z.enum(["read", "write", "control"]),
  resourceScope: z.array(z.string().min(1).max(240)).min(1).max(16),
  source: z.literal("explicit_user_request"),
  // ADDITIVE BAĞ. Derlenmiş görevde grant, çalıştırılacak ADIMA ve o adımın
  // hazırlanmış argümanlarının özetine bağlanır; böylece bir yetki, verildiği
  // adımdan başka bir çağrıya taşınamaz. Eski runtime'lar alanı yok sayar.
  stepId: z.string().min(1).max(100).optional(),
  argsHash: z.string().min(1).max(80).optional(),
  riskClass: z.enum(["low", "elevated"]).optional(),
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
  output: z.object({
    operation: z.enum([
      "answer",
      "create",
      "transform",
      "export",
      "edit",
      "analyze_then_export",
    ]),
    kind: z.enum(["chat_reply", "document", "table", "chart", "image", "svg"]),
    format: z.string().min(1).max(40).nullable(),
    target: z.enum(["chat", "artifact", "desktop"]),
    artifactRequired: z.boolean(),
  }),
  execution: z.object({
    mode: z.enum(["compiled", "dynamic"]),
    workload: z.string().min(1).max(100),
    requiredRuntime: z.enum(["server", "desktop", "both"]),
    allowedCapabilities: z.array(z.string().min(1).max(120)).max(96),
    selectedTools: z.array(taskExecutionToolSchema).max(32),
    selectedSkills: z.array(taskExecutionSkillSchema).max(16),
    steps: z.array(taskExecutionStepSchema).max(TASK_EXECUTION_MAX_STEPS),
    maxSteps: z.number().int().min(1).max(TASK_EXECUTION_MAX_STEPS),
  }),
  approval: z.object({
    required: z.boolean(),
    scope: z.array(z.string().max(120)).max(32).default([]),
    separateApprovalFor: z.array(z.string().max(120)).max(32).default([]),
    grants: z.array(taskExecutionGrantSchema).max(32).default([]),
    ttlSeconds: z.number().int().min(1).max(86_400),
  }),
  verification: z.object({
    artifactRequired: z.boolean(),
    stateReadbackRequired: z.boolean(),
    successPolicy: z.literal("all_required"),
    criteria: z.array(z.object({
      id: z.string().min(1).max(120),
      description: z.string().min(1).max(300),
      evidence: z.enum(["runtime_status", "tool_result", "artifact", "state_readback"]),
    })).max(16),
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
  binding: z.object({
    algorithm: z.literal("sha256"),
    hash: z.string().regex(/^[a-f0-9]{64}$/u),
  }),
}).passthrough();

export type TaskExecutionTool = z.output<typeof taskExecutionToolSchema>;
export type TaskExecutionSkill = z.output<typeof taskExecutionSkillSchema>;
export type TaskExecutionStep = z.output<typeof taskExecutionStepSchema>;
export type TaskExecutionGrant = z.output<typeof taskExecutionGrantSchema>;
export type TaskExecutionContract = z.output<typeof taskExecutionContractSchema>;

export type TaskExecutionContractValidation =
  | { ok: true; value: TaskExecutionContract; errors: [] }
  | { ok: false; value: null; errors: Array<{ code: string; path: string; message: string }> };

export function knownTaskCapabilityIds(): Set<string> {
  return new Set([
    ...capabilityManifestById.keys(),
    ...SERVER_CAPABILITY_IDS,
    ...mcpCapabilityIndex.keys(),
  ]);
}

export function knownTaskLocalCapabilityIds(): Set<string> {
  // MCP araçları YEREL değildir: masaüstü adım havuzuna girmezler, uzak
  // sunucuda çalışırlar. Bu ayrım korunmalı, yoksa bir MCP aracı masaüstü
  // yürütme adımı olarak planlanabilirdi.
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

function stableJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableJson(item)).join(",")}]`;
  }
  const record = recordOf(value);
  if (record) {
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableJson(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value ?? null);
}

function authoritySnapshot(
  contract: Omit<TaskExecutionContract, "binding">,
): Record<string, unknown> {
  return {
    contract: contract.contract,
    taskId: contract.taskId,
    goalId: contract.goalId,
    turnId: contract.turnId,
    planRevision: contract.planRevision,
    intent: contract.intent,
    goal: contract.goal,
    output: contract.output,
    execution: contract.execution,
    approval: contract.approval,
    verification: contract.verification,
    privacy: contract.privacy,
  };
}

export function taskExecutionContractHash(
  contract: Omit<TaskExecutionContract, "binding">,
): string {
  return createHash("sha256")
    .update(stableJson(authoritySnapshot(contract)), "utf8")
    .digest("hex");
}

function bindTaskExecutionContract(
  contract: Omit<TaskExecutionContract, "binding">,
): TaskExecutionContract {
  return {
    ...contract,
    binding: {
      algorithm: "sha256",
      hash: taskExecutionContractHash(contract),
    },
  } as TaskExecutionContract;
}

/**
 * TURA ÖZGÜ MCP CAPABILITY'LERİ.
 *
 * Capability manifesti derleme zamanında sabittir; kullanıcının bağladığı MCP
 * araçları orada olamaz. Bu yüzden `mcp:<sunucu>:<araç>` adları "bilinmeyen
 * araç" diye düşürülüyor ve MCP araçları generic `mcp_call_tool` altında
 * kalıyordu — dar yetki alamıyor, her çağrıda ayrı onay istiyorlardı.
 *
 * Harita tur başına kurulur ve manifestin YANINDA sorulur; manifest sabit
 * kalır. Kayıt, sunucunun beyanı değil backend'in fail-closed
 * sınıflandırmasıdır.
 */
let mcpCapabilityIndex = new Map<string, DesktopCapabilityManifestEntry>();

export function setMcpCapabilityIndex(
  index: Map<string, DesktopCapabilityManifestEntry>,
): void {
  mcpCapabilityIndex = index;
}

function knownCapability(id: string): DesktopCapabilityManifestEntry | null {
  return capabilityManifestById.get(id) ?? mcpCapabilityIndex.get(id) ?? null;
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

function isCompiledWorkOrder(
  workOrder: DesktopWorkOrder | null | undefined,
): boolean {
  const source = workOrder?.planPreview?.planSource;
  return (
    workOrder?.planPreview?.contract === "elyan.compiled_plan.v1" &&
    (source === "server_materialized" || source === "deterministic_registry")
  );
}

function outputSnapshot(input: {
  turnContract: CommandTurnContract;
  workOrder?: DesktopWorkOrder | null;
}): TaskExecutionContract["output"] {
  const contract = input.turnContract.outputContract;
  const scope = input.workOrder?.resourceScope as
    | { writeRoots?: string[]; desktopDeliveryRequested?: boolean }
    | undefined;
  return {
    operation: contract.operation,
    kind: contract.outputKind,
    format: contract.outputFormat,
    target: resolveOutputTarget({
      artifactRequired: contract.requiresArtifact,
      writeRoots: scope?.writeRoots ?? [],
      route: input.turnContract.routeDecision.route,
      desktopDeliveryRequested: scope?.desktopDeliveryRequested === true,
      stepLocalPaths: collectStepLocalPaths(input.workOrder),
    }),
    artifactRequired: contract.requiresArtifact,
  };
}

function allowedCapabilitiesForInput(input: {
  routeDecision: CommandRouteDecision;
  workOrder?: DesktopWorkOrder | null;
  selectedTools: TaskExecutionTool[];
  steps: TaskExecutionStep[];
}): string[] {
  const compiled = isCompiledWorkOrder(input.workOrder);
  return uniqueStrings([
    // Compiled graphs may carry their already-materialized capability scope.
    // Dynamic routes are different: route capabilities are discovery hints,
    // not an executable grant. Only the policy-filtered direct shortlist may
    // become the hard scope; tool_search remains confined to this same set.
    ...(compiled ? (input.workOrder?.requiredCapabilities ?? []) : []),
    ...(compiled ? (input.workOrder?.materializedCapabilityScope ?? []) : []),
    ...input.selectedTools.map((tool) => tool.id),
    ...input.steps.map((step) => step.capability),
  ], compiled ? 96 : TASK_EXECUTION_DIRECT_TOOL_LIMIT).filter((capability) =>
    knownTaskCapabilityIds().has(capability),
  );
}

const EXPLICIT_ARTIFACT_WRITE_CAPABILITIES = new Set([
  "document_write",
  "spreadsheet_write",
  "presentation_write",
  "canvas_write",
]);

function explicitArtifactWriteGrants(input: {
  taskId: string;
  turnId: string;
  output: TaskExecutionContract["output"];
  workOrder?: DesktopWorkOrder | null;
  allowedCapabilities: string[];
  steps?: TaskExecutionStep[];
}): TaskExecutionGrant[] {
  const writeRoots = uniqueStrings(
    input.workOrder?.resourceScope?.writeRoots ?? [],
    16,
  );
  if (
    !input.output.artifactRequired ||
    input.output.target !== "desktop" ||
    writeRoots.length === 0
  ) {
    return [];
  }
  return input.allowedCapabilities
    .filter((capability) => EXPLICIT_ARTIFACT_WRITE_CAPABILITIES.has(capability))
    // ÜZERİNE YAZMA BU YOLDAN DA GEÇEMEZ.
    //
    // Bu fonksiyon "kullanıcı açıkça dosya istedi" gerekçesiyle yazma yetkisi
    // üretir ve adımlara BAKMIYORDU. Güncelleme zinciri eklenince aynı
    // gerekçe `mode:"update"` adımını da yetkilendirmeye başladı — yani
    // ayrı onay kapısı sessizce atlandı. Adımı üzerine yazma olan capability
    // burada da yetki almaz.
    .filter((capability) => !overwritesCapability(capability, input.steps, input.workOrder))
    .slice(0, 8)
    .map((capability, index) => ({
      id: `grant_${compact(input.taskId, 48)}_${index + 1}`,
      taskId: compact(input.taskId, 160),
      turnId: compact(input.turnId, 160),
      capability,
      effect: "write" as const,
      resourceScope: writeRoots,
      source: "explicit_user_request" as const,
    }));
}

function stableGrantJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableGrantJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableGrantJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

function grantArgsHash(args: Record<string, unknown>): string {
  return createHash("sha256").update(stableGrantJson(args)).digest("hex").slice(0, 32);
}

/**
 * Bu adım var olan bir dosyanın ÜZERİNE mi yazıyor?
 *
 * Üzerine yazma geri alınamaz ve kullanıcının zaten sahip olduğu içeriği
 * yok edebilir; hiçbir koşulda önceden yetkilendirilmez.
 */
function isOverwriteStep(args: Record<string, unknown>): boolean {
  const mode = String(args?.mode ?? "").trim().toLowerCase();
  if (mode === "update" || mode === "overwrite" || mode === "replace") return true;
  return args?.overwrite === true || args?.force === true;
}

/**
 * Bu capability bu turda ÜZERİNE YAZAN bir adımla mı çağrılacak?
 *
 * Sözleşme adımları `buildTaskExecutionContract` anında HENÜZ BOŞTUR — plan
 * iş emrinden sonra materialize edilir. Yalnız sözleşme adımlarına bakmak,
 * güncelleme zincirini görünmez kılıyor ve üzerine yazma yetkisi sessizce
 * veriliyordu. Bu yüzden iş emrinin plan önizlemesi de taranır.
 */
function overwritesCapability(
  capability: string,
  steps: TaskExecutionStep[] | undefined,
  workOrder: DesktopWorkOrder | null | undefined,
): boolean {
  if ((steps ?? []).some((step) => step.capability === capability && isOverwriteStep(step.args))) {
    return true;
  }
  const planSteps = (workOrder as { planPreview?: { steps?: unknown } } | null | undefined)
    ?.planPreview?.steps;
  if (!Array.isArray(planSteps)) return false;
  return planSteps.some((value) => {
    const step = recordOf(value);
    if (!step || compact(step.capability, 120) !== capability) return false;
    return isOverwriteStep(recordOf(step.args) ?? {});
  });
}

function hasElevatedRiskArguments(args: Record<string, unknown>): boolean {
  const serialized = stableGrantJson(args);
  return serialized.length > 0 && ELEVATED_RISK_ARGUMENT_PATTERN.test(serialized);
}

function taskScopedDesktopAccessGrants(input: {
  taskId: string;
  turnId: string;
  turnContract: CommandTurnContract;
  routeDecision: CommandRouteDecision;
  workOrder?: DesktopWorkOrder | null;
  selectedTools: TaskExecutionTool[];
  steps: TaskExecutionStep[];
  allowedCapabilities: string[];
  existingGrants: TaskExecutionGrant[];
  mode: "compiled" | "dynamic";
}): { grants: TaskExecutionGrant[]; withheld: string[] } {
  const access = input.turnContract.authorization?.desktopAccess;
  if (
    access?.mode !== "task" ||
    input.routeDecision.route !== "desktop_runtime" ||
    input.routeDecision.targetDeviceId !== access.targetDeviceId
  ) return { grants: [], withheld: [] };

  const existing = new Set(input.existingGrants.map((grant) => grant.capability));
  const selected = uniqueStrings([
    ...input.steps.map((step) => step.capability),
    ...input.selectedTools.map((tool) => tool.id),
  ], TASK_EXECUTION_DIRECT_TOOL_LIMIT);
  const readRoots = uniqueStrings(input.workOrder?.resourceScope?.readRoots ?? [], 16);
  const writeRoots = uniqueStrings(input.workOrder?.resourceScope?.writeRoots ?? [], 16);
  const grants: TaskExecutionGrant[] = [];
  const withheld: string[] = [];
  const withhold = (capability: string) => {
    if (!withheld.includes(capability)) withheld.push(capability);
  };

  for (const capability of selected) {
    if (existing.has(capability) || !input.allowedCapabilities.includes(capability)) continue;
    if (SEPARATE_APPROVAL_CAPABILITY_PATTERN.test(capability)) {
      withhold(capability);
      continue;
    }
    // Generic yürütücü hiçbir modda önceden yetki almaz.
    if (GENERIC_EXECUTOR_CAPABILITY_PATTERN.test(capability)) {
      withhold(capability);
      continue;
    }
    const manifest = knownCapability(capability);
    if (!manifest?.requiresApproval || manifest.sideEffectClass === "destructive") {
      if (manifest?.sideEffectClass === "destructive") withhold(capability);
      continue;
    }
    const effect = manifest.mutatesPath
      ? "write"
      : manifest.sideEffectClass === "read" || manifest.sideEffectClass === "none"
        ? "read"
        : "control";
    const capabilitySteps = input.steps.filter((step) => step.capability === capability);
    const stepRoots = uniqueStrings(
      capabilitySteps.flatMap((step) => step.resourceScope),
      16,
    );
    // Argümanı riskli olan adım, adı ne olursa olsun ayrı onaya düşer.
    if (capabilitySteps.some((step) => hasElevatedRiskArguments(step.args))) {
      withhold(capability);
      continue;
    }
    // ÜZERİNE YAZMA HER ZAMAN AYRI ONAY.
    //
    // `document_write` adı temizdir ve normalde task-bound yetki alabilir;
    // ama `mode: "update"` var olan bir dosyanın üzerine yazar ve geri
    // alınamaz. Bu ayrım argümanda yaşadığı için ad taramasıyla görülmez.
    if (capabilitySteps.some((step) => isOverwriteStep(step.args))) {
      withhold(capability);
      continue;
    }
    const resourceScope = stepRoots.length > 0
      ? stepRoots
      : effect === "write" && writeRoots.length > 0
        ? writeRoots
        : effect === "read" && readRoots.length > 0
          ? readRoots
          : effect === "write"
            // Yazma etkisi için somut kök yoksa yetki verilmez: kapsamsız bir
            // yazma grant'i "bu cihazda istediğin yere yaz" demekti.
            ? []
            : [`device:${access.targetDeviceId}`];
    if (resourceScope.length === 0) {
      withhold(capability);
      continue;
    }
    // Derlenmiş görevde yetki TEK adıma ve o adımın argüman özetine bağlanır.
    const boundStep = input.mode === "compiled" && capabilitySteps.length === 1
      ? capabilitySteps[0]
      : null;
    grants.push({
      id: `grant_${compact(access.clientGrantId, 48)}_${grants.length + 1}`,
      taskId: compact(input.taskId, 160),
      turnId: compact(input.turnId, 160),
      capability,
      effect,
      resourceScope,
      source: "explicit_user_request",
      ...(boundStep
        ? { stepId: boundStep.id, argsHash: grantArgsHash(boundStep.args) }
        : {}),
      riskClass: "low",
    });
  }
  return { grants, withheld };
}

function verificationSnapshot(
  workOrder: DesktopWorkOrder | null | undefined,
  artifactRequired: boolean,
): TaskExecutionContract["verification"] {
  const criteria = (workOrder?.verificationRules ?? []).slice(0, 16).map((rule) => ({
    id: compact(rule.id, 120),
    description: compact(rule.description, 300),
    evidence: rule.evidence,
  }));
  if (artifactRequired && !criteria.some((criterion) => criterion.evidence === "artifact")) {
    criteria.push({
      id: "artifact_exists",
      description: "Requested artifact exists and matches the requested output contract.",
      evidence: "artifact",
    });
  }
  return {
    artifactRequired,
    stateReadbackRequired: criteria.some((criterion) => criterion.evidence === "state_readback"),
    successPolicy: "all_required",
    criteria,
  };
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
  const compiled = isCompiledWorkOrder(input.workOrder);
  const candidates = [
    ...steps.map((step) => ({
      id: step.capability,
      args: "stepId" in step ? step.input : step.args,
      reason: "server_plan_step",
    })),
    ...(compiled
      ? []
      : input.routeDecision.capabilities.map((id) => ({
          id,
          args: {},
          reason: "route_capability",
        }))),
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
    if (selectedTools.length >= TASK_EXECUTION_DIRECT_TOOL_LIMIT) break;
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

function upgradeV1TaskExecutionContract(
  legacy: z.output<typeof taskExecutionContractV1Schema>,
): TaskExecutionContract {
  const workOrder = recordOf(legacy.desktopWorkOrder);
  const contextPack = recordOf(workOrder?.contextPack);
  const legacyOutput = recordOf(contextPack?.outputContract);
  const resourceScope = recordOf(workOrder?.resourceScope);
  const writeRoots = Array.isArray(resourceScope?.writeRoots)
    ? uniqueStrings(resourceScope.writeRoots, 16)
    : [];
  const expectedOutputs = Array.isArray(workOrder?.expectedOutputs)
    ? workOrder.expectedOutputs.map(recordOf).filter(Boolean)
    : [];
  const artifactRequired =
    legacyOutput?.requiresArtifact === true ||
    expectedOutputs.some(
      (item) =>
        item?.required === true &&
        (item?.kind === "artifact" || item?.kind === "file_update"),
    );
  const rawKind = compact(legacyOutput?.outputKind, 40);
  const kind: TaskExecutionContract["output"]["kind"] =
    rawKind === "document" ||
    rawKind === "table" ||
    rawKind === "chart" ||
    rawKind === "image" ||
    rawKind === "svg"
      ? rawKind
      : artifactRequired
        ? "document"
        : "chat_reply";
  const rawOperation = compact(legacyOutput?.operation, 40);
  const operation: TaskExecutionContract["output"]["operation"] =
    rawOperation === "create" ||
    rawOperation === "transform" ||
    rawOperation === "export" ||
    rawOperation === "edit" ||
    rawOperation === "analyze_then_export"
      ? rawOperation
      : artifactRequired
        ? "create"
        : "answer";
  const allowedCapabilities = uniqueStrings([
    ...legacy.execution.selectedTools.map((tool) => tool.id),
    ...legacy.execution.steps.map((step) => step.capability),
    ...(Array.isArray(workOrder?.requiredCapabilities)
      ? workOrder.requiredCapabilities
      : []),
  ], 96);
  const criteria = Array.isArray(workOrder?.verificationRules)
    ? workOrder.verificationRules
        .map(recordOf)
        .filter(Boolean)
        .slice(0, 16)
        .map((rule, index) => ({
          id: compact(rule?.id, 120) || `criterion_${index + 1}`,
          description:
            compact(rule?.description, 300) || "Görev sonucu doğrulanmalı.",
          evidence:
            rule?.evidence === "runtime_status" ||
            rule?.evidence === "artifact" ||
            rule?.evidence === "state_readback"
              ? rule.evidence
              : ("tool_result" as const),
        }))
    : [];
  const upgraded: Omit<TaskExecutionContract, "binding"> = {
    ...legacy,
    contract: TASK_EXECUTION_CONTRACT,
    output: {
      operation,
      kind,
      format: compact(legacyOutput?.outputFormat, 40) || null,
      target: resolveOutputTarget({
        artifactRequired,
        writeRoots,
        route: "desktop_runtime",
        desktopDeliveryRequested:
          recordOf(workOrder?.resourceScope)?.desktopDeliveryRequested === true,
        stepLocalPaths: collectStepLocalPaths(workOrder),
      }),
      artifactRequired,
    },
    execution: {
      ...legacy.execution,
      mode: legacy.execution.steps.length > 0 ? "compiled" : "dynamic",
      allowedCapabilities,
    },
    approval: {
      ...legacy.approval,
      grants: [],
    },
    verification: {
      artifactRequired,
      stateReadbackRequired: criteria.some(
        (criterion) => criterion.evidence === "state_readback",
      ),
      successPolicy: "all_required",
      criteria,
    },
  };
  return bindTaskExecutionContract(upgraded);
}

function parseCompatibleTaskExecutionContract(
  value: unknown,
):
  | { success: true; data: TaskExecutionContract }
  | { success: false; error: z.ZodError } {
  const current = taskExecutionContractSchema.safeParse(value);
  if (current.success) return current;
  const legacy = taskExecutionContractV1Schema.safeParse(value);
  if (legacy.success) {
    return { success: true, data: upgradeV1TaskExecutionContract(legacy.data) };
  }
  return { success: false, error: current.error };
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
  const steps = isCompiledWorkOrder(workOrder)
    ? executionStepsForWorkOrder(workOrder)
        .slice(0, TASK_EXECUTION_MAX_STEPS)
        .map(stepSnapshot)
    : [];
  const output = outputSnapshot({
    turnContract: input.turnContract,
    workOrder,
  });
  const allowedCapabilities = allowedCapabilitiesForInput({
    routeDecision: input.routeDecision,
    workOrder,
    selectedTools: toolSelection.selectedTools,
    steps,
  });
  const explicitGrants = explicitArtifactWriteGrants({
    taskId: input.taskId,
    turnId: input.turnId,
    output,
    workOrder,
    allowedCapabilities,
    steps,
  });
  const executionMode: "compiled" | "dynamic" = steps.length > 0 ? "compiled" : "dynamic";
  const taskScopedAccess = taskScopedDesktopAccessGrants({
    taskId: input.taskId,
    turnId: input.turnId,
    turnContract: input.turnContract,
    routeDecision: input.routeDecision,
    workOrder,
    selectedTools: toolSelection.selectedTools,
    steps,
    allowedCapabilities,
    existingGrants: explicitGrants,
    mode: executionMode,
  });
  const grants = [...explicitGrants, ...taskScopedAccess.grants];
  const grantedCapabilities = new Set(grants.map((grant) => grant.capability));
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
    ...(workOrder?.approvalCapabilities ?? []).filter(
      (capability) => knownCapability(capability)?.requiresApproval === true,
    ),
    // Yetkisi bilinçli olarak TUTULAN capability'ler ayrı onay listesine düşer;
    // "yetki verilmedi" sessiz bir boşluk değil, görünür bir onay talebidir.
    ...taskScopedAccess.withheld,
  ], 32).filter((capability) => !grantedCapabilities.has(capability));
  const selectedWorkload: SharedBrainWorkload | string = input.turnContract.selectedWorkload;
  const contract: Omit<TaskExecutionContract, "binding"> = {
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
    output,
    execution: {
      mode: executionMode,
      workload: selectedWorkload,
      requiredRuntime,
      allowedCapabilities,
      selectedTools: toolSelection.selectedTools,
      selectedSkills: skillSelection.selectedSkills,
      steps,
      maxSteps: Math.min(
        steps.length > 0
          ? TASK_EXECUTION_MAX_STEPS
          : TASK_EXECUTION_DYNAMIC_MAX_STEPS,
        Math.max(
          1,
          workOrder?.execution.maxSteps ??
            (steps.length > 0
              ? TASK_EXECUTION_MAX_STEPS
              : TASK_EXECUTION_DYNAMIC_MAX_STEPS),
        ),
      ),
    },
    approval: {
      required:
        (input.routeDecision.requiresApproval === true && grants.length === 0) ||
        (workOrder?.requiresApproval === true && approvalScope.length > 0) ||
        approvalScope.length > 0,
      scope: approvalScope,
      separateApprovalFor: approvalScope,
      grants,
      ttlSeconds: 900,
    },
    verification: verificationSnapshot(workOrder, output.artifactRequired),
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
  return bindTaskExecutionContract(contract);
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
  const parsed = parseCompatibleTaskExecutionContract(input.contract);
  if (!parsed.success) return null;

  const contract = parsed.data;
  const steps = executionStepsForWorkOrder(input.workOrder)
    .slice(0, TASK_EXECUTION_MAX_STEPS)
    .map(stepSnapshot);
  if (steps.length > contract.execution.maxSteps) return null;

  const existingToolsById = new Map(
    contract.execution.selectedTools.map((tool) => [tool.id, tool] as const),
  );
  let selectedTools: TaskExecutionTool[] = [];
  if (steps.length > 0) {
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
  } else {
    // Dynamic mode has no server-owned graph yet, but it still needs the
    // contract's initial evidence-backed shortlist. Clearing it here forced
    // the AgentLoop to rediscover every tool from the full allowed ceiling.
    selectedTools = contract.execution.selectedTools.map((tool) => ({
      ...tool,
      args: { ...tool.args },
    }));
  }
  const planRevision =
    input.planRevision == null
      ? contract.planRevision
      : Math.max(1, Math.floor(input.planRevision));
  const allowedCapabilities = uniqueStrings([
    ...selectedTools.map((tool) => tool.id),
    ...steps.map((step) => step.capability),
    ...(input.workOrder.requiredCapabilities ?? []),
    ...(input.workOrder.materializedCapabilityScope ?? []),
  ], 96).filter((capability) => knownTaskCapabilityIds().has(capability));
  if (steps.length === 0) {
    const allowedSet = new Set(allowedCapabilities);
    selectedTools = selectedTools.filter((tool) => allowedSet.has(tool.id));
  }
  const syncScope = input.workOrder.resourceScope as
    | { writeRoots?: string[]; desktopDeliveryRequested?: boolean }
    | undefined;
  const output: TaskExecutionContract["output"] = {
    ...contract.output,
    target: resolveOutputTarget({
      artifactRequired: contract.output.artifactRequired,
      writeRoots: syncScope?.writeRoots ?? [],
      route: "desktop_runtime",
      desktopDeliveryRequested: syncScope?.desktopDeliveryRequested === true,
      stepLocalPaths: collectStepLocalPaths(input.workOrder),
    }),
  };
  const grants = explicitArtifactWriteGrants({
    taskId: contract.taskId,
    turnId: contract.turnId,
    output,
    workOrder: input.workOrder,
    allowedCapabilities,
    steps,
  });
  const grantedCapabilities = new Set(grants.map((grant) => grant.capability));
  const approvalScope = uniqueStrings([
    ...selectedTools
      .filter((tool) => knownCapability(tool.id)?.requiresApproval === true)
      .map((tool) => tool.id),
    ...(input.workOrder.approvalCapabilities ?? []).filter(
      (capability) => knownCapability(capability)?.requiresApproval === true,
    ),
  ], 32).filter((capability) => !grantedCapabilities.has(capability));
  const { binding: _previousBinding, ...unboundContract } = contract;
  const updated: Omit<TaskExecutionContract, "binding"> = {
    ...unboundContract,
    planRevision,
    output,
    execution: {
      ...contract.execution,
      mode: steps.length > 0 ? "compiled" : "dynamic",
      allowedCapabilities,
      selectedTools,
      steps,
    },
    approval: {
      ...contract.approval,
      required: approvalScope.length > 0,
      scope: approvalScope,
      separateApprovalFor: approvalScope,
      grants,
    },
    verification: verificationSnapshot(
      input.workOrder,
      contract.output.artifactRequired,
    ),
    desktopWorkOrder: safeWorkOrderSnapshot(input.workOrder),
  };
  return bindTaskExecutionContract(updated);
}

export function validateTaskExecutionContract(
  value: unknown,
  options: { taskId?: string; planRevision?: number } = {},
): TaskExecutionContractValidation {
  const parsed = parseCompatibleTaskExecutionContract(value);
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
  const allowedCapabilities = new Set(contract.execution.allowedCapabilities);
  for (const [index, capability] of contract.execution.allowedCapabilities.entries()) {
    if (!knownCapabilities.has(capability)) {
      errors.push({
        code: "TASK_CONTRACT_UNKNOWN_ALLOWED_CAPABILITY",
        path: `execution.allowedCapabilities.${index}`,
        message: "Capability registry dışında bir yürütme yetkisi verildi.",
      });
    }
  }
  for (const [index, tool] of contract.execution.selectedTools.entries()) {
    if (!knownCapabilities.has(tool.id)) {
      errors.push({
        code: "TASK_CONTRACT_UNKNOWN_TOOL",
        path: `execution.selectedTools.${index}.id`,
        message: "Capability registry dışında bir tool seçildi.",
      });
    }
    if (!allowedCapabilities.has(tool.id)) {
      errors.push({
        code: "TASK_CONTRACT_TOOL_OUTSIDE_SCOPE",
        path: `execution.selectedTools.${index}.id`,
        message: "Seçili tool görev capability sınırının dışında.",
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
    if (
      contract.execution.requiredRuntime === "desktop" &&
      step.device !== undefined &&
      step.device !== "desktop"
    ) {
      errors.push({
        code: "TASK_CONTRACT_REMOTE_STEP_DEVICE",
        path: `execution.steps.${index}.device`,
        message: "Desktop plan step'i başka bir cihaza bağlanamaz.",
      });
    }
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
    if (!allowedCapabilities.has(step.capability)) {
      errors.push({
        code: "TASK_CONTRACT_STEP_OUTSIDE_SCOPE",
        path: `execution.steps.${index}.capability`,
        message: "Plan step görev capability sınırının dışında.",
      });
    }
  }
  if (
    contract.execution.mode === "compiled" &&
    contract.execution.requiredRuntime !== "server" &&
    contract.execution.steps.length === 0
  ) {
    errors.push({
      code: "TASK_CONTRACT_COMPILED_PLAN_EMPTY",
      path: "execution.steps",
      message: "Compiled yürütme yolu boş bir step grafiği taşıyamaz.",
    });
  }
  if (contract.execution.steps.length > contract.execution.maxSteps) {
    errors.push({
      code: "TASK_CONTRACT_STEP_BUDGET_EXCEEDED",
      path: "execution.steps",
      message: "Plan step sayısı maxSteps sınırını aşıyor.",
    });
  }
  for (const [index, grant] of contract.approval.grants.entries()) {
    if (grant.taskId !== contract.taskId || grant.turnId !== contract.turnId) {
      errors.push({
        code: "TASK_CONTRACT_GRANT_BINDING_MISMATCH",
        path: `approval.grants.${index}`,
        message: "İzin grant'i task/turn bağıyla eşleşmiyor.",
      });
    }
    if (!allowedCapabilities.has(grant.capability)) {
      errors.push({
        code: "TASK_CONTRACT_GRANT_OUTSIDE_SCOPE",
        path: `approval.grants.${index}.capability`,
        message: "İzin grant'i görev capability sınırının dışında.",
      });
    }
  }
  if (
    contract.output.artifactRequired &&
    (!contract.verification.artifactRequired ||
      !contract.verification.criteria.some((criterion) => criterion.evidence === "artifact"))
  ) {
    errors.push({
      code: "TASK_CONTRACT_ARTIFACT_VERIFICATION_MISSING",
      path: "verification.criteria",
      message: "Zorunlu artifact çıktısı artifact kanıtıyla doğrulanmalı.",
    });
  }
  const { binding: _binding, ...unboundContract } = contract;
  if (taskExecutionContractHash(unboundContract) !== contract.binding.hash) {
    errors.push({
      code: "TASK_CONTRACT_HASH_MISMATCH",
      path: "binding.hash",
      message: "Task contract hash doğrulaması başarısız.",
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
