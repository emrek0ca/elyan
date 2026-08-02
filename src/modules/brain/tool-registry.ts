import { createHash } from "node:crypto";
import { z } from "zod";
import type { FastifyInstance } from "fastify";
import {
  advanceGoal,
  createGoal,
  getActiveGoalForContext,
  getGoalExecutionContext,
  updateGoal,
} from "../goals/service.js";
import { listConnectedCapabilityGrants } from "../integrations/service.js";
import { listActiveSkillSummaries } from "../skills/registry.js";
import type { SkillSummary } from "../skills/types.js";
import {
  isSemanticSelectableTool,
  semanticToolConfidence,
  type CoreToolHint,
} from "./tool-semantic.js";
import { callMcpTool, isMcpToolName } from "./mcp-tools.js";
import { searchBrainMemory } from "./memory.js";
import { recordTurnMemoryOps } from "./memory-fabric.js";
import { cognitiveMemoryRepository } from "./cognitive-memory-repository.js";
import { isCognitiveFoundationEnabled } from "./cognitive-foundation-policy.js";
import type { TurnEnvelope } from "./turn-envelope.js";
import {
  extractNumericEvidenceFromGrounding,
  searchPublicWebGrounding,
} from "./web-grounding.js";
import { fetchUrlContext } from "./url-context.js";
import {
  executeCalendarCreateEvent,
  executeCalendarListEvents,
  executeDriveSearch,
  executeGithubSearch,
  executeGmailRead,
  executeGmailSearch,
  executeGmailSend,
  executeNotionSearch,
  executeSlackSearch,
} from "./connector-tools.js";
import type { SharedBrainWorkload } from "./workloads.js";
import type { AuthoritativeArtifactData } from "../artifacts/types.js";
import {
  DEFAULT_USER_APPROVAL_MODE,
  decideUserToolApproval,
  type ApprovalToolIdempotency,
  type ApprovalToolScope,
  type UserApprovalMode,
  type UserToolApprovalDecision,
} from "../approval-policy/policy.js";

export type AgentToolPermission = "read" | "write" | "side_effect";

export const AGENT_TOOL_SELECTION_CONFIDENCE_THRESHOLD = 0.72;

export type AgentToolSelectionHints = {
  purpose: string;
  intents: string[];
  capabilities: string[];
  desiredOutputKinds: string[];
  resultBlockTypes: string[];
  modelContract: string;
  connectorCapability?: string;
  authoritativeArtifactAdapter?: "numeric_points.v1";
};

export type AgentToolSelectionContext = {
  prompt: string;
  intent?: string | null;
  action?: string | null;
  desiredOutputKinds?: readonly string[];
  requiredCapabilities?: readonly string[];
  advertisedConnectorTools?: readonly string[];
  connectorReadHint?: { tool: string; score: number } | null;
  /**
   * Resolved once per turn by `selectSemanticCoreToolHint` and passed in, since
   * the transformer call is async and this builder is synchronous — the same
   * arrangement `connectorReadHint` uses.
   */
  coreToolHint?: CoreToolHint | null;
  deterministicToolNames?: readonly string[];
  memoryCandidateCount?: number;
  sideEffectRequested?: boolean;
  localPrivate?: boolean;
  includeCoreTools?: boolean;
};

export type AgentToolRequest = {
  tool: string;
  args: Record<string, unknown>;
};

export type AgentToolContext = {
  userId: string;
  taskId?: string | null;
  sessionId?: string | null;
  workload: SharedBrainWorkload;
  allowStateWrites?: boolean;
  allowSideEffects?: boolean;
  approvalMode?: UserApprovalMode;
  approvalGranted?: boolean;
  shouldAbort?: () => boolean | Promise<boolean>;
};

export type AgentToolResult = {
  tool: string;
  ok: boolean;
  permission: AgentToolPermission;
  durationMs: number;
  output: Record<string, unknown> | null;
  error: { code: string; message: string } | null;
};

function canonicalToolResultValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalToolResultValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, nested]) => [key, canonicalToolResultValue(nested)]),
    );
  }
  if (
    value == null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return value;
  }
  return String(value);
}

/** Stable server proof for binding derived artifact data to one tool result. */
export function agentToolResultDigest(result: AgentToolResult): string {
  return createHash("sha256")
    .update(
      JSON.stringify(
        canonicalToolResultValue({
          tool: result.tool,
          ok: result.ok,
          output: result.output,
        }),
      ),
    )
    .digest("hex")
    .slice(0, 32);
}

function boundedArtifactText(value: unknown, max: number): string {
  return typeof value === "string"
    ? value.replace(/\s+/g, " ").trim().slice(0, max)
    : "";
}

/** Registry-owned adapter from verified tool output to artifact authority. */
export function buildAuthoritativeArtifactDataFromToolResults(
  requestedType: "table" | "chart" | null,
  results: AgentToolResult[],
): AuthoritativeArtifactData | null {
  if (!requestedType) return null;
  const result = results.find(
    (candidate) =>
      candidate.ok &&
      getAgentToolMetadata(candidate.tool)?.selectionHints
        .authoritativeArtifactAdapter === "numeric_points.v1" &&
      Array.isArray(candidate.output?.points),
  );
  if (!result?.output) return null;
  const points = (result.output.points as unknown[]).flatMap((value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return [];
    const point = value as Record<string, unknown>;
    if (typeof point.value !== "number" || !Number.isFinite(point.value)) {
      return [];
    }
    const date = boundedArtifactText(point.date, 80);
    const context = boundedArtifactText(point.context, 320);
    const unit = boundedArtifactText(point.unit, 40);
    const sourceHost = boundedArtifactText(point.sourceHost, 160);
    const label = date || context || sourceHost;
    return label
      ? [{ label, value: point.value, unit, source: sourceHost }]
      : [];
  });
  if (points.length === 0) return null;
  const source = {
    authority: "tool_connector" as const,
    producerId: result.tool,
    resultDigest: agentToolResultDigest(result),
  };
  if (requestedType === "chart") {
    const datedPointCount = (result.output.points as unknown[]).filter(
      (value) => {
        const point =
          value && typeof value === "object" && !Array.isArray(value)
            ? (value as Record<string, unknown>)
            : null;
        return Boolean(boundedArtifactText(point?.date, 80));
      },
    ).length;
    return {
      type: "chart",
      chartType: datedPointCount >= 2 ? "line" : "bar",
      xKey: "label",
      yKey: "value",
      series: [{ key: "value", label: "Değer", valueType: "number" }],
      data: points.slice(0, 1_500),
      source,
    };
  }
  return {
    type: "table",
    columns: [
      { key: "label", label: "Etiket", dataType: "string", required: true, align: "left" },
      { key: "value", label: "Değer", dataType: "number", required: true, align: "right" },
      { key: "unit", label: "Birim", dataType: "string", required: false, align: "left" },
      { key: "source", label: "Kaynak", dataType: "string", required: false, align: "left" },
    ],
    rows: points.slice(0, 500),
    source,
  };
}

type AgentToolDefinition<TArgs extends z.ZodTypeAny> = {
  name: string;
  permission: AgentToolPermission;
  outputSchema?: z.ZodType<Record<string, unknown>>;
  timeoutMs?: number;
  idempotency?: ApprovalToolIdempotency;
  approvalScope?: ApprovalToolScope;
  /**
   * Model kaynaklı yaygın anahtar varyantları (q→query, max_results→limit).
   * Kanonik anahtar yoksa alias'ın değeri kopyalanır; şema gevşemez, parse
   * yine kanonik şemadan geçer. Yalnız read araçlarında kullanılır.
   */
  argAliases?: Record<string, string[] | undefined>;
  /**
   * Args parse başarısız olduğunda şema salt-default `{}` parse'ını kabul
   * ediyorsa onunla çalıştır (read-only listeleme araçları için güvenli:
   * en kötü sonuç filtresiz liste). Yazma araçlarında ASLA kullanılmaz.
   */
  allowEmptyArgsFallback?: boolean;
  argsSchema: TArgs;
  execute: (
    app: FastifyInstance,
    context: AgentToolContext,
    args: z.output<TArgs>,
  ) => Promise<Record<string, unknown>>;
};

