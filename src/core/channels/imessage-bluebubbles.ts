import { NextRequest } from 'next/server';
import { dispatchOperatorRequest } from '@/core/operator';
import { readRuntimeEnvValue } from '@/core/runtime-config';
import { readRuntimeSettingsSync } from '@/core/runtime-settings';

function getBlueBubblesConfig() {
  const settings = readRuntimeSettingsSync();
  return {
    enabled: settings.channels.imessage.enabled,
    webhookPath: settings.channels.imessage.webhookPath,
    serverUrl: readRuntimeEnvValue('BLUEBUBBLES_SERVER_URL'),
    guid: readRuntimeEnvValue('BLUEBUBBLES_SERVER_GUID'),
    replyUrl: readRuntimeEnvValue('BLUEBUBBLES_REPLY_URL'),
    webhookSecret: readRuntimeEnvValue('BLUEBUBBLES_WEBHOOK_SECRET'),
  };
}

export function getBlueBubblesStatus() {
  const config = getBlueBubblesConfig();

  return {
    configured: Boolean(config.serverUrl && config.guid),
    enabled: config.enabled,
    webhookPath: config.webhookPath,
    securityChecks: {
      webhookSecret: Boolean(config.webhookSecret),
      replyUrl: Boolean(config.replyUrl),
    },
    costProfile: 'self_hosted_macos_imessage',
  };
}

export async function probeBlueBubblesServer() {
  const config = getBlueBubblesConfig();
  if (!config.serverUrl || !config.guid) {
    return {
      ok: false,
      configured: false,
      status: 'missing_server_url_or_guid',
    };
  }

  const response = await fetch(config.serverUrl, {
    headers: {
      Authorization: `Bearer ${config.guid}`,
    },
  });
  return {
    ok: response.ok,
    configured: true,
    status: response.ok ? response.status : `http_${response.status}`,
  };
}

async function sendBlueBubblesReply(config: ReturnType<typeof getBlueBubblesConfig>, payload: { conversationId: string; text: string }) {
  if (!config.replyUrl) {
    return false;
  }

  const response = await fetch(config.replyUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(config.guid ? { Authorization: `Bearer ${config.guid}` } : {}),
    },
    body: JSON.stringify(payload),
  });

  return response.ok;
}

export async function handleBlueBubblesWebhook(request: NextRequest) {
  const config = getBlueBubblesConfig();

  if (!config.enabled) {
    return new Response('BlueBubbles bridge is disabled.', { status: 403 });
  }

  if (config.webhookSecret && request.headers.get('x-elyan-webhook-secret') !== config.webhookSecret) {
    return new Response('Invalid BlueBubbles webhook secret.', { status: 403 });
  }

  const payload = await request.json().catch(() => null);
  const conversationId =
    (payload as { conversationId?: string; chatGuid?: string; chat_id?: string } | null)?.conversationId ??
    (payload as { conversationId?: string; chatGuid?: string; chat_id?: string } | null)?.chatGuid ??
    (payload as { conversationId?: string; chatGuid?: string; chat_id?: string } | null)?.chat_id ??
    'unknown';
  const text =
    (payload as { text?: string; message?: string; body?: string } | null)?.text ??
    (payload as { text?: string; message?: string; body?: string } | null)?.message ??
    (payload as { text?: string; message?: string; body?: string } | null)?.body ??
    '';

  if (!text.trim()) {
    return Response.json({ ok: true, received: false });
  }

  const response = await dispatchOperatorRequest({
    source: 'imessage_bluebubbles',
    text,
    mode: 'speed',
    conversationId: String(conversationId),
    metadata: {
      channel: 'imessage_bluebubbles',
    },
  });

  const replied = await sendBlueBubblesReply(config, {
    conversationId: String(conversationId),
    text: response.text,
  });

  return Response.json({
    ok: true,
    replied,
  });
}
