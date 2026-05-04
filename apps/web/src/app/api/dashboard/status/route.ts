import { NextResponse } from 'next/server';
import { readRuntimeStatusSnapshot } from '@/core/runtime-status';
import { buildRuntimeSurfaceSnapshot } from '@/core/runtime-surface';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
  const result = await readRuntimeStatusSnapshot();

  if (!result.ok) {
    return NextResponse.json(
      {
        ok: false,
        error: 'Environment configuration is invalid.',
        issues: result.issues,
      },
      { status: 503 }
    );
  }

  const { snapshot } = result;
  const runtimeSurfaces =
    snapshot.surfaces ??
    buildRuntimeSurfaceSnapshot({
      localModelCount: snapshot.models.length,
      searchEnabled: snapshot.readiness.searchEnabled,
      searchAvailable: snapshot.readiness.searchAvailable,
      controlPlaneReady: snapshot.controlPlane.health?.ok === true,
      hostedAuthConfigured: snapshot.controlPlane.health?.connection?.hostedReady ?? false,
      hostedBillingConfigured:
        snapshot.controlPlane.health?.connection?.billingMode === 'production' ||
        snapshot.controlPlane.health?.connection?.billingMode === 'sandbox',
    });

  return NextResponse.json({
    ok: true,
    runtime: snapshot.runtime,
    secrets: snapshot.secrets,
    readiness: snapshot.readiness,
    models: snapshot.models,
    capabilities: snapshot.capabilities,
    connections: snapshot.connections,
    channels: snapshot.channels,
    localAgent: snapshot.localAgent,
    voice: snapshot.voice,
    team: snapshot.team,
    operator: snapshot.operator,
    registry: snapshot.registry,
    optimization: snapshot.optimization,
    mcp: snapshot.mcp,
    controlPlane: snapshot.controlPlane,
    workspace: snapshot.workspace,
    surfaces: runtimeSurfaces.surfaces,
    nextSteps: snapshot.nextSteps ?? runtimeSurfaces.nextSteps,
    runtimeSettings: snapshot.runtimeSettings,
  });
}