const AGENT_TOOL_SELECTION_HINTS: Record<string, AgentToolSelectionHints> = {
  "system.capabilities": {
    purpose:
      "Inspect Elyan's own installed tools, skills and connected integrations before claiming or refusing a capability.",
    intents: ["chat", "planning", "automation"],
    capabilities: [],
    desiredOutputKinds: ["chat_reply"],
    resultBlockTypes: ["tool_call"],
    modelContract:
      "system.capabilities {section?:\"all\"|\"tools\"|\"skills\"|\"connectors\"}",
  },
  "web.search": {
    purpose: "Search current public-web evidence for research or time-sensitive questions.",
    intents: ["research", "document"],
    capabilities: ["browser.read"],
    desiredOutputKinds: ["chat_reply", "pdf", "docx", "artifact"],
    resultBlockTypes: ["web_search", "tool_call"],
    modelContract: "web.search {query:string}",
  },
  "web.fetch_url": {
    purpose: "Read one explicit public URL after the user supplies it or research identifies it.",
    intents: ["research", "document"],
    capabilities: ["browser.read", "document.read"],
    desiredOutputKinds: ["chat_reply", "pdf", "docx", "artifact"],
    resultBlockTypes: ["web_search", "tool_call"],
    modelContract: "web.fetch_url {url:string}",
  },
  "web.numeric_facts": {
    purpose: "Extract verified numeric series suitable for tables and charts from public-web evidence.",
    intents: ["research", "math", "document"],
    capabilities: ["browser.read", "table.generate", "chart.generate"],
    desiredOutputKinds: ["table", "chart", "xlsx"],
    resultBlockTypes: ["table", "chart", "web_search", "tool_call"],
    modelContract: "web.numeric_facts {query:string}",
    authoritativeArtifactAdapter: "numeric_points.v1",
  },
  "memory.query": {
    purpose: "Read durable user memory only when the user explicitly refers to prior preferences or conversations.",
    intents: ["chat", "planning"],
    capabilities: ["memory.query"],
    desiredOutputKinds: ["chat_reply"],
    resultBlockTypes: ["memory_echo", "tool_call"],
    modelContract: "memory.query {query:string, limit?:1..10}",
  },
  "memory.write": {
    purpose: "Persist an explicit user fact, correction, preference, or forget request.",
    intents: ["chat"],
    capabilities: ["memory.write"],
    desiredOutputKinds: ["chat_reply", "action"],
    resultBlockTypes: ["memory_echo", "tool_call"],
    modelContract: "memory.write {op, kind, key, value, confidence?, ttl_days?}",
  },
  "goals.get": {
    purpose: "Read the active goal and its recent execution events before continuing goal work.",
    intents: ["planning", "automation"],
    capabilities: ["goal.read"],
    desiredOutputKinds: ["chat_reply", "task_result"],
    resultBlockTypes: ["goal_progress", "tool_call"],
    modelContract: "goals.get {goalId?:uuid, eventLimit?:1..50}",
  },
  "goals.update": {
    purpose: "Open, advance, complete, or block an explicit durable user goal.",
    intents: ["planning", "automation"],
    capabilities: ["goal.update"],
    desiredOutputKinds: ["action", "task_result"],
    resultBlockTypes: ["goal_progress", "tool_call"],
    modelContract: "goals.update {action, goalId?, title?, description?, step?, ofSteps?, advancedTo?, next?, note?, blocker?}",
  },
  "gmail.search": {
    purpose: "Search or list messages in the user's connected Gmail account.",
    intents: ["research", "chat", "planning"],
    capabilities: ["gmail.read"],
    desiredOutputKinds: ["chat_reply", "task_result"],
    resultBlockTypes: ["mail_list", "tool_call"],
    modelContract: "gmail.search {query:string, limit?:1..10}",
    connectorCapability: "gmail",
  },
  "gmail.read": {
    purpose: "Read one exact Gmail message selected by a trusted message identifier.",
    intents: ["research", "chat", "planning"],
    capabilities: ["gmail.read"],
    desiredOutputKinds: ["chat_reply", "task_result"],
    resultBlockTypes: ["mail_detail", "tool_call"],
    modelContract: "gmail.read {messageId:string}",
    connectorCapability: "gmail",
  },
  "calendar.list_events": {
    purpose: "List events from the user's connected calendar.",
    intents: ["chat", "planning", "automation"],
    capabilities: ["calendar.read"],
    desiredOutputKinds: ["chat_reply", "task_result"],
    resultBlockTypes: ["calendar_agenda", "tool_call"],
    modelContract: "calendar.list_events {query?:string, days?:1..60, limit?:1..20}",
    connectorCapability: "calendar",
  },
  "drive.search": {
    purpose: "Search files in the user's connected Google Drive.",
    intents: ["research", "document", "chat"],
    capabilities: ["drive.read"],
    desiredOutputKinds: ["chat_reply", "task_result"],
    resultBlockTypes: ["drive_files", "tool_call"],
    modelContract: "drive.search {query:string, limit?:1..20}",
    connectorCapability: "drive",
  },
  "notion.search": {
    purpose: "Search pages and databases in the user's connected Notion workspace.",
    intents: ["research", "document", "chat"],
    capabilities: ["notion.read"],
    desiredOutputKinds: ["chat_reply", "task_result"],
    resultBlockTypes: ["notion_page", "tool_call"],
    modelContract: "notion.search {query?:string, limit?:1..20}",
    connectorCapability: "notion",
  },
  "github.search": {
    purpose: "Search issues and pull requests connected to the user's GitHub account.",
    intents: ["research", "coding", "planning"],
    capabilities: ["github.read"],
    desiredOutputKinds: ["chat_reply", "task_result"],
    resultBlockTypes: ["github_activity", "tool_call"],
    modelContract: "github.search {query?:string, limit?:1..20}",
    connectorCapability: "github",
  },
  "slack.search": {
    purpose: "Search messages in the user's connected Slack workspace.",
    intents: ["research", "chat", "planning"],
    capabilities: ["slack.read"],
    desiredOutputKinds: ["chat_reply", "task_result"],
    resultBlockTypes: ["slack_messages", "tool_call"],
    modelContract: "slack.search {query?:string, limit?:1..20}",
    connectorCapability: "slack",
  },
  "gmail.send": {
    purpose: "Stage an explicit Gmail send request for user approval; never send inline.",
    intents: ["chat", "automation"],
    capabilities: ["gmail.send"],
    desiredOutputKinds: ["action", "task_result"],
    resultBlockTypes: ["actionable", "tool_call"],
    modelContract: "gmail.send {to:string, subject:string, body:string, cc?:string, bcc?:string}",
    connectorCapability: "gmail",
  },
  "calendar.create_event": {
    purpose: "Stage an explicit calendar event creation request for user approval; never create inline.",
    intents: ["planning", "automation", "chat"],
    capabilities: ["calendar.write"],
    desiredOutputKinds: ["action", "task_result"],
    resultBlockTypes: ["actionable", "tool_call"],
    modelContract: "calendar.create_event {title:string, start:ISO8601, end:ISO8601, description?:string, location?:string, attendees?:string[]}",
    connectorCapability: "calendar",
  },
};

const webSearchArgsSchema = z.object({
  query: z.string().trim().min(1).max(320),
});

const webFetchUrlArgsSchema = z.object({
  url: z.string().trim().url().max(2_000),
});

const memoryQueryArgsSchema = z.object({
  query: z.string().trim().min(1).max(320),
  limit: z.coerce.number().int().min(1).max(10).default(5),
});

const memoryWriteArgsSchema = z.object({
  op: z.enum(["write", "update", "contest", "forget"]).default("write"),
  kind: z.enum(["fact", "preference", "episode", "self_model"]),
  key: z.string().trim().min(1).max(160),
  value: z.string().trim().max(2_000).default(""),
  confidence: z.coerce.number().min(0).max(1).default(0.7),
  ttl_days: z.coerce.number().int().positive().max(3650).optional(),
}).superRefine((value, ctx) => {
  if (value.op !== "forget" && value.value.length === 0) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["value"], message: "value is required" });
  }
});

