import { NextRequest, NextResponse } from 'next/server';
import { getControlPlaneService } from '@/core/control-plane';
import { controlPlaneDeviceLinkCompleteSchema } from '@/core/control-plane/types';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const input = controlPlaneDeviceLinkCompleteSchema.safeParse(body);

    if (!input.success) {
      return NextResponse.json(
        { ok: false, error: 'Invalid device link completion body', issues: input.error.flatten().fieldErrors },
        { status: 400 }
      );
    }

    const result = await getControlPlaneService().completeDeviceLink(input.data);
    return NextResponse.json({ ok: true, ...result });
  } catch (error: unknown) {
    const status = error && typeof error === 'object' && 'statusCode' in error ? Number((error as { statusCode: number }).statusCode) || 500 : 500;
    const message = error instanceof Error ? error.message : 'device link completion failed';
    return NextResponse.json({ ok: false, error: message }, { status });
  }
}
