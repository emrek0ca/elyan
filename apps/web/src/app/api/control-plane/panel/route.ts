/**
 * Hosted panel aggregation endpoint for dashboard UI and local probes.
 * Layer: control-plane API. Critical entrypoint for authenticated account, device, and billing state.
 */
import { NextRequest, NextResponse } from 'next/server';
import { buildControlPlanePanelResponse, getControlPlaneService } from '@/core/control-plane';
import { requireControlPlaneSession } from '@/core/control-plane/session';
import { createApiErrorResponse, normalizeApiError } from '@/core/http/api-errors';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(request: NextRequest) {
  try {
    const session = await requireControlPlaneSession(request);
    const service = getControlPlaneService();
    const [profile, devices] = await Promise.all([
      service.getHostedProfile(session.accountId!),
      service.listDevices(session.accountId!, 20),
    ]);

    return NextResponse.json({
      ok: true,
      ...buildControlPlanePanelResponse(profile, devices),
    });
  } catch (error: unknown) {
    const normalized = normalizeApiError(error, {
      status: 500,
      code: 'control_plane_panel_failed',
      message: 'control-plane panel request failed',
    });
    return createApiErrorResponse(normalized);
  }
}
