import { NextRequest, NextResponse } from 'next/server';
import { getDispatchStatus } from '@/core/dispatch';
import { createApiErrorResponse, normalizeApiError } from '@/core/http/api-errors';
import { resolveDispatchSession } from '@/core/dispatch/auth';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(request: NextRequest) {
  try {
    await resolveDispatchSession(request);
    const snapshot = await getDispatchStatus();
    return NextResponse.json({
      ok: true,
      snapshot,
    });
  } catch (error: unknown) {
    const normalized = normalizeApiError(error, {
      status: 500,
      code: 'dispatch_status_failed',
      message: 'Dispatch status request failed',
    });
    return createApiErrorResponse(normalized);
  }
}
