import { and, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { tasks } from "../../db/schema.js";
import { agentEngineRepository } from "./agent-engine-repository.js";
import { applyAgentReplan } from "./agent-engine.js";
import { blockAgentRun } from "./agent-engine.js";
import { generateGovernedSharedBrainReply } from "./inference.js";
import { parseTurnEnvelope, parseTurnEnvelopeText } from "./turn-envelope.js";
import type { SharedBrainWorkload } from "./workloads.js";

function taskPrompt(payload: unknown): string {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return "";
  const value = (payload as Record<string, unknown>).prompt;
  return typeof value === "string" ? value.slice(0, 4_000) : "";
}

export async function attemptAgentReplan(input: {
  app: FastifyInstance;
  userId: string;
  runId: string;
  workload: SharedBrainWorkload;
}): Promise<boolean> {
  const repository = agentEngineRepository(input.app);
  const snapshot = await repository.loadRun(input.userId, input.runId);
  if (snapshot.run.state !== "waiting_evidence") return false;
  if (snapshot.run.replanCount >= snapshot.run.maxReplans) {
    await blockAgentRun({
      app: input.app, userId: input.userId, runId: input.runId,
      eventType: "agent.replan_budget_exhausted", failureCode: "replan_budget_exhausted",
    });
    return false;
  }
  const task = (await input.app.db.select({ payload: tasks.payload, title: tasks.title }).from(tasks).where(and(
    eq(tasks.id, snapshot.run.taskId), eq(tasks.userId, input.userId),
  )).limit(1))[0];
  if (!task) return false;
  const failures = snapshot.steps.flatMap((step) => {
    if (!step.verification || typeof step.verification !== "object" || Array.isArray(step.verification)) return [];
    const verification = step.verification as Record<string, unknown>;
    return [{
      stepId: step.stepKey,
      missingEvidence: Array.isArray(verification.missing_evidence) ? verification.missing_evidence.slice(0, 8) : [],
      failedRules: Array.isArray(verification.failed_rules) ? verification.failed_rules.slice(0, 8) : [],
    }];
  });
  const prompt = [
    "Create a replacement agent_plan.v2 for the task below.",
    "Use new step ids that do not appear in previous_step_ids.",
    "Do not claim completion. Every step needs deterministic tool_result, artifact, or state_readback rules.",
    JSON.stringify({
      task: taskPrompt(task.payload),
      previous_step_ids: snapshot.steps.map((step) => step.stepKey),
      verification_failures: failures,
      remaining_replans: snapshot.run.maxReplans - snapshot.run.replanCount,
      remaining_tool_calls: snapshot.run.maxToolCalls - snapshot.run.toolCallCount,
    }),
  ].join("\n");
  const inference = await generateGovernedSharedBrainReply(input.app, {
    userId: input.userId,
    taskId: snapshot.run.taskId,
    title: task.title,
    prompt,
    workload: "planning",
    route: "agent_replan",
    meteringSurface: "task",
    maxCompletionTokensOverride: 1_200,
    timeoutMsOverride: 20_000,
    requestMetadata: { agentReplan: true, runId: snapshot.run.id },
    internalEvaluation: {
      skipUsageValidation: true,
      skipReviewLogging: true,
      refinementPass: true,
    },
  });
  const metadataEnvelope = parseTurnEnvelope(inference.metadata.turnEnvelope);
  const textEnvelope = metadataEnvelope.ok ? metadataEnvelope : parseTurnEnvelopeText(inference.text);
  const plan = textEnvelope.ok ? textEnvelope.envelope.agent_plan : null;
  if (!plan) return false;
  return applyAgentReplan({
    app: input.app,
    userId: input.userId,
    runId: input.runId,
    plan,
    workload: input.workload,
  });
}
