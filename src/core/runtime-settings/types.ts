import { z } from 'zod';
import { mcpServerConfigListSchema, type McpServerConfig } from '@/core/mcp/types';

export const runtimeRoutingModeSchema = z.enum(['local_only', 'local_first', 'balanced', 'cloud_preferred']);

export const runtimeTelegramSettingsSchema = z.object({
  enabled: z.boolean().default(false),
  mode: z.enum(['polling', 'webhook']).default('polling'),
  webhookPath: z.string().default('/api/channels/telegram/webhook'),
  botUsername: z.string().optional(),
});

export const runtimeWhatsAppCloudSettingsSchema = z.object({
  enabled: z.boolean().default(false),
  webhookPath: z.string().default('/api/channels/whatsapp/webhook'),
  phoneNumberId: z.string().optional(),
  verifyToken: z.string().optional(),
  accessToken: z.string().optional(),
  appSecret: z.string().optional(),
});

export const runtimeWhatsAppBaileysSettingsSchema = z.object({
  enabled: z.boolean().default(false),
  sessionPath: z.string().default('storage/channels/whatsapp-baileys.json'),
});

export const runtimeImessageSettingsSchema = z.object({
  enabled: z.boolean().default(false),
  mode: z.enum(['bluebubbles']).default('bluebubbles'),
  webhookPath: z.string().default('/api/channels/imessage/bluebubbles/webhook'),
  serverUrl: z.string().url().optional(),
  guid: z.string().optional(),
  webhookSecret: z.string().optional(),
});

export const runtimeChannelSettingsSchema = z.object({
  telegram: runtimeTelegramSettingsSchema.default({
    enabled: false,
    mode: 'polling',
    webhookPath: '/api/channels/telegram/webhook',
  }),
  whatsappCloud: runtimeWhatsAppCloudSettingsSchema.default({
    enabled: false,
    webhookPath: '/api/channels/whatsapp/webhook',
  }),
  whatsappBaileys: runtimeWhatsAppBaileysSettingsSchema.default({
    enabled: false,
    sessionPath: 'storage/channels/whatsapp-baileys.json',
  }),
  imessage: runtimeImessageSettingsSchema.default({
    enabled: false,
    mode: 'bluebubbles',
    webhookPath: '/api/channels/imessage/bluebubbles/webhook',
  }),
});

export const runtimeVoiceSettingsSchema = z.object({
  enabled: z.boolean().default(false),
  wakeWord: z.string().default('elyan'),
  accessKey: z.string().optional(),
  modelPath: z.string().optional(),
  keywordPath: z.string().optional(),
  vadModelPath: z.string().optional(),
  language: z.string().default('en'),
  sampleRate: z.number().int().positive().default(16000),
});

export const runtimeModelSettingsSchema = z.object({
  preferredModelId: z.string().optional(),
  routingMode: runtimeRoutingModeSchema.default('local_first'),
  searchEnabled: z.boolean().default(true),
});

export const runtimeSettingsSchema = z.object({
  version: z.literal(1),
  routing: runtimeModelSettingsSchema.default({
    routingMode: 'local_first',
    searchEnabled: true,
  }),
  channels: runtimeChannelSettingsSchema.default({
    telegram: {
      enabled: false,
      mode: 'polling',
      webhookPath: '/api/channels/telegram/webhook',
    },
    whatsappCloud: {
      enabled: false,
      webhookPath: '/api/channels/whatsapp/webhook',
    },
    whatsappBaileys: {
      enabled: false,
      sessionPath: 'storage/channels/whatsapp-baileys.json',
    },
    imessage: {
      enabled: false,
      mode: 'bluebubbles',
      webhookPath: '/api/channels/imessage/bluebubbles/webhook',
    },
  }),
  voice: runtimeVoiceSettingsSchema.default({
    enabled: false,
    wakeWord: 'elyan',
    language: 'en',
    sampleRate: 16000,
  }),
  mcp: z.object({
    servers: mcpServerConfigListSchema.default([]),
  }).default({ servers: [] }),
});

export type RuntimeRoutingMode = z.infer<typeof runtimeRoutingModeSchema>;
export type RuntimeChannelSettings = z.infer<typeof runtimeChannelSettingsSchema>;
export type RuntimeVoiceSettings = z.infer<typeof runtimeVoiceSettingsSchema>;
export type RuntimeModelSettings = z.infer<typeof runtimeModelSettingsSchema>;
export type RuntimeSettings = z.infer<typeof runtimeSettingsSchema>;

export type RuntimeSettingsPatch = Partial<{
  routing: Partial<RuntimeModelSettings>;
  channels: Partial<RuntimeChannelSettings>;
  voice: Partial<RuntimeVoiceSettings>;
  mcp: Partial<{
    servers: McpServerConfig[];
  }>;
}>;
