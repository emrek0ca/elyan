import { NextRequest, NextResponse } from 'next/server';
import { buildControlPlanePanelResponse, getControlPlaneService } from '@/core/control-plane';
import { requireControlPlaneSession } from '@/core/control-plane/session';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(request: NextRequest) {
  try {
    const session = await requireControlPlaneSession(request);
    const service = getControlPlaneService();
    const [profile, devices] = await Promise.all([
      service.getHostedProfile(session.accountId!),
      service.listDevices(session.accountId!, 20),
    ]);

    return NextResponse.json({
      ok: true,
      ...buildControlPlanePanelResponse(profile, devices),
    });
  } catch (error: unknown) {
    const status =
      error && typeof error === 'object' && 'statusCode' in error
        ? Number((error as { statusCode: number }).statusCode) || 500
        : 500;
    const message = error instanceof Error ? error.message : 'control-plane panel request failed';
    return NextResponse.json({ ok: false, error: message }, { status });
  }
}
