import { NextResponse } from 'next/server';
import { buildCapabilityDirectorySnapshot } from '@/core/capabilities/directory';
import { buildOperatorStatusSnapshot } from '@/core/operator/status';
import { buildRuntimeRegistryHealthSnapshot, buildRuntimeRegistrySnapshot } from '@/core/runtime-registry';
import { registry } from '@/core/providers';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
  const includeLiveMcp = true;
  const [snapshot, operator] = await Promise.all([
    buildCapabilityDirectorySnapshot(includeLiveMcp),
    buildOperatorStatusSnapshot(),
  ]);
  let models: Awaited<ReturnType<typeof registry.listAvailableModels>> = [];
  let modelError: string | undefined;
  try {
    models = await registry.listAvailableModels();
  } catch (error) {
    modelError = error instanceof Error ? error.message : 'Failed to list available models';
  }
  const runtimeRegistry = buildRuntimeRegistrySnapshot({
    models,
    capabilities: snapshot,
    operator,
    modelError,
  });
  const registryHealth = buildRuntimeRegistryHealthSnapshot(runtimeRegistry);

  return NextResponse.json({
    ok: true,
    surface: 'local',
    executionModel: 'local_module_first',
    ...snapshot,
    health: registryHealth,
    registry: runtimeRegistry,
  });
}
