import { NextResponse } from 'next/server';
import { getLatestElyanReleaseResponse } from '@/core/control-plane/releases';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
  try {
    return NextResponse.json(await getLatestElyanReleaseResponse());
  } catch (error) {
    const message = error instanceof Error ? error.message : 'release lookup failed';
    return NextResponse.json(
      {
        ok: false,
        error: message,
        repository: process.env.GITHUB_REPOSITORY ?? 'emrek0ca/elyan',
      },
      { status: 503 }
    );
  }
}
