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

export type RuntimeCapabilityHandshake = {
  canonicalCapabilityId: string;
  adapter: string;
  ready: boolean;
  dependencyReady: boolean;
  permissionReady: boolean;
  aliases: string[];
  version: string | null;
  inputContractHash: string | null;
};

export type NormalizedRuntimeCapabilityHandshake = {
  capabilities: string[];
  capabilityStates: Record<string, unknown>;
  descriptors: RuntimeCapabilityHandshake[];
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

function boundedString(value: unknown, maxLength: number): string {
  return String(value ?? "").trim().slice(0, maxLength);
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function normalizeCapabilityHandshakeEntry(
  value: unknown,
): RuntimeCapabilityHandshake | null {
  const record = readRecord(value);
  if (!record) return null;
  const canonicalCapabilityId = normalizeCapabilityName(
    boundedString(record.canonicalCapabilityId, 120),
  );
  if (!canonicalCapabilityId) return null;
  const aliases = normalizeRuntimeCapabilities(
    Array.isArray(record.aliases) ? record.aliases.slice(0, 16) : [],
  );
  return {
    canonicalCapabilityId,
    adapter: boundedString(record.adapter, 160) || canonicalCapabilityId,
    ready: readBoolean(record.ready, true),
    dependencyReady: readBoolean(record.dependencyReady, true),
    permissionReady: readBoolean(record.permissionReady, true),
    aliases,
    version: boundedString(record.version, 80) || null,
    inputContractHash: boundedString(record.inputContractHash, 120) || null,
  };
}

export function normalizeRuntimeCapabilityHandshake(input: {
  capabilities?: unknown;
  capabilityStates?: unknown;
  capabilityHandshake?: unknown;
}): NormalizedRuntimeCapabilityHandshake {
  const legacyCapabilities = normalizeRuntimeCapabilities(input.capabilities);
  const states = readCapabilityStateRecord(input.capabilityStates);
  const descriptors = Array.isArray(input.capabilityHandshake)
    ? input.capabilityHandshake
        .map(normalizeCapabilityHandshakeEntry)
        .filter((item): item is RuntimeCapabilityHandshake => Boolean(item))
        .slice(0, 256)
    : [];
  const capabilities = new Set(legacyCapabilities);
  const capabilityStates: Record<string, unknown> = { ...states };
  for (const descriptor of descriptors) {
    capabilities.add(descriptor.canonicalCapabilityId);
    for (const alias of descriptor.aliases) capabilities.add(alias);
    const existing = readRecord(capabilityStates[descriptor.canonicalCapabilityId]) ?? {};
    capabilityStates[descriptor.canonicalCapabilityId] = {
      ...existing,
      canonicalCapabilityId: descriptor.canonicalCapabilityId,
      adapter: descriptor.adapter,
      ready: descriptor.ready,
      dependencyReady: descriptor.dependencyReady,
      permissionReady: descriptor.permissionReady,
      aliases: descriptor.aliases,
      version: descriptor.version,
      inputContractHash: descriptor.inputContractHash,
      handshakeContract: "elyan.runtime_capability_handshake.v1",
    };
  }
  return {
    capabilities: [...capabilities],
    capabilityStates,
    descriptors,
  };
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
  if (typeof record.dependencyReady === "boolean" && record.dependencyReady === false) return false;
  if (typeof record.permissionReady === "boolean" && record.permissionReady === false) return false;
  if (typeof record.systemPermissionRequired === "boolean" && record.systemPermissionRequired === true) return false;
  if (typeof record.ready === "boolean") return record.ready;
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
  if (record.permissionReady === false) return "permission_unavailable";
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

export function unrunnableRuntimeCapabilityIds(
  capabilityStates: unknown,
): { capability: string; errorCode: string }[] {
  // Cihazın KOŞAMAYACAĞI yetenekler. `ready: false` DEĞİL, `available: false`
  // ölçütü kullanılır ve bu ayrım kritik:
  //
  //   browser_agent.run   ready=false available=FALSE  no_decision_provider
  //   local_files.index   ready=false available=true   permission_required
  //   desktop_operator.run ready=false available=true  (kod yok)
  //
  // İkinci ve üçüncüsü ÇALIŞIR — yalnızca izin/onay bekliyorlar. Onları
  // katalogdan atmak, kullanıcıya izin sorusu hiç sorulmadan ekran operatörünü
  // ve yerel dosya indekslemeyi kaybettirirdi. Yalnız `available: false` olan,
  // yani yapısal olarak işlevsiz olan yetenek çıkarılır.
  //
  // `summarizeRuntimeCapabilityReadiness` ile bilinçli olarak AYRI: o özet
  // adları `normalizeCapabilityName` ile kabaca sınıflara indiriyor
  // (`browser_agent.run` → `browser.agent.run`). Planlayıcı kataloğu ise
  // masaüstünün KENDİ yetenek adlarıyla anahtarlı, bu yüzden burada ham kimlik
  // korunur; normalize adla eşleştirmek hiçbir şeyi filtrelemez ve düzeltmeyi
  // sessizce etkisiz bırakır.
  const states = readCapabilityStateRecord(capabilityStates);
  const blocked: { capability: string; errorCode: string }[] = [];
  for (const [rawName, state] of Object.entries(states)) {
    const capability = String(rawName ?? "").trim();
    if (!capability) continue;
    if (!state || typeof state !== "object" || Array.isArray(state)) continue;
    if ((state as Record<string, unknown>).available !== false) continue;
    blocked.push({
      capability,
      errorCode: stateErrorCode(state) || stateBlockedReason(state) || "not_available",
    });
  }
  return blocked.slice(0, 128);
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
