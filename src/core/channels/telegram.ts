import { Bot, webhookCallback } from 'grammy';
import { readRuntimeEnvValue } from '@/core/runtime-config';
import { readRuntimeSettingsSync } from '@/core/runtime-settings';
import { dispatchOperatorRequest } from '@/core/operator';

let singletonBot: Bot | null = null;
let singletonToken: string | null = null;

function createTelegramBot() {
  const token = readRuntimeEnvValue('TELEGRAM_BOT_TOKEN');
  if (!token) {
    return null;
  }

  if (singletonBot && singletonToken === token) {
    return singletonBot;
  }

  const bot = new Bot(token);

  bot.command('start', async (ctx) => {
    await ctx.reply('Elyan is connected. Send a message to route it into the local operator.');
  });

  bot.command('help', async (ctx) => {
    await ctx.reply('Send a text request. Elyan will route it through the local operator and reply with the result.');
  });

  bot.on('message:text', async (ctx) => {
    const settings = readRuntimeSettingsSync();
    const allowedChatIds = settings.channels.telegram.allowedChatIds;
    if (allowedChatIds.length > 0 && !allowedChatIds.includes(String(ctx.chat.id))) {
      await ctx.reply('This Telegram chat is not allowed for this Elyan runtime.');
      return;
    }

    const response = await dispatchOperatorRequest({
      source: 'telegram',
      text: ctx.message.text,
      mode: settings.routing.searchEnabled ? 'speed' : 'speed',
      conversationId: String(ctx.chat.id),
      messageId: String(ctx.message.message_id),
      userId: ctx.from?.id ? String(ctx.from.id) : undefined,
      displayName: ctx.from ? [ctx.from.first_name, ctx.from.last_name].filter(Boolean).join(' ') : undefined,
      metadata: {
        chatType: ctx.chat.type,
      },
    });

    for (const chunk of response.text.match(/[\s\S]{1,3900}/g) ?? ['']) {
      await ctx.reply(chunk, {
        link_preview_options: { is_disabled: true },
      });
    }
  });

  bot.catch(async (error) => {
    console.error('Telegram adapter error:', error.error);
  });

  singletonBot = bot;
  singletonToken = token;
  return bot;
}

export function getTelegramStatus() {
  const settings = readRuntimeSettingsSync();
  const token = readRuntimeEnvValue('TELEGRAM_BOT_TOKEN');

  return {
    configured: Boolean(token),
    enabled: settings.channels.telegram.enabled,
    mode: settings.channels.telegram.mode,
    webhookPath: settings.channels.telegram.webhookPath,
    securityChecks: {
      webhookSecret: Boolean(settings.channels.telegram.webhookSecret || readRuntimeEnvValue('TELEGRAM_WEBHOOK_SECRET')),
      allowedChatIds: settings.channels.telegram.allowedChatIds.length,
    },
    costProfile: 'free_api',
  };
}

export async function probeTelegramBot() {
  const token = readRuntimeEnvValue('TELEGRAM_BOT_TOKEN');
  const settings = readRuntimeSettingsSync();
  if (!token) {
    return {
      ok: false,
      configured: false,
      status: 'missing_token',
      botUsername: settings.channels.telegram.botUsername,
    };
  }

  const response = await fetch(`https://api.telegram.org/bot${token}/getMe`);
  const body = await response.json().catch(() => null);
  return {
    ok: response.ok && body?.ok === true,
    configured: true,
    status: response.ok ? response.status : `http_${response.status}`,
    botUsername: body?.result?.username ?? settings.channels.telegram.botUsername,
  };
}

export async function startTelegramPolling() {
  const bot = createTelegramBot();
  if (!bot) {
    throw new Error('Telegram bot is not configured. Set TELEGRAM_BOT_TOKEN first.');
  }

  await bot.start();
}

export async function handleTelegramWebhook(request: Request) {
  const settings = readRuntimeSettingsSync();
  const secret = settings.channels.telegram.webhookSecret || readRuntimeEnvValue('TELEGRAM_WEBHOOK_SECRET');
  if (secret && request.headers.get('x-telegram-bot-api-secret-token') !== secret) {
    return new Response('Invalid Telegram webhook secret.', { status: 403 });
  }

  const bot = createTelegramBot();
  if (!bot) {
    return new Response('Telegram bot is not configured.', { status: 503 });
  }

  const callback = webhookCallback(bot, 'std/http');
  return callback(request);
}
