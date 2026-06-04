import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BootstrapSnapshot } from '../src/shared/protocol';

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

vi.mock('../src/renderer/desktop-api', () => ({
  getDesktopApi: () => desktopApiMock,
}));

import { SettingsSurface } from '../src/renderer/panels/SettingsSurface';

function createSnapshot(): BootstrapSnapshot {
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
        desktopDeviceId: '11111111-1111-4111-8111-111111111111',
        realtimeReady: false,
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

async function renderSettings(snapshot: BootstrapSnapshot): Promise<{ container: HTMLDivElement; root: Root }> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      createElement(SettingsSurface, {
        snapshot,
        systemCapabilities: null,
        logoUrl: 'elyan://logo',
        onBack: vi.fn(),
        onLogout: vi.fn(),
        onRefresh: vi.fn(),
        onEnsureRegistered: vi.fn(),
        onCreatePairingSession: vi.fn(),
      }),
    );
    await Promise.resolve();
    await Promise.resolve();
  });
  return { container, root };
}

async function clickButton(container: HTMLElement, label: string): Promise<void> {
  const button = Array.from(container.querySelectorAll('button')).find((item) => item.textContent?.includes(label));
  expect(button).toBeTruthy();
  await act(async () => {
    button?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await Promise.resolve();
  });
}

describe('settings surface', () => {
  afterEach(() => {
    vi.clearAllMocks();
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
    expect(container.textContent).toContain('Bağlantı anahtarı ekleyebilirsin.');
    expect(container.textContent).not.toContain('provider_unreachable');
    expect(container.textContent).not.toContain('baseUrl');

    await act(async () => {
      root.unmount();
    });
  });

  it('renders pairing section with phone-first copy', async () => {
    const { container, root } = await renderSettings(createSnapshot());

    await clickButton(container, 'Telefon Bağlantısı');
    expect(container.textContent).toContain('Telefon bağlantısı');
    expect(container.textContent).toContain('PWGSFB5B');
    expect(container.textContent).toContain('Bağlantı bekleniyor');
    expect(container.textContent).not.toContain('session-1');
    expect(container.textContent).not.toContain('heartbeat_missing');

    await act(async () => {
      root.unmount();
    });
  });
});
