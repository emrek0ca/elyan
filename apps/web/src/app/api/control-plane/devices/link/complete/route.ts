import { NextRequest, NextResponse } from 'next/server';
import { getControlPlaneService } from '@/core/control-plane';
import { controlPlaneDeviceLinkCompleteSchema } from '@/core/control-plane/types';
import { createApiErrorResponse, normalizeApiError } from '@/core/http/api-errors';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const input = controlPlaneDeviceLinkCompleteSchema.safeParse(body);

    if (!input.success) {
      return createApiErrorResponse({
        status: 400,
        code: 'invalid_device_link_completion_body',
        message: 'Invalid device link completion body',
        issues: input.error.flatten().fieldErrors,
      });
    }

    const result = await getControlPlaneService().completeDeviceLink(input.data);
    return NextResponse.json({ ok: true, ...result });
  } catch (error: unknown) {
    const normalized = normalizeApiError(error, {
      status: 500,
      code: 'device_link_completion_failed',
      message: 'device link completion failed',
    });
    return createApiErrorResponse(normalized);
  }
}
