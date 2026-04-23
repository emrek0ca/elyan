import { NextResponse } from 'next/server';
import { readRuntimeStatusSnapshot } from '@/core/runtime-status';

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

  return NextResponse.json({
    ok: true,
    runtime: snapshot.runtime,
    secrets: snapshot.secrets,
    readiness: snapshot.readiness,
    models: snapshot.models,
    capabilities: snapshot.capabilities,
    channels: snapshot.channels,
    voice: snapshot.voice,
    mcp: snapshot.mcp,
    controlPlane: snapshot.controlPlane,
    surfaces: snapshot.surfaces,
    nextSteps: snapshot.nextSteps,
    runtimeSettings: snapshot.runtimeSettings,
  });
}
