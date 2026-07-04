import { z } from "zod";
import type { FastifyInstance } from "fastify";
import {
  advanceGoal,
  createGoal,
  getActiveGoalForContext,
  updateGoal,
} from "../goals/service.js";
import { searchBrainMemory } from "./memory.js";
import { recordTurnMemoryOps } from "./memory-fabric.js";
import type { TurnEnvelope } from "./turn-envelope.js";
import {
  extractNumericEvidenceFromGrounding,
  searchPublicWebGrounding,
} from "./web-grounding.js";
import type { SharedBrainWorkload } from "./workloads.js";

export type AgentToolPermission = "read" | "write" | "side_effect";

export type AgentToolRequest = {
  tool: string;
  args: Record<string, unknown>;
};

export type AgentToolContext = {
  userId: string;
  sessionId?: string | null;
  workload: SharedBrainWorkload;
  allowStateWrites?: boolean;
  allowSideEffects?: boolean;
};

export type AgentToolResult = {
  tool: string;
  ok: boolean;
  permission: AgentToolPermission;
  durationMs: number;
  output: Record<string, unknown> | null;
  error: { code: string; message: string } | null;
};

type AgentToolDefinition<TArgs extends z.ZodTypeAny> = {
  name: string;
  permission: AgentToolPermission;
  argsSchema: TArgs;
  execute: (
    app: FastifyInstance,
    context: AgentToolContext,
    args: z.output<TArgs>,
  ) => Promise<Record<string, unknown>>;
};

const webSearchArgsSchema = z.object({
  query: z.string().trim().min(1).max(320),
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

function compactError(error: unknown): { code: string; message: string } {
  if (error instanceof z.ZodError) {
    return {
      code: "invalid_tool_args",
      message: error.issues[0]?.message ?? "Invalid tool arguments.",
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
    name: "web.search",
    permission: "read",
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
          snippet: result.snippet,
          verificationState: result.verificationState,
        })),
      };
    },
  },
  {
    name: "web.numeric_facts",
    permission: "read",
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
      const result = await recordTurnMemoryOps(app, {
        userId: context.userId,
        sessionId: context.sessionId ?? null,
        envelope,
      });
      return result;
    },
  },
  {
    name: "goals.update",
    permission: "write",
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

export async function executeAgentTool(
  app: FastifyInstance,
  context: AgentToolContext,
  request: AgentToolRequest,
): Promise<AgentToolResult> {
  const startedAt = Date.now();
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
  if (tool.permission === "side_effect" && context.allowSideEffects !== true) {
    return sideEffectBlocked(tool);
  }
  if (tool.permission === "write" && context.allowStateWrites !== true) {
    return stateWriteBlocked(tool);
  }
  try {
    const args = tool.argsSchema.parse(request.args);
    const output = await tool.execute(app, context, args);
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
