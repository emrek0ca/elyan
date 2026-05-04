import { describe, expect, it, vi } from 'vitest';

vi.mock('@/core/operator/runs', async () => {
  return {
    getOperatorRunStore: () => ({
      list: async () => [
        {
          id: 'run_2',
          title: 'Code patch',
          mode: 'code',
          status: 'blocked',
          updatedAt: '2026-04-29T10:00:00.000Z',
          reasoning: { depth: 'deep' },
          approvals: [{ status: 'pending' }],
        },
        {
          id: 'run_1',
          title: 'Research brief',
          mode: 'research',
          status: 'completed',
          updatedAt: '2026-04-29T09:00:00.000Z',
          reasoning: { depth: 'standard' },
          approvals: [],
        },
      ],
    }),
    listOperatorApprovals: async () => [
      {
        id: 'appr_1',
        title: 'Approve patch',
        status: 'pending',
        approvalLevel: 'CONFIRM',
        riskLevel: 'write_safe',
        requestedAt: '2026-04-29T09:55:00.000Z',
      },
      {
        id: 'appr_2',
        title: 'Review design',
        status: 'approved',
        approvalLevel: 'AUTO',
        riskLevel: 'low',
        requestedAt: '2026-04-29T09:45:00.000Z',
      },
    ],
  };
});

describe('operator status snapshot', () => {
  it('summarizes runs and approvals for the dashboard', async () => {
    const { buildOperatorStatusSnapshot } = await import('@/core/operator/status');
    const snapshot = await buildOperatorStatusSnapshot();

    expect(snapshot.status).toBe('degraded');
    expect(snapshot.runs.total).toBe(2);
    expect(snapshot.runs.blocked).toBe(1);
    expect(snapshot.runs.latest?.id).toBe('run_2');
    expect(snapshot.approvals.pending).toBe(1);
    expect(snapshot.approvals.latest?.id).toBe('appr_1');
    expect(snapshot.summary).toContain('2 runs');
  });
});
