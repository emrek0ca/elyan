import { NextRequest } from 'next/server';
import { handleChatRequest } from './handler';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  return handleChatRequest(request, {
    requireHostedSession: true,
    learningMode: 'authenticated_optional',
  });
}
