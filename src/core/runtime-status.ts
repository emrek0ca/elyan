import { buildCapabilityDirectorySnapshot } from '@/core/capabilities/directory';
import { getBlueBubblesStatus, getTelegramStatus, getWhatsappCloudStatus } from '@/core/channels';
import { readControlPlaneHealthSnapshot } from '@/core/control-plane';
import { readRuntimeEnvValue } from '@/core/runtime-config';
import { registry } from '@/core/providers';
import { readRuntimeSettingsSync } from '@/core/runtime-settings';
import { inspectEnv } from '@/lib/env';
import { buildRuntimeSurfaceSnapshot } from './runtime-surface';

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
    WHATSAPP_CLOUD_ACCESS_TOKEN: Boolean(readRuntimeEnvValue('WHATSAPP_CLOUD_ACCESS_TOKEN')),
    WHATSAPP_CLOUD_PHONE_NUMBER_ID: Boolean(readRuntimeEnvValue('WHATSAPP_CLOUD_PHONE_NUMBER_ID')),
    WHATSAPP_CLOUD_VERIFY_TOKEN: Boolean(readRuntimeEnvValue('WHATSAPP_CLOUD_VERIFY_TOKEN')),
    WHATSAPP_CLOUD_APP_SECRET: Boolean(readRuntimeEnvValue('WHATSAPP_CLOUD_APP_SECRET')),
    BLUEBUBBLES_SERVER_URL: Boolean(readRuntimeEnvValue('BLUEBUBBLES_SERVER_URL')),
    BLUEBUBBLES_SERVER_GUID: Boolean(readRuntimeEnvValue('BLUEBUBBLES_SERVER_GUID')),
    BLUEBUBBLES_REPLY_URL: Boolean(readRuntimeEnvValue('BLUEBUBBLES_REPLY_URL')),
    BLUEBUBBLES_WEBHOOK_SECRET: Boolean(readRuntimeEnvValue('BLUEBUBBLES_WEBHOOK_SECRET')),
    PICOVOICE_ACCESS_KEY: Boolean(readRuntimeEnvValue('PICOVOICE_ACCESS_KEY')),
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
  const [models, capabilities, controlPlaneHealth] = await Promise.all([
    registry.listAvailableModels(),
    buildCapabilityDirectorySnapshot(true),
    readControlPlaneHealthSnapshot(),
  ]);

  const hostedAuthConfigured =
    controlPlaneHealth.runtime?.authConfigured ?? controlPlaneHealth.authConfigured ?? false;
  const hostedBillingConfigured =
    controlPlaneHealth.runtime?.billingConfigured ?? controlPlaneHealth.billingConfigured ?? false;
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
      },
      models,
      capabilities,
      channels: {
        telegram: getTelegramStatus(),
        whatsappCloud: getWhatsappCloudStatus(),
        imessage: getBlueBubblesStatus(),
      },
      voice: runtimeSettings.voice,
      mcp: {
        servers: runtimeSettings.mcp.servers,
        configured: runtimeSettings.mcp.servers.length > 0,
      },
      controlPlane: {
        health: controlPlaneHealth,
      },
      surfaces,
      nextSteps: surfaces.nextSteps,
      runtimeSettings,
    },
  };
}
