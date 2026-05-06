/**
 * Authenticated hosted session lookup.
 * Layer: control-plane API. Critical for session checks and panel/account hydration.
 */
import { NextRequest, NextResponse } from 'next/server';
import { buildControlPlaneProfileResponse, getControlPlaneService } from '@/core/control-plane';
import { isHostedAuthConfigured } from '@/core/control-plane/auth';
import { requireControlPlaneSession } from '@/core/control-plane/session';
import { createApiErrorResponse, normalizeApiError } from '@/core/http/api-errors';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(request: NextRequest) {
  if (!isHostedAuthConfigured()) {
    return createApiErrorResponse({
      status: 401,
      code: 'hosted_identity_unavailable',
      message: 'Hosted identity is disabled in local mode',
    });
  }

  try {
    const session = await requireControlPlaneSession(request);
    const profile = await getControlPlaneService().getHostedProfile(session.accountId!);
    const response = buildControlPlaneProfileResponse(profile);
    return NextResponse.json({
      ok: true,
      ...response,
    });
  } catch (error: unknown) {
    const normalized = normalizeApiError(error, {
      status: 401,
      code: 'control_plane_session_required',
      message: 'Control-plane session is required',
    });
    return createApiErrorResponse(normalized);
  }
}
