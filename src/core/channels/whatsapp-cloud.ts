import { NextRequest } from 'next/server';
import { dispatchOperatorRequest } from '@/core/operator';
import { readRuntimeEnvValue } from '@/core/runtime-config';
import { readRuntimeSettingsSync } from '@/core/runtime-settings';

function getWhatsappConfig() {
  const settings = readRuntimeSettingsSync();
  return {
    enabled: settings.channels.whatsappCloud.enabled,
    webhookPath: settings.channels.whatsappCloud.webhookPath,
    accessToken: readRuntimeEnvValue('WHATSAPP_CLOUD_ACCESS_TOKEN'),
    phoneNumberId: readRuntimeEnvValue('WHATSAPP_CLOUD_PHONE_NUMBER_ID'),
    verifyToken: readRuntimeEnvValue('WHATSAPP_CLOUD_VERIFY_TOKEN'),
    appSecret: readRuntimeEnvValue('WHATSAPP_CLOUD_APP_SECRET'),
    apiVersion: readRuntimeEnvValue('WHATSAPP_CLOUD_API_VERSION') || 'v21.0',
  };
}

export function getWhatsappCloudStatus() {
  const config = getWhatsappConfig();

  return {
    configured: Boolean(config.accessToken && config.phoneNumberId && config.verifyToken),
    enabled: config.enabled,
    webhookPath: config.webhookPath,
  };
}

function extractIncomingTextMessages(payload: unknown) {
  const entries = (payload as { entry?: unknown[] } | null)?.entry ?? [];
  const messages: Array<{ from: string; body: string; id?: string }> = [];

  for (const entry of entries) {
    const changes = (entry as { changes?: unknown[] })?.changes ?? [];
    for (const change of changes) {
      const value = (change as { value?: { messages?: unknown[] } }).value;
      const incomingMessages = value?.messages ?? [];
      for (const message of incomingMessages) {
        const text = (message as { text?: { body?: string } }).text?.body;
        const from = (message as { from?: string }).from;
        if (text && from) {
          messages.push({ from, body: text, id: (message as { id?: string }).id });
        }
      }
    }
  }

  return messages;
}

async function sendReply(config: ReturnType<typeof getWhatsappConfig>, to: string, text: string) {
  if (!config.accessToken || !config.phoneNumberId) {
    return;
  }

  await fetch(`https://graph.facebook.com/${config.apiVersion}/${config.phoneNumberId}/messages`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${config.accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      messaging_product: 'whatsapp',
      to,
      type: 'text',
      text: { body: text },
    }),
  });
}

export async function handleWhatsappCloudWebhook(request: NextRequest) {
  const config = getWhatsappConfig();
  const url = new URL(request.url);

  if (request.method === 'GET') {
    const mode = url.searchParams.get('hub.mode');
    const token = url.searchParams.get('hub.verify_token');
    const challenge = url.searchParams.get('hub.challenge');

    if (mode === 'subscribe' && token && token === config.verifyToken && challenge) {
      return new Response(challenge, { status: 200 });
    }

    return new Response('Verification failed', { status: 403 });
  }

  if (!config.enabled) {
    return new Response('WhatsApp Cloud integration is disabled.', { status: 403 });
  }

  const payload = await request.json().catch(() => null);
  const messages = extractIncomingTextMessages(payload);

  for (const message of messages) {
    const response = await dispatchOperatorRequest({
      source: 'whatsapp_cloud',
      text: message.body,
      mode: 'speed',
      conversationId: message.from,
      messageId: message.id,
      metadata: {
        channel: 'whatsapp_cloud',
      },
    });

    await sendReply(config, message.from, response.text);
  }

  return Response.json({ ok: true, received: messages.length });
}
