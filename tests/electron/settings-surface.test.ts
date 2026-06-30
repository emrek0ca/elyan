import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BootstrapSnapshot } from '../../src/shared/protocol';

const desktopApiMock = vi.hoisted(() => {
  const vaultStatus = {
    available: true,
    persistent: false,
    backend: 'preview',
    reason: 'session_only',
    providerIds: ['openai'],
  };
  const catalogState = {
    response: {
      ok: true,
      result: {
        providers: [
          {
            id: 'ollama',
            label: 'Ollama',
            enabled: true,
            configured: true,
            defaultModel: 'llama3.1:8b',
            displayStatus: 'Hazır',
            displayHint: 'llama3.1:8b kullanılabilir.',
            runtimeStatus: {
              available: true,
              configured: true,
              reachable: true,
              latencyMs: 42,
              lastCheckedAt: '2030-05-22T15:31:12Z',
              errorCode: '',
              binary: '/opt/homebrew/bin/ollama',
            },
          },
          {
            id: 'lmstudio',
            label: 'LM Studio',
            enabled: false,
            configured: false,
            defaultModel: '',
            displayStatus: 'Bağlı değil',
            displayHint: 'Açık olduğunda bağlanır.',
            runtimeStatus: {
              available: false,
              configured: false,
              reachable: false,
              errorCode: 'provider_unreachable',
            },
          },
          {
            id: 'openai',
            label: 'OpenAI',
            enabled: true,
            configured: true,
            secretConfigured: true,
            displayStatus: 'Bağlı',
            displayHint: 'Kullanıma hazır.',
            runtimeStatus: {},
          },
          {
            id: 'anthropic',
            label: 'Anthropic',
            enabled: false,
            configured: false,
            secretConfigured: false,
            displayStatus: 'Bağlı değil',
            displayHint: 'Bağlantı anahtarı ekleyebilirsin.',
            runtimeStatus: {},
          },
          {
            id: 'gemini',
            label: 'Gemini',
            enabled: false,
            configured: false,
            secretConfigured: false,
            displayStatus: 'Bağlı değil',
            displayHint: 'Bağlantı anahtarı ekleyebilirsin.',
            runtimeStatus: {},
          },
          {
            id: 'llamacpp',
            label: 'llama.cpp',
            enabled: true,
            configured: true,
            defaultModel: 'local-gguf',
            baseUrl: 'http://127.0.0.1:8080/v1',
            binaryPath: '/opt/llama.cpp/server',
            modelPath: '/models/local.gguf',
            displayStatus: 'Kurulum gerekli',
            displayHint: 'Model dosyası seçilince kullanılabilir.',
            runtimeStatus: {
              available: false,
              configured: true,
              reachable: false,
              errorCode: 'provider_unreachable',
            },
          },
        ],
        cloudProviders: [
          {
            id: 'openai',
            label: 'OpenAI',
            enabled: true,
            configured: true,
            secretConfigured: true,
            displayStatus: 'Bağlı',
            displayHint: 'Kullanıma hazır.',
          },
          {
            id: 'anthropic',
            label: 'Anthropic',
            enabled: false,
            configured: false,
            secretConfigured: false,
            displayStatus: 'Bağlı değil',
            displayHint: 'Bağlantı anahtarı ekleyebilirsin.',
          },
          {
            id: 'gemini',
            label: 'Gemini',
            enabled: false,
            configured: false,
            secretConfigured: false,
            displayStatus: 'Bağlı değil',
            displayHint: 'Bağlantı anahtarı ekleyebilirsin.',
          },
        ],
        advancedProviders: [
          {
            id: 'llamacpp',
            label: 'llama.cpp',
            enabled: true,
            configured: true,
            baseUrl: 'http://127.0.0.1:8080/v1',
            defaultModel: 'local-gguf',
            binaryPath: '/opt/llama.cpp/server',
            modelPath: '/models/local.gguf',
            displayStatus: 'Kurulum gerekli',
            displayHint: 'Model dosyası seçilince kullanılabilir.',
            runtimeStatus: {
              available: false,
              configured: true,
              reachable: false,
              errorCode: 'provider_unreachable',
            },
          },
        ],
        fallbackToCloud: true,
        defaultLocalRuntime: 'ollama',
        localModels: {
          selectedRuntime: 'ollama',
          defaultLocalModel: 'llama3.1:8b',
          summary: {
            status: 'Hazır',
            hint: 'llama3.1:8b kullanılabilir.',
            selectedRuntime: 'ollama',
          },
          status: {
            available: true,
            configured: true,
            reachable: true,
            latencyMs: 42,
            lastCheckedAt: '2030-05-22T15:31:12Z',
            errorCode: '',
          },
          models: {
            models: [{ name: 'llama3.1:8b' }],
          },
          jobs: [],
          recommendedModels: ['llama3.1:8b', 'qwen2.5:7b'],
        },
      },
      events: [],
      artifacts: [],
      error: null,
      durationMs: 0,
    },
    validateResponse: {
      ok: false,
      result: { error: 'provider_unreachable' },
      events: [],
      artifacts: [],
      error: { code: 'provider_unreachable', message: 'network failed' },
      durationMs: 0,
    },
  };
  return {
    state: catalogState,
    request: vi.fn(async (request: { capability: string }) => {
      if (request.capability === 'providers.catalog') {
        return catalogState.response;
      }
      if (request.capability === 'providers.validate') {
        return catalogState.validateResponse;
      }
      return {
        ok: true,
        result: {},
        events: [],
        artifacts: [],
        error: null,
        durationMs: 0,
      };
    }),
    providers: {
      getVaultStatus: vi.fn(async () => vaultStatus),
      saveSecret: vi.fn(async () => vaultStatus),
      removeSecret: vi.fn(async () => vaultStatus),
    },
  };
});

