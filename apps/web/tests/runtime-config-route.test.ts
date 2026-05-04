import { NextRequest } from 'next/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  patch: vi.fn(),
  readRuntimeSettingsSync: vi.fn(),
  setRuntimeEnvValue: vi.fn(),
  removeRuntimeEnvValue: vi.fn(),
}));

vi.mock('@/core/runtime-settings', () => ({
  getRuntimeSettingsStore: vi.fn(() => ({
    patch: mocks.patch,
  })),
  readRuntimeSettingsSync: mocks.readRuntimeSettingsSync,
}));

vi.mock('@/core/runtime-config', () => ({
  readMergedRuntimeEnv: vi.fn(() => ({})),
  readRuntimeEnvValue: vi.fn(() => undefined),
  setRuntimeEnvValue: mocks.setRuntimeEnvValue,
  removeRuntimeEnvValue: mocks.removeRuntimeEnvValue,
}));

vi.mock('@/lib/runtime-paths', () => ({
  getGlobalEnvPath: vi.fn(() => '/tmp/elyan/.env'),
}));

describe('runtime config patch route', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('normalizes nullable fields before persisting runtime settings', async () => {
    const runtimeSettings = {
      version: 1,
      routing: { routingMode: 'local_first', searchEnabled: true },
      channels: {
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
      },
      voice: { enabled: false, wakeWord: 'elyan', language: 'en', sampleRate: 16000 },
      team: {
        enabled: true,
        defaultMode: 'auto',
        maxConcurrentAgents: 2,
        maxTasksPerRun: 6,
        allowCloudEscalation: false,
      },
      localAgent: {
        enabled: false,
        allowedRoots: ['.'],
        protectedPaths: ['.env'],
        approvalPolicy: {
          readOnly: 'AUTO',
          writeSafe: 'CONFIRM',
          writeSensitive: 'SCREEN',
          destructive: 'TWO_FA',
          systemCritical: 'TWO_FA',
        },
        evidenceDir: 'storage/evidence',
      },
      mcp: { servers: [] },
    };
    mocks.readRuntimeSettingsSync.mockReturnValue(runtimeSettings);
    mocks.patch.mockResolvedValue(runtimeSettings);

    const { PATCH } = await import('@/app/api/runtime/config/route');
    const request = new NextRequest('http://127.0.0.1:3000/api/runtime/config', {
      method: 'PATCH',
      body: JSON.stringify({
        settings: {
          routing: {
            preferredModelId: null,
            routingMode: 'local_first',
            searchEnabled: true,
          },
          channels: {
            telegram: {
              enabled: true,
              mode: 'polling',
              webhookPath: '/api/channels/telegram/webhook',
              botUsername: null,
              webhookSecret: null,
              allowedChatIds: [' 123 ', '  '],
            },
          },
        },
        secrets: {
          TELEGRAM_BOT_TOKEN: null,
          TELEGRAM_WEBHOOK_SECRET: 'secret-123',
        },
      }),
      headers: {
        'content-type': 'application/json',
      },
    });

    const response = await PATCH(request);
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.ok).toBe(true);
    expect(mocks.patch).toHaveBeenCalledTimes(1);
    const patch = mocks.patch.mock.calls[0][0];
    expect(patch.routing.preferredModelId).toBeUndefined();
    expect(patch.routing.routingMode).toBe('local_first');
    expect(patch.routing.searchEnabled).toBe(true);
    expect(patch.channels.telegram.botUsername).toBeUndefined();
    expect(patch.channels.telegram.webhookSecret).toBeUndefined();
    expect(patch.channels.telegram.allowedChatIds).toEqual(['123']);
    expect(mocks.removeRuntimeEnvValue).toHaveBeenCalledWith('TELEGRAM_BOT_TOKEN');
    expect(mocks.setRuntimeEnvValue).toHaveBeenCalledWith('TELEGRAM_WEBHOOK_SECRET', 'secret-123');
  });
});
