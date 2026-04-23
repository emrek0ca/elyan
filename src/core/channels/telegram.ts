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

    await ctx.reply(response.text, {
      link_preview_options: { is_disabled: true },
    });
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
  const bot = createTelegramBot();
  if (!bot) {
    return new Response('Telegram bot is not configured.', { status: 503 });
  }

  const callback = webhookCallback(bot, 'std/http');
  return callback(request);
}
