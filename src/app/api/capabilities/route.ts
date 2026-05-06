import { NextResponse } from 'next/server';
import { buildCapabilityDirectorySnapshot } from '@/core/capabilities/directory';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
  const includeLiveMcp = true;
  const snapshot = await buildCapabilityDirectorySnapshot(includeLiveMcp);

  return NextResponse.json({
    ok: true,
    surface: 'local',
    executionModel: 'local_module_first',
    ...snapshot,
  });
}
