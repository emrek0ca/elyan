import { NextRequest, NextResponse } from 'next/server';
import { getIyzicoBillingClient } from '@/core/control-plane/iyzico';
import {
  controlPlaneIdentityRegisterSchema,
  getControlPlanePlan,
  getControlPlaneService,
} from '@/core/control-plane';
import { assertHostedAuthConfigured } from '@/core/control-plane/auth';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

function mapControlPlaneError(error: unknown) {
  if (error instanceof SyntaxError) {
    return {
      status: 400,
      message: 'Invalid JSON body',
    };
  }

  if (error && typeof error === 'object' && 'statusCode' in error) {
    return {
      status: Number((error as { statusCode: number }).statusCode) || 500,
      message: error instanceof Error ? error.message : 'control-plane request failed',
    };
  }

  return {
    status: 500,
    message: error instanceof Error ? error.message : 'control-plane request failed',
  };
}

export async function POST(request: NextRequest) {
  try {
    assertHostedAuthConfigured();

    const body = await request.json();
    const input = controlPlaneIdentityRegisterSchema.safeParse(body);
    if (!input.success) {
      return NextResponse.json(
        { ok: false, error: 'Invalid registration body', issues: input.error.flatten().fieldErrors },
        { status: 400 }
      );
    }

    const plan = getControlPlanePlan(input.data.planId);
    if (plan.entitlements.hostedAccess && !getIyzicoBillingClient().isConfigured()) {
      return NextResponse.json(
        {
          ok: false,
          error:
            'Hosted plan registration requires iyzico API credentials. Local BYOK registration can still proceed.',
        },
        { status: 503 }
      );
    }

    const account = await getControlPlaneService().registerIdentity(input.data);
    return NextResponse.json({ ok: true, ...account });
  } catch (error: unknown) {
    const mapped = mapControlPlaneError(error);
    return NextResponse.json({ ok: false, error: mapped.message }, { status: mapped.status });
  }
}
