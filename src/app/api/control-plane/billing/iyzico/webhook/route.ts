import { NextRequest, NextResponse } from 'next/server';
import { getControlPlaneService } from '@/core/control-plane';
import { getIyzicoBillingClient, iyzicoSubscriptionWebhookSchema } from '@/core/control-plane/iyzico';
import { ControlPlaneAuthenticationError } from '@/core/control-plane/errors';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  try {
    const client = getIyzicoBillingClient();
    if (!client.isConfigured()) {
      throw new Error('Iyzico webhook verification requires hosted billing credentials');
    }

    const signature = request.headers.get('X-IYZ-SIGNATURE-V3');
    if (!signature) {
      throw new ControlPlaneAuthenticationError('Missing iyzico signature header');
    }

    const body = await request.json();
    const parsed = iyzicoSubscriptionWebhookSchema.safeParse(body);
    if (!parsed.success) {
      return NextResponse.json(
        { ok: false, error: 'Invalid iyzico webhook body', issues: parsed.error.flatten().fieldErrors },
        { status: 400 }
      );
    }

    const payload = parsed.data;
    const result = await getControlPlaneService().applyIyzicoWebhook(payload, signature);
    return NextResponse.json({ ok: true, ...result });
  } catch (error: unknown) {
    const status = error && typeof error === 'object' && 'statusCode' in error ? Number((error as { statusCode: number }).statusCode) || 500 : 500;
    const message = error instanceof Error ? error.message : 'iyzico webhook handling failed';
    return NextResponse.json({ ok: false, error: message }, { status });
  }
}
