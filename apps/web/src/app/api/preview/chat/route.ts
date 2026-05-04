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
