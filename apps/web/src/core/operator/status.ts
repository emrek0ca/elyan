import { listOperatorApprovals, getOperatorRunStore, type OperatorApproval, type OperatorRun } from './runs';

export type OperatorStatusSnapshot = {
  status: 'healthy' | 'degraded' | 'unknown';
  runs: {
    total: number;
    blocked: number;
    completed: number;
    failed: number;
    byMode: Record<OperatorRun['mode'], number>;
    latest?: {
      id: string;
      title: string;
      mode: OperatorRun['mode'];
      status: OperatorRun['status'];
      updatedAt: string;
      reasoningDepth: OperatorRun['reasoning']['depth'];
      approvalCount: number;
      pendingApprovals: number;
    };
  };
  approvals: {
    total: number;
    pending: number;
    approved: number;
    rejected: number;
    expired: number;
    latest?: {
      id: string;
      title: string;
      status: OperatorApproval['status'];
      approvalLevel: OperatorApproval['approvalLevel'];
      riskLevel: OperatorApproval['riskLevel'];
      requestedAt: string;
    };
  };
  summary: string;
};

export async function buildOperatorStatusSnapshot(): Promise<OperatorStatusSnapshot> {
  const [runs, approvals] = await Promise.all([getOperatorRunStore().list(), listOperatorApprovals()]);
  const blockedRuns = runs.filter((run) => run.status === 'blocked');
  const completedRuns = runs.filter((run) => run.status === 'completed');
  const failedRuns = runs.filter((run) => run.status === 'failed');
  const byMode = runs.reduce<Record<OperatorRun['mode'], number>>(
    (accumulator, run) => {
      accumulator[run.mode] = (accumulator[run.mode] ?? 0) + 1;
      return accumulator;
    },
    { auto: 0, research: 0, code: 0, cowork: 0 }
  );
  const latestRun = runs[0];
  const latestApproval = approvals[0];
  const pendingApprovals = approvals.filter((approval) => approval.status === 'pending');
  const approvedApprovals = approvals.filter((approval) => approval.status === 'approved');
  const rejectedApprovals = approvals.filter((approval) => approval.status === 'rejected');
  const expiredApprovals = approvals.filter((approval) => approval.status === 'expired');
  const status = blockedRuns.length > 0 || failedRuns.length > 0 ? 'degraded' : 'healthy';

  return {
    status,
    runs: {
      total: runs.length,
      blocked: blockedRuns.length,
      completed: completedRuns.length,
      failed: failedRuns.length,
      byMode,
      latest: latestRun
        ? {
            id: latestRun.id,
            title: latestRun.title,
            mode: latestRun.mode,
            status: latestRun.status,
            updatedAt: latestRun.updatedAt,
            reasoningDepth: latestRun.reasoning.depth,
            approvalCount: latestRun.approvals.length,
            pendingApprovals: latestRun.approvals.filter((approval) => approval.status === 'pending').length,
          }
        : undefined,
    },
    approvals: {
      total: approvals.length,
      pending: pendingApprovals.length,
      approved: approvedApprovals.length,
      rejected: rejectedApprovals.length,
      expired: expiredApprovals.length,
      latest: latestApproval
        ? {
            id: latestApproval.id,
            title: latestApproval.title,
            status: latestApproval.status,
            approvalLevel: latestApproval.approvalLevel,
            riskLevel: latestApproval.riskLevel,
            requestedAt: latestApproval.requestedAt,
          }
        : undefined,
    },
    summary: runs.length > 0
      ? `${runs.length} runs · ${pendingApprovals.length} pending approvals`
      : 'No operator runs recorded yet.',
  };
}
