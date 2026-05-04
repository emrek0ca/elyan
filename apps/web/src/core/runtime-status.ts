import { buildCapabilityDirectorySnapshot } from '@/core/capabilities/directory';
import { buildOperatorStatusSnapshot } from '@/core/operator/status';
import { buildRuntimeRegistrySnapshot } from '@/core/runtime-registry';
import {
  getBlueBubblesStatus,
  getTelegramStatus,
  getWhatsappBaileysStatus,
  getWhatsappCloudStatus,
  probeBlueBubblesServer,
  probeTelegramBot,
  probeWhatsappBaileysSession,
  probeWhatsappCloudConfig,
} from '@/core/channels';
import { readControlPlaneHealthSnapshot } from '@/core/control-plane';
import { buildRuntimeConnectionRegistry } from '@/core/control-plane/governance';
import { readLocalAgentStatus } from '@/core/local-agent';
import { readRuntimeEnvValue } from '@/core/runtime-config';
import { registry } from '@/core/providers';
import { readRuntimeSettingsSync } from '@/core/runtime-settings';
import { readTeamRuntimeStatus } from '@/core/teams';
import { buildWorkspaceStatusSnapshot } from '@/core/workspace';
import { inspectEnv } from '@/lib/env';
import { buildRuntimeSurfaceSnapshot } from './runtime-surface';
import { buildOptimizationStatusSnapshot } from './optimization/status';

type ProbeResult = {
  ok: boolean;
  status: number | string;
};

async function probeJsonEndpoint(url: string, timeoutMs = 2500): Promise<ProbeResult> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, { signal: controller.signal });

    return {
      ok: response.ok,
      status: response.status,
    };
  } catch (error) {
    return {
      ok: false,
      status: error instanceof Error ? error.message : 'unreachable',
    };
  } finally {
    clearTimeout(timeout);
  }
}

function summarizeSecrets() {
  return {
    TELEGRAM_BOT_TOKEN: Boolean(readRuntimeEnvValue('TELEGRAM_BOT_TOKEN')),
    TELEGRAM_WEBHOOK_SECRET: Boolean(readRuntimeEnvValue('TELEGRAM_WEBHOOK_SECRET')),
    WHATSAPP_CLOUD_ACCESS_TOKEN: Boolean(readRuntimeEnvValue('WHATSAPP_CLOUD_ACCESS_TOKEN')),
    WHATSAPP_CLOUD_PHONE_NUMBER_ID: Boolean(readRuntimeEnvValue('WHATSAPP_CLOUD_PHONE_NUMBER_ID')),
    WHATSAPP_CLOUD_VERIFY_TOKEN: Boolean(readRuntimeEnvValue('WHATSAPP_CLOUD_VERIFY_TOKEN')),
    WHATSAPP_CLOUD_APP_SECRET: Boolean(readRuntimeEnvValue('WHATSAPP_CLOUD_APP_SECRET')),
    BLUEBUBBLES_SERVER_URL: Boolean(readRuntimeEnvValue('BLUEBUBBLES_SERVER_URL')),
    BLUEBUBBLES_SERVER_GUID: Boolean(readRuntimeEnvValue('BLUEBUBBLES_SERVER_GUID')),
    BLUEBUBBLES_REPLY_URL: Boolean(readRuntimeEnvValue('BLUEBUBBLES_REPLY_URL')),
    BLUEBUBBLES_WEBHOOK_SECRET: Boolean(readRuntimeEnvValue('BLUEBUBBLES_WEBHOOK_SECRET')),
    PICOVOICE_ACCESS_KEY: Boolean(readRuntimeEnvValue('PICOVOICE_ACCESS_KEY')),
    GITHUB_OWNER: Boolean(readRuntimeEnvValue('GITHUB_OWNER')),
    GITHUB_REPO: Boolean(readRuntimeEnvValue('GITHUB_REPO')),
    GITHUB_TOKEN: Boolean(readRuntimeEnvValue('GITHUB_TOKEN')),
    OBSIDIAN_VAULT_PATH: Boolean(readRuntimeEnvValue('OBSIDIAN_VAULT_PATH')),
    NOTION_TOKEN: Boolean(readRuntimeEnvValue('NOTION_TOKEN')),
  };
}

