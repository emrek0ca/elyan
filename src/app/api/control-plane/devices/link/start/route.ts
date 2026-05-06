import { NextRequest, NextResponse } from 'next/server';
import { getControlPlaneService } from '@/core/control-plane';
import { requireControlPlaneSession } from '@/core/control-plane/session';
import { controlPlaneDeviceLinkStartSchema } from '@/core/control-plane/types';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  try {
    const session = await requireControlPlaneSession(request);
    const body = await request.json();
    const input = controlPlaneDeviceLinkStartSchema.safeParse(body);

    if (!input.success) {
      return NextResponse.json(
        { ok: false, error: 'Invalid device link body', issues: input.error.flatten().fieldErrors },
        { status: 400 }
      );
    }

    const link = await getControlPlaneService().startDeviceLink(
      session.accountId!,
      session.sub!,
      input.data
    );

    return NextResponse.json({ ok: true, link });
  } catch (error: unknown) {
    const status = error && typeof error === 'object' && 'statusCode' in error ? Number((error as { statusCode: number }).statusCode) || 500 : 500;
    const message = error instanceof Error ? error.message : 'device link start failed';
    return NextResponse.json({ ok: false, error: message }, { status });
  }
}
