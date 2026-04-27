import { NextRequest, NextResponse } from 'next/server';
import { getControlPlaneService } from '@/core/control-plane';
import { controlPlaneIntegrationActionSchema } from '@/core/control-plane/types';
import { requireControlPlaneSession } from '@/core/control-plane/session';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  try {
    const session = await requireControlPlaneSession(request);
    const body = await request.json();
    const input = controlPlaneIntegrationActionSchema.safeParse(body);

    if (!input.success) {
      return NextResponse.json(
        { ok: false, error: 'Invalid integration action body', issues: input.error.flatten().fieldErrors },
        { status: 400 }
      );
    }

    const result = await getControlPlaneService().executeIntegrationAction(session.accountId!, input.data);
    return NextResponse.json(result);
  } catch (error: unknown) {
    const status =
      error && typeof error === 'object' && 'statusCode' in error
        ? Number((error as { statusCode: number }).statusCode) || 500
        : 500;
    const message = error instanceof Error ? error.message : 'integration action failed';
    return NextResponse.json({ ok: false, error: message }, { status });
  }
}
