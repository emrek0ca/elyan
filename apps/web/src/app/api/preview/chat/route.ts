/**
 * Preview chat entrypoint used by the frontend and local probes.
 * Layer: preview API. Critical behavior is shared with the main chat handler and must stay aligned.
 */
import { NextRequest } from 'next/server';
import { handleChatRequest } from '../../chat/handler';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  return handleChatRequest(request, {
    requireHostedSession: false,
    learningMode: 'authenticated_optional',
  });
}
