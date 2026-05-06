/**
 * Main chat API entrypoint for the local runtime and website surfaces.
 * Layer: chat API. Critical request path that delegates into the interaction orchestrator.
 */
import { NextRequest } from 'next/server';
import { handleChatRequest } from './handler';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  return handleChatRequest(request, {
    requireHostedSession: false,
    learningMode: 'authenticated_optional',
  });
}
