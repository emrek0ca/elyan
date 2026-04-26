import { describe, expect, it } from 'vitest';
import { CapabilityAuditTrail, CapabilityRegistry } from '@/core/capabilities';

describe('Spreadsheet capabilities', () => {
  it('writes and reads spreadsheet workbooks', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());

    const written = await registry.execute('spreadsheet_write', {
      format: 'xlsx',
      workbookName: 'Elyan Workbook',
      sheets: [
        {
          name: 'Tasks',
          rows: [
            { id: '1', title: 'Plan', status: 'done' },
            { id: '2', title: 'Execute', status: 'pending' },
          ],
          columns: ['id', 'title', 'status'],
        },
        {
          name: 'Scores',
          rows: [
            { name: 'Elyan', score: 12 },
            { name: 'Iris', score: 18 },
          ],
        },
      ],
    });

    const readBack = await registry.execute('spreadsheet_read', {
      base64: written.base64,
    });

    expect(readBack.kind).toBe('workbook');
    expect(readBack.sheetCount).toBe(2);
    expect(readBack.sheets[0]?.rows[0]?.title).toBe('Plan');
    expect(readBack.sheets[1]?.rows[1]?.name).toBe('Iris');
  });
});
