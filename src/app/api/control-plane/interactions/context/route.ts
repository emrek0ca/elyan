import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { getControlPlaneService } from '@/core/control-plane';
import { assertControlPlaneAccountAccess, requireControlPlaneSession } from '@/core/control-plane/session';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const querySchema = z.object({
  query: z.string().trim().min(1),
  source: z.string().trim().min(1).default('web'),
  conversationId: z.string().trim().min(1).optional(),
  threadId: z.string().trim().min(1).optional(),
});

function mapControlPlaneError(error: unknown) {
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

export async function GET(request: NextRequest) {
  try {
    const session = await requireControlPlaneSession(request);
    const url = new URL(request.url);
    const params = querySchema.safeParse({
      query: url.searchParams.get('query') ?? '',
      source: url.searchParams.get('source') ?? 'web',
      conversationId: url.searchParams.get('conversationId') ?? undefined,
      threadId: url.searchParams.get('threadId') ?? undefined,
    });

    if (!params.success) {
      return NextResponse.json(
        { ok: false, error: 'Invalid interaction context query', issues: params.error.flatten().fieldErrors },
        { status: 400 }
      );
    }

    assertControlPlaneAccountAccess(session, session.accountId!);
    const context = await getControlPlaneService().getInteractionContext(session.accountId!, params.data);

    return NextResponse.json({ ok: true, context });
  } catch (error: unknown) {
    const mapped = mapControlPlaneError(error);
    return NextResponse.json({ ok: false, error: mapped.message }, { status: mapped.status });
  }
}
