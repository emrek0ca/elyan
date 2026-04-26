import { NextRequest, NextResponse } from 'next/server';
import { getControlPlaneService } from '@/core/control-plane';
import { requireControlPlaneSession } from '@/core/control-plane/session';
import type { ControlPlaneHostedDevice } from '@/core/control-plane/types';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

function serializeHostedDevice(device: ControlPlaneHostedDevice) {
  return {
    deviceId: device.deviceId,
    deviceLabel: device.deviceLabel,
    status: device.status,
    linkedAt: device.linkedAt,
    lastSeenAt: device.lastSeenAt,
    lastSeenReleaseTag: device.lastSeenReleaseTag,
    revokedAt: device.revokedAt,
    createdAt: device.createdAt,
    updatedAt: device.updatedAt,
  };
}

export async function GET(request: NextRequest) {
  try {
    const session = await requireControlPlaneSession(request);
    const service = getControlPlaneService();
    const [profile, devices] = await Promise.all([
      service.getHostedProfile(session.accountId!),
      service.listDevices(session.accountId!, 20),
    ]);

    return NextResponse.json({
      ok: true,
      session: profile.session,
      profile,
      account: profile.account,
      devices: devices.map((device) => serializeHostedDevice(device)),
    });
  } catch (error: unknown) {
    const status =
      error && typeof error === 'object' && 'statusCode' in error
        ? Number((error as { statusCode: number }).statusCode) || 500
        : 500;
    const message = error instanceof Error ? error.message : 'control-plane panel request failed';
    return NextResponse.json({ ok: false, error: message }, { status });
  }
}
