import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { getGlobalEnvPath } from '@/lib/runtime-paths';
import { readMergedRuntimeEnv, readRuntimeEnvValue, removeRuntimeEnvValue, setRuntimeEnvValue } from '@/core/runtime-config';
import { getRuntimeSettingsStore, type RuntimeSettingsPatch } from '@/core/runtime-settings';
import type { McpServerConfig } from '@/core/mcp';
import { readRuntimeSettingsSync } from '@/core/runtime-settings';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const runtimeSettingsPatchSchema = z.object({
  routing: z
    .object({
      preferredModelId: z.string().trim().min(1).optional().nullable(),
      routingMode: z.enum(['local_only', 'local_first', 'balanced', 'cloud_preferred']).optional(),
      searchEnabled: z.boolean().optional(),
    })
    .optional(),
  channels: z
    .object({
      telegram: z
        .object({
          enabled: z.boolean().optional(),
          mode: z.enum(['polling', 'webhook']).optional(),
          webhookPath: z.string().trim().min(1).optional(),
          botUsername: z.string().trim().min(1).optional().nullable(),
          webhookSecret: z.string().trim().min(1).optional().nullable(),
          allowedChatIds: z.array(z.string()).optional(),
        })
        .optional(),
      whatsappCloud: z
        .object({
          enabled: z.boolean().optional(),
          webhookPath: z.string().trim().min(1).optional(),
          phoneNumberId: z.string().trim().min(1).optional().nullable(),
          accessToken: z.string().trim().min(1).optional().nullable(),
          verifyToken: z.string().trim().min(1).optional().nullable(),
          appSecret: z.string().trim().min(1).optional().nullable(),
        })
        .optional(),
      whatsappBaileys: z
        .object({
          enabled: z.boolean().optional(),
          sessionPath: z.string().trim().min(1).optional(),
        })
        .optional(),
      imessage: z
        .object({
          enabled: z.boolean().optional(),
          mode: z.enum(['bluebubbles']).optional(),
          webhookPath: z.string().trim().min(1).optional(),
          serverUrl: z.string().trim().min(1).optional().nullable(),
          guid: z.string().trim().min(1).optional().nullable(),
          webhookSecret: z.string().trim().min(1).optional().nullable(),
        })
        .optional(),
    })
    .optional(),
  voice: z
    .object({
      enabled: z.boolean().optional(),
      wakeWord: z.string().trim().min(1).optional(),
      accessKey: z.string().trim().min(1).optional().nullable(),
      modelPath: z.string().trim().min(1).optional().nullable(),
      keywordPath: z.string().trim().min(1).optional().nullable(),
      vadModelPath: z.string().trim().min(1).optional().nullable(),
      language: z.string().trim().min(1).optional(),
      sampleRate: z.number().int().positive().optional(),
    })
    .optional(),
  team: z
    .object({
      enabled: z.boolean().optional(),
      defaultMode: z.enum(['auto', 'single', 'team']).optional(),
      maxConcurrentAgents: z.number().int().min(1).max(4).optional(),
      maxTasksPerRun: z.number().int().min(2).max(12).optional(),
      allowCloudEscalation: z.boolean().optional(),
    })
    .optional(),
  localAgent: z
    .object({
      enabled: z.boolean().optional(),
      allowedRoots: z.array(z.string().trim().min(1)).optional(),
      protectedPaths: z.array(z.string().trim().min(1)).optional(),
      evidenceDir: z.string().trim().min(1).optional(),
      approvalPolicy: z
        .object({
          readOnly: z.enum(['AUTO', 'CONFIRM', 'SCREEN', 'TWO_FA']).optional(),
          writeSafe: z.enum(['AUTO', 'CONFIRM', 'SCREEN', 'TWO_FA']).optional(),
          writeSensitive: z.enum(['AUTO', 'CONFIRM', 'SCREEN', 'TWO_FA']).optional(),
          destructive: z.enum(['AUTO', 'CONFIRM', 'SCREEN', 'TWO_FA']).optional(),
          systemCritical: z.enum(['AUTO', 'CONFIRM', 'SCREEN', 'TWO_FA']).optional(),
        })
        .optional(),
    })
    .optional(),
  mcp: z
    .object({
      servers: z.array(z.unknown()).optional(),
    })
    .optional(),
});

const runtimeConfigPatchSchema = z.object({
  settings: runtimeSettingsPatchSchema.optional(),
  secrets: z.record(z.string().trim().min(1), z.string().nullable()).optional(),
});

function normalizeOptionalString(value: string | null | undefined) {
  const normalized = typeof value === 'string' ? value.trim() : '';
  return normalized.length > 0 ? normalized : undefined;
}