vi.mock('../../src/renderer/desktop-api', () => ({
  getDesktopApi: () => desktopApiMock,
}));

import { SettingsSurface } from '../../src/renderer/panels/SettingsSurface';

function createSnapshot(overrides?: {
  subscription?: Record<string, unknown>;
  usage?: Record<string, unknown>;
}): BootstrapSnapshot {
  return {
    state: {
      account: {
        displayName: 'Operator',
        email: 'operator@elyan.dev',
        hasAvatar: false,
        dataManagement: 'local_first',
      },
      pairing: {
        lastSessionStatus: 'claimed',
        lastSessionId: 'session-1',
        pairingCode: 'PWGSFB5B',
        manualEntryCode: 'session-1|PWGSFB5B',
        desktopDeviceId: '11111111-1111-4111-8111-111111111111',
        realtimeReady: false,
        expiresAt: '2030-05-22T15:40:00Z',
        lastHeartbeatAt: '2030-05-22T15:30:00Z',
      },
      permissions: {
        allow_file_indexing: false,
      },
    },
    workspace: { projects: [] },
    conversations: [],
    runtime: {
      controlPlane: {
        authMe: {
          data: {
            user: {
              id: 'user-1',
              email: 'operator@elyan.dev',
              displayName: 'Operator',
            },
            subscription: {
              planCode: 'free',
              status: 'trialing',
              periodEndsAt: '2030-05-29T15:30:00Z',
              ...(overrides?.subscription ?? {}),
            },
            usage: {
              dailyRemaining: 4,
              weeklyRemaining: 22,
              trialActive: true,
              trialEndsAt: '2030-05-29T15:30:00Z',
              serverBrainAllowed: true,
              accessMode: 'trial',
              planLabelSource: 'trial',
              ...(overrides?.usage ?? {}),
            },
          },
        },
        runtimeSession: {
          data: {
            device: {
              id: '11111111-1111-4111-8111-111111111111',
              label: 'Elyan Bilgisayar',
            },
            readiness: {
              canReceiveTasks: false,
            },
            connection: {},
          },
        },
      },
    },
    backend: {},
    localModels: {},
  };
}

async function renderSettings(
  snapshot: BootstrapSnapshot,
  overrides: Partial<{
    onBack: ReturnType<typeof vi.fn>;
    onLogout: ReturnType<typeof vi.fn>;
    onRefresh: ReturnType<typeof vi.fn>;
    onEnsureRegistered: ReturnType<typeof vi.fn>;
    onCreatePairingSession: ReturnType<typeof vi.fn>;
  }> = {},
): Promise<{ container: HTMLDivElement; root: Root; callbacks: Record<string, ReturnType<typeof vi.fn>> }> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  const callbacks = {
    onBack: overrides.onBack ?? vi.fn(),
    onLogout: overrides.onLogout ?? vi.fn(),
    onRefresh: overrides.onRefresh ?? vi.fn(),
    onEnsureRegistered: overrides.onEnsureRegistered ?? vi.fn(),
    onCreatePairingSession: overrides.onCreatePairingSession ?? vi.fn(),
  };
  await act(async () => {
    root.render(
      createElement(SettingsSurface, {
        snapshot,
        systemCapabilities: null,
        logoUrl: 'elyan://logo',
        ...callbacks,
      }),
    );
    await Promise.resolve();
    await Promise.resolve();
  });
  return { container, root, callbacks };
}

