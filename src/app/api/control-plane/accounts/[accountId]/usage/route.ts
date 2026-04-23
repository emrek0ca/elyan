import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import {
  controlPlaneUsageInputSchema,
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

export async function POST(
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
    const input = controlPlaneUsageInputSchema.safeParse(body);

    if (!input.success) {
      return NextResponse.json(
        { ok: false, error: 'Invalid usage body', issues: input.error.flatten().fieldErrors },
        { status: 400 }
      );
    }

    const result = await getControlPlaneService().recordUsage(accountId, input.data);
    return NextResponse.json({ ok: true, ...result });
  } catch (error: unknown) {
    const mapped = mapControlPlaneError(error);
    return NextResponse.json({ ok: false, error: mapped.message }, { status: mapped.status });
  }
}
