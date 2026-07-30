import path from "node:path";
import { DESKTOP_CAPABILITY_MANIFEST } from "./desktop-capability-manifest.js";
import { DESKTOP_SKILL_MANIFEST } from "./desktop-skill-manifest.js";
import type {
  DesktopWorkOrder,
  DesktopWorkOrderStep,
} from "./desktop-work-order.js";

const CAPABILITY_MANIFEST_BY_NAME = new Map(
  DESKTOP_CAPABILITY_MANIFEST.map((entry) => [entry.name, entry] as const),
);
const SKILL_MANIFEST_BY_ID = new Map(
  DESKTOP_SKILL_MANIFEST.map((entry) => [entry.id, entry] as const),
);
const STEP_TEMPLATE_RE = /\{\{\s*steps\.([A-Za-z0-9_-]+)/g;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function templateStepReferences(value: unknown): Set<string> {
  const refs = new Set<string>();
  if (Array.isArray(value)) {
    for (const item of value) {
      for (const ref of templateStepReferences(item)) refs.add(ref);
    }
    return refs;
  }
  const record = asRecord(value);
  if (record) {
    for (const item of Object.values(record)) {
      for (const ref of templateStepReferences(item)) refs.add(ref);
    }
    return refs;
  }
  if (typeof value !== "string" || !value.includes("{{")) return refs;
  for (const match of value.matchAll(STEP_TEMPLATE_RE)) {
    const id = String(match[1] ?? "").trim();
    if (id) refs.add(id);
  }
  return refs;
}

export function buildAllowedCapabilities(
  workOrder: DesktopWorkOrder,
): string[] {
  const required = new Set(
    (Array.isArray(workOrder.requiredCapabilities)
      ? workOrder.requiredCapabilities
      : []
    )
      .map((capability) => String(capability ?? "").trim())
      .filter(Boolean),
  );
  const forbidden = new Set(
    workOrder.semanticGoal?.forbiddenCapabilities ?? [],
  );
  const autonomyAllowed = workOrder.autonomy
    ? new Set(workOrder.autonomy.allowedCapabilities)
    : null;
  const authorization = asRecord(workOrder.capabilityAuthorization);
  const allowPrivateRead = authorization
    ? authorization.allowPrivateRead === true
    : true;
  return DESKTOP_CAPABILITY_MANIFEST.filter((entry) => {
    if (!required.has(entry.name)) return false;
    if (forbidden.has(entry.name)) return false;
    if (autonomyAllowed && !autonomyAllowed.has(entry.name)) return false;
    if (
      authorization &&
      !allowPrivateRead &&
      entry.privacyClass.includes("_read")
    ) {
      return false;
    }
    return true;
  }).map((entry) => entry.name);
}

function hasConcreteArgument(
  args: Record<string, unknown>,
  key: string,
): boolean {
  const value = args[key];
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

function isGroundedPlanPath(value: string): boolean {
  const candidate = value.trim();
  return (
    candidate.includes("{{steps.") ||
    candidate === "workspace" ||
    candidate.startsWith("workspace/") ||
    candidate.startsWith("workspace\\") ||
    candidate.startsWith("~/") ||
    candidate.startsWith("/") ||
    /^[A-Za-z]:[\\/]/.test(candidate) ||
    candidate.startsWith("\\\\")
  );
}

function validateGroundedPaths(
  value: unknown,
  location: string,
  issues: string[],
): void {
  const record = asRecord(value);
  if (!record) return;
  for (const [key, nestedValue] of Object.entries(record)) {
    const nestedLocation = `${location}.${key}`;
    if (
      /path$/i.test(key) &&
      typeof nestedValue === "string" &&
      nestedValue.trim() &&
      !isGroundedPlanPath(nestedValue)
    ) {
      issues.push(
        `${nestedLocation} must use an explicit root such as ~/Desktop, workspace/, an absolute path, or a prior-step reference`,
      );
    }
    if (Array.isArray(nestedValue)) {
      nestedValue.forEach((item, index) =>
        validateGroundedPaths(item, `${nestedLocation}[${index}]`, issues),
      );
    } else {
      validateGroundedPaths(nestedValue, nestedLocation, issues);
    }
  }
}

export function validateMaterializedPlanContracts(
  steps: DesktopWorkOrderStep[],
): string[] {
  const issues: string[] = [];
  const priorStepIds = new Set<string>();
  for (const step of steps) {
    for (const dependency of step.dependsOn ?? []) {
      if (!priorStepIds.has(dependency)) {
        issues.push(
          `${step.id}: dependsOn must reference an earlier step; invalid dependency id`,
        );
      }
    }
    const manifest = CAPABILITY_MANIFEST_BY_NAME.get(step.capability);
    if (!manifest) {
      issues.push(
        `${step.id}: capability ${step.capability} is not in the desktop manifest`,
      );
      continue;
    }
    for (const requiredArg of manifest.requiredArgs) {
      const hasInlineDocumentText =
        step.capability === "document_read" &&
        requiredArg === "path" &&
        hasConcreteArgument(step.args, "text");
      if (hasInlineDocumentText) continue;
      if (!hasConcreteArgument(step.args, requiredArg)) {
        issues.push(
          `${step.id}: ${step.capability} requires args.${requiredArg}`,
        );
      }
    }
    validateGroundedPaths(step.args, `${step.id}: args`, issues);
    if (step.capability === "run_skill") {
      const skillId =
        typeof step.args.skillId === "string" ? step.args.skillId.trim() : "";
      const skill = SKILL_MANIFEST_BY_ID.get(skillId);
      if (!skill) {
        issues.push(
          `${step.id}: run_skill requires an exact args.skillId from the desktop skill manifest`,
        );
        continue;
      }
      const payload = asRecord(step.args.payload);
      if (!payload) {
        issues.push(`${step.id}: run_skill requires args.payload as an object`);
        continue;
      }
      const allowedParameters = new Set(skill.parameters);
      for (const key of Object.keys(payload)) {
        if (!allowedParameters.has(key)) {
          issues.push(
            `${step.id}: skill ${skill.id} does not accept payload.${key}`,
          );
        }
      }
      for (const requiredParameter of skill.requiredParameters) {
        if (!hasConcreteArgument(payload, requiredParameter)) {
          issues.push(
            `${step.id}: skill ${skill.id} requires payload.${requiredParameter}`,
          );
        }
      }
      for (const capability of skill.stepCapabilities) {
        if (!CAPABILITY_MANIFEST_BY_NAME.has(capability)) {
          issues.push(
            `${step.id}: skill ${skill.id} references unknown desktop capability ${capability}`,
          );
        }
      }
    }
    priorStepIds.add(step.id);
  }
  return issues;
}

function effectivePlanCapabilities(
  steps: DesktopWorkOrderStep[],
): Set<string> {
  const capabilities = new Set<string>();
  for (const step of steps) {
    capabilities.add(step.capability);
    if (step.capability !== "run_skill") continue;
    const skillId =
      typeof step.args.skillId === "string" ? step.args.skillId.trim() : "";
    const skill = SKILL_MANIFEST_BY_ID.get(skillId);
    for (const capability of skill?.stepCapabilities ?? []) {
      capabilities.add(capability);
    }
  }
  return capabilities;
}

function collectPlanPaths(
  value: unknown,
  paths: string[] = [],
): string[] {
  const record = asRecord(value);
  if (!record) return paths;
  for (const [key, nested] of Object.entries(record)) {
    const isPathField = /paths?$/iu.test(key);
    if (
      isPathField &&
      typeof nested === "string" &&
      nested.trim() &&
      !nested.includes("{{steps.")
    ) {
      paths.push(nested.trim());
    }
    if (Array.isArray(nested)) {
      for (const item of nested) {
        if (
          isPathField &&
          typeof item === "string" &&
          item.trim() &&
          !item.includes("{{steps.")
        ) {
          paths.push(item.trim());
        } else {
          collectPlanPaths(item, paths);
        }
      }
    } else {
      collectPlanPaths(nested, paths);
    }
  }
  return paths;
}

function pathIsWithinRoot(pathValue: string, rootValue: string): boolean {
  const normalize = (value: string) => {
    const portable = value.trim().replaceAll("\\", "/");
    if (/^[A-Za-z]:\//u.test(portable) || portable.startsWith("//")) {
      return path.win32
        .normalize(portable.replaceAll("/", "\\"))
        .replaceAll("\\", "/")
        .replace(/\/+$/u, "")
        .toLocaleLowerCase("en-US");
    }
    return path.posix.normalize(portable).replace(/\/+$/u, "");
  };
  const candidatePath = normalize(pathValue);
  const root = normalize(rootValue);
  return candidatePath === root || candidatePath.startsWith(`${root}/`);
}

function publicQueryContainsPrivateMaterial(
  query: string,
  workOrder: DesktopWorkOrder,
): boolean {
  if (workOrder.semanticGoal?.risk.localPrivate !== true) return false;
  const value = query.trim();
  if (!value || value.length > 280) return true;
  const approvedQueries = new Set(
    (workOrder.planPreview.steps ?? [])
      .filter((step) => step.capability === "web_research")
      .map((step) =>
        typeof step.args.query === "string"
          ? step.args.query.replace(/\s+/gu, " ").trim()
          : "",
      )
      .filter(Boolean),
  );
  if (!approvedQueries.has(value.replace(/\s+/gu, " ").trim())) return true;
  if (
    /(?:[A-Z]:[\\/]|\\\\|~\/|\/Users\/|\/home\/|workspace[\\/])/u.test(
      value,
    ) ||
    /[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/u.test(value) ||
    /\b[0-9a-f]{8}-[0-9a-f-]{27,}\b/iu.test(value) ||
    /\b\d{7,}\b/u.test(value)
  ) {
    return true;
  }
  const normalizeWords = (text: string) =>
    text
      .toLocaleLowerCase("tr-TR")
      .replace(/[^\p{L}\p{N}]+/gu, " ")
      .trim()
      .split(/\s+/u)
      .filter(Boolean);
  const queryWords = normalizeWords(value);
  if (queryWords.length < 8) return false;
  const goalWords = normalizeWords(
    workOrder.contextPack?.conversationState &&
      typeof workOrder.contextPack.conversationState.currentGoal === "string"
      ? workOrder.contextPack.conversationState.currentGoal
      : workOrder.goal.summary,
  );
  const goalText = ` ${goalWords.join(" ")} `;
  for (let index = 0; index <= queryWords.length - 8; index += 1) {
    const fragment = ` ${queryWords.slice(index, index + 8).join(" ")} `;
    if (goalText.includes(fragment)) return true;
  }
  return false;
}

export function validateMaterializedPlanAgainstWorkOrder(
  steps: DesktopWorkOrderStep[],
  workOrder: DesktopWorkOrder,
): string[] {
  const issues = validateMaterializedPlanContracts(steps);
  const effectiveCapabilities = effectivePlanCapabilities(steps);
  const allowed = new Set(buildAllowedCapabilities(workOrder));
  const forbidden = new Set(
    workOrder.semanticGoal?.forbiddenCapabilities ?? [],
  );
  const autonomyAllowed = workOrder.autonomy
    ? new Set(workOrder.autonomy.allowedCapabilities)
    : null;
  for (const capability of effectiveCapabilities) {
    if (!allowed.has(capability)) {
      issues.push(
        `capability ${capability} is outside the semantic authorization scope`,
      );
    }
    if (forbidden.has(capability)) {
      issues.push(`capability ${capability} is forbidden by the semantic goal`);
    }
    if (autonomyAllowed && !autonomyAllowed.has(capability)) {
      issues.push(
        `capability ${capability} exceeds the unattended autonomy ceiling`,
      );
    }
  }
  if (workOrder.resourceScope?.contract === "elyan.resource_scope.v1") {
    for (const step of steps) {
      const manifest = CAPABILITY_MANIFEST_BY_NAME.get(step.capability);
      const isWrite =
        manifest?.privacyClass.includes("_write") === true ||
        asRecord(manifest?.outputContract)?.primary === "artifact";
      const roots = isWrite
        ? workOrder.resourceScope.writeRoots
        : workOrder.resourceScope.readRoots;
      for (const candidatePath of collectPlanPaths(step.args)) {
        if (!roots.some((root) => pathIsWithinRoot(candidatePath, root))) {
          issues.push(
            `${step.id}: path is outside the authorized WorkOrder resource scope`,
          );
        }
      }
    }
  }
  const hasSemanticContract =
    workOrder.semanticGoal?.contract === "elyan.semantic_task_contract.v1";
  if (hasSemanticContract) {
    for (const requiredCapability of workOrder.semanticGoal!
      .requiredCapabilities) {
      if (!effectiveCapabilities.has(requiredCapability)) {
        issues.push(
          `semantic work order requires capability ${requiredCapability}`,
        );
      }
    }
  }
  const requiresArtifact = workOrder.expectedOutputs.some(
    (output) => output.required && output.kind === "artifact",
  );
  if (
    hasSemanticContract &&
    requiresArtifact &&
    ![...effectiveCapabilities].some((capability) => {
      const manifest = CAPABILITY_MANIFEST_BY_NAME.get(capability);
      return (
        Object.keys(manifest?.artifactContract ?? {}).length > 0 ||
        asRecord(manifest?.outputContract)?.primary === "artifact"
      );
    })
  ) {
    issues.push("required artifact has no artifact-producing capability");
  }
  const stepById = new Map(steps.map((step) => [step.id, step] as const));
  for (const step of steps) {
    if (step.capability !== "web_research") continue;
    const query =
      typeof step.args.query === "string" ? step.args.query.trim() : "";
    if (templateStepReferences(query).size > 0) {
      issues.push(
        `${step.id}: public web query cannot consume prior-step or private context`,
      );
    }
    if (publicQueryContainsPrivateMaterial(query, workOrder)) {
      issues.push(
        `${step.id}: public web query contains unapproved private task material`,
      );
    }
    for (const dependency of step.dependsOn ?? []) {
      const producer = stepById.get(dependency);
      const privacyClass = producer
        ? CAPABILITY_MANIFEST_BY_NAME.get(producer.capability)?.privacyClass
        : null;
      if (privacyClass?.startsWith("local_private")) {
        issues.push(
          `${step.id}: public web query cannot depend on local-private capability output`,
        );
      }
    }
  }
  return [...new Set(issues)];
}
