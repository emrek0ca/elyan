import { describe, expect, it } from 'vitest';
import { CapabilityAuditTrail, CapabilityRegistry } from '@/core/capabilities';

describe('Capability smoke checks', () => {
  it('boots the registry with tested capabilities', () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());
    const capabilityIds = registry.list().map((capability) => capability.id);

    expect(capabilityIds).toEqual(
      expect.arrayContaining([
        'fuzzy_find',
        'math_exact',
        'math_decimal',
        'csv_parse',
        'csv_export',
        'docx_read',
        'docx_write',
        'pdf_extract',
        'pdf_workflow',
        'image_process',
        'spreadsheet_read',
        'spreadsheet_write',
        'archive_zip',
        'ocr_image',
        'metadata_parse',
        'markdown_render',
        'local_search_index',
        'web_read_dynamic',
        'web_crawl',
        'browser_automation',
        'chart_generate',
        'tool_bridge',
        'mcp_bridge',
      ])
    );
  });
});
