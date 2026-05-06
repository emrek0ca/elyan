/**
 * Hosted control-plane readiness probe.
 * Layer: control-plane diagnostics. Critical for env, schema, auth, and billing visibility.
 */
import { NextResponse } from 'next/server';
import { readControlPlaneHealthSnapshot } from '@/core/control-plane';

export const dynamic = 'force-dynamic';

export async function GET() {
  const health = await readControlPlaneHealthSnapshot();
  return NextResponse.json(health, { status: health.ok ? 200 : 500 });
}
