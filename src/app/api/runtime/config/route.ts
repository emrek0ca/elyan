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
          allowedChatIds: z.array(z.string().trim().min(1)).optional(),
        })
        .optional(),
      whatsappCloud: z
        .object({
          enabled: z.boolean().optional(),
          webhookPath: z.string().trim().min(1).optional(),
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
        preferredModelId: settings.routing.preferredModelId ?? undefined,
        routingMode: settings.routing.routingMode,
        searchEnabled: settings.routing.searchEnabled,
      };
    }

    if (settings.channels) {
      patch.channels = settings.channels as RuntimeSettingsPatch['channels'];
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
