/**
 * Hosted account registration endpoint.
 * Layer: control-plane API. Critical for creating real users/accounts in PostgreSQL-backed state.
 */
import { NextRequest, NextResponse } from 'next/server';
import { getIyzicoBillingClient } from '@/core/control-plane/iyzico';
import {
  controlPlaneIdentityRegisterSchema,
  getControlPlanePlan,
  getControlPlaneService,
} from '@/core/control-plane';
import { isHostedAuthConfigured } from '@/core/control-plane/auth';
import { createApiErrorResponse, normalizeApiError } from '@/core/http/api-errors';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  try {
    if (!isHostedAuthConfigured()) {
      return createApiErrorResponse({
        status: 503,
        code: 'hosted_identity_unavailable',
        message: 'Hosted identity is disabled in local mode',
      });
    }

    const body = await request.json();
    const input = controlPlaneIdentityRegisterSchema.safeParse(body);
    if (!input.success) {
      return createApiErrorResponse({
        status: 400,
        code: 'invalid_registration_body',
        message: 'Invalid registration body',
        issues: input.error.flatten().fieldErrors,
      });
    }

    const plan = getControlPlanePlan(input.data.planId);
    if (plan.entitlements.hostedAccess && !getIyzicoBillingClient().isConfigured()) {
      return createApiErrorResponse({
        status: 503,
        code: 'billing_configuration_required',
        message: 'Hosted plan registration requires iyzico API credentials. Local BYOK registration can still proceed.',
      });
    }

    const account = await getControlPlaneService().registerIdentity(input.data);
    return NextResponse.json({ ok: true, ...account });
  } catch (error: unknown) {
    const mapped = normalizeApiError(error, {
      status: 500,
      code: 'control_plane_request_failed',
      message: 'control-plane request failed',
    });
    return createApiErrorResponse(mapped);
  }
}
