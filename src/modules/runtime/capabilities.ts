export type RuntimeCapabilityCategory =
  | "runtime"
  | "task"
  | "browser"
  | "computer"
  | "file"
  | "document"
  | "model"
  | "quantum"
  | "automation"
  | "connector"
  | "other";

export type RuntimeCapabilitySummary = {
  total: number;
  categories: Record<RuntimeCapabilityCategory, number>;
};

export type RuntimeCapabilityReadinessSummary = {
  total: number;
  ready: number;
  blocked: number;
  dependencyBlocked: number;
  permissionBlocked: number;
  unknown: number;
  blockedCapabilities: Array<{
    name: string;
    reason: string;
    errorCode: string;
  }>;
};

const CATEGORY_KEYS: RuntimeCapabilityCategory[] = [
  "runtime",
  "task",
  "browser",
  "computer",
  "file",
  "document",
  "model",
  "quantum",
  "automation",
  "connector",
  "other",
];

function normalizeCapabilityName(value: string): string {
  const canonical = value.trim().toLowerCase().replace(/[\s_]+/g, ".");

  switch (canonical) {
    case "file.system":
    case "filesystem":
      return "filesystem";
    case "browser.control":
    case "browser":
      return "browser.control";
    case "computer.control":
    case "computer":
      return "computer.control";
    case "llm.local":
    case "llm":
      return "llm.local";
    case "task":
      return "task.execution";
    case "runtime":
      return "runtime.status";
    default:
      return canonical;
  }
}

function categorizeCapability(capability: string): RuntimeCapabilityCategory {
  if (capability === "runtime.status") {
    return "runtime";
  }

  if (capability === "task.execution") {
    return "task";
  }

  if (capability === "browser.control") {
    return "browser";
  }

  if (capability === "computer.control") {
    return "computer";
  }

  if (capability === "filesystem" || capability.startsWith("file.") || capability.startsWith("local.files.")) {
    return "file";
  }

  if (
    capability.startsWith("document.") ||
    capability.startsWith("spreadsheet.") ||
    capability.startsWith("presentation.") ||
    capability === "text.analyze" ||
    capability === "data.analyze" ||
    capability === "web.research"
  ) {
    return "document";
  }

  if (capability === "llm.local" || capability.startsWith("model.")) {
    return "model";
  }

  if (capability === "math.solve" || capability.startsWith("quantum.")) {
    return "quantum";
  }

  if (capability.startsWith("automation.") || capability.startsWith("workflow.")) {
    return "automation";
  }

  if (capability.startsWith("connector.") || capability.startsWith("oauth") || capability === "mcp") {
    return "connector";
  }

  return "other";
}

export function normalizeRuntimeCapabilities(input: unknown): string[] {
  if (!Array.isArray(input)) {
    return [];
  }

  return [...new Set(input.map((capability) => String(capability ?? "").trim()).filter(Boolean).map(normalizeCapabilityName))];
}

export function supportsRequestedCapabilities(
  availableCapabilities: unknown,
  requestedCapabilities: string[] = [],
): boolean {
  const normalizedAvailable = new Set(normalizeRuntimeCapabilities(availableCapabilities));
  const normalizedRequested = normalizeRuntimeCapabilities(requestedCapabilities);
  return normalizedRequested.every((capability) => normalizedAvailable.has(capability));
}

export function missingRuntimeCapabilities(
  availableCapabilities: unknown,
  requestedCapabilities: string[] = [],
): string[] {
  const normalizedAvailable = new Set(normalizeRuntimeCapabilities(availableCapabilities));
  const normalizedRequested = normalizeRuntimeCapabilities(requestedCapabilities);
  return normalizedRequested.filter((capability) => !normalizedAvailable.has(capability));
}

function readCapabilityStateRecord(
  capabilityStates: unknown,
): Record<string, unknown> {
  return capabilityStates &&
    typeof capabilityStates === "object" &&
    !Array.isArray(capabilityStates)
    ? (capabilityStates as Record<string, unknown>)
    : {};
}

function stateReady(value: unknown): boolean | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (typeof record.ready === "boolean") return record.ready;
  if (typeof record.dependencyReady === "boolean" && record.dependencyReady === false) return false;
  if (typeof record.systemPermissionRequired === "boolean" && record.systemPermissionRequired === true) return false;
  return null;
}

function stateErrorCode(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const record = value as Record<string, unknown>;
  return String(
    record.errorCode ??
      record.lastErrorCode ??
      record.degradationReason ??
      record.reason ??
      "",
  ).trim();
}

function stateBlockedReason(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const record = value as Record<string, unknown>;
  if (record.dependencyReady === false) return "dependency_unavailable";
  if (record.systemPermissionRequired === true) return "os_permission_required";
  return stateErrorCode(value) || "not_ready";
}

export function summarizeRuntimeCapabilityReadiness(
  capabilityStates: unknown,
): RuntimeCapabilityReadinessSummary {
  const states = readCapabilityStateRecord(capabilityStates);
  const summary: RuntimeCapabilityReadinessSummary = {
    total: 0,
    ready: 0,
    blocked: 0,
    dependencyBlocked: 0,
    permissionBlocked: 0,
    unknown: 0,
    blockedCapabilities: [],
  };
  for (const [rawName, state] of Object.entries(states)) {
    const name = normalizeCapabilityName(rawName);
    const ready = stateReady(state);
    const reason = stateBlockedReason(state);
    const errorCode = stateErrorCode(state);
    summary.total += 1;
    if (ready === true) {
      summary.ready += 1;
      continue;
    }
    if (ready === false) {
      summary.blocked += 1;
      if (reason.includes("dependency")) summary.dependencyBlocked += 1;
      if (reason.includes("permission") || errorCode.includes("PERMISSION")) {
        summary.permissionBlocked += 1;
      }
      summary.blockedCapabilities.push({ name, reason, errorCode });
      continue;
    }
    summary.unknown += 1;
  }
  return {
    ...summary,
    blockedCapabilities: summary.blockedCapabilities.slice(0, 24),
  };
}

export function preflightRequestedRuntimeCapabilities(input: {
  availableCapabilities: unknown;
  capabilityStates: unknown;
  requestedCapabilities: string[];
}): {
  ok: boolean;
  missingCapabilities: string[];
  blockedCapabilities: RuntimeCapabilityReadinessSummary["blockedCapabilities"];
} {
  const missingCapabilities = missingRuntimeCapabilities(
    input.availableCapabilities,
    input.requestedCapabilities,
  );
  const requested = new Set(normalizeRuntimeCapabilities(input.requestedCapabilities));
  const readiness = summarizeRuntimeCapabilityReadiness(input.capabilityStates);
  const blockedCapabilities = readiness.blockedCapabilities.filter((item) =>
    requested.has(item.name),
  );
  return {
    ok: missingCapabilities.length === 0 && blockedCapabilities.length === 0,
    missingCapabilities,
    blockedCapabilities,
  };
}

export function summarizeRuntimeCapabilities(input: unknown): RuntimeCapabilitySummary {
  const capabilities = normalizeRuntimeCapabilities(input);
  const categories = Object.fromEntries(CATEGORY_KEYS.map((category) => [category, 0])) as Record<
    RuntimeCapabilityCategory,
    number
  >;

  for (const capability of capabilities) {
    categories[categorizeCapability(capability)] += 1;
  }

  return {
    total: capabilities.length,
    categories,
  };
}
