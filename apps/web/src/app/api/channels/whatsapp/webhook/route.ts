import { NextRequest } from 'next/server';
import { handleWhatsappCloudWebhook } from '@/core/channels';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(request: NextRequest) {
  return handleWhatsappCloudWebhook(request);
}

export async function POST(request: NextRequest) {
  return handleWhatsappCloudWebhook(request);
}
