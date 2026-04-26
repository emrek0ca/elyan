import ExcelJS from 'exceljs';
import { z } from 'zod';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';

class SpreadsheetCapabilityError extends Error {
  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'SpreadsheetCapabilityError';

    if (cause !== undefined) {
      (this as Error & { cause?: unknown }).cause = cause;
    }
  }
}

const spreadsheetRowSchema = z.record(z.string(), z.unknown());

const spreadsheetSheetSchema = z.object({
  name: z.string().min(1),
  rowCount: z.number().int().nonnegative(),
  columnNames: z.array(z.string()),
  truncated: z.boolean(),
  rows: z.array(spreadsheetRowSchema),
});

const spreadsheetReadInputSchema = z.object({
  base64: z.string().min(1),
  sheetName: z.string().min(1).optional(),
  maxRows: z.number().int().min(1).max(10_000).default(1_000),
});

const spreadsheetReadOutputSchema = z.object({
  kind: z.literal('workbook'),
  format: z.string(),
  sheetCount: z.number().int().nonnegative(),
  sheets: z.array(spreadsheetSheetSchema),
});

const spreadsheetWriteInputSchema = z.object({
  format: z.enum(['xlsx', 'xls', 'ods']).default('xlsx'),
  workbookName: z.string().min(1).optional(),
  sheets: z
    .array(
      z.object({
        name: z.string().min(1),
        rows: z.array(spreadsheetRowSchema).min(1),
        columns: z.array(z.string().min(1)).optional(),
      })
    )
    .min(1),
});

const spreadsheetWriteOutputSchema = z.object({
  kind: z.literal('workbook'),
  format: z.enum(['xlsx', 'xls', 'ods']),
  base64: z.string(),
  byteLength: z.number().int().positive(),
  sheetCount: z.number().int().positive(),
});

function uniqueColumns(rows: Array<Record<string, unknown>>) {
  const columns: string[] = [];
  const seen = new Set<string>();

  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (seen.has(key)) {
        continue;
      }

      seen.add(key);
      columns.push(key);
    }
  }

  return columns;
}

function assertXlsxFormat(format: 'xlsx' | 'xls' | 'ods') {
  if (format !== 'xlsx') {
    throw new SpreadsheetCapabilityError(`${format.toUpperCase()} export is unavailable in the v1.2 runtime. Use XLSX or CSV.`);
  }
}

function normalizeCellValue(value: ExcelJS.CellValue): unknown {
  if (value instanceof Date) {
    return value.toISOString();
  }

  if (value && typeof value === 'object') {
    if ('text' in value && typeof value.text === 'string') {
      return value.text;
    }

    if ('result' in value) {
      return normalizeCellValue(value.result as ExcelJS.CellValue);
    }

    if ('richText' in value && Array.isArray(value.richText)) {
      return value.richText.map((entry) => entry.text).join('');
    }
  }

  return value ?? null;
}

async function parseWorkbook(base64: string) {
  try {
    const workbook = new ExcelJS.Workbook();
    const loadWorkbook = workbook.xlsx.load.bind(workbook.xlsx) as unknown as (data: unknown) => Promise<ExcelJS.Workbook>;
    await loadWorkbook(Buffer.from(base64, 'base64'));
    return workbook;
  } catch (error) {
    throw new SpreadsheetCapabilityError('Unable to read XLSX spreadsheet workbook', error);
  }
}

function sheetToRows(sheet: ExcelJS.Worksheet, maxRows: number) {
  const headerRow = sheet.getRow(1);
  const headers = Array.from({ length: sheet.columnCount }, (_, index) => {
    const header = normalizeCellValue(headerRow.getCell(index + 1).value);
    return typeof header === 'string' && header.trim().length > 0 ? header.trim() : `column_${index + 1}`;
  });
  const rows: Array<Record<string, unknown>> = [];

  for (let rowNumber = 2; rowNumber <= sheet.rowCount; rowNumber += 1) {
    const row = sheet.getRow(rowNumber);
    if (!row.hasValues) {
      continue;
    }

    const record: Record<string, unknown> = {};
    headers.forEach((header, index) => {
      record[header] = normalizeCellValue(row.getCell(index + 1).value);
    });
    rows.push(record);
  }

  const truncatedRows = rows.slice(0, maxRows);

  return {
    rowCount: rows.length,
    rows: truncatedRows,
    truncated: rows.length > truncatedRows.length,
    columnNames: uniqueColumns(truncatedRows),
  };
}

