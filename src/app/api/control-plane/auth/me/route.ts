import { NextRequest, NextResponse } from 'next/server';
import { getControlPlaneService } from '@/core/control-plane';
import { requireControlPlaneSession } from '@/core/control-plane/session';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(request: NextRequest) {
  try {
    const session = await requireControlPlaneSession(request);

    const account = await getControlPlaneService().getAccount(session.accountId!);
    return NextResponse.json({
      ok: true,
      session: {
        userId: session.sub,
        email: session.email,
        name: session.name,
        accountId: session.accountId,
        ownerType: session.ownerType,
        role: session.role,
        planId: session.planId,
      },
      account,
    });
  } catch (error: unknown) {
    const status = error && typeof error === 'object' && 'statusCode' in error ? Number((error as { statusCode: number }).statusCode) || 500 : 500;
    const message = error instanceof Error ? error.message : 'control-plane session request failed';
    return NextResponse.json({ ok: false, error: message }, { status });
  }
}
