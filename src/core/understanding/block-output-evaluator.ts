import { readFile } from "node:fs/promises";
import path from "node:path";
import { elyanAssistantBlockSchema } from "../../contracts/domain.js";
import { selectHybridMobileChatWorkload } from "../../modules/brain/chat-heuristics.js";
import {
  validateAssistantBlockContract,
  type AssistantMessageBlock,
} from "../../modules/chat/message-blocks.js";
import { decideCommandRoute } from "../../modules/routing-policy/service.js";
import {
  decideStructuredResponseDecision,
  shouldPromoteMarkdownTableToWidget,
  type StructuredResponseDecision,
} from "./structured-output-policy.js";

export type BlockOutputFixtureExpected = {
  workload: string;
  primaryShape: StructuredResponseDecision["primaryShape"];
  tablePolicy: StructuredResponseDecision["tablePolicy"];
  expectedBlockTypes: string[];
};

export type BlockOutputFixture = {
  id: string;
  message: string;
  expected: BlockOutputFixtureExpected;
};

export type BlockOutputEvaluationCase = {
  id: string;
  message: string;
  expected: BlockOutputFixtureExpected;
  actual: {
    workload: string;
    primaryShape: StructuredResponseDecision["primaryShape"];
    tablePolicy: StructuredResponseDecision["tablePolicy"];
    blockTypes: string[];
    qualityScore: number;
  };
  pass: boolean;
  failures: string[];
};

export type BlockOutputEvaluationSummary = {
  version: "elyan_block_output_evaluator.v1";
  fixtureCount: number;
  passCount: number;
  failCount: number;
  routeAccuracy: number;
  shapeAccuracy: number;
  schemaValidRate: number;
  duplicateTableRate: number;
  rawJsonLeakRate: number;
  averageQualityScore: number;
  ciPass: boolean;
  ciViolations: string[];
  cases: BlockOutputEvaluationCase[];
};

class FakeQuery<T> {
  constructor(private readonly result: T) {}

  from() {
    return this;
  }

  where() {
    return this;
  }

  orderBy() {
    return this;
  }

  groupBy() {
    return this;
  }

  limit() {
    return this;
  }

  then<TResult1 = T, TResult2 = never>(
    resolve?: ((value: T) => TResult1 | PromiseLike<TResult1>) | null,
    reject?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
  ) {
    return Promise.resolve(this.result).then(resolve, reject);
  }
}

class FakeDb {
  constructor(private readonly results: unknown[]) {}

  select() {
    return new FakeQuery(this.results.shift() ?? []);
  }
}

function createEvaluationApp() {
  return {
    db: new FakeDb([
      [
        {
          planCode: "pro",
          status: "active",
          trialEndsAt: null,
        },
      ],
    ]),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
    },
    services: {
      realtimeHub: {
        isRuntimeConnected: () => false,
      },
    },
  };
}

export async function loadBlockOutputFixtures(
  filePath = path.join(process.cwd(), "benchmarks", "block-output-policy.jsonl"),
): Promise<BlockOutputFixture[]> {
  const raw = await readFile(filePath, "utf8");
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line) as BlockOutputFixture);
}

function sampleBlockForType(type: string): Record<string, unknown> {
  switch (type) {
    case "table":
      return {
        type: "table",
        title: "Örnek tablo",
        columns: ["Alan", "Değer"],
        rows: [["Kalite", "Yüksek"]],
      };
    case "chart":
      return {
        type: "chart",
        title: "Örnek grafik",
        chartType: "line",
        xAxis: "Gün",
        yAxis: "Değer",
        series: [{ name: "Değer", data: [1, 2, 3] }],
      };
    case "math_surface_3d":
      return {
        type: "math_surface_3d",
        title: "Örnek yüzey",
        expression: "z = x^2 + y^2",
        variables: ["x", "y"],
      };
    case "math":
      return {
        type: "math",
        title: "Örnek çözüm",
        latex: "x^2 - 4 = 0",
        steps: [{ label: "Çözüm", latex: "x = \\pm 2" }],
      };
    case "svg":
      return {
        type: "svg",
        title: "Örnek çizim",
        svg: "<svg viewBox=\"0 0 100 100\"><path d=\"M10 90 L50 10 L90 90 Z\"/></svg>",
      };
    case "document_block":
      return {
        type: "document_block",
        title: "Örnek rapor",
        format: "report",
        summary: "Kısa ve düzenli bir rapor.",
        sections: [
          { heading: "Özet", content: "Ana sonuçlar kısa biçimde verildi.", level: 1 },
          { heading: "Detay", content: "İkinci bölüm destekleyici bilgileri içerir.", level: 2 },
        ],
        wordCount: 14,
      };
    case "goal_progress":
      return {
        type: "goal_progress",
        title: "Hedef ilerlemesi",
        status: "running",
        completedSteps: 1,
        totalSteps: 3,
        steps: [
          { title: "Plan", status: "completed" },
          { title: "Uygulama", status: "running" },
        ],
      };
    case "task_trace":
      return {
        type: "task_trace",
        title: "Görev izleme",
        status: "running",
        steps: [
          { id: "analysis", label: "Analiz", status: "completed" },
          { id: "execution", label: "Uygulama", status: "running" },
        ],
      };
    case "text":
    default:
      return {
        type: "text",
        markdown: "Kısa ve temiz cevap.",
      };
  }
}

