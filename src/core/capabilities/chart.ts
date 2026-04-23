import React from 'react';
import { z } from 'zod';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';

export type ChartRow = Record<string, string | number | null>;

const chartRowSchema = z.record(z.string(), z.union([z.string(), z.number(), z.null()]));

const chartGenerateInputSchema = z.object({
  title: z.string().min(1),
  chartType: z.enum(['line', 'bar', 'area', 'pie']).default('line'),
  xKey: z.string().min(1),
  seriesKeys: z.array(z.string().min(1)).min(1).max(4),
  data: z.array(chartRowSchema).min(1),
  width: z.number().int().min(320).max(1600).default(800),
  height: z.number().int().min(240).max(1200).default(440),
});

const chartSeriesSummarySchema = z.object({
  key: z.string(),
  min: z.number(),
  max: z.number(),
  average: z.number(),
});

const chartGenerateOutputSchema = z.object({
  markup: z.string(),
  summary: z.object({
    rows: z.number().int().nonnegative(),
    series: z.array(chartSeriesSummarySchema),
  }),
});

export { chartGenerateInputSchema, chartGenerateOutputSchema, chartSeriesSummarySchema };

const COLORS = ['#6d8cff', '#48c78e', '#f59e0b', '#f97316'];

function toNumber(value: string | number | null): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
}

function summarizeSeries(data: ChartRow[], seriesKeys: string[]) {
  return seriesKeys.map((key) => {
    const values = data.map((row) => toNumber(row[key])).filter((value): value is number => value !== null);
    const total = values.reduce((sum, value) => sum + value, 0);
    const average = values.length > 0 ? total / values.length : 0;

    return {
      key,
      min: values.length > 0 ? Math.min(...values) : 0,
      max: values.length > 0 ? Math.max(...values) : 0,
      average,
    };
  });
}

export function summarizeChartSeries(data: ChartRow[], seriesKeys: string[]) {
  return summarizeSeries(data, seriesKeys);
}

export async function renderChartMarkup(input: z.output<typeof chartGenerateInputSchema>): Promise<string> {
  const {
    Area,
    AreaChart,
    Bar,
    BarChart,
    CartesianGrid,
    Cell,
    Legend,
    Line,
    LineChart,
    Pie,
    PieChart,
    Tooltip,
    XAxis,
    YAxis,
  } = await import('recharts');

  const rows: Array<{ name: string; [key: string]: string | number | null }> = input.data.map((row, index) => ({
    name: String(row[input.xKey] ?? index + 1),
    ...Object.fromEntries(
      input.seriesKeys.map((key) => [key, toNumber(row[key])])
    ),
  }));

  const chart =
    input.chartType === 'pie'
      ? React.createElement(
          PieChart,
          { width: input.width, height: input.height },
          React.createElement(Tooltip, null),
          React.createElement(
            Pie,
            {
              data: rows.map((row) => ({
                name: row.name,
                value: (row[input.seriesKeys[0]] as number | null | undefined) ?? 0,
              })),
              dataKey: 'value',
              nameKey: 'name',
              outerRadius: Math.min(input.height, input.width) / 3,
              isAnimationActive: false,
            },
            rows.map((_, index) =>
              React.createElement(Cell, {
                key: `cell-${index}`,
                fill: COLORS[index % COLORS.length],
              })
            )
          ),
          React.createElement(Legend, null)
        )
      : input.chartType === 'bar'
        ? React.createElement(
            BarChart,
            { width: input.width, height: input.height, data: rows },
            React.createElement(CartesianGrid, { strokeDasharray: '3 3' }),
            React.createElement(XAxis, { dataKey: 'name' }),
            React.createElement(YAxis, null),
            React.createElement(Tooltip, null),
            React.createElement(Legend, null),
            input.seriesKeys.map((key, index) =>
              React.createElement(Bar, {
                key,
                dataKey: key,
                fill: COLORS[index % COLORS.length],
                isAnimationActive: false,
              })
            )
          )
        : input.chartType === 'area'
          ? React.createElement(
              AreaChart,
              { width: input.width, height: input.height, data: rows },
              React.createElement(CartesianGrid, { strokeDasharray: '3 3' }),
              React.createElement(XAxis, { dataKey: 'name' }),
              React.createElement(YAxis, null),
              React.createElement(Tooltip, null),
              React.createElement(Legend, null),
              input.seriesKeys.map((key, index) =>
                React.createElement(Area, {
                  key,
                  type: 'monotone',
                  dataKey: key,
                  fill: COLORS[index % COLORS.length],
                  stroke: COLORS[index % COLORS.length],
                  isAnimationActive: false,
                  stackId: '1',
                })
              )
            )
          : React.createElement(
              LineChart,
              { width: input.width, height: input.height, data: rows },
              React.createElement(CartesianGrid, { strokeDasharray: '3 3' }),
              React.createElement(XAxis, { dataKey: 'name' }),
              React.createElement(YAxis, null),
              React.createElement(Tooltip, null),
              React.createElement(Legend, null),
              input.seriesKeys.map((key, index) =>
                React.createElement(Line, {
                  key,
                  type: 'monotone',
                  dataKey: key,
                  stroke: COLORS[index % COLORS.length],
                  dot: false,
                  isAnimationActive: false,
                })
              )
            );

  const { renderToStaticMarkup } = await import('react-dom/server');

  return renderToStaticMarkup(
    React.createElement(
      'figure',
      { className: 'elyan-chart' },
      React.createElement('figcaption', { key: 'caption' }, input.title),
      chart
    )
  );
}

export const chartGenerateCapability: CapabilityDefinition<
  typeof chartGenerateInputSchema,
  typeof chartGenerateOutputSchema
> = {
  id: 'chart_generate',
  title: 'Chart Generate',
  description: 'Computes chart summaries and renders static Recharts markup.',
  library: 'recharts',
  enabled: true,
  timeoutMs: 4_000,
  inputSchema: chartGenerateInputSchema,
  outputSchema: chartGenerateOutputSchema,
  run: async (input: z.output<typeof chartGenerateInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    return {
      markup: await renderChartMarkup(input),
      summary: {
        rows: input.data.length,
        series: summarizeChartSeries(input.data, input.seriesKeys),
      },
    };
  },
};