const goalsUpdateArgsSchema = z.object({
  goalId: z.string().uuid().optional(),
  action: z.enum(["open", "advance", "complete", "block"]),
  title: z.string().trim().min(1).max(200).optional(),
  description: z.string().trim().max(4_000).optional(),
  step: z.coerce.number().int().min(0).max(20).optional(),
  ofSteps: z.coerce.number().int().min(1).max(20).optional(),
  advancedTo: z.string().trim().min(1).max(400).optional(),
  next: z.string().trim().min(1).max(400).optional(),
  note: z.string().trim().min(1).max(400).optional(),
  blocker: z.string().trim().min(1).max(400).optional(),
});

const goalsGetArgsSchema = z.object({
  goalId: z.string().uuid().optional(),
  eventLimit: z.coerce.number().int().min(1).max(50).default(12),
});

const systemCapabilitiesArgsSchema = z.object({
  /** Narrow the answer instead of returning the whole inventory. */
  section: z
    .enum(["all", "tools", "skills", "connectors"])
    .default("all"),
});

const systemCapabilitiesOutputSchema = z.object({
  tools: z.array(
    z.object({
      name: z.string(),
      permission: z.string(),
      purpose: z.string(),
      contract: z.string(),
      available: z.boolean(),
      requiresConnection: z.boolean(),
    }),
  ),
  skills: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      purpose: z.string(),
      slashCommand: z.string().nullable(),
      produces: z.array(z.string()),
    }),
  ),
  connectedCapabilities: z.array(z.string()),
  notes: z.array(z.string()),
});

const webSearchOutputSchema = z.object({
  used: z.boolean(),
  query: z.string(),
  results: z.array(z.object({ title: z.string(), url: z.string() }).passthrough()),
}).passthrough();
const webFetchUrlOutputSchema = z.object({
  url: z.string(),
  title: z.string(),
  content: z.string(),
  source: z.enum(["jina", "html_fallback"]),
  sourceAuthority: z.enum(["official", "trusted", "standard", "low"]),
  retrievedAt: z.string(),
  contentLength: z.number().int().nonnegative(),
  error: z.string().optional(),
}).passthrough();
const numericFactsOutputSchema = z.object({
  query: z.string(), hasNumericFacts: z.boolean(), hasChartableSeries: z.boolean(), points: z.array(z.unknown()),
}).passthrough();
const memoryQueryOutputSchema = z.object({
  retrievalMode: z.string(), results: z.array(z.object({ id: z.string(), confidence: z.number() }).passthrough()),
}).passthrough();
const memoryWriteOutputSchema = z.object({
  processed: z.number().int().nonnegative(), factsWritten: z.number().int().nonnegative(), episodesWritten: z.number().int().nonnegative(),
}).passthrough();
const goalOutputSchema = z.object({ goal: z.record(z.string(), z.unknown()).nullable() }).passthrough();
const goalContextOutputSchema = z.object({ goal: z.record(z.string(), z.unknown()).nullable(), events: z.array(z.unknown()) }).passthrough();

const gmailSearchArgsSchema = z.object({
  // "Mailleri oku" gibi sorgusuz isteklerde model boş/eksik query üretir;
  // boş sorgu gelen kutusu listelemek demektir. min(1) burada canlıda
  // invalid_tool_args → "araç kataloğu doğrulayamıyor" hatasına dönüşüyordu.
  query: z
    .string()
    .trim()
    .max(400)
    .default("in:inbox")
    .transform((value) => (value.length > 0 ? value : "in:inbox")),
  limit: z.coerce.number().int().min(1).max(10).default(5),
});
const gmailReadArgsSchema = z.object({
  messageId: z.string().trim().min(1).max(120),
});
const calendarListArgsSchema = z.object({
  query: z.string().trim().max(200).optional(),
  days: z.coerce.number().int().min(1).max(60).default(7),
  limit: z.coerce.number().int().min(1).max(20).default(10),
});
const driveSearchArgsSchema = z.object({
  query: z.string().trim().max(240).default(""),
  limit: z.coerce.number().int().min(1).max(20).default(10),
});
const notionSearchArgsSchema = z.object({
  query: z.string().trim().max(240).default(""),
  limit: z.coerce.number().int().min(1).max(20).default(10),
});
const githubSearchArgsSchema = z.object({
  query: z.string().trim().max(240).default(""),
  limit: z.coerce.number().int().min(1).max(20).default(10),
});
const slackSearchArgsSchema = z.object({
  query: z.string().trim().max(240).default(""),
  limit: z.coerce.number().int().min(1).max(20).default(10),
});
const gmailSendArgsSchema = z.object({
  to: z.string().trim().email().max(320),
  subject: z.string().trim().min(1).max(320),
  body: z.string().trim().min(1).max(10_000),
  cc: z.string().trim().email().max(320).optional(),
  bcc: z.string().trim().email().max(320).optional(),
});
const calendarCreateArgsSchema = z.object({
  title: z.string().trim().min(1).max(320),
  start: z.string().trim().datetime({ offset: true }),
  end: z.string().trim().datetime({ offset: true }),
  description: z.string().trim().max(4_000).optional(),
  location: z.string().trim().max(320).optional(),
  attendees: z.array(z.string().trim().email().max(320)).max(25).optional(),
});
const connectorListOutputSchema = z.object({
  resultCount: z.number().int().nonnegative(),
  results: z.array(z.unknown()),
}).passthrough();
const connectorMessageOutputSchema = z.object({
  messageId: z.string(),
}).passthrough();
const gmailSendOutputSchema = z.object({
  messageId: z.string(),
  sent: z.boolean(),
}).passthrough();
const calendarCreateOutputSchema = z.object({
  eventId: z.string(),
  created: z.boolean(),
}).passthrough();

/**
 * Model kaynaklı yaygın argüman bozulmalarını deterministik onarır (tek
 * "retry" budur — ikinci model çağrısı yok, maliyet sıfır):
 * 1. args JSON string geldiyse parse et
 * 2. args {arguments:{...}} / {input:{...}} / {params:{...}} sarmalandıysa aç
 * Onarım şemayı ASLA gevşetmez; parse yine schema'dan geçer.
 */
function normalizeToolArgs(raw: unknown): unknown {
  let args = raw;
  if (typeof args === "string") {
    const trimmed = args.trim();
    if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
      try {
        args = JSON.parse(trimmed);
      } catch {
        return raw;
      }
    }
  }
  if (args && typeof args === "object" && !Array.isArray(args)) {
    const record = args as Record<string, unknown>;
    const keys = Object.keys(record);
    if (keys.length === 1 && ["arguments", "input", "params"].includes(keys[0])) {
      const inner = record[keys[0]];
      if (inner && typeof inner === "object" && !Array.isArray(inner)) {
        return inner;
      }
    }
  }
  return args;
}

/**
 * Alias onarımı + null temizliği. Kanonik anahtar eksik/boşken bilinen bir
 * varyant doluysa değeri kanonik anahtara taşır; null değerler silinir ki
 * şema default'ları devreye girebilsin ({query: null} → {} → "in:inbox").
 * Şemayı gevşetmez: sonuç yine tool.argsSchema.parse'tan geçer.
 */
function applyArgAliases(
  raw: unknown,
  aliases: Record<string, string[] | undefined> | undefined,
): unknown {
  if (!aliases || !raw || typeof raw !== "object" || Array.isArray(raw)) {
    return raw;
  }
  const record: Record<string, unknown> = { ...(raw as Record<string, unknown>) };
  for (const key of Object.keys(record)) {
    if (record[key] === null || record[key] === undefined) {
      delete record[key];
    }
  }
  for (const [canonical, variants] of Object.entries(aliases)) {
    if (!variants) continue;
    const current = record[canonical];
    const missing =
      current === undefined ||
      (typeof current === "string" && current.trim().length === 0);
    if (!missing) continue;
    for (const variant of variants) {
      const value = record[variant];
      if (value !== undefined && value !== null) {
        record[canonical] = value;
        break;
      }
    }
  }
  return record;
}

