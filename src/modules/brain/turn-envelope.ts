import { z } from "zod";
import { elyanAssistantBlockSchema } from "../../contracts/domain.js";
import type { AssistantMessageBlock } from "../chat/message-blocks.js";
import { agentPlanEnvelopeSchema } from "./agent-plan.js";

const turnEnvelopeReplySchema = z.object({
  text: z.string().default(""),
  lang: z.string().trim().min(1).max(16).default("tr"),
  tone: z.enum(["warm", "neutral", "technical"]).default("neutral"),
});

const memoryOpSchema = z.object({
  op: z.enum(["write", "update", "contest", "forget"]),
  kind: z.enum(["fact", "preference", "episode", "self_model"]),
  key: z.string().trim().min(1).max(160),
  value: z.string().trim().max(2_000).default(""),
  confidence: z.coerce.number().min(0).max(1).default(0.7),
  ttl_days: z.coerce.number().int().positive().max(3650).optional(),
}).superRefine((value, ctx) => {
  if (value.op !== "forget" && value.value.length === 0) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["value"],
      message: "memory value is required unless op=forget",
    });
  }
});

const goalOpSchema = z.object({
  op: z.enum(["advance", "complete", "block", "open"]),
  goalId: z.string().trim().min(1).max(160).optional(),
  step: z.string().trim().min(1).max(500).optional(),
  next: z.string().trim().min(1).max(500).optional(),
});

const followUpDueSchema = z.union([
  z.enum(["next_turn", "same_day", "tomorrow"]),
  z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  z.string().datetime({ offset: true }),
]);

const followUpSchema = z.object({
  due: followUpDueSchema,
  topic: z.string().trim().min(1).max(240),
  nudge: z.string().trim().min(1).max(500),
});

const toolRequestSchema = z.object({
  tool: z.string().trim().min(1).max(120),
  args: z.record(z.string(), z.unknown()).default({}),
});

const affectSchema = z.object({
  user_mood_guess: z.string().trim().max(160).default("unknown"),
  energy: z.enum(["low", "mid", "high"]).default("mid"),
  register: z.string().trim().max(160).default("neutral"),
});

const proactiveOpSchema = z.object({
  op: z.enum(["mute", "unmute", "enable", "disable", "set_daily_limit", "set_quiet_hours"]),
  kind: z.string().trim().min(1).max(40).optional(),
  max_daily: z.coerce.number().int().min(0).max(20).optional(),
  quiet_start_hour: z.coerce.number().int().min(0).max(23).optional(),
  quiet_end_hour: z.coerce.number().int().min(0).max(23).optional(),
  timezone: z.string().trim().min(1).max(80).optional(),
});

export const turnEnvelopeSchema = z
  .object({
    reply: turnEnvelopeReplySchema.default({}),
    blocks: z.array(elyanAssistantBlockSchema).default([]),
    memory_ops: z.array(memoryOpSchema).max(20).default([]),
    goal_ops: z.array(goalOpSchema).max(20).default([]),
    follow_ups: z.array(followUpSchema).max(20).default([]),
    tool_requests: z.array(toolRequestSchema).max(20).default([]),
    agent_plan: agentPlanEnvelopeSchema.nullish(),
    affect: affectSchema.default({}),
    proactive_ops: z.array(proactiveOpSchema).max(10).default([]),
  })
  .strip();

export type TurnEnvelope = Omit<z.output<typeof turnEnvelopeSchema>, "proactive_ops"> & {
  blocks: AssistantMessageBlock[];
  proactive_ops?: z.output<typeof proactiveOpSchema>[];
};

export type TurnEnvelopeParseResult =
  | { ok: true; envelope: TurnEnvelope }
  | { ok: false; error: string };

function readEnvelopeCandidate(value: unknown): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return value;
  }
  const record = value as Record<string, unknown>;
  if (record.reply && typeof record.reply === "object") {
    return record;
  }
  if (record.envelope && typeof record.envelope === "object") {
    return record.envelope;
  }
  if (record.turn_envelope && typeof record.turn_envelope === "object") {
    return record.turn_envelope;
  }
  return record;
}

export function parseTurnEnvelope(value: unknown): TurnEnvelopeParseResult {
  const parsed = turnEnvelopeSchema.safeParse(readEnvelopeCandidate(value));
  if (!parsed.success) {
    return { ok: false, error: parsed.error.issues[0]?.message ?? "invalid_turn_envelope" };
  }
  return { ok: true, envelope: parsed.data as TurnEnvelope };
}

