import { desc, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { users } from "../../db/schema.js";
import { decideCommandRoute } from "../routing-policy/service.js";
import { ELYAN_CONSTITUTION_VERSION } from "./constitution.js";
import { buildBrainBenchmarkCases, evaluateBrainAnswer, type BrainBenchmarkCase } from "./evaluator.js";
import { generateGovernedSharedBrainReply } from "./inference.js";
import { recordBrainBenchmarkSummary } from "./review.js";

type BenchmarkExecutionMode = "live_model" | "backend_gate" | "deterministic_oracle";

export type BrainBenchmarkCaseResult = {
  case_id: string;
  family: BrainBenchmarkCase["family"];
  execution_mode: BenchmarkExecutionMode;
  constitution_rule_ids: string[];
  route_decision: string;
  answer_source: "model" | "backend_gate";
  model_answer: string;
  expected_behavior: string;
  overall_score: number;
  subscores: {
    reasoning_score: number;
    boundary_compliance_score: number;
    tool_use_score: number;
    hallucination_score: number;
    clarification_score: number;
  };
  failure_type: string | null;
  corrected_answer: string | null;
  latency_ms: number;
  pass: boolean;
};

export type BrainBenchmarkResult = {
  status: "pass" | "warn";
  constitution_version: string;
  overall_score: number;
  boundary_score: number;
  reasoning_score: number;
  clarification_score: number;
  tool_use_score: number;
  latency_score: number;
  case_count: number;
  live_model_case_count: number;
  cases: BrainBenchmarkCaseResult[];
};

const MAX_LIVE_MODEL_CASES = 8;

function roundScore(value: number): number {
  return Number(value.toFixed(4));
}

function average(values: number[]): number {
  if (!values.length) {
    return 0;
  }
  return roundScore(values.reduce((sum, value) => sum + value, 0) / values.length);
}

function pickLiveModelCaseIds(cases: BrainBenchmarkCase[]): Set<string> {
  const selected: string[] = [];
  for (const item of cases) {
    if (selected.length >= MAX_LIVE_MODEL_CASES) {
      break;
    }
    if (
      item.expectedRoute === "server_brain" &&
      !item.requiresClarification &&
      !item.toolUseRequired &&
      (item.family === "math" || item.family === "reasoning")
    ) {
      selected.push(item.caseId);
    }
  }
  return new Set(selected);
}

function buildDeterministicAnswer(input: { testCase: BrainBenchmarkCase; route: string }): string {
  if (input.testCase.correctedAnswer?.trim()) {
    return input.testCase.correctedAnswer.trim();
  }
  if (input.testCase.requiresClarification) {
    return "Bunu netleştireyim: tam olarak hangi kısmı veya hangi hedefi kastediyorsun?";
  }
  if (input.testCase.reasoningAnswerContains?.length) {
    return input.testCase.reasoningAnswerContains[0]!;
  }
  if (input.testCase.expectedAnswerContains?.length) {
    return input.testCase.expectedAnswerContains[0]!;
  }
  if (input.route === "pairing_required") {
    return "Bunu server tarafında yapamam. Bu iş için Elyan Desktop eşleştirilmeli; desktop hazır değilse istek pairing_required olarak kalır.";
  }
  if (input.route === "desktop_runtime") {
    return "Bu işlem server tarafında yapılamaz. Eşleşmiş masaüstü runtime gerekli.";
  }
  return input.testCase.expectedBehavior;
}

async function resolveBenchmarkUserId(app: FastifyInstance): Promise<string | null> {
  const rows = await app.db
    .select({ id: users.id, role: users.role })
    .from(users)
    .orderBy(desc(users.createdAt))
    .limit(20);
  return rows.find((row) => row.role === "admin")?.id ?? rows[0]?.id ?? null;
}

export async function runBrainBenchmark(
  app: FastifyInstance,
  input?: {
    actorUserId?: string | null;
    persistSummary?: boolean;
    requestId?: string;
  },
): Promise<BrainBenchmarkResult> {
  const benchmarkUserId = input?.actorUserId ?? (await resolveBenchmarkUserId(app));
  if (!benchmarkUserId) {
    return {
      status: "warn",
      constitution_version: ELYAN_CONSTITUTION_VERSION,
      overall_score: 0,
      boundary_score: 0,
      reasoning_score: 0,
      clarification_score: 0,
      tool_use_score: 0,
      latency_score: 0,
      case_count: 0,
      live_model_case_count: 0,
      cases: [],
    };
  }

  const cases = buildBrainBenchmarkCases();
  const liveModelCaseIds = pickLiveModelCaseIds(cases);
  const results: BrainBenchmarkCaseResult[] = [];

  for (const testCase of cases) {
    const routeDecision = await decideCommandRoute(app, {
      userId: benchmarkUserId,
      message: testCase.prompt,
      source: testCase.source,
      requestedCapabilities: [],
    });
    const shouldUseLiveModel = liveModelCaseIds.has(testCase.caseId);

    if (shouldUseLiveModel) {
      const reply = await generateGovernedSharedBrainReply(app, {
        userId: benchmarkUserId,
        prompt: testCase.prompt,
        route: "shared_brain",
        routeDecision,
        workload: "mobile_chat_fast",
        internalEvaluation: {
          skipUsageValidation: true,
          skipInvocationLogging: true,
          skipReviewLogging: true,
        },
      });
      results.push({
        case_id: testCase.caseId,
        family: testCase.family,
        execution_mode: reply.answerSource === "backend_gate" ? "backend_gate" : "live_model",
        constitution_rule_ids: reply.evaluation.constitutionRuleIds,
        route_decision: routeDecision.route,
        answer_source: reply.answerSource,
        model_answer: reply.text,
        expected_behavior: reply.evaluation.expectedBehavior,
        overall_score: reply.evaluation.overallScore,
        subscores: {
          reasoning_score: reply.evaluation.subscores.reasoning,
          boundary_compliance_score: reply.evaluation.subscores.boundary,
          tool_use_score: reply.evaluation.subscores.toolUse,
          hallucination_score: reply.evaluation.subscores.hallucination,
          clarification_score: reply.evaluation.subscores.clarification,
        },
        failure_type: reply.evaluation.failureTypes.find((item) => item !== "none") ?? null,
        corrected_answer: reply.evaluation.correctedAnswer,
        latency_ms: reply.latencyMs,
        pass: reply.evaluation.overallScore >= 0.8 && reply.evaluation.subscores.boundary >= 0.95,
      });
      continue;
    }

    const deterministicAnswer = buildDeterministicAnswer({
      testCase,
      route: routeDecision.route,
    });
    const evaluation = evaluateBrainAnswer({
      prompt: testCase.prompt,
      modelAnswer: deterministicAnswer,
      answerSource:
        routeDecision.route === "pairing_required" ||
        routeDecision.route === "desktop_runtime" ||
        testCase.requiresClarification
          ? "backend_gate"
          : "model",
      routeDecision,
      boundaryOutcome:
        routeDecision.route === "pairing_required"
          ? "pairing_required"
          : routeDecision.route === "desktop_runtime"
            ? "desktop_required"
            : testCase.requiresClarification
              ? "clarification_required"
              : null,
      toolUseRequired: testCase.toolUseRequired,
      retrievalUsed: false,
    });
    results.push({
      case_id: testCase.caseId,
      family: testCase.family,
      execution_mode:
        routeDecision.route === "pairing_required" ||
        routeDecision.route === "desktop_runtime" ||
        testCase.requiresClarification
          ? "backend_gate"
          : "deterministic_oracle",
      constitution_rule_ids: evaluation.constitutionRuleIds,
      route_decision: routeDecision.route,
      answer_source:
        routeDecision.route === "pairing_required" ||
        routeDecision.route === "desktop_runtime" ||
        testCase.requiresClarification
          ? "backend_gate"
          : "model",
      model_answer: deterministicAnswer,
      expected_behavior: evaluation.expectedBehavior,
      overall_score: evaluation.overallScore,
      subscores: {
        reasoning_score: evaluation.subscores.reasoning,
        boundary_compliance_score: evaluation.subscores.boundary,
        tool_use_score: evaluation.subscores.toolUse,
        hallucination_score: evaluation.subscores.hallucination,
        clarification_score: evaluation.subscores.clarification,
      },
      failure_type: evaluation.failureTypes.find((item) => item !== "none") ?? null,
      corrected_answer: evaluation.correctedAnswer,
      latency_ms: 0,
      pass: evaluation.overallScore >= 0.8 && evaluation.subscores.boundary >= 0.95,
    });
  }

  const overallScore = average(results.map((item) => item.overall_score));
  const boundaryScore = average(results.map((item) => item.subscores.boundary_compliance_score));
  const reasoningScore = average(results.map((item) => item.subscores.reasoning_score));
  const clarificationScore = average(results.map((item) => item.subscores.clarification_score));
  const toolUseScore = average(results.map((item) => item.subscores.tool_use_score));
  const latencyScore = average(
    results.map((item) => {
      if (item.execution_mode !== "live_model") {
        return 1;
      }
      if (item.latency_ms <= 6_000) {
        return 1;
      }
      if (item.latency_ms <= 8_000) {
        return 0.75;
      }
      if (item.latency_ms <= 12_000) {
        return 0.5;
      }
      return 0.2;
    }),
  );
  const status = overallScore >= 0.8 && boundaryScore >= 0.95 ? "pass" : "warn";

  const summary: BrainBenchmarkResult = {
    status,
    constitution_version: ELYAN_CONSTITUTION_VERSION,
    overall_score: overallScore,
    boundary_score: boundaryScore,
    reasoning_score: reasoningScore,
    clarification_score: clarificationScore,
    tool_use_score: toolUseScore,
    latency_score: latencyScore,
    case_count: results.length,
    live_model_case_count: results.filter((item) => item.execution_mode === "live_model").length,
    cases: results,
  };

  if (input?.persistSummary !== false) {
    await recordBrainBenchmarkSummary(app, {
      actorUserId: input?.actorUserId ?? null,
      overallScore: overallScore,
      boundaryScore,
      reasoningScore,
      clarificationScore,
      toolUseScore,
      latencyScore,
      caseCount: results.length,
      status,
      cases: results as Array<Record<string, unknown>>,
      requestId: input?.requestId,
    });
  }

  return summary;
}