function compactError(error: unknown): { code: string; message: string } {
  if (error instanceof z.ZodError) {
    // Alan yolu + beklenen tip: refinement prompt'u bu mesajı modele geri
    // taşıyor — "Invalid arguments" yerine düzeltilebilir bir tarif ver.
    const detail = error.issues
      .slice(0, 3)
      .map((issue) => `${issue.path.join(".") || "args"}: ${issue.message}`)
      .join("; ");
    return {
      code: "invalid_tool_args",
      message: detail || "Invalid tool arguments.",
    };
  }
  if (error && typeof error === "object") {
    const record = error as Record<string, unknown>;
    const code = typeof record.code === "string" ? record.code : "tool_failed";
    const message = typeof record.message === "string" ? record.message : "Tool failed.";
    return { code, message };
  }
  return { code: "tool_failed", message: "Tool failed." };
}

function sideEffectBlocked(tool: AgentToolDefinition<z.ZodTypeAny>): AgentToolResult {
  return {
    tool: tool.name,
    ok: false,
    permission: tool.permission,
    durationMs: 0,
    output: null,
    error: {
      code: "tool_side_effect_requires_approval",
      message: "This tool requires explicit approval before it can write state.",
    },
  };
}

function stateWriteBlocked(tool: AgentToolDefinition<z.ZodTypeAny>): AgentToolResult {
  return {
    tool: tool.name,
    ok: false,
    permission: tool.permission,
    durationMs: 0,
    output: null,
    error: {
      code: "tool_write_requires_state_policy",
      message: "This tool requires the agent state-write policy to be enabled.",
    },
  };
}

async function resolveGoalIdForUpdate(
  app: FastifyInstance,
  context: AgentToolContext,
  explicitGoalId: string | undefined,
): Promise<string> {
  if (explicitGoalId) {
    return explicitGoalId;
  }
  const active = await getActiveGoalForContext(app, {
    userId: context.userId,
    sessionId: context.sessionId ?? null,
  });
  if (!active?.id) {
    throw new z.ZodError([
      {
        code: "custom",
        path: ["goalId"],
        message: "No active goal found for this session.",
      },
    ]);
  }
  return active.id;
}

function resolveGoalProgressText(args: z.output<typeof goalsUpdateArgsSchema>): string {
  return args.advancedTo ?? args.next ?? args.note ?? args.title ?? "advanced";
}

