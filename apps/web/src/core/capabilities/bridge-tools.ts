import { tool, type Tool } from 'ai';
import { z } from 'zod';
import {
  calculateDecimalMath,
  decimalInputSchema,
  decimalOutputSchema,
  evaluateExactMath,
  mathExactInputSchema,
  mathExactOutputSchema,
} from './math';
import {
  csvExportInputSchema,
  csvExportOutputSchema,
  csvParseInputSchema,
  csvParseOutputSchema,
  exportCsvData,
  parseCsvData,
} from './csv';
import {
  chartGenerateInputSchema,
  chartGenerateOutputSchema,
  summarizeChartSeries,
  renderChartMarkup,
} from './chart';
import {
  executeOptimizationSolve,
  optimizationSolveInputSchema,
  optimizationSolveOutputSchema,
} from './optimization';

export type BridgeToolId =
  | 'math_exact'
  | 'math_decimal'
  | 'csv_parse'
  | 'csv_export'
  | 'chart_generate'
  | 'optimization_solve';

export type BridgeToolManifest = {
  id: BridgeToolId;
  title: string;
  description: string;
  library: string;
  timeoutMs: number;
};

export type BridgeToolDefinition = {
  id: BridgeToolId;
  title: string;
  description: string;
  library: string;
  timeoutMs: number;
  inputSchema: z.ZodTypeAny;
  outputSchema: z.ZodTypeAny;
  run: (input: unknown) => Promise<unknown> | unknown;
};

const BRIDGE_TOOL_TIMEOUT_BUFFER_MS = 250;

const bridgeToolDefinitions: BridgeToolDefinition[] = [
  {
    id: 'math_exact',
    title: 'Exact Math',
    description: 'Evaluates deterministic math expressions.',
    library: 'mathjs',
    timeoutMs: 250,
    inputSchema: mathExactInputSchema,
    outputSchema: mathExactOutputSchema,
    run: (input) => {
      const typed = input as z.output<typeof mathExactInputSchema>;
      return evaluateExactMath(typed.expression);
    },
  },
  {
    id: 'math_decimal',
    title: 'Decimal Math',
    description: 'Performs high precision decimal arithmetic.',
    library: 'decimal.js',
    timeoutMs: 250,
    inputSchema: decimalInputSchema,
    outputSchema: decimalOutputSchema,
    run: (input) => {
      const typed = input as z.output<typeof decimalInputSchema>;
      return calculateDecimalMath(typed.left, typed.right, typed.operation);
    },
  },
  {
    id: 'csv_parse',
    title: 'CSV Parse',
    description: 'Parses CSV text into row objects.',
    library: 'papaparse',
    timeoutMs: 250,
    inputSchema: csvParseInputSchema,
    outputSchema: csvParseOutputSchema,
    run: (input) => parseCsvData(input as z.output<typeof csvParseInputSchema>),
  },
  {
    id: 'csv_export',
    title: 'CSV Export',
    description: 'Serializes row objects to CSV.',
    library: 'papaparse',
    timeoutMs: 250,
    inputSchema: csvExportInputSchema,
    outputSchema: csvExportOutputSchema,
    run: (input) => exportCsvData(input as z.output<typeof csvExportInputSchema>),
  },
  {
    id: 'chart_generate',
    title: 'Chart Generate',
    description: 'Computes chart summaries and renders static Recharts markup.',
    library: 'recharts',
    timeoutMs: 2_000,
    inputSchema: chartGenerateInputSchema,
    outputSchema: chartGenerateOutputSchema,
    run: async (input) => {
      const typed = input as z.output<typeof chartGenerateInputSchema>;

      return {
        markup: await renderChartMarkup(typed),
        summary: {
          rows: typed.data.length,
          series: summarizeChartSeries(typed.data, typed.seriesKeys),
        },
      };
    },
  },
  {
    id: 'optimization_solve',
    title: 'Optimization Solve',
    description: 'Models assignment and resource allocation problems, builds QUBO, and compares solver outputs.',
    library: 'elyan-optimization',
    timeoutMs: 3_000,
    inputSchema: optimizationSolveInputSchema,
    outputSchema: optimizationSolveOutputSchema,
    run: (input) => executeOptimizationSolve(input as z.output<typeof optimizationSolveInputSchema>),
  },
];

export function getBridgeToolManifest(): BridgeToolManifest[] {
  return bridgeToolDefinitions.map(({ id, title, description, library, timeoutMs }) => ({
    id,
    title,
    description,
    library,
    timeoutMs,
  }));
}

export function getBridgeToolExecutionTimeoutMs() {
  return (
    bridgeToolDefinitions.reduce((maxTimeout, definition) => Math.max(maxTimeout, definition.timeoutMs), 0) +
    BRIDGE_TOOL_TIMEOUT_BUFFER_MS
  );
}

export function getBridgeToolDefinition(toolId: BridgeToolId) {
  const definition = bridgeToolDefinitions.find((entry) => entry.id === toolId);
  if (!definition) {
    throw new Error(`Bridge tool not found: ${toolId}`);
  }

  return definition;
}

export function executeBridgeTool(toolId: BridgeToolId, input: unknown) {
  const definition = getBridgeToolDefinition(toolId);
  const parsedInput = definition.inputSchema.parse(input);
  return definition.run(parsedInput);
}

export function createAiSdkBridgeTools(): Record<BridgeToolId, Tool<unknown, unknown>> {
  return Object.fromEntries(
    bridgeToolDefinitions.map((definition) => [
      definition.id,
      tool({
        title: definition.title,
        description: definition.description,
        inputSchema: definition.inputSchema,
        execute: async (input, options) => {
          void options;
          return definition.run(input);
        },
      }),
    ])
  ) as Record<BridgeToolId, Tool<unknown, unknown>>;
}
