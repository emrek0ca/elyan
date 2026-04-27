import { describe, expect, it } from 'vitest';
import { CapabilityAuditTrail, CapabilityRegistry } from '@/core/capabilities';

describe('Chart capability', () => {
  it('renders a static chart and separates summary from markup', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());
    const result = await registry.execute('chart_generate', {
      title: 'Revenue',
      chartType: 'line',
      xKey: 'month',
      seriesKeys: ['value'],
      data: [
        { month: 'Jan', value: 10 },
        { month: 'Feb', value: 14 },
        { month: 'Mar', value: 9 },
      ],
      width: 640,
      height: 320,
    });

    expect(result.markup).toContain('Revenue');
    expect(result.markup).toContain('recharts-wrapper');
    expect(result.summary.rows).toBe(3);
    expect(result.summary.series[0]?.max).toBe(14);
  });
});