const toolDefinitions = [
  {
    /**
     * Lets Elyan inspect its own installation.
     *
     * Without this the assistant can only guess at what it is able to do, which
     * is why it both refused things it could do and promised things it could
     * not. The answer is read from the same registries that actually gate
     * execution — the tool list, the skill registry, and the user's connected
     * capabilities — so "what can you do" is answered from the system's real
     * state rather than from prompt text that drifts as features change.
     */
    name: "system.capabilities",
    permission: "read",
    idempotency: "read_only",
    timeoutMs: 3_000,
    outputSchema: systemCapabilitiesOutputSchema,
    argsSchema: systemCapabilitiesArgsSchema,
    async execute(app, context, args) {
      const section = args.section ?? "all";
      const wantTools = section === "all" || section === "tools";
      const wantSkills = section === "all" || section === "skills";
      const wantConnectors = section === "all" || section === "connectors";

      const connected =
        wantConnectors || wantTools
          ? await listConnectedCapabilityGrants(app, context.userId).catch(
              () => [] as Array<{ capabilities: string[] }>,
            )
          : [];
      const connectedCapabilities = [
        ...new Set(
          connected.flatMap((grant) =>
            (grant.capabilities ?? [])
              .map((capability) => String(capability).trim())
              .filter(Boolean),
          ),
        ),
      ];

      const tools = !wantTools
        ? []
        : listAgentTools().flatMap((entry) => {
            const metadata = getAgentToolMetadata(entry.name);
            if (!metadata) return [];
            const requiredCapability =
              metadata.selectionHints.connectorCapability ?? null;
            return [
              {
                name: metadata.name,
                permission: metadata.permission,
                purpose: metadata.selectionHints.purpose,
                contract: metadata.selectionHints.modelContract,
                // A connector tool the user has not linked is real but
                // unusable; saying so is what stops it being promised.
                available:
                  !requiredCapability ||
                  connectedCapabilities.includes(requiredCapability),
                requiresConnection: Boolean(requiredCapability),
              },
            ];
          });

      const skills = !wantSkills
        ? []
        : (
            await listActiveSkillSummaries().catch(() => [] as SkillSummary[])
          ).map((skill) => ({
            id: skill.id,
            name: skill.displayName || skill.name,
            purpose: skill.purpose ?? skill.summary ?? "",
            slashCommand: skill.slashCommand ?? null,
            produces: Array.isArray(skill.produces)
              ? skill.produces.map((item) => String(item))
              : [],
          }));

      const notes: string[] = [];
      if (wantTools && tools.some((tool) => !tool.available)) {
        notes.push(
          "Bağlantısı olmayan araçlar listede 'available:false' ile işaretlidir; bunları yapabileceğini söyleme, önce bağlanmasını iste.",
        );
      }
      return { tools, skills, connectedCapabilities, notes };
    },
  },
  {
    name: "web.search",
    permission: "read",
    idempotency: "read_only",
    timeoutMs: 7_000,
    outputSchema: webSearchOutputSchema,
    argsSchema: webSearchArgsSchema,
    async execute(app, context, args) {
      const grounding = await searchPublicWebGrounding(app, {
        prompt: args.query,
        workload: context.workload,
      });
      return {
        used: grounding.used,
        query: grounding.query,
        queries: grounding.queries,
        source: grounding.source,
        confidence: grounding.confidence,
        degradedReason: grounding.degradedReason,
        retrievedAt: grounding.retrievedAt,
        results: grounding.results.slice(0, 4).map((result) => ({
          title: result.title,
          url: result.url,
          sourceHost: result.sourceHost,
          sourceAuthority: result.sourceAuthority,
          snippet: result.snippet,
          verificationState: result.verificationState,
        })),
      };
    },
  },
  {
    name: "web.fetch_url",
    permission: "read",
    idempotency: "read_only",
    timeoutMs: 8_000,
    outputSchema: webFetchUrlOutputSchema,
    argsSchema: webFetchUrlArgsSchema,
    async execute(app, _context, args) {
      return fetchUrlContext(app, args.url);
    },
  },
  {
    name: "web.numeric_facts",
    permission: "read",
    idempotency: "read_only",
    timeoutMs: 7_000,
    outputSchema: numericFactsOutputSchema,
    argsSchema: webSearchArgsSchema,
    async execute(app, context, args) {
      const grounding = await searchPublicWebGrounding(app, {
        prompt: args.query,
        workload: context.workload,
      });
      const evidence = extractNumericEvidenceFromGrounding(grounding);
      return {
        query: grounding.query,
        hasNumericFacts: evidence.hasNumericFacts,
        hasChartableSeries: evidence.hasChartableSeries,
        points: evidence.points,
        degradedReason: grounding.degradedReason,
      };
    },
  },
  {
    name: "memory.query",
    permission: "read",
    idempotency: "read_only",
    timeoutMs: 4_000,
    outputSchema: memoryQueryOutputSchema,
    argsSchema: memoryQueryArgsSchema,
    async execute(app, context, args) {
      const memory = await searchBrainMemory(app, {
        userId: context.userId,
        query: args.query,
        limit: args.limit,
      });
      return {
        retrievalMode: memory.retrievalMode,
        degradedReason: memory.degradedReason ?? null,
        results: memory.results.map((result) => ({
          id: result.id,
          source: result.memorySource,
          type: result.memoryType,
          title: result.title,
          content: result.content,
          confidence: result.confidence,
          staleness: result.staleness,
          score: result.score,
        })),
      };
    },
  },
  {
    name: "memory.write",
    permission: "write",
    idempotency: "internal_state_write",
    approvalScope: "internal_state",
    timeoutMs: 5_000,
    outputSchema: memoryWriteOutputSchema,
    argsSchema: memoryWriteArgsSchema,
    async execute(app, context, args) {
      const envelope = {
        reply: { text: "", lang: "tr", tone: "neutral" },
        blocks: [],
        memory_ops: [args],
        goal_ops: [],
        follow_ups: [],
        tool_requests: [],
        affect: { user_mood_guess: "unknown", energy: "mid", register: "neutral" },
      } satisfies TurnEnvelope;
      const result = isCognitiveFoundationEnabled(app, context.userId)
        ? await cognitiveMemoryRepository(app).writeTurn({
            userId: context.userId,
            sessionId: context.sessionId ?? null,
            sourceKind: "turn_envelope",
            sourceId: context.sessionId ?? null,
            envelope,
          })
        : await recordTurnMemoryOps(app, {
            userId: context.userId,
            sessionId: context.sessionId ?? null,
            envelope,
          });
      return result;
    },
  },
  {
    name: "goals.get",
    permission: "read",
    idempotency: "read_only",
    timeoutMs: 3_000,
    outputSchema: goalContextOutputSchema,
    argsSchema: goalsGetArgsSchema,
    async execute(app, context, args) {
      const execution = await getGoalExecutionContext(app, {
        userId: context.userId,
        sessionId: context.sessionId ?? null,
        goalId: args.goalId,
        eventLimit: args.eventLimit,
      });
      return {
        goal: execution.goal,
        events: execution.events.map((event) => ({
          ...event,
          createdAt: event.createdAt.toISOString(),
        })),
      };
    },
  },
  {
    name: "goals.update",
    permission: "write",
    idempotency: "internal_state_write",
    approvalScope: "internal_state",
    timeoutMs: 5_000,
    outputSchema: goalOutputSchema,
    argsSchema: goalsUpdateArgsSchema,
    async execute(app, context, args) {
      if (args.action === "open") {
        const opened = await createGoal(app, {
          userId: context.userId,
          sessionId: context.sessionId ?? undefined,
          title: args.title ?? args.advancedTo ?? args.next ?? "Open goal",
          description: args.description,
        });
        return { goal: opened.goal };
      }
      const goalId = await resolveGoalIdForUpdate(app, context, args.goalId);
      if (args.action === "complete") {
        const updated = await updateGoal(app, {
          userId: context.userId,
          goalId,
          status: "done",
        });
        return { goal: updated.goal };
      }
      if (args.action === "block") {
        const advanced = await advanceGoal(app, {
          userId: context.userId,
          goalId,
          step: args.step ?? 0,
          ofSteps: args.ofSteps ?? 1,
          advancedTo: resolveGoalProgressText(args),
          blocker: args.blocker ?? args.next ?? "blocked",
        });
        return { goal: advanced.goal };
      }
      const advanced = await advanceGoal(app, {
        userId: context.userId,
        goalId,
        step: args.step ?? 1,
        ofSteps: args.ofSteps ?? 1,
        advancedTo: resolveGoalProgressText(args),
      });
      return { goal: advanced.goal };
    },
  },
  {
    name: "gmail.search",
    permission: "read",
    idempotency: "read_only",
    timeoutMs: 12_000,
    outputSchema: connectorListOutputSchema,
    argAliases: {
      query: ["q", "search", "search_query", "searchQuery", "text", "keywords"],
      limit: ["max", "max_results", "maxResults", "count", "n"],
    },
    allowEmptyArgsFallback: true,
    argsSchema: gmailSearchArgsSchema,
    async execute(app, context, args) {
      return executeGmailSearch(app, context.userId, args);
    },
  },
  {
    name: "gmail.read",
    permission: "read",
    idempotency: "read_only",
    timeoutMs: 12_000,
    outputSchema: connectorMessageOutputSchema,
    argAliases: {
      messageId: ["id", "message_id", "messageID", "mail_id", "email_id"],
    },
    argsSchema: gmailReadArgsSchema,
    async execute(app, context, args) {
      return executeGmailRead(app, context.userId, args);
    },
  },
  {
    name: "calendar.list_events",
    permission: "read",
    idempotency: "read_only",
    timeoutMs: 12_000,
    outputSchema: connectorListOutputSchema,
    argAliases: {
      query: ["q", "search", "text"],
      days: ["day", "range_days", "window_days"],
      limit: ["max", "max_results", "maxResults", "count", "n"],
    },
    allowEmptyArgsFallback: true,
    argsSchema: calendarListArgsSchema,
    async execute(app, context, args) {
      return executeCalendarListEvents(app, context.userId, args);
    },
  },
  {
    name: "drive.search",
    permission: "read",
    idempotency: "read_only",
    timeoutMs: 12_000,
    outputSchema: connectorListOutputSchema,
    argAliases: {
      query: ["q", "search", "text", "name", "filename", "file_name"],
      limit: ["max", "max_results", "maxResults", "count", "n"],
    },
    allowEmptyArgsFallback: true,
    argsSchema: driveSearchArgsSchema,
    async execute(app, context, args) {
      return executeDriveSearch(app, context.userId, args);
    },
  },
  {
    name: "notion.search",
    permission: "read",
    idempotency: "read_only",
    timeoutMs: 12_000,
    outputSchema: connectorListOutputSchema,
    argAliases: {
      query: ["q", "search", "text", "title", "keywords"],
      limit: ["max", "max_results", "maxResults", "count", "n", "page_size"],
    },
    allowEmptyArgsFallback: true,
    argsSchema: notionSearchArgsSchema,
    async execute(app, context, args) {
      return executeNotionSearch(app, context.userId, args);
    },
  },
  {
    name: "github.search",
    permission: "read",
    idempotency: "read_only",
    timeoutMs: 12_000,
    outputSchema: connectorListOutputSchema,
    argAliases: {
      query: ["q", "search", "text", "keywords"],
      limit: ["max", "max_results", "maxResults", "count", "n", "per_page"],
    },
    allowEmptyArgsFallback: true,
    argsSchema: githubSearchArgsSchema,
    async execute(app, context, args) {
      return executeGithubSearch(app, context.userId, args);
    },
  },
  {
    name: "slack.search",
    permission: "read",
    idempotency: "read_only",
    timeoutMs: 12_000,
    outputSchema: connectorListOutputSchema,
    argAliases: {
      query: ["q", "search", "text", "keywords"],
      limit: ["max", "max_results", "maxResults", "count", "n"],
    },
    allowEmptyArgsFallback: true,
    argsSchema: slackSearchArgsSchema,
    async execute(app, context, args) {
      return executeSlackSearch(app, context.userId, args);
    },
  },
  {
    // side_effect: executeAgentTool blocks this unless context.allowSideEffects
    // is set, which only the post-approval resume does. The model can draft it,
    // but the send never reaches Google without the user's explicit approval.
    name: "gmail.send",
    permission: "side_effect",
    idempotency: "non_idempotent",
    timeoutMs: 15_000,
    outputSchema: gmailSendOutputSchema,
    argsSchema: gmailSendArgsSchema,
    async execute(app, context, args) {
      return executeGmailSend(app, context.userId, args);
    },
  },
  {
    name: "calendar.create_event",
    permission: "side_effect",
    idempotency: "non_idempotent",
    timeoutMs: 15_000,
    outputSchema: calendarCreateOutputSchema,
    argsSchema: calendarCreateArgsSchema,
    async execute(app, context, args) {
      return executeCalendarCreateEvent(app, context.userId, args);
    },
  },
] satisfies Array<AgentToolDefinition<z.ZodTypeAny>>;

const registry = new Map<string, AgentToolDefinition<z.ZodTypeAny>>(
  toolDefinitions.map((tool) => [tool.name, tool]),
);

export function listAgentTools(): Array<{ name: string; permission: AgentToolPermission }> {
  return toolDefinitions.map((tool) => ({
    name: tool.name,
    permission: tool.permission,
  }));
}

export type AgentToolMetadata = {
  name: string;
  permission: AgentToolPermission;
  timeoutMs: number;
  idempotency: ApprovalToolIdempotency;
  approvalScope: ApprovalToolScope;
  parallelSafe: boolean;
  selectionHints: AgentToolSelectionHints;
};

export type AgentToolCatalogEntry = AgentToolMetadata & {
  selectionConfidence: number;
  selectionReasons: string[];
};

