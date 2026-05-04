import { NextRequest, NextResponse } from 'next/server';
import { getControlPlaneService } from '@/core/control-plane';
import { controlPlaneDevicePushSchema } from '@/core/control-plane/types';

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
      return NextResponse.json({ ok: false, error: 'Device token is required' }, { status: 401 });
    }

    const body = await request.json();
    const input = controlPlaneDevicePushSchema.safeParse({ ...body, deviceToken });

    if (!input.success) {
      return NextResponse.json(
        { ok: false, error: 'Invalid device sync payload', issues: input.error.flatten().fieldErrors },
        { status: 400 }
      );
    }

    const result = await getControlPlaneService().pushDevice(input.data);
    return NextResponse.json(result);
  } catch (error: unknown) {
    const status = error && typeof error === 'object' && 'statusCode' in error ? Number((error as { statusCode: number }).statusCode) || 500 : 500;
    const message = error instanceof Error ? error.message : 'device sync push failed';
    return NextResponse.json({ ok: false, error: message }, { status });
  }
}
