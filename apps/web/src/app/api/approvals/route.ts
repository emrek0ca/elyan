import { NextResponse } from 'next/server';
import { listOperatorApprovals } from '@/core/operator';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
  const approvals = await listOperatorApprovals();

  return NextResponse.json({
    ok: true,
    approvals,
  });
}