export async function readRuntimeStatusSnapshot() {
  const envInspection = inspectEnv();
  const runtimeSettings = readRuntimeSettingsSync();

  if (!envInspection.ok) {
    return {
      ok: false as const,
      issues: envInspection.issues,
      runtimeSettings,
    };
  }

  const runtimeEnv = envInspection.data;
  const searchProbe = runtimeSettings.routing.searchEnabled
    ? await probeJsonEndpoint(`${runtimeEnv.SEARXNG_URL.replace(/\/$/, '')}/healthz`)
    : { ok: true, status: 'disabled' as const };
  let models: Awaited<ReturnType<typeof registry.listAvailableModels>> = [];
  let modelError: string | undefined;
  try {
    models = await registry.listAvailableModels();
  } catch (error) {
    modelError = error instanceof Error ? error.message : 'Failed to list available models';
  }

  const [capabilities, operator, controlPlaneHealth, workspace, team] = await Promise.all([
    buildCapabilityDirectorySnapshot(true),
    buildOperatorStatusSnapshot(),
    readControlPlaneHealthSnapshot(),
    buildWorkspaceStatusSnapshot(runtimeSettings),
    readTeamRuntimeStatus(),
  ]);

  const hostedAuthConfigured =
    controlPlaneHealth.runtime?.authConfigured ?? controlPlaneHealth.authConfigured ?? false;
  const hostedBillingConfigured =
    controlPlaneHealth.runtime?.billingConfigured ?? controlPlaneHealth.billingConfigured ?? false;
  const optimization = buildOptimizationStatusSnapshot(capabilities);
  const registrySnapshot = buildRuntimeRegistrySnapshot({
    models,
    capabilities,
    operator,
    modelError,
  });
  const [telegramProbe, whatsappCloudProbe, whatsappBaileysProbe, blueBubblesProbe] = await Promise.all([
    runtimeSettings.channels.telegram.enabled ? probeTelegramBot().catch((error) => ({ ok: false, configured: false, status: error instanceof Error ? error.message : 'probe_failed' })) : Promise.resolve(null),
    runtimeSettings.channels.whatsappCloud.enabled ? probeWhatsappCloudConfig().catch((error) => ({ ok: false, configured: false, status: error instanceof Error ? error.message : 'probe_failed' })) : Promise.resolve(null),
    runtimeSettings.channels.whatsappBaileys.enabled ? probeWhatsappBaileysSession().catch((error) => ({ ok: false, configured: false, status: error instanceof Error ? error.message : 'probe_failed' })) : Promise.resolve(null),
    runtimeSettings.channels.imessage.enabled ? probeBlueBubblesServer().catch((error) => ({ ok: false, configured: false, status: error instanceof Error ? error.message : 'probe_failed' })) : Promise.resolve(null),
  ]);
  const surfaces = buildRuntimeSurfaceSnapshot({
    localModelCount: models.length,
    searchEnabled: runtimeSettings.routing.searchEnabled,
    searchAvailable: searchProbe.ok,
    controlPlaneReady: controlPlaneHealth.ok === true,
    hostedAuthConfigured,
    hostedBillingConfigured,
  });

  return {
    ok: true as const,
    snapshot: {
      runtime: 'local-first' as const,
      search: {
        url: runtimeEnv.SEARXNG_URL,
        probe: searchProbe,
      },
      secrets: summarizeSecrets(),
      readiness: {
        hasLocalModels: models.length > 0,
        searchEnabled: runtimeSettings.routing.searchEnabled,
        searchAvailable: runtimeSettings.routing.searchEnabled ? searchProbe.ok : false,
        mcpConfigured: runtimeSettings.mcp.servers.length > 0,
        voiceConfigured: Boolean(runtimeSettings.voice.accessKey || readRuntimeEnvValue('PICOVOICE_ACCESS_KEY')),
        workspaceConfigured: workspace.summary.configuredSourceCount > 0,
      },
      models,
      modelError,
      capabilities,
      channels: {
        telegram: {
          ...getTelegramStatus(),
          probe: telegramProbe,
        },
        whatsappCloud: {
          ...getWhatsappCloudStatus(),
          probe: whatsappCloudProbe,
        },
        whatsappBaileys: {
          ...getWhatsappBaileysStatus(),
          probe: whatsappBaileysProbe,
        },
        imessage: {
          ...getBlueBubblesStatus(),
          probe: blueBubblesProbe,
        },
      },
      connections: buildRuntimeConnectionRegistry({
        telegram: {
          enabled: runtimeSettings.channels.telegram.enabled,
          mode: runtimeSettings.channels.telegram.mode,
          webhookPath: runtimeSettings.channels.telegram.webhookPath,
          botToken: readRuntimeEnvValue('TELEGRAM_BOT_TOKEN'),
        },
        whatsappCloud: {
          enabled: runtimeSettings.channels.whatsappCloud.enabled,
          webhookPath: runtimeSettings.channels.whatsappCloud.webhookPath,
          accessToken: readRuntimeEnvValue('WHATSAPP_CLOUD_ACCESS_TOKEN'),
          phoneNumberId: readRuntimeEnvValue('WHATSAPP_CLOUD_PHONE_NUMBER_ID'),
          verifyToken: readRuntimeEnvValue('WHATSAPP_CLOUD_VERIFY_TOKEN'),
          appSecret: readRuntimeEnvValue('WHATSAPP_CLOUD_APP_SECRET'),
        },
        imessage: {
          enabled: runtimeSettings.channels.imessage.enabled,
          webhookPath: runtimeSettings.channels.imessage.webhookPath,
          serverUrl: readRuntimeEnvValue('BLUEBUBBLES_SERVER_URL'),
          guid: readRuntimeEnvValue('BLUEBUBBLES_SERVER_GUID'),
          replyUrl: readRuntimeEnvValue('BLUEBUBBLES_REPLY_URL'),
          webhookSecret: readRuntimeEnvValue('BLUEBUBBLES_WEBHOOK_SECRET'),
        },
        controlPlane: {
          storage: controlPlaneHealth.connection?.storage ?? 'file',
          hostedReady: controlPlaneHealth.connection?.hostedReady ?? false,
          callbackUrl: controlPlaneHealth.connection?.callbackUrl ?? `${runtimeEnv.NEXTAUTH_URL ?? 'http://localhost:3000'}/api/control-plane/billing/iyzico/webhook`,
          apiBaseUrl: controlPlaneHealth.connection?.apiBaseUrl ?? runtimeEnv.IYZICO_BASE_URL,
          billingMode: controlPlaneHealth.connection?.billingMode ?? (runtimeEnv.IYZICO_ENV as 'sandbox' | 'production'),
          authConfigured: controlPlaneHealth.authConfigured ?? false,
          billingConfigured: controlPlaneHealth.billingConfigured ?? false,
        },
      }),
      voice: runtimeSettings.voice,
      team: {
        settings: runtimeSettings.team,
        status: team,
      },
      operator,
      registry: registrySnapshot,
      localAgent: readLocalAgentStatus(),
      mcp: {
        servers: runtimeSettings.mcp.servers,
        configured: runtimeSettings.mcp.servers.length > 0,
      },
      controlPlane: {
        health: controlPlaneHealth,
      },
      optimization,
      workspace,
      surfaces,
      nextSteps: surfaces.nextSteps,
      runtimeSettings,
    },
  };
}