export function parseTurnEnvelopeText(text: string): TurnEnvelopeParseResult {
  const trimmed = text.trim();
  if (!trimmed) {
    return { ok: false, error: "empty_turn_envelope" };
  }
  try {
    return parseTurnEnvelope(JSON.parse(trimmed));
  } catch {
    return { ok: false, error: "invalid_turn_envelope_json" };
  }
}

export function looksLikeTurnEnvelopeJson(text: string): boolean {
  const trimmed = text.trim();
  return (
    trimmed.startsWith("{") &&
    /"reply"\s*:/.test(trimmed) &&
    (/"memory_ops"\s*:/.test(trimmed) ||
      /"goal_ops"\s*:/.test(trimmed) ||
      /"follow_ups"\s*:/.test(trimmed) ||
      /"tool_requests"\s*:/.test(trimmed) ||
      /"blocks"\s*:/.test(trimmed))
  );
}

export const TURN_ENVELOPE_SYSTEM_INSTRUCTION = [
  "Return one TurnEnvelope JSON object without markdown or hidden reasoning.",
  "Keep visible prose only in reply.text and renderable UI only in blocks.",
  "Encode explicit preferences and corrections in memory_ops; use op=forget when the user asks to forget a memory key. Use the other typed arrays for goals, follow-ups, and tools, or [] when absent.",
  "For multi-step tool tasks, emit agent_plan.v2 with explicit dependencies and evidence rules; never mark execution complete in prose.",
].join(" ");

export function buildTurnEnvelopeSystemInstruction(includeProactiveOps = false): string {
  return includeProactiveOps
    ? `${TURN_ENVELOPE_SYSTEM_INSTRUCTION} Encode explicit mute, quiet-hour, and proactive-message controls in proactive_ops.`
    : TURN_ENVELOPE_SYSTEM_INSTRUCTION;
}

