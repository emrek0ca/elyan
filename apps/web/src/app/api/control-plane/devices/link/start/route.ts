import { NextRequest, NextResponse } from 'next/server';
import { getControlPlaneService } from '@/core/control-plane';
import { requireControlPlaneSession } from '@/core/control-plane/session';
import { controlPlaneDeviceLinkStartSchema } from '@/core/control-plane/types';
import { createApiErrorResponse, normalizeApiError } from '@/core/http/api-errors';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  try {
    const session = await requireControlPlaneSession(request);
    const body = await request.json();
    const input = controlPlaneDeviceLinkStartSchema.safeParse(body);

    if (!input.success) {
      return createApiErrorResponse({
        status: 400,
        code: 'invalid_device_link_body',
        message: 'Invalid device link body',
        issues: input.error.flatten().fieldErrors,
      });
    }

    const link = await getControlPlaneService().startDeviceLink(
      session.accountId!,
      session.sub!,
      input.data
    );

    return NextResponse.json({ ok: true, link });
  } catch (error: unknown) {
    const normalized = normalizeApiError(error, {
      status: 500,
      code: 'device_link_start_failed',
      message: 'device link start failed',
    });
    return createApiErrorResponse(normalized);
  }
}