export function getAgentToolMetadata(name: string): AgentToolMetadata | null {
  const tool = registry.get(name);
  if (!tool) return null;
  const selectionHints = AGENT_TOOL_SELECTION_HINTS[name];
  if (!selectionHints) return null;
  const idempotency = tool.idempotency ?? (tool.permission === "read" ? "read_only" : "non_idempotent");
  return {
    name: tool.name,
    permission: tool.permission,
    timeoutMs: Math.max(100, Math.min(tool.timeoutMs ?? 8_000, 30_000)),
    idempotency,
    approvalScope: tool.approvalScope ?? "user_action",
    parallelSafe: tool.permission === "read" && idempotency === "read_only",
    selectionHints,
  };
}

function normalizeSelectionText(value: string): string {
  return value.toLocaleLowerCase("tr-TR").replace(/\s+/g, " ").trim();
}

function hasAnySelectionValue(
  left: readonly string[] | undefined,
  right: readonly string[],
): boolean {
  if (!left || left.length === 0) return false;
  const normalized = new Set(left.map((value) => normalizeSelectionText(value)));
  return right.some((value) => normalized.has(normalizeSelectionText(value)));
}

function scoreCoreToolForTurn(
  tool: AgentToolMetadata,
  input: AgentToolSelectionContext,
): { confidence: number; reasons: string[] } | null {
  const prompt = normalizeSelectionText(input.prompt);
  const intent = normalizeSelectionText(input.intent ?? "");
  const desiredOutputKinds = input.desiredOutputKinds ?? [];
  const requiredCapabilities = input.requiredCapabilities ?? [];
  const hint = tool.selectionHints;
  const reasons: string[] = [];

  const intentMatch = Boolean(intent && hint.intents.includes(intent));
  const capabilityMatch = hasAnySelectionValue(
    requiredCapabilities,
    hint.capabilities,
  );
  const outputMatch = hasAnySelectionValue(
    desiredOutputKinds,
    hint.desiredOutputKinds,
  );

  if (tool.name === "system.capabilities") {
    // Deliberately broad. "Ne yapabiliyorsun", "hangi araçların var", "bunu
    // yapabilir misin" are the turns where a wrong answer costs the most
    // trust, and the tool is read-only and cheap, so a false positive is
    // nearly free while a false negative produces a confident lie.
    const selfQuery =
      /(?<!\p{L})(ne\s+yapabil\p{L}*|neler\s+yapabil\p{L}*|yapabilir\s+misin|hangi\s+(araç|arac|yetenek|skill|beceri|özellik|ozellik)\p{L}*|araçlar\p{L}*|yeteneklerin|becerilerin|özelliklerin|ozelliklerin|kendini\s+tanıt|nelere\s+erişebil\p{L}*|erişimin\s+var|bağlı\s+mı|bagli\s+mi|what\s+can\s+you\s+do|your\s+(tools|skills|capabilities)|can\s+you\s+(do|access))(?!\p{L})/iu.test(
        prompt,
      );
    if (!selfQuery && !capabilityMatch) return null;
    reasons.push(selfQuery ? "self_capability_query" : "capability_match");
    return { confidence: selfQuery ? 0.94 : 0.78, reasons };
  }

  if (tool.name === "web.search") {
    const explicitResearch =
      intent === "research" ||
      // "bugün"/"latest" alone are time words, not research requests: they fire
      // on "bugün hava çok güzel" just as readily as on a real query. They now
      // count only alongside another research signal; the semantic layer covers
      // the genuine time-sensitive phrasings this drops.
      /(?<!\p{L})(araştır\p{L}*|arastir\p{L}*|research\p{L}*|güncel|guncel|kaynak\p{L}*|source\p{L}*|internetten|webden)(?!\p{L})/iu.test(
        prompt,
      );
    if (!explicitResearch && !capabilityMatch) return null;
    reasons.push(explicitResearch ? "explicit_research" : "capability_match");
    return { confidence: explicitResearch ? 0.92 : 0.82, reasons };
  }

  if (tool.name === "web.fetch_url") {
    const explicitUrl = /https?:\/\/[^\s]+/iu.test(input.prompt);
    if (!explicitUrl && intent !== "research") return null;
    reasons.push(explicitUrl ? "explicit_url" : "research_followup");
    return { confidence: explicitUrl ? 0.96 : 0.76, reasons };
  }

  if (tool.name === "web.numeric_facts") {
    const numericOutput = desiredOutputKinds.some((kind) =>
      ["table", "chart", "xlsx"].includes(kind),
    );
    const numericPrompt =
      /(?<!\p{L})(veri|istatistik|oran|fiyat|kur|trend|seri|grafik|chart|tablo|table)(?!\p{L})/iu.test(
        prompt,
      );
    if (!numericOutput || (!numericPrompt && intent !== "research")) return null;
    reasons.push("numeric_output", numericPrompt ? "numeric_prompt" : "research_intent");
    return { confidence: 0.88, reasons };
  }

  if (tool.name === "memory.query") {
    const explicitMemoryRead =
      /(?<!\p{L})(hatırl\p{L}*|hatirla\p{L}*|daha önce|daha once|geçen sefer|gecen sefer|önceden|onceden|tercihim|beni tanıyor|beni taniyor|remember|previously|last time)(?!\p{L})/iu.test(
        prompt,
      );
    if (!explicitMemoryRead) return null;
    return { confidence: 0.9, reasons: ["explicit_memory_read"] };
  }

  if (tool.name === "memory.write") {
    if ((input.memoryCandidateCount ?? 0) <= 0) return null;
    return { confidence: 0.96, reasons: ["typed_memory_candidate"] };
  }

  if (tool.name === "goals.get" || tool.name === "goals.update") {
    const explicitGoal =
      /(?<!\p{L})(hedef\p{L}*|goal\p{L}*|ilerle\p{L}*|tamamla\p{L}*|planımı|planimi|görev planı|gorev plani)(?!\p{L})/iu.test(
        prompt,
      );
    if (!explicitGoal) return null;
    if (
      tool.name === "goals.update" &&
      !/(?<!\p{L})(oluştur\p{L}*|olustur\p{L}*|aç\p{L}*|ac\p{L}*|başlat\p{L}*|baslat\p{L}*|güncelle\p{L}*|guncelle\p{L}*|ilerlet\p{L}*|tamamla\p{L}*|engelle\p{L}*|block\p{L}*|create\p{L}*|start\p{L}*|update\p{L}*|advance\p{L}*|complete\p{L}*)(?!\p{L})/iu.test(
        prompt,
      )
    ) {
      return null;
    }
    reasons.push(intentMatch ? "planning_intent" : "explicit_goal");
    return {
      confidence: tool.name === "goals.get" ? 0.88 : 0.82,
      reasons,
    };
  }

  if (!intentMatch && !capabilityMatch && !outputMatch) return null;
  if (intentMatch) reasons.push("intent_match");
  if (capabilityMatch) reasons.push("capability_match");
  if (outputMatch) reasons.push("output_match");
  return { confidence: 0.72, reasons };
}

/**
 * Runs after the deterministic scorer has declined, so an explicit phrasing
 * always keeps its higher confidence and its reason string. This only rescues
 * the paraphrases the patterns never anticipated.
 */
function scoreCoreToolFallbackSemantic(
  tool: AgentToolMetadata,
  input: AgentToolSelectionContext,
): { confidence: number; reasons: string[] } | null {
  const hint = input.coreToolHint;
  if (!hint || hint.tool !== tool.name) return null;
  if (!isSemanticSelectableTool(tool.name)) return null;
  return {
    confidence: semanticToolConfidence(hint.score),
    reasons: ["semantic_paraphrase_match"],
  };
}

