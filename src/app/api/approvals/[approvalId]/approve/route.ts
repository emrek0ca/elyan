import { NextResponse } from 'next/server';
import { resolveOperatorApproval } from '@/core/operator';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

type RouteContext = {
  params: Promise<{
    approvalId: string;
  }>;
};

export async function POST(_request: Request, context: RouteContext) {
  const { approvalId } = await context.params;
  const approval = await resolveOperatorApproval(approvalId, 'approved');

  if (!approval) {
    return NextResponse.json(
      {
        ok: false,
        error: 'Approval request not found.',
      },
      { status: 404 }
    );
  }

  return NextResponse.json({
    ok: true,
    approval,
  });
}

