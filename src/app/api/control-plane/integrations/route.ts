import { NextRequest, NextResponse } from 'next/server';
import { getControlPlaneService } from '@/core/control-plane';
import { requireControlPlaneSession } from '@/core/control-plane/session';
import {
  getIntegrationProviderConfig,
  isIntegrationProviderConfigured,
} from '@/core/control-plane/integration-provider';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const PROVIDERS = ['google', 'github', 'notion'] as const;

export async function GET(request: NextRequest) {
  try {
    const session = await requireControlPlaneSession(request);
    const service = getControlPlaneService();
    const [integrations, providers] = await Promise.all([
      service.listIntegrations(session.accountId!),
      Promise.all(
        PROVIDERS.map((provider) => {
          const config = getIntegrationProviderConfig(provider);
          return {
            provider,
            displayName: config.displayName,
            configured: isIntegrationProviderConfigured(provider),
            surfaces: config.surfaces,
            defaultScopes: config.defaultScopes,
          };
        })
      ),
    ]);

    return NextResponse.json({
      ok: true,
      integrations,
      providers,
    });
  } catch (error: unknown) {
    const status =
      error && typeof error === 'object' && 'statusCode' in error
        ? Number((error as { statusCode: number }).statusCode) || 500
        : 500;
    const message = error instanceof Error ? error.message : 'control-plane integration request failed';
    return NextResponse.json({ ok: false, error: message }, { status });
  }
}
