import { NextRequest, NextResponse } from 'next/server';
import { getControlPlaneService } from '@/core/control-plane';
import { controlPlaneDevicePushSchema } from '@/core/control-plane/types';
import { createApiErrorResponse, normalizeApiError } from '@/core/http/api-errors';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

function readDeviceToken(request: NextRequest) {
  return (
    request.headers.get('x-elyan-device-token') ??
    request.headers.get('authorization')?.replace(/^Bearer\s+/i, '') ??
    undefined
  );
}

export async function POST(request: NextRequest) {
  try {
    const deviceToken = readDeviceToken(request);
    if (!deviceToken) {
      return createApiErrorResponse({
        status: 401,
        code: 'device_token_required',
        message: 'Device token is required',
      });
    }

    const body = await request.json();
    const input = controlPlaneDevicePushSchema.safeParse({ ...body, deviceToken });

    if (!input.success) {
      return createApiErrorResponse({
        status: 400,
        code: 'invalid_device_sync_payload',
        message: 'Invalid device sync payload',
        issues: input.error.flatten().fieldErrors,
      });
    }

    const result = await getControlPlaneService().pushDevice(input.data);
    return NextResponse.json(result);
  } catch (error: unknown) {
    const normalized = normalizeApiError(error, {
      status: 500,
      code: 'device_sync_push_failed',
      message: 'device sync push failed',
    });
    return createApiErrorResponse(normalized);
  }
}
