import { NextRequest, NextResponse } from 'next/server';
import { buildControlPlaneProfileResponse, getControlPlaneService } from '@/core/control-plane';
import { isHostedAuthConfigured } from '@/core/control-plane/auth';
import { requireControlPlaneSession } from '@/core/control-plane/session';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(request: NextRequest) {
  if (!isHostedAuthConfigured()) {
    return NextResponse.json(
      {
        ok: false,
        error: 'Hosted identity is disabled in local mode',
        code: 'hosted_identity_unavailable',
      },
      { status: 503 }
    );
  }

  try {
    const session = await requireControlPlaneSession(request);
    const profile = await getControlPlaneService().getHostedProfile(session.accountId!);
    const response = buildControlPlaneProfileResponse(profile);
    return NextResponse.json({
      ok: true,
      ...response,
    });
  } catch (error: unknown) {
    const status = error && typeof error === 'object' && 'statusCode' in error ? Number((error as { statusCode: number }).statusCode) || 500 : 500;
    const message = error instanceof Error ? error.message : 'control-plane session request failed';
    return NextResponse.json({ ok: false, error: message }, { status });
  }
}
