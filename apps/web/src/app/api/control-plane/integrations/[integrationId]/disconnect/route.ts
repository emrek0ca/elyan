import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { getControlPlaneService } from '@/core/control-plane';
import { requireControlPlaneSession } from '@/core/control-plane/session';
import { createApiErrorResponse, normalizeApiError } from '@/core/http/api-errors';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const paramsSchema = z.object({
  integrationId: z.string().trim().min(1),
});

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ integrationId: string }> }
) {
  try {
    const params = paramsSchema.safeParse(await context.params);
    if (!params.success) {
      return NextResponse.json(
        { ok: false, error: 'Invalid integration parameters', issues: params.error.flatten().fieldErrors },
        { status: 400 }
      );
    }

    const session = await requireControlPlaneSession(request);
    const result = await getControlPlaneService().disconnectIntegration(session.accountId!, {
      integrationId: params.data.integrationId,
    });

    return NextResponse.json({ ok: true, integration: result });
  } catch (error: unknown) {
    const normalized = normalizeApiError(error, {
      status: 500,
      code: 'integration_disconnect_failed',
      message: 'integration disconnect failed',
    });
    return createApiErrorResponse(normalized);
  }
}