function scoreConnectorToolForTurn(
  tool: AgentToolMetadata,
  input: AgentToolSelectionContext,
): { confidence: number; reasons: string[] } | null {
  if (!input.advertisedConnectorTools?.includes(tool.name)) return null;
  if (input.deterministicToolNames?.includes(tool.name)) {
    return { confidence: 1, reasons: ["typed_deterministic_action"] };
  }

  if (tool.permission === "read") {
    if (input.connectorReadHint?.tool === tool.name) {
      const score = Number.isFinite(input.connectorReadHint.score)
        ? Math.max(0, Math.min(1, input.connectorReadHint.score))
        : 0;
      return {
        confidence: score,
        reasons: ["connected_capability", "semantic_connector_hint"],
      };
    }
    const prompt = normalizeSelectionText(input.prompt);
    const deterministicRead =
      tool.name === "gmail.search"
        ? /(?=.*(?<!\p{L})(e-?posta\p{L}*|email\p{L}*|mail\p{L}*|gelen kutu\p{L}*|inbox)(?!\p{L}))(?=.*(?<!\p{L})(ara\p{L}*|bul\p{L}*|listele\p{L}*|göster\p{L}*|goster\p{L}*|kontrol\p{L}*|son|yeni|bugün|bugun|search\p{L}*|find\p{L}*|list\p{L}*|recent|latest)(?!\p{L}))/iu.test(
            prompt,
          )
        : tool.name === "calendar.list_events"
          ? /(?=.*(?<!\p{L})(takvim\p{L}*|etkinlik\p{L}*|toplantı\p{L}*|toplanti\p{L}*|calendar|event\p{L}*|meeting\p{L}*)(?!\p{L}))(?=.*(?<!\p{L})(listele\p{L}*|göster\p{L}*|goster\p{L}*|bak\p{L}*|bugün|bugun|yarın|yarin|yaklaşan|yaklasan|list\p{L}*|show\p{L}*|today|tomorrow|upcoming)(?!\p{L}))/iu.test(
              prompt,
            )
            : tool.name === "drive.search"
              ? /(?=.*(?<!\p{L})drive\p{L}*(?!\p{L}))(?=.*(?<!\p{L})(dosya\p{L}*|belge\p{L}*|doküman\p{L}*|dokuman\p{L}*|file\p{L}*|document\p{L}*)(?!\p{L}))(?=.*(?<!\p{L})(ara\p{L}*|bul\p{L}*|listele\p{L}*|göster\p{L}*|goster\p{L}*|son|yeni|benim|search\p{L}*|find\p{L}*|list\p{L}*|show\p{L}*|recent|latest|my)(?!\p{L}))/iu.test(
                  prompt,
                )
              : tool.name === "notion.search"
                ? /(?=.*(?<!\p{L})notion(?!\p{L}))(?=.*(?<!\p{L})(ara\p{L}*|bul\p{L}*|listele\p{L}*|göster\p{L}*|goster\p{L}*|benim|notlarım|notlarim|çalışma alan\p{L}*|calisma alan\p{L}*|search\p{L}*|find\p{L}*|list\p{L}*|show\p{L}*|my|workspace)(?!\p{L}))/iu.test(
                    prompt,
                  )
                : tool.name === "github.search"
                  ? /(?=.*(?<!\p{L})github(?!\p{L}))(?=.*(?<!\p{L})(issue\p{L}*|pull request\p{L}*|pr\p{L}*|repo\p{L}*|activity)(?!\p{L}))(?=.*(?<!\p{L})(ara\p{L}*|bul\p{L}*|listele\p{L}*|göster\p{L}*|goster\p{L}*|benim|search\p{L}*|find\p{L}*|list\p{L}*|show\p{L}*|my)(?!\p{L}))/iu.test(
                      prompt,
                    )
                  : tool.name === "slack.search"
                    ? /(?=.*(?<!\p{L})slack(?!\p{L}))(?=.*(?<!\p{L})(mesaj\p{L}*|kanal\p{L}*|message\p{L}*|channel\p{L}*)(?!\p{L}))(?=.*(?<!\p{L})(ara\p{L}*|bul\p{L}*|listele\p{L}*|göster\p{L}*|goster\p{L}*|benim|search\p{L}*|find\p{L}*|list\p{L}*|show\p{L}*|my)(?!\p{L}))/iu.test(
                        prompt,
                      )
                    : false;
    return deterministicRead
      ? {
          confidence: 0.88,
          reasons: ["connected_capability", "deterministic_connector_intent"],
        }
      : null;
  }

  if (input.sideEffectRequested !== true) return null;
  const prompt = normalizeSelectionText(input.prompt);
  if (
    /(?<!\p{L})(gönderme\p{L}*|gonderme\p{L}*|gönderilme\p{L}*|gonderilme\p{L}*|ekleme\p{L}*|oluşturma\p{L}*|olusturma\p{L}*|do not send|don't send|do not create|don't create|without sending|without creating)(?!\p{L})/iu.test(
      prompt,
    )
  ) {
    return null;
  }
  const explicitWrite =
    tool.name === "gmail.send"
      ? /(?=.*(?<!\p{L})(e-?posta\p{L}*|email\p{L}*|mail\p{L}*)(?!\p{L}))(?=.*(?<!\p{L})(gönder\p{L}*|gonder\p{L}*|send\p{L}*)(?!\p{L}))/iu.test(
          prompt,
        )
      : tool.name === "calendar.create_event"
        ? /(?=.*(?<!\p{L})(takvim\p{L}*|etkinlik\p{L}*|toplantı\p{L}*|toplanti\p{L}*|calendar|event|meeting)(?!\p{L}))(?=.*(?<!\p{L})(ekle\p{L}*|oluştur\p{L}*|olustur\p{L}*|planla\p{L}*|ayarla\p{L}*|create\p{L}*|add\p{L}*|schedule\p{L}*)(?!\p{L}))/iu.test(
            prompt,
          )
        : false;
  if (!explicitWrite) return null;
  return {
    confidence: 0.96,
    reasons: ["connected_capability", "explicit_side_effect"],
  };
}

export function buildAgentToolCatalogForTurn(
  input: AgentToolSelectionContext,
): AgentToolCatalogEntry[] {
  if (input.localPrivate) return [];

  const advertisedConnectorTools = new Set(
    (input.advertisedConnectorTools ?? []).map((name) => name.trim()),
  );
  const catalog: AgentToolCatalogEntry[] = [];

  for (const tool of toolDefinitions) {
    const metadata = getAgentToolMetadata(tool.name);
    if (!metadata) continue;

    let selection: { confidence: number; reasons: string[] } | null = null;
    if (metadata.selectionHints.connectorCapability) {
      if (!advertisedConnectorTools.has(metadata.name)) continue;
      selection = scoreConnectorToolForTurn(metadata, input);
    } else if (input.includeCoreTools !== false) {
      selection =
        scoreCoreToolForTurn(metadata, input) ??
        scoreCoreToolFallbackSemantic(metadata, input);
    }

    if (
      !selection ||
      selection.confidence < AGENT_TOOL_SELECTION_CONFIDENCE_THRESHOLD
    ) {
      continue;
    }
    catalog.push({
      ...metadata,
      selectionConfidence: selection.confidence,
      selectionReasons: selection.reasons,
    });
  }

  return catalog.sort(
    (left, right) =>
      right.selectionConfidence - left.selectionConfidence ||
      left.name.localeCompare(right.name),
  );
}

export function decideAgentToolApproval(input: {
  tool: string;
  mode?: UserApprovalMode;
  explicitApproval?: boolean;
}): UserToolApprovalDecision {
  const metadata = getAgentToolMetadata(input.tool);
  return decideUserToolApproval({
    mode: input.mode ?? DEFAULT_USER_APPROVAL_MODE,
    permission: metadata?.permission,
    idempotency: metadata?.idempotency,
    scope: metadata?.approvalScope,
    explicitApproval: input.explicitApproval,
  });
}

/**
 * Normalize and validate a tool call with the exact schema used at execution.
 * Approval staging uses this so the call shown to the user cannot differ from
 * the call that will later execute after approval.
 */
export function readCanonicalAgentToolArgs(
  name: string,
  rawArgs: unknown,
): Record<string, unknown> | null {
  const tool = registry.get(name);
  if (!tool) return null;
  const parsed = tool.argsSchema.safeParse(
    applyArgAliases(normalizeToolArgs(rawArgs), tool.argAliases),
  );
  if (
    !parsed.success ||
    !parsed.data ||
    typeof parsed.data !== "object" ||
    Array.isArray(parsed.data)
  ) {
    return null;
  }
  return { ...(parsed.data as Record<string, unknown>) };
}