function sampleContentForFixture(fixture: BlockOutputFixture): string {
  if (fixture.expected.expectedBlockTypes.some((type) => type !== "text")) {
    return "İstenen çıktı block olarak hazırlandı.";
  }
  return `Yanıt: ${fixture.message}`;
}

function renderStandardMissingCount(blocks: AssistantMessageBlock[]): number {
  return blocks.filter((block) => {
    const record = block as Record<string, unknown>;
    return (
      typeof record.type !== "string" ||
      record.visibility !== "user_visible" ||
      typeof record.stableBlockId !== "string" ||
      typeof record.cacheDigest !== "string" ||
      !record.renderHints ||
      typeof record.renderHints !== "object" ||
      Array.isArray(record.renderHints)
    );
  }).length;
}

export async function evaluateBlockOutputPolicyFixtures(
  fixtures?: BlockOutputFixture[],
): Promise<BlockOutputEvaluationSummary> {
  const evaluationFixtures = fixtures ?? await loadBlockOutputFixtures();
  const cases: BlockOutputEvaluationCase[] = [];
  let routeMatches = 0;
  let shapeMatches = 0;
  let validBlockCount = 0;
  let totalBlockCount = 0;
  let duplicateTableCases = 0;
  let rawJsonLeakCases = 0;
  let qualityScoreTotal = 0;

  for (const fixture of evaluationFixtures) {
    const route = await decideCommandRoute(createEvaluationApp() as never, {
      userId: "user-1",
      message: fixture.message,
      source: "mobile",
    });
    const selectedWorkload =
      route.selectedWorkload ||
      selectHybridMobileChatWorkload({
        message: fixture.message,
        primaryIntent: "chat",
        brainProfile: null,
      });
    const decision = decideStructuredResponseDecision({
      prompt: fixture.message,
      selectedWorkload,
    });
    const rawBlocks = fixture.expected.expectedBlockTypes.map(sampleBlockForType);
    const validation = validateAssistantBlockContract({
      blocks: rawBlocks,
      content: sampleContentForFixture(fixture),
      tablePolicy: shouldPromoteMarkdownTableToWidget({
        prompt: fixture.message,
        selectedWorkload,
      })
        ? "explicit_only"
        : "forbidden",
    });
    const normalizedBlocks = validation.blocks;
    const quality = validation.blockQuality;

    const blockTypes = normalizedBlocks.map((block) => block.type);
    const schemaInvalidCount = normalizedBlocks.filter(
      (block) => !elyanAssistantBlockSchema.safeParse(block).success,
    ).length;
    validBlockCount += normalizedBlocks.length - schemaInvalidCount;
    totalBlockCount += normalizedBlocks.length;
    qualityScoreTotal += quality.score;
    if (quality.metrics.duplicateTableBlockCount > 0) {
      duplicateTableCases += 1;
    }
    if (quality.metrics.rawJsonLeakPreventedCount > 0) {
      rawJsonLeakCases += 1;
    }
    if (selectedWorkload === fixture.expected.workload) {
      routeMatches += 1;
    }
    const primaryBlockType = blockTypes[0] ?? "";
    const expectedPrimaryBlockType = fixture.expected.expectedBlockTypes[0] ?? "";
    if (
      decision.primaryShape === fixture.expected.primaryShape &&
      decision.tablePolicy === fixture.expected.tablePolicy &&
      primaryBlockType === expectedPrimaryBlockType
    ) {
      shapeMatches += 1;
    }

    const failures: string[] = [];
    if (selectedWorkload !== fixture.expected.workload) {
      failures.push(`workload expected ${fixture.expected.workload}, got ${selectedWorkload}`);
    }
    if (decision.primaryShape !== fixture.expected.primaryShape) {
      failures.push(`primaryShape expected ${fixture.expected.primaryShape}, got ${decision.primaryShape}`);
    }
    if (decision.tablePolicy !== fixture.expected.tablePolicy) {
      failures.push(`tablePolicy expected ${fixture.expected.tablePolicy}, got ${decision.tablePolicy}`);
    }
    if (primaryBlockType !== expectedPrimaryBlockType) {
      failures.push(`primary block expected ${expectedPrimaryBlockType}, got ${primaryBlockType}`);
    }
    if (schemaInvalidCount > 0) {
      failures.push(`schema invalid blocks ${schemaInvalidCount}`);
    }
    if (renderStandardMissingCount(normalizedBlocks) > 0) {
      failures.push("missing render standard metadata");
    }
    if (quality.metrics.duplicateTableBlockCount > 0) {
      failures.push(`duplicate tables ${quality.metrics.duplicateTableBlockCount}`);
    }
    if (quality.metrics.rawJsonLeakPreventedCount > 0) {
      failures.push(`raw json leak prevented ${quality.metrics.rawJsonLeakPreventedCount}`);
    }
    if (quality.score < 95) {
      failures.push(`quality score ${quality.score}`);
    }

    cases.push({
      id: fixture.id,
      message: fixture.message,
      expected: fixture.expected,
      actual: {
        workload: selectedWorkload,
        primaryShape: decision.primaryShape,
        tablePolicy: decision.tablePolicy,
        blockTypes,
        qualityScore: quality.score,
      },
      pass: failures.length === 0,
      failures,
    });
  }

  const fixtureCount = evaluationFixtures.length;
  const routeAccuracy = fixtureCount > 0 ? routeMatches / fixtureCount : 0;
  const shapeAccuracy = fixtureCount > 0 ? shapeMatches / fixtureCount : 0;
  const schemaValidRate = totalBlockCount > 0 ? validBlockCount / totalBlockCount : 0;
  const duplicateTableRate = fixtureCount > 0 ? duplicateTableCases / fixtureCount : 0;
  const rawJsonLeakRate = fixtureCount > 0 ? rawJsonLeakCases / fixtureCount : 0;
  const averageQualityScore = fixtureCount > 0 ? qualityScoreTotal / fixtureCount : 0;
  const passCount = cases.filter((item) => item.pass).length;
  const ciViolations: string[] = [];

  if (fixtureCount !== 55) ciViolations.push(`fixture count expected 55, got ${fixtureCount}`);
  if (routeAccuracy < 1) ciViolations.push(`route accuracy ${(routeAccuracy * 100).toFixed(1)}% < 100%`);
  if (shapeAccuracy < 1) ciViolations.push(`shape accuracy ${(shapeAccuracy * 100).toFixed(1)}% < 100%`);
  if (schemaValidRate < 0.95) ciViolations.push(`schema valid rate ${(schemaValidRate * 100).toFixed(1)}% < 95%`);
  if (duplicateTableRate > 0) ciViolations.push(`duplicate table rate ${(duplicateTableRate * 100).toFixed(1)}% > 0%`);
  if (rawJsonLeakRate > 0) ciViolations.push(`raw json leak rate ${(rawJsonLeakRate * 100).toFixed(1)}% > 0%`);
  if (averageQualityScore < 95) ciViolations.push(`average quality score ${averageQualityScore.toFixed(1)} < 95`);
  for (const item of cases) {
    if (!item.pass) {
      ciViolations.push(`${item.id}: ${item.failures.join("; ")}`);
    }
  }

  return {
    version: "elyan_block_output_evaluator.v1",
    fixtureCount,
    passCount,
    failCount: fixtureCount - passCount,
    routeAccuracy,
    shapeAccuracy,
    schemaValidRate,
    duplicateTableRate,
    rawJsonLeakRate,
    averageQualityScore,
    ciPass: ciViolations.length === 0,
    ciViolations,
    cases,
  };
}
