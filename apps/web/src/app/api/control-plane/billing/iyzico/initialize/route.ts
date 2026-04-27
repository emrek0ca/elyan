import { NextRequest, NextResponse } from 'next/server';
import { getControlPlaneService } from '@/core/control-plane';
import { ControlPlaneConfigurationError, ControlPlaneProviderError } from '@/core/control-plane/errors';
import { requireControlPlaneSession } from '@/core/control-plane/session';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  try {
    const session = await requireControlPlaneSession(request);
    const result = await getControlPlaneService().ensureIyzicoBillingBinding(session.accountId!);
    return NextResponse.json({ ok: true, ...result });
  } catch (error: unknown) {
    const status = error && typeof error === 'object' && 'statusCode' in error ? Number((error as { statusCode: number }).statusCode) || 500 : 500;
    const message = error instanceof Error ? error.message : 'iyzico billing initialization failed';
    const unavailable =
      error instanceof ControlPlaneConfigurationError || error instanceof ControlPlaneProviderError;
    return NextResponse.json(
      {
        ok: false,
        error: message,
        billing: unavailable
          ? {
              provider: 'iyzico',
              status: 'unavailable',
              setupRequired: error instanceof ControlPlaneConfigurationError,
            }
          : undefined,
      },
      { status }
    );
  }
}
