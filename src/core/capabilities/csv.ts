import Papa from 'papaparse';
import { z } from 'zod';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';

const csvParseInputSchema = z.object({
  csv: z.string().min(1),
  header: z.literal(true).default(true),
  skipEmptyLines: z.boolean().default(true),
  delimiter: z.string().max(1).optional(),
});

const csvParseOutputSchema = z.object({
  rows: z.array(z.record(z.string(), z.unknown())),
  columns: z.array(z.string()),
  errors: z.array(
    z.object({
      type: z.string(),
      code: z.string(),
      message: z.string(),
      row: z.number().nullable().optional(),
    })
  ),
});

const csvExportInputSchema = z.object({
  rows: z.array(z.record(z.string(), z.unknown())).min(1),
  columns: z.array(z.string()).optional(),
});

const csvExportOutputSchema = z.object({
  csv: z.string(),
});

export { csvParseInputSchema, csvParseOutputSchema, csvExportInputSchema, csvExportOutputSchema };

export function parseCsvData(input: z.output<typeof csvParseInputSchema>) {
  const result = Papa.parse<Record<string, unknown>>(input.csv, {
    header: input.header,
    skipEmptyLines: input.skipEmptyLines,
    delimiter: input.delimiter,
  });

  return {
    rows: result.data.filter((row) => row && typeof row === 'object' && !Array.isArray(row)) as Record<string, unknown>[],
    columns: result.meta.fields ?? [],
    errors: result.errors.map((error) => ({
      type: error.type,
      code: error.code,
      message: error.message,
      row: error.row ?? null,
    })),
  };
}

export function exportCsvData(input: z.output<typeof csvExportInputSchema>) {
  return {
    csv: Papa.unparse(input.rows, {
      columns: input.columns,
    }),
  };
}

export const csvParseCapability: CapabilityDefinition<
  typeof csvParseInputSchema,
  typeof csvParseOutputSchema
> = {
  id: 'csv_parse',
  title: 'CSV Parse',
  description: 'Parses CSV data into typed rows with Papa Parse.',
  library: 'papaparse',
  enabled: true,
  timeoutMs: 250,
  inputSchema: csvParseInputSchema,
  outputSchema: csvParseOutputSchema,
  run: async (input: z.output<typeof csvParseInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    return parseCsvData(input);
  },
};

export const csvExportCapability: CapabilityDefinition<
  typeof csvExportInputSchema,
  typeof csvExportOutputSchema
> = {
  id: 'csv_export',
  title: 'CSV Export',
  description: 'Serializes row objects to CSV with Papa Parse.',
  library: 'papaparse',
  enabled: true,
  timeoutMs: 250,
  inputSchema: csvExportInputSchema,
  outputSchema: csvExportOutputSchema,
  run: async (input: z.output<typeof csvExportInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    return exportCsvData(input);
  },
};
