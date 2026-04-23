import { NextResponse } from 'next/server';
import { readRuntimeEnvValue } from '@/core/runtime-config';
import { readRuntimeStatusSnapshot } from '@/core/runtime-status';

export async function GET() {
  const result = await readRuntimeStatusSnapshot();

  if (!result.ok) {
    return NextResponse.json(
      {
        ok: false,
        service: 'elyan',
        mode: process.env.NODE_ENV ?? 'development',
        runtime: 'local-first',
        ready: false,
        error: 'Environment configuration is invalid.',
        issues: result.issues,
      },
      { status: 503 }
    );
  }

  const { snapshot } = result;
  const runtimeSettings = snapshot.runtimeSettings;
  const searchProbe = snapshot.search.probe;
  const hasModels = snapshot.models.length > 0;
  const controlPlaneHealth = snapshot.controlPlane.health;
  const hostedAuthConfigured =
    controlPlaneHealth.runtime?.authConfigured ?? controlPlaneHealth.authConfigured ?? false;
  const hostedBillingConfigured =
    controlPlaneHealth.runtime?.billingConfigured ?? controlPlaneHealth.billingConfigured ?? false;
  const mcpConfigured =
    runtimeSettings.mcp.servers.length > 0 || Boolean(readRuntimeEnvValue('ELYAN_MCP_SERVERS')?.trim());
  const channelStatus = {
    telegram: {
      enabled: runtimeSettings.channels.telegram.enabled,
      configured: Boolean(readRuntimeEnvValue('TELEGRAM_BOT_TOKEN')),
      mode: runtimeSettings.channels.telegram.mode,
    },
    whatsappCloud: {
      enabled: runtimeSettings.channels.whatsappCloud.enabled,
      configured:
        Boolean(readRuntimeEnvValue('WHATSAPP_CLOUD_ACCESS_TOKEN')) &&
        Boolean(readRuntimeEnvValue('WHATSAPP_CLOUD_PHONE_NUMBER_ID')) &&
        Boolean(readRuntimeEnvValue('WHATSAPP_CLOUD_VERIFY_TOKEN')),
    },
    whatsappBaileys: {
      enabled: runtimeSettings.channels.whatsappBaileys.enabled,
      configured: runtimeSettings.channels.whatsappBaileys.enabled,
    },
    imessage: {
      enabled: runtimeSettings.channels.imessage.enabled,
      configured: Boolean(readRuntimeEnvValue('BLUEBUBBLES_SERVER_URL')) && Boolean(readRuntimeEnvValue('BLUEBUBBLES_SERVER_GUID')),
      mode: runtimeSettings.channels.imessage.mode,
    },
  };
  const voiceConfigured = Boolean(runtimeSettings.voice.accessKey || readRuntimeEnvValue('PICOVOICE_ACCESS_KEY'));
  const ready = hasModels;

  return NextResponse.json({
    ok: true,
    service: 'elyan',
    mode: process.env.NODE_ENV ?? 'development',
    runtime: 'local-first',
    ready,
    checks: {
      search: {
        ok: runtimeSettings.routing.searchEnabled ? searchProbe.ok : true,
        url: snapshot.search.url,
        status: searchProbe.status,
        optional: true,
        enabled: runtimeSettings.routing.searchEnabled,
        hint: searchProbe.ok
          ? undefined
          : runtimeSettings.routing.searchEnabled
            ? 'Search is optional. Start SearxNG or update SEARXNG_URL if you want live web retrieval and citations.'
            : 'Search is disabled in runtime settings.',
      },
      models: {
        ok: hasModels,
        count: snapshot.models.length,
        local: snapshot.models.filter((model) => model.type === 'local').map((model) => model.id),
        cloud: snapshot.models.filter((model) => model.type === 'cloud').map((model) => model.id),
        hint: hasModels
          ? undefined
          : 'Run Ollama and pull a model, or set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GROQ_API_KEY.',
      },
      mcp: {
        configured: mcpConfigured,
        hint: mcpConfigured ? undefined : 'Optional. Set ELYAN_MCP_SERVERS only if you want live MCP integration.',
      },
      channels: {
        ...channelStatus,
      },
      voice: {
        configured: voiceConfigured,
        enabled: runtimeSettings.voice.enabled,
        wakeWord: runtimeSettings.voice.wakeWord,
        hint: voiceConfigured
          ? undefined
          : 'Optional. Set PICOVOICE_ACCESS_KEY to enable the local wake-word voice path.',
      },
      hosted: {
        authConfigured: hostedAuthConfigured,
        billingConfigured: hostedBillingConfigured,
        hint:
          hostedAuthConfigured && hostedBillingConfigured
            ? undefined
            : 'Optional. Hosted auth and billing are only required for shared control-plane flows.',
      },
    },
    nextSteps: snapshot.nextSteps,
    surfaces: snapshot.surfaces,
  });
}