function normalizeChannelPatch(
  channels: NonNullable<z.infer<typeof runtimeConfigPatchSchema>['settings']>['channels']
) {
  if (!channels) {
    return undefined;
  }

  return {
    telegram: channels.telegram
      ? {
          ...channels.telegram,
          botUsername: normalizeOptionalString(channels.telegram.botUsername),
          webhookSecret: normalizeOptionalString(channels.telegram.webhookSecret),
          allowedChatIds: channels.telegram.allowedChatIds
            ?.map((item) => item.trim())
            .filter((item) => item.length > 0),
        }
      : undefined,
    whatsappCloud: channels.whatsappCloud
      ? {
          ...channels.whatsappCloud,
          webhookPath: normalizeOptionalString(channels.whatsappCloud.webhookPath) ?? channels.whatsappCloud.webhookPath,
          phoneNumberId: normalizeOptionalString(channels.whatsappCloud.phoneNumberId),
          accessToken: normalizeOptionalString(channels.whatsappCloud.accessToken),
          verifyToken: normalizeOptionalString(channels.whatsappCloud.verifyToken),
          appSecret: normalizeOptionalString(channels.whatsappCloud.appSecret),
        }
      : undefined,
    whatsappBaileys: channels.whatsappBaileys
      ? {
          ...channels.whatsappBaileys,
          sessionPath: normalizeOptionalString(channels.whatsappBaileys.sessionPath) ?? channels.whatsappBaileys.sessionPath,
        }
      : undefined,
    imessage: channels.imessage
      ? {
          ...channels.imessage,
          mode: channels.imessage.mode,
          webhookPath: normalizeOptionalString(channels.imessage.webhookPath) ?? channels.imessage.webhookPath,
          serverUrl: normalizeOptionalString(channels.imessage.serverUrl),
          guid: normalizeOptionalString(channels.imessage.guid),
          webhookSecret: normalizeOptionalString(channels.imessage.webhookSecret),
        }
      : undefined,
  };
}

function summarizeSecrets() {
  const secretKeys = [
    'TELEGRAM_BOT_TOKEN',
    'TELEGRAM_WEBHOOK_SECRET',
    'WHATSAPP_CLOUD_ACCESS_TOKEN',
    'WHATSAPP_CLOUD_PHONE_NUMBER_ID',
    'WHATSAPP_CLOUD_VERIFY_TOKEN',
    'WHATSAPP_CLOUD_APP_SECRET',
    'BLUEBUBBLES_SERVER_URL',
    'BLUEBUBBLES_SERVER_GUID',
    'PICOVOICE_ACCESS_KEY',
  ];

  return Object.fromEntries(
    secretKeys.map((key) => [
      key,
      {
        configured: Boolean(readRuntimeEnvValue(key)),
      },
    ])
  );
}

export async function GET() {
  const settings = readRuntimeSettingsSync();
  return NextResponse.json({
    ok: true,
    envPath: getGlobalEnvPath(),
    settings,
    secrets: summarizeSecrets(),
    mergedEnvKeys: Object.keys(readMergedRuntimeEnv()).filter((key) =>
      /^(TELEGRAM_|WHATSAPP_|BLUEBUBBLES_|PICOVOICE_|ELYAN_MCP_SERVERS|SEARXNG_URL|OLLAMA_URL)/.test(key)
    ),
  });
}

export async function PATCH(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const parsed = runtimeConfigPatchSchema.safeParse(body);

  if (!parsed.success) {
    return NextResponse.json(
      {
        ok: false,
        error: 'Invalid runtime config patch.',
        issues: parsed.error.flatten().fieldErrors,
      },
      { status: 400 }
    );
  }

  const { settings, secrets } = parsed.data;

  if (settings) {
    const patch: RuntimeSettingsPatch = {};

    if (settings.routing) {
      patch.routing = {
        preferredModelId: normalizeOptionalString(settings.routing.preferredModelId),
        routingMode: settings.routing.routingMode,
        searchEnabled: settings.routing.searchEnabled,
      };
    }

    if (settings.channels) {
      patch.channels = normalizeChannelPatch(settings.channels) as RuntimeSettingsPatch['channels'];
    }

    if (settings.voice) {
      patch.voice = settings.voice as RuntimeSettingsPatch['voice'];
    }

    if (settings.team) {
      patch.team = settings.team as RuntimeSettingsPatch['team'];
    }

    if (settings.localAgent) {
      patch.localAgent = settings.localAgent as RuntimeSettingsPatch['localAgent'];
    }

    if (settings.mcp?.servers) {
      patch.mcp = {
        servers: settings.mcp.servers as McpServerConfig[],
      };
    }

    await getRuntimeSettingsStore().patch(patch);
  }

  if (secrets) {
    for (const [key, value] of Object.entries(secrets)) {
      if (value === null || value.trim().length === 0) {
        removeRuntimeEnvValue(key);
      } else {
        setRuntimeEnvValue(key, value);
      }
    }
  }

  return NextResponse.json({
    ok: true,
    settings: readRuntimeSettingsSync(),
    secrets: summarizeSecrets(),
  });
}