export async function readSpreadsheetWorkbook(input: z.output<typeof spreadsheetReadInputSchema>) {
  const workbook = await parseWorkbook(input.base64);
  const sheetNames = workbook.worksheets.map((sheet) => sheet.name);
  const targetSheetNames = input.sheetName ? [input.sheetName] : sheetNames;

  const sheets = targetSheetNames.map((name) => {
    const sheet = workbook.getWorksheet(name);

    if (!sheet) {
      throw new SpreadsheetCapabilityError(`Spreadsheet sheet not found: ${name}`);
    }

    const sheetData = sheetToRows(sheet, input.maxRows);

    return {
      name,
      rowCount: sheetData.rowCount,
      columnNames: sheetData.columnNames,
      truncated: sheetData.truncated,
      rows: sheetData.rows,
    };
  });

  return {
    kind: 'workbook' as const,
    format: 'xlsx',
    sheetCount: sheetNames.length,
    sheets,
  };
}

export async function writeSpreadsheetWorkbook(input: z.output<typeof spreadsheetWriteInputSchema>) {
  try {
    assertXlsxFormat(input.format);
    const workbook = new ExcelJS.Workbook();
    workbook.creator = 'Elyan';
    workbook.lastModifiedBy = 'Elyan';
    workbook.created = new Date('2000-01-01T00:00:00.000Z');
    workbook.modified = new Date('2000-01-01T00:00:00.000Z');

    if (input.workbookName) {
      workbook.title = input.workbookName;
    }

    for (const sheet of input.sheets) {
      const columns = sheet.columns ?? uniqueColumns(sheet.rows);
      const worksheet = workbook.addWorksheet(sheet.name);
      worksheet.addRow(columns);
      for (const row of sheet.rows) {
        worksheet.addRow(columns.map((column) => row[column] ?? null));
      }
    }

    const rawBuffer = await workbook.xlsx.writeBuffer();
    const buffer = Buffer.isBuffer(rawBuffer) ? rawBuffer : Buffer.from(rawBuffer);

    return {
      kind: 'workbook' as const,
      format: input.format,
      base64: buffer.toString('base64'),
      byteLength: buffer.byteLength,
      sheetCount: input.sheets.length,
    };
  } catch (error) {
    throw new SpreadsheetCapabilityError('Unable to write spreadsheet workbook', error);
  }
}

export const spreadsheetReadCapability: CapabilityDefinition<
  typeof spreadsheetReadInputSchema,
  typeof spreadsheetReadOutputSchema
> = {
  id: 'spreadsheet_read',
  title: 'Spreadsheet Read',
  description: 'Reads XLSX workbooks into normalized rows with ExcelJS.',
  library: 'exceljs',
  enabled: true,
  timeoutMs: 1_500,
  inputSchema: spreadsheetReadInputSchema,
  outputSchema: spreadsheetReadOutputSchema,
  run: async (input: z.output<typeof spreadsheetReadInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    return await readSpreadsheetWorkbook(input);
  },
};

export const spreadsheetWriteCapability: CapabilityDefinition<
  typeof spreadsheetWriteInputSchema,
  typeof spreadsheetWriteOutputSchema
> = {
  id: 'spreadsheet_write',
  title: 'Spreadsheet Write',
  description: 'Creates XLSX workbooks from normalized row objects with ExcelJS.',
  library: 'exceljs',
  enabled: true,
  timeoutMs: 1_500,
  inputSchema: spreadsheetWriteInputSchema,
  outputSchema: spreadsheetWriteOutputSchema,
  run: async (input: z.output<typeof spreadsheetWriteInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    return await writeSpreadsheetWorkbook(input);
  },
};
