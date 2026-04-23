import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import {
  controlPlaneAccountUpsertSchema,
  getControlPlaneService,
} from '@/core/control-plane';
import { assertControlPlaneAccountAccess, requireControlPlaneSession } from '@/core/control-plane/session';

export const dynamic = 'force-dynamic';

const accountParamsSchema = z.object({
  accountId: z.string().trim().min(1),
});

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

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ accountId: string }> }
) {
  try {
    const params = accountParamsSchema.safeParse(await context.params);
    if (!params.success) {
      return NextResponse.json(
        { ok: false, error: 'Invalid account parameters', issues: params.error.flatten().fieldErrors },
        { status: 400 }
      );
    }

    const { accountId } = params.data;
    const session = await requireControlPlaneSession(request);
    assertControlPlaneAccountAccess(session, accountId);
    const account = await getControlPlaneService().getAccount(accountId);
    return NextResponse.json({ ok: true, account });
  } catch (error: unknown) {
    const mapped = mapControlPlaneError(error);
    return NextResponse.json({ ok: false, error: mapped.message }, { status: mapped.status });
  }
}

export async function PUT(
  request: NextRequest,
  context: { params: Promise<{ accountId: string }> }
) {
  try {
    const params = accountParamsSchema.safeParse(await context.params);
    if (!params.success) {
      return NextResponse.json(
        { ok: false, error: 'Invalid account parameters', issues: params.error.flatten().fieldErrors },
        { status: 400 }
      );
    }

    const { accountId } = params.data;
    const session = await requireControlPlaneSession(request);
    assertControlPlaneAccountAccess(session, accountId);
    const body = await request.json();
    const input = controlPlaneAccountUpsertSchema.safeParse(body);

    if (!input.success) {
      return NextResponse.json(
        { ok: false, error: 'Invalid account body', issues: input.error.flatten().fieldErrors },
        { status: 400 }
      );
    }

    const account = await getControlPlaneService().upsertAccount(accountId, {
      ...input.data,
      ownerUserId: session.sub,
      billingCustomerRef: undefined,
    });
    return NextResponse.json({ ok: true, account });
  } catch (error: unknown) {
    const mapped = mapControlPlaneError(error);
    return NextResponse.json({ ok: false, error: mapped.message }, { status: mapped.status });
  }
}
