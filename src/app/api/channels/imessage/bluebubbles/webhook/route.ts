import { NextRequest } from 'next/server';
import { handleBlueBubblesWebhook } from '@/core/channels';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  return handleBlueBubblesWebhook(request);
}
