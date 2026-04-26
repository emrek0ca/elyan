import { z } from 'zod';
import { mcpServerConfigListSchema, type McpServerConfig } from '@/core/mcp/types';

export const runtimeRoutingModeSchema = z.enum(['local_only', 'local_first', 'balanced', 'cloud_preferred']);

export const runtimeTelegramSettingsSchema = z.object({
  enabled: z.boolean().default(false),
  mode: z.enum(['polling', 'webhook']).default('polling'),
  webhookPath: z.string().default('/api/channels/telegram/webhook'),
  botUsername: z.string().optional(),
  webhookSecret: z.string().optional(),
  allowedChatIds: z.array(z.string()).default([]),
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
    allowedChatIds: [],
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

export const runtimeTeamSettingsSchema = z.object({
  enabled: z.boolean().default(true),
  defaultMode: z.enum(['auto', 'single', 'team']).default('auto'),
  maxConcurrentAgents: z.number().int().min(1).max(4).default(2),
  maxTasksPerRun: z.number().int().min(2).max(12).default(6),
  allowCloudEscalation: z.boolean().default(false),
});

export const runtimeLocalAgentSettingsSchema = z.object({
  enabled: z.boolean().default(false),
  allowedRoots: z.array(z.string().trim().min(1)).default(['.']),
  protectedPaths: z.array(z.string().trim().min(1)).default([
    '.env',
    '.ssh',
    '.gnupg',
    '.aws',
    '.config/gcloud',
    '.kube',
    'id_rsa',
    'id_ed25519',
    'wallet',
    'Library/Keychains',
    '/etc',
    '/System',
    '/private/etc',
  ]),
  approvalPolicy: z.object({
    readOnly: z.enum(['AUTO', 'CONFIRM', 'SCREEN', 'TWO_FA']).default('AUTO'),
    writeSafe: z.enum(['AUTO', 'CONFIRM', 'SCREEN', 'TWO_FA']).default('CONFIRM'),
    writeSensitive: z.enum(['AUTO', 'CONFIRM', 'SCREEN', 'TWO_FA']).default('SCREEN'),
    destructive: z.enum(['AUTO', 'CONFIRM', 'SCREEN', 'TWO_FA']).default('TWO_FA'),
    systemCritical: z.enum(['AUTO', 'CONFIRM', 'SCREEN', 'TWO_FA']).default('TWO_FA'),
  }).default({
    readOnly: 'AUTO',
    writeSafe: 'CONFIRM',
    writeSensitive: 'SCREEN',
    destructive: 'TWO_FA',
    systemCritical: 'TWO_FA',
  }),
  evidenceDir: z.string().default('storage/evidence'),
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
      allowedChatIds: [],
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
  team: runtimeTeamSettingsSchema.default({
    enabled: true,
    defaultMode: 'auto',
    maxConcurrentAgents: 2,
    maxTasksPerRun: 6,
    allowCloudEscalation: false,
  }),
  localAgent: runtimeLocalAgentSettingsSchema.default({
    enabled: false,
    allowedRoots: ['.'],
    protectedPaths: [
      '.env',
      '.ssh',
      '.gnupg',
      '.aws',
      '.config/gcloud',
      '.kube',
      'id_rsa',
      'id_ed25519',
      'wallet',
      'Library/Keychains',
      '/etc',
      '/System',
      '/private/etc',
    ],
    approvalPolicy: {
      readOnly: 'AUTO',
      writeSafe: 'CONFIRM',
      writeSensitive: 'SCREEN',
      destructive: 'TWO_FA',
      systemCritical: 'TWO_FA',
    },
    evidenceDir: 'storage/evidence',
  }),
  mcp: z.object({
    servers: mcpServerConfigListSchema.default([]),
  }).default({ servers: [] }),
});

export type RuntimeRoutingMode = z.infer<typeof runtimeRoutingModeSchema>;
export type RuntimeChannelSettings = z.infer<typeof runtimeChannelSettingsSchema>;
export type RuntimeVoiceSettings = z.infer<typeof runtimeVoiceSettingsSchema>;
export type RuntimeTeamSettings = z.infer<typeof runtimeTeamSettingsSchema>;
export type RuntimeLocalAgentSettings = z.infer<typeof runtimeLocalAgentSettingsSchema>;
export type RuntimeModelSettings = z.infer<typeof runtimeModelSettingsSchema>;
export type RuntimeSettings = z.infer<typeof runtimeSettingsSchema>;

export type RuntimeSettingsPatch = Partial<{
  routing: Partial<RuntimeModelSettings>;
  channels: Partial<RuntimeChannelSettings>;
  voice: Partial<RuntimeVoiceSettings>;
  team: Partial<RuntimeTeamSettings>;
  localAgent: Partial<RuntimeLocalAgentSettings>;
  mcp: Partial<{
    servers: McpServerConfig[];
  }>;
}>;