export function buildTurnEnvelopeResponseFormat(includeProactiveOps = false): Record<string, unknown> {
  const format = {
    type: "json_schema",
    json_schema: {
      name: "elyan_turn_envelope",
      // Groq strict mode requires every object property to be listed in
      // `required` and forbids open objects. TurnEnvelope intentionally has
      // optional ops plus open elyan_blocks.v2/tool args, so strict mode is
      // rejected before inference. JSON-schema mode still constrains the
      // provider output; the Zod parser below remains the authoritative gate.
      strict: false,
      schema: {
        type: "object",
        additionalProperties: false,
        required: [
          "reply",
          "blocks",
          "memory_ops",
          "goal_ops",
          "follow_ups",
          "tool_requests",
          "affect",
          "proactive_ops",
        ],
        properties: {
          reply: {
            type: "object",
            additionalProperties: false,
            required: ["text", "lang", "tone"],
            properties: {
              text: { type: "string" },
              lang: { type: "string" },
              tone: { type: "string", enum: ["warm", "neutral", "technical"] },
            },
          },
          blocks: {
            type: "array",
            items: {
              type: "object",
              additionalProperties: true,
              required: ["type"],
              properties: {
                type: { type: "string" },
              },
            },
          },
          memory_ops: {
            type: "array",
            description:
              "Durable user facts and preferences. Explicit corrections replace the previous value; how the user wants to be addressed uses kind=preference and key=preferred_name.",
            items: {
              type: "object",
              additionalProperties: false,
              required: ["op", "kind", "key", "value", "confidence"],
              properties: {
                op: { type: "string", enum: ["write", "update", "contest", "forget"] },
                kind: {
                  type: "string",
                  enum: ["fact", "preference", "episode", "self_model"],
                },
                key: { type: "string" },
                value: { type: "string" },
                confidence: { type: "number", minimum: 0, maximum: 1 },
                ttl_days: { type: "integer", minimum: 1 },
              },
            },
          },
          goal_ops: {
            type: "array",
            items: {
              type: "object",
              additionalProperties: false,
              required: ["op"],
              properties: {
                op: { type: "string", enum: ["advance", "complete", "block", "open"] },
                goalId: { type: "string" },
                step: { type: "string" },
                next: { type: "string" },
              },
            },
          },
          follow_ups: {
            type: "array",
            items: {
              type: "object",
              additionalProperties: false,
              required: ["due", "topic", "nudge"],
              properties: {
                due: { type: "string" },
                topic: { type: "string" },
                nudge: { type: "string" },
              },
            },
          },
          tool_requests: {
            type: "array",
            description:
              'Typed server tools with exact arg contracts: web.search {query:string} | web.numeric_facts {query:string} | memory.query {query:string, limit?:1..10} | memory.write {op:"write"|"update"|"contest"|"forget", kind:"fact"|"preference"|"episode"|"self_model", key:string, value:string, confidence?:0..1} | goals.get {goalId?:uuid} | goals.update {action:"open"|"advance"|"complete"|"block", goalId?:uuid, title?:string, step?:int, ofSteps?:int, advancedTo?:string, blocker?:string}. Args must be a flat object exactly matching the contract — no extra nesting, no stringified JSON. Read current goal state with goals.get before continuing a multi-turn goal; use write tools only for explicit durable state changes.',
            items: {
              type: "object",
              additionalProperties: false,
              required: ["tool", "args"],
              properties: {
                tool: { type: "string" },
                args: { type: "object", additionalProperties: true },
              },
            },
          },
          agent_plan: {
            type: ["object", "null"],
            description: "Optional typed DAG for task execution. The server validates and owns all transitions.",
            additionalProperties: false,
            required: ["version", "goal", "steps"],
            properties: {
              version: { type: "string", enum: ["agent_plan.v2"] },
              goal: {
                type: "object",
                additionalProperties: false,
                required: ["title", "success_criteria"],
                properties: {
                  title: { type: "string" },
                  success_criteria: { type: "array", minItems: 1, maxItems: 8, items: { type: "string" } },
                },
              },
              steps: {
                type: "array",
                minItems: 1,
                maxItems: 8,
                items: {
                  type: "object",
                  additionalProperties: false,
                  required: ["id", "title", "depends_on", "tool_request", "expected_outcome", "max_attempts"],
                  properties: {
                    id: { type: "string" },
                    title: { type: "string" },
                    depends_on: { type: "array", maxItems: 7, items: { type: "string" } },
                    tool_request: {
                      type: "object",
                      additionalProperties: false,
                      required: ["tool", "args"],
                      properties: { tool: { type: "string" }, args: { type: "object", additionalProperties: true } },
                    },
                    expected_outcome: {
                      type: "object",
                      additionalProperties: false,
                      required: ["description", "rules"],
                      properties: {
                        description: { type: "string" },
                        rules: {
                          type: "array",
                          minItems: 1,
                          maxItems: 8,
                          items: {
                            type: "object",
                            additionalProperties: false,
                            required: ["source", "path", "operator"],
                            properties: {
                              source: { type: "string", enum: ["tool_result", "artifact", "state_readback"] },
                              path: { type: "string" },
                              operator: { type: "string", enum: ["exists", "equals", "not_equals", "non_empty", "gte", "lte", "sha256"] },
                              value: {},
                            },
                          },
                        },
                      },
                    },
                    max_attempts: { type: "integer", minimum: 1, maximum: 3 },
                  },
                },
              },
            },
          },
          proactive_ops: {
            type: "array",
            description: "Explicit user controls for proactive messages, quiet hours, and daily limits.",
            items: {
              type: "object",
              additionalProperties: false,
              required: ["op"],
              properties: {
                op: { type: "string", enum: ["mute", "unmute", "enable", "disable", "set_daily_limit", "set_quiet_hours"] },
                kind: { type: "string" },
                max_daily: { type: "integer", minimum: 0, maximum: 20 },
                quiet_start_hour: { type: "integer", minimum: 0, maximum: 23 },
                quiet_end_hour: { type: "integer", minimum: 0, maximum: 23 },
                timezone: { type: "string" },
              },
            },
          },
          affect: {
            type: "object",
            additionalProperties: false,
            required: ["user_mood_guess", "energy", "register"],
            properties: {
              user_mood_guess: { type: "string" },
              energy: { type: "string", enum: ["low", "mid", "high"] },
              register: { type: "string" },
            },
          },
        },
      },
    },
  } as Record<string, unknown>;
  if (!includeProactiveOps) {
    const jsonSchema = format.json_schema as Record<string, unknown>;
    const schema = jsonSchema.schema as Record<string, unknown>;
    schema.required = (schema.required as string[]).filter((key) => key !== "proactive_ops");
    delete (schema.properties as Record<string, unknown>).proactive_ops;
  }
  return format;
}