async function clickButton(container: HTMLElement, label: string): Promise<void> {
  const button = Array.from(container.querySelectorAll('button')).find((item) => item.textContent?.includes(label));
  expect(button).toBeTruthy();
  await act(async () => {
    button?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await Promise.resolve();
  });
}

async function changeFileInput(container: HTMLElement, file: File): Promise<void> {
  const input = container.querySelector('input[type="file"]') as HTMLInputElement | null;
  expect(input).toBeTruthy();
  Object.defineProperty(input, 'files', {
    configurable: true,
    value: [file],
  });
  await act(async () => {
    input?.dispatchEvent(new Event('change', { bubbles: true }));
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('settings surface', () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    desktopApiMock.request.mockImplementation(async (request: { capability: string }) => {
      if (request.capability === 'providers.catalog') {
        return desktopApiMock.state.response;
      }
      if (request.capability === 'providers.validate') {
        return desktopApiMock.state.validateResponse;
      }
      return {
        ok: true,
        result: {},
        events: [],
        artifacts: [],
        error: null,
        durationMs: 0,
      };
    });
    document.body.innerHTML = '';
  });

  it('renders local model settings as a compact list without technical copy', async () => {
    const { container, root } = await renderSettings(createSnapshot());

    expect(container.textContent).toContain('Yerel Modeller');
    expect(container.textContent).toContain('Ollama');
    expect(container.textContent).toContain('Önerilen modeller');
    expect(container.textContent).toContain('llama3.1:8b');
    expect(container.textContent).not.toContain('http://127.0.0.1:11434');
    expect(container.textContent).not.toContain('reachable');
    expect(container.textContent).not.toContain('runtime=');

    await act(async () => {
      root.unmount();
    });
  });

  it('renders cloud providers with simple connection language', async () => {
    const { container, root } = await renderSettings(createSnapshot());

    await clickButton(container, 'Bulut Modeller');
    expect(container.textContent).toContain('OpenAI');
    expect(container.textContent).toContain('Anthropic');
    expect(container.textContent).toContain('Gemini');
    expect(container.textContent).toContain('Bağlı');
    expect(container.textContent).toContain('Bağlı değil');
    expect(container.textContent).toContain('Kontrol et');
    expect(container.textContent).not.toContain('provider_unreachable');
    expect(container.textContent).not.toContain('baseUrl');

    await act(async () => {
      root.unmount();
    });
  });

  it('renders pairing section with phone-first copy', async () => {
    const snapshot = createSnapshot();
    snapshot.backend = {
      mobileBootstrap: {
        ok: true,
        data: {
          devices: [
            {
              id: 'mobile-1',
              type: 'mobile',
              label: 'iPhone',
              platform: 'ios',
              runtime: { isConnected: true },
              lastSeenAt: '2030-05-22T15:35:00Z',
            },
          ],
        },
      },
    };
    const { container, root } = await renderSettings(snapshot);

    await clickButton(container, 'Telefon Bağlantısı');
    expect(container.textContent).toContain('Bağlı cihazlar');
    expect(container.textContent).toContain('PWGSFB5B');
    expect(container.textContent).toContain('session-1|PWGSFB5B');
    expect(container.textContent).toContain('Bekliyor');
    expect(container.textContent).toContain('Elyan Bilgisayar');
    expect(container.textContent).toContain('iPhone');
    expect(container.textContent).not.toContain('heartbeat_missing');

    await act(async () => {
      root.unmount();
    });
  });

  it('removes a paired phone through the runtime cleanup capability', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true));
    const requestMock = desktopApiMock.request;
    const onRefresh = vi.fn();
    const snapshot = createSnapshot();
    snapshot.backend = {
      mobileBootstrap: {
        ok: true,
        data: {
          devices: [
            {
              id: 'mobile-1',
              type: 'mobile',
              label: 'iPhone',
              platform: 'ios',
              runtime: { isConnected: false },
            },
          ],
        },
      },
    };

    const { container, root } = await renderSettings(snapshot, { onRefresh });
    await clickButton(container, 'Telefon Bağlantısı');
    await clickButton(container, 'Kaldır');

    expect(requestMock).toHaveBeenCalledWith(
      expect.objectContaining({
        capability: 'backend.device_deactivate',
        payload: { deviceId: 'mobile-1' },
      }),
    );
    expect(onRefresh).toHaveBeenCalled();

    vi.unstubAllGlobals();
    await act(async () => {
      root.unmount();
    });
  });

  it('shows device cleanup failures instead of refreshing stale phone state', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true));
    const requestMock = desktopApiMock.request;
    requestMock.mockImplementation(async (request: { capability: string }) => {
      if (request.capability === 'backend.device_deactivate') {
        return {
          ok: false,
          result: {},
          events: [],
          artifacts: [],
          error: { code: 'DEVICE_DEACTIVATE_FAILED', message: 'Cihaz kaldırılamadı.' },
          durationMs: 0,
        };
      }
      return {
        ok: true,
        result: {},
        events: [],
        artifacts: [],
        error: null,
        durationMs: 0,
      };
    });
    const onRefresh = vi.fn();
    const snapshot = createSnapshot();
    snapshot.backend = {
      mobileBootstrap: {
        ok: true,
        data: {
          devices: [
            {
              id: 'mobile-1',
              type: 'mobile',
              label: 'iPhone',
              platform: 'ios',
            },
          ],
        },
      },
    };

    const { container, root } = await renderSettings(snapshot, { onRefresh });
    await clickButton(container, 'Telefon Bağlantısı');
    await clickButton(container, 'Kaldır');

    expect(onRefresh).not.toHaveBeenCalled();
    expect(container.textContent).toContain('Cihaz kaldırılamadı.');

    vi.unstubAllGlobals();
    await act(async () => {
      root.unmount();
    });
  });

  it('locks pairing controls when runtime truth reports a plan restriction', async () => {
    const snapshot = createSnapshot();
    snapshot.state.account.subscription = { planCode: 'free', status: 'free' } as never;
    snapshot.state.billing = { planCode: 'free', status: 'free' } as never;
    snapshot.state.pairing.lastSessionStatus = '';
    snapshot.runtime = {
      targetErrorCode: 'desktop_plan_required',
      targetStatus: 'plan_restricted',
    };

    const { container, root } = await renderSettings(snapshot);

    await clickButton(container, 'Telefon Bağlantısı');
    expect(container.textContent).toContain('Plan yetersiz');
    expect(container.textContent).toContain('Kilitli');

    await act(async () => {
      root.unmount();
    });
  });

  it('renders persistent permission controls in privacy settings', async () => {
    const { container, root } = await renderSettings(createSnapshot());

    await clickButton(container, 'Gizlilik');
    expect(container.textContent).toContain('Gizlilik');
    expect(container.textContent).toContain('Yerel çalışma');
    expect(container.textContent).toContain('Güvenli hata gizleme');
    expect(container.textContent).toContain('Gelişmiş İzinler');
    expect(container.textContent).toContain('Geçmişi temizle');
    expect(container.textContent).toContain('Hesabı sil');

    await act(async () => {
      root.unmount();
    });
  });

  it('renders compact trial quota details without backend wording', async () => {
    const { container, root } = await renderSettings(createSnapshot());

    await clickButton(container, 'Hesap');
    expect(container.textContent).toContain('Ücretsiz');
    expect(container.textContent).toContain('Deneme');
    expect(container.textContent).toContain('Token durumu');
    expect(container.textContent).toContain('Token dahil');
    expect(container.textContent).toContain('Plan dönemi');
    expect(container.textContent).toMatch(/Günlük\s*4 kaldı/);
    expect(container.textContent).toContain('4 kaldı');
    expect(container.textContent).toMatch(/Haftalık\s*22 kaldı/);
    expect(container.textContent).toContain('22 kaldı');
    expect(container.textContent).not.toContain('Ödeme açılana kadar erişim');
    expect(container.textContent).not.toContain('Backend');
    expect(container.textContent).not.toContain('serverBrainAllowed');

    await act(async () => {
      root.unmount();
    });
  });

  it('shows the subscription-backed plan and token summary in account settings', async () => {
    const { container, root } = await renderSettings(
      createSnapshot({
        subscription: {
          planCode: 'pro',
          status: 'active',
          periodEndsAt: '2030-06-15T15:30:00Z',
          aiCreditsMonthly: 2000,
          creditBalance: 742,
        },
        usage: {
          trialActive: false,
          accessMode: 'paid',
          planLabelSource: 'subscription',
          trialEndsAt: null,
          dailyRemaining: 5,
          weeklyRemaining: 25,
        },
      }),
    );

    await clickButton(container, 'Hesap');
    expect(container.textContent).toContain('Pro');
    expect(container.textContent).toContain('742 token bakiye');
    expect(container.textContent).toMatch(/Günlük\s*5 kaldı/);
    expect(container.textContent).toContain('5 kaldı');
    expect(container.textContent).not.toContain('team');

    await act(async () => {
      root.unmount();
    });
  });

  it('shows a locked limited-usage state after access expires', async () => {
    const { container, root } = await renderSettings(
      createSnapshot({
        subscription: {
          planCode: 'free',
          status: 'free',
          periodEndsAt: '2020-05-29T15:30:00Z',
        },
        usage: {
          trialActive: false,
          accessMode: 'free',
          planLabelSource: 'subscription',
          trialEndsAt: '2020-05-29T15:30:00Z',
          serverBrainAllowed: false,
          upgradeRequiredForServerBrain: true,
          dailyRemaining: 0,
          weeklyRemaining: 0,
        },
      }),
    );

    await clickButton(container, 'Hesap');
    expect(container.textContent).toContain('Kullanıma kapalı');
    expect(container.textContent).toMatch(/Günlük\s*0 kaldı/);

    await act(async () => {
      root.unmount();
    });
  });

  it('keeps the local avatar preview visible even when upload returns runtime not ready', async () => {
    const originalFileReader = globalThis.FileReader;
    const requestMock = desktopApiMock.request;
    const fileReaderStub = class {
      result = 'data:image/png;base64,ZmFrZQ==';
      onload: null | (() => void) = null;
      onerror: null | (() => void) = null;
      readAsDataURL() {
        this.onload?.();
      }
    } as unknown as typeof FileReader;

    globalThis.FileReader = fileReaderStub;
    requestMock.mockImplementation(async (request: { capability: string }) => {
      if (request.capability === 'providers.catalog') {
        return desktopApiMock.state.response;
      }
      if (request.capability === 'backend.auth_avatar_upload') {
        return {
          ok: false,
          result: {},
          events: [],
          artifacts: [],
          error: { code: 'RUNTIME_NOT_READY', message: 'Yerel Elyan runtime hazır değil.' },
          durationMs: 0,
        };
      }
      return {
        ok: true,
        result: {},
        events: [],
        artifacts: [],
        error: null,
        durationMs: 0,
      };
    });

    const { container, root } = await renderSettings(createSnapshot());
    await clickButton(container, 'Hesap');
    await clickButton(container, 'Düzenle');
    await changeFileInput(container, new File(['fake'], 'avatar.png', { type: 'image/png' }));
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 760));
    });

    const preview = container.querySelector('.settings-avatar-row img') as HTMLImageElement | null;
    expect(preview?.src).toContain('elyan://logo');
    expect(container.textContent).toContain('Profil fotoğrafı şu anda yüklenemiyor. Birkaç saniye sonra tekrar dene.');
    expect(container.textContent).not.toContain('runtime hazır değil');

    globalThis.FileReader = originalFileReader;
    await act(async () => {
      root.unmount();
    });
  });

  it('clears canonical server conversation history from privacy settings', async () => {
    const requestMock = desktopApiMock.request;
    const { container, root, callbacks } = await renderSettings(createSnapshot(), {
      onRefresh: vi.fn(),
    });

    requestMock.mockImplementation(async (request: { capability: string }) => {
      if (request.capability === 'conversation.clear_history') {
        return {
          ok: true,
          result: {
            state: {
              conversation: {
                activeId: '',
                items: [],
              },
            },
            conversations: [],
          },
          events: [],
          artifacts: [],
          error: null,
          durationMs: 0,
        };
      }
      return {
        ok: true,
        result: {},
        events: [],
        artifacts: [],
        error: null,
        durationMs: 0,
      };
    });

    await clickButton(container, 'Gizlilik');
    await clickButton(container, 'Geçmişi temizle');

    expect(requestMock).toHaveBeenCalledWith(
      expect.objectContaining({
        capability: 'conversation.clear_history',
        payload: {},
      }),
    );
    expect(callbacks.onRefresh).toHaveBeenCalled();
    expect(container.textContent).toContain('Geçmiş temizlendi.');

    await act(async () => {
      root.unmount();
    });
  });
});
