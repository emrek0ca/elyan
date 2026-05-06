import { NextRequest, NextResponse } from 'next/server';
import { getControlPlaneService } from '@/core/control-plane';
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

    const result = await getControlPlaneService().rotateDeviceToken(deviceToken);
    return NextResponse.json(result);
  } catch (error: unknown) {
    const normalized = normalizeApiError(error, {
      status: 500,
      code: 'device_token_rotation_failed',
      message: 'device token rotation failed',
    });
    return createApiErrorResponse(normalized);
  }
}