// ── Per-user tool rate limiting ──────────────────────────────────────
const toolRateLimits = new Map<string, { count: number; windowStart: number }>();
const TOOL_RATE_WINDOW_MS = 60_000;
const TOOL_RATE_MAX_CALLS = 30;
const WRITE_TOOL_RATE_MAX_CALLS = 10;

/**
 * Dinamik MCP aracı çalıştırma.
 *
 * Yerleşik araçlarla aynı kapılardan geçer (kullanıcı kapsamı, iptal, hız
 * sınırı) ama onay kapısından geçmez: ürün kararı gereği MCP araçları
 * okuma/yazma diye ayrılmıyor. Hız sınırı için `write` sayılıyorlar —
 * kotaları okuma araçlarından ayrı ve daha dar tutulsun.
 */
async function executeDynamicMcpTool(
  app: FastifyInstance,
  context: AgentToolContext,
  request: AgentToolRequest,
  startedAt: number,
): Promise<AgentToolResult> {
  const permission: AgentToolPermission = "write";
  const fail = (code: string, message: string): AgentToolResult => ({
    tool: request.tool,
    ok: false,
    permission,
    durationMs: Date.now() - startedAt,
    output: null,
    error: { code, message },
  });

  if (
    !context.userId ||
    typeof context.userId !== "string" ||
    context.userId.trim().length === 0
  ) {
    return fail(
      "missing_user_context",
      "Tool execution requires a valid userId scope.",
    );
  }
  if (context.shouldAbort && (await context.shouldAbort())) {
    return fail("task_canceled", "Tool execution was canceled.");
  }
  const rateCheck = checkToolRateLimit(context.userId, permission);
  if (!rateCheck.allowed) {
    return fail(
      "tool_rate_limited",
      `Too many tool calls. Retry after ${Math.ceil(rateCheck.retryAfterMs / 1000)}s.`,
    );
  }

  const args = normalizeToolArgs(request.args);
  const outcome = await callMcpTool(app, {
    userId: context.userId,
    toolName: request.tool,
    args: (args ?? {}) as Record<string, unknown>,
  });

  if (!outcome.ok) {
    return fail(
      outcome.errorCode ?? "mcp_tool_failed",
      outcome.errorMessage ?? "MCP tool call failed.",
    );
  }

  return {
    tool: request.tool,
    ok: true,
    permission,
    durationMs: Date.now() - startedAt,
    output: outcome.output,
    error: null,
  };
}

function checkToolRateLimit(userId: string, permission: AgentToolPermission): { allowed: boolean; retryAfterMs: number } {
  const now = Date.now();
  const key = `${userId}:${permission === "write" || permission === "side_effect" ? "write" : "all"}`;
  const limit = permission === "write" || permission === "side_effect" ? WRITE_TOOL_RATE_MAX_CALLS : TOOL_RATE_MAX_CALLS;

  const entry = toolRateLimits.get(key);
  if (!entry || now - entry.windowStart > TOOL_RATE_WINDOW_MS) {
    toolRateLimits.set(key, { count: 1, windowStart: now });
    return { allowed: true, retryAfterMs: 0 };
  }
  if (entry.count >= limit) {
    return { allowed: false, retryAfterMs: Math.max(1000, TOOL_RATE_WINDOW_MS - (now - entry.windowStart)) };
  }
  entry.count += 1;
  return { allowed: true, retryAfterMs: 0 };
}

export async function executeAgentTool(
  app: FastifyInstance,
  context: AgentToolContext,
  request: AgentToolRequest,
): Promise<AgentToolResult> {
  const startedAt = Date.now();
  // Dinamik MCP araçları statik kayıtta YOKTUR: katalog kullanıcının bağlı
  // sunucularından turda üretilir. Bu yüzden `unknown_tool` demeden önce
  // MCP ad alanını deniyoruz.
  if (isMcpToolName(request.tool)) {
    return executeDynamicMcpTool(app, context, request, startedAt);
  }
  const tool = registry.get(request.tool);
  if (!tool) {
    return {
      tool: request.tool,
      ok: false,
      permission: "read",
      durationMs: 0,
      output: null,
      error: {
        code: "unknown_tool",
        message: "Tool is not registered.",
      },
    };
  }
  if (!context.userId || typeof context.userId !== "string" || context.userId.trim().length === 0) {
    return {
      tool: tool.name,
      ok: false,
      permission: tool.permission,
      durationMs: 0,
      output: null,
      error: {
        code: "missing_user_context",
        message: "Tool execution requires a valid userId scope.",
      },
    };
  }
  if (context.shouldAbort && (await context.shouldAbort())) {
    return {
      tool: tool.name,
      ok: false,
      permission: tool.permission,
      durationMs: 0,
      output: null,
      error: { code: "task_canceled", message: "Tool execution was canceled." },
    };
  }
  const rateCheck = checkToolRateLimit(context.userId, tool.permission);
  if (!rateCheck.allowed) {
    return {
      tool: tool.name,
      ok: false,
      permission: tool.permission,
      durationMs: 0,
      output: null,
      error: {
        code: "tool_rate_limited",
        message: `Too many tool calls. Retry after ${Math.ceil(rateCheck.retryAfterMs / 1000)}s.`,
      },
    };
  }
  if (tool.permission === "side_effect" && context.allowSideEffects !== true) {
    return sideEffectBlocked(tool);
  }
  if (tool.permission === "write" && context.allowStateWrites !== true) {
    return stateWriteBlocked(tool);
  }
  const approvalDecision = decideAgentToolApproval({
    tool: tool.name,
    mode: context.approvalMode,
    explicitApproval:
      context.approvalGranted === true ||
      (tool.permission === "side_effect" && context.allowSideEffects === true),
  });
  if (approvalDecision.requiresApproval) {
    return sideEffectBlocked(tool);
  }
  try {
    const normalizedArgs = applyArgAliases(
      normalizeToolArgs(request.args),
      tool.argAliases,
    );
    let args: unknown;
    const parsedArgs = tool.argsSchema.safeParse(normalizedArgs);
    if (parsedArgs.success) {
      args = parsedArgs.data;
    } else if (tool.allowEmptyArgsFallback === true) {
      // Read-only listeleme araçları: model argümanı bozduysa salt-default
      // çalıştırma, "araç kataloğu doğrulayamıyor" cevabından her zaman
      // iyidir (en kötü sonuç filtresiz liste). Şeması {} kabul etmeyen
      // araçlar (gmail.read gibi) burada yine orijinal hatayla düşer.
      const fallback = tool.argsSchema.safeParse({});
      if (!fallback.success) {
        throw parsedArgs.error;
      }
      args = fallback.data;
      app.log?.info?.(
        { tool: tool.name, droppedArgs: Object.keys(
          (normalizedArgs as Record<string, unknown> | null) ?? {},
        ) },
        "connector tool args repaired to defaults",
      );
    } else {
      throw parsedArgs.error;
    }
    const timeoutMs = Math.max(100, Math.min(tool.timeoutMs ?? 8_000, 30_000));
    const timeout = new Promise<never>((_, reject) => {
      const timer = setTimeout(() => reject(Object.assign(new Error("Tool timed out."), { code: "tool_timeout" })), timeoutMs);
      timer.unref?.();
    });
    if (context.shouldAbort && (await context.shouldAbort())) {
      throw Object.assign(new Error("Tool execution was canceled."), {
        code: "task_canceled",
      });
    }
    const rawOutput = await Promise.race([tool.execute(app, context, args), timeout]);
    const parsedOutput = (tool.outputSchema ?? z.record(z.string(), z.unknown())).safeParse(rawOutput);
    if (!parsedOutput.success) {
      throw Object.assign(new Error("Tool returned an invalid typed result."), {
        code: "invalid_tool_output",
      });
    }
    const output = parsedOutput.data;
    return {
      tool: tool.name,
      ok: true,
      permission: tool.permission,
      durationMs: Date.now() - startedAt,
      output,
      error: null,
    };
  } catch (error) {
    return {
      tool: tool.name,
      ok: false,
      permission: tool.permission,
      durationMs: Date.now() - startedAt,
      output: null,
      error: compactError(error),
    };
  }
}
