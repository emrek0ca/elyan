import type { FastifyInstance } from "fastify";
import { z } from "zod";
import type { IntentClassification, UnderstandingIntent } from "../../core/understanding/types.js";
import { buildGeminiFreePublicOperationFrame } from "./gemini-free-tier-guard.js";
import { callGeminiFreeStructured } from "./gemini-utility-client.js";

const intents = [
  "chat", "coding", "debugging", "research", "math", "document", "writing",
  "image", "automation", "browser", "computer", "planning", "unknown",
] as const satisfies readonly UnderstandingIntent[];

const routeSchema = z.object({
  primaryIntent: z.enum(intents),
  requiresCitation: z.boolean(),
  shouldClarify: z.boolean(),
  confidence: z.number().min(0).max(1),
});

const routeJsonSchema = {
  type: "object",
  additionalProperties: false,
  required: ["primaryIntent", "requiresCitation", "shouldClarify", "confidence"],
  properties: {
    primaryIntent: { type: "string", enum: intents },
    requiresCitation: { type: "boolean" },
    shouldClarify: { type: "boolean" },
    confidence: { type: "number", minimum: 0, maximum: 1 },
  },
};

function routingHints(intent: UnderstandingIntent, requiresCitation: boolean) {
  const requiresLocalRuntime = ["automation", "browser", "computer"].includes(intent);
  if (requiresLocalRuntime) {
    return {
      mode: "local_private" as const,
      preferredCapabilities: [intent, "tool_use", "local_runtime"],
      avoidCloud: true,
      requiresLocalRuntime: true,
    };
  }
  if (requiresCitation || intent === "research") {
    return {
      mode: "research" as const,
      preferredCapabilities: ["retrieval", "citation"],
      avoidCloud: false,
      requiresLocalRuntime: false,
    };
  }
  return {
    mode: "fast" as const,
    preferredCapabilities: intent === "chat" || intent === "unknown" ? [] : [intent],
    avoidCloud: false,
    requiresLocalRuntime: false,
  };
}

export async function enhanceIntentWithGeminiFree(
  app: FastifyInstance,
  input: { userId: string; message: string; current: IntentClassification },
): Promise<IntentClassification> {
  const message = input.message.replace(/\s+/g, " ").trim();
  const publicOperationFrame = buildGeminiFreePublicOperationFrame(message);
  if (
    !publicOperationFrame ||
    message.length < 12 ||
    message.length > 2_000 ||
    input.current.confidence >= 0.58 ||
    input.current.privacyRisk !== "low" ||
    input.current.requiresLocalRuntime
  ) return input.current;

  const routed = await callGeminiFreeStructured(app, {
    feature: "intent_route",
    userId: input.userId,
    system: "Classify the user's operational intent. Return JSON only. Never infer private facts or invent a requested action.",
    payload: {
      publicOperationFrame,
      deterministicIntent: input.current.primaryIntent,
      allowedIntents: intents,
    },
    schema: routeSchema,
    jsonSchema: routeJsonSchema,
    sensitivity: "none",
    maxOutputTokens: 180,
    timeoutMs: 2_500,
  });
  if (!routed || routed.confidence < 0.72) return input.current;

  const requiresLocalRuntime = ["automation", "browser", "computer"].includes(routed.primaryIntent);
  const requiresToolUse = requiresLocalRuntime || ["coding", "debugging", "document", "image"].includes(routed.primaryIntent);
  return {
    ...input.current,
    primaryIntent: routed.primaryIntent,
    secondaryIntents: [input.current.primaryIntent, ...input.current.secondaryIntents]
      .filter((value, index, values) => value !== routed.primaryIntent && values.indexOf(value) === index),
    requiresLocalRuntime,
    requiresToolUse,
    requiresCitation: input.current.requiresCitation || routed.requiresCitation,
    requiresRetrieval: input.current.requiresRetrieval || routed.requiresCitation || routed.primaryIntent === "research",
    confidence: Math.max(input.current.confidence, Math.min(0.85, routed.confidence)),
    reason: `${input.current.reason}+gemini_free_${routed.primaryIntent}`,
    taskFrame: { ...input.current.taskFrame, shouldClarify: routed.shouldClarify },
    routingHints: routingHints(routed.primaryIntent, routed.requiresCitation),
  };
}
