import { NextResponse } from 'next/server';
import { getOperatorRunStore } from '@/core/operator';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

type RouteContext = {
  params: Promise<{
    runId: string;
  }>;
};

export async function GET(_request: Request, context: RouteContext) {
  const { runId } = await context.params;
  const run = await getOperatorRunStore().get(runId);

  if (!run) {
    return NextResponse.json(
      {
        ok: false,
        error: 'Operator run not found.',
      },
      { status: 404 }
    );
  }

  return NextResponse.json({
    ok: true,
    run,
  });
}

