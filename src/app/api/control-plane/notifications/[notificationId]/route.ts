import { NextRequest, NextResponse } from 'next/server';
import { getControlPlaneService } from '@/core/control-plane';
import { requireControlPlaneSession } from '@/core/control-plane/session';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ notificationId: string }> }
) {
  try {
    const session = await requireControlPlaneSession(request);
    const { notificationId } = await context.params;
    const notification = await getControlPlaneService().markNotificationSeen(
      session.accountId!,
      notificationId
    );

    return NextResponse.json({ ok: true, notification });
  } catch (error: unknown) {
    const status =
      error && typeof error === 'object' && 'statusCode' in error
        ? Number((error as { statusCode: number }).statusCode) || 500
        : 500;
    const message = error instanceof Error ? error.message : 'notification update failed';
    return NextResponse.json({ ok: false, error: message }, { status });
  }
}
