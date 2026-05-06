import { NextRequest, NextResponse } from 'next/server';
import { getControlPlaneService } from '@/core/control-plane';
import { requireControlPlaneSession } from '@/core/control-plane/session';
import { createApiErrorResponse, normalizeApiError } from '@/core/http/api-errors';

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
    const normalized = normalizeApiError(error, {
      status: 500,
      code: 'notification_update_failed',
      message: 'notification update failed',
    });
    return createApiErrorResponse(normalized);
  }
}
