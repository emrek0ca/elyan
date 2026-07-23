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
