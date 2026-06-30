import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { BootstrapSnapshot, RuntimeRequest, RuntimeResponse, SystemCapabilities, WindowState } from '../../src/shared/protocol';

const historySnapshot: BootstrapSnapshot = {
  state: {
    account: {
      accessToken: 'user-token',
      displayName: 'Operator',
      email: 'operator@elyan.dev',
    },
    conversation: {
      activeId: '',
      items: [
        {
          id: 'conv-history',
          title: 'Geçmiş sohbet',
          preview: 'Önceki cevap',
          updatedAt: '2030-05-22T15:30:00Z',
          messages: [{ id: 'msg-1', role: 'assistant', text: 'Önceki cevap' }],
        },
      ],
    },
  },
  workspace: { projects: [] },
  conversations: [],
  runtime: {},
  backend: {
    authMe: {
      ok: true,
      data: {
        user: {
          id: 'user-1',
          email: 'operator@elyan.dev',
          displayName: 'Operator',
        },
      },
    },
  },
  localModels: {},
};

const desktopApiMock = vi.hoisted(() => {
  const subscribers = new Map<string, Set<(payload: unknown) => void>>();
  const response = (request: RuntimeRequest, result: unknown): RuntimeResponse => ({
    id: request.id ?? '',
    taskId: request.taskId ?? '',
    ok: true,
    capability: request.capability,
    result: result as RuntimeResponse['result'],
    events: [],
    artifacts: [],
    error: null,
    durationMs: 0,
  });
  return {
    emit(channel: string, payload: unknown) {
      for (const listener of subscribers.get(channel) ?? []) {
        listener(payload);
      }
    },
    api: {
      bootstrap: vi.fn(async () => historySnapshot),
      request: vi.fn(async (request: RuntimeRequest) => {
        if (request.capability === 'backend.truth_refresh') {
          return response(request, {
            runtime: {},
            state: historySnapshot.state,
            authMe: historySnapshot.backend?.authMe,
          });
        }
        if (request.capability === 'conversation.select') {
          return response(request, {
            activeConversationId: 'conv-history',
            state: {
              ...historySnapshot.state,
              conversation: {
                ...(historySnapshot.state?.conversation as Record<string, unknown>),
                activeId: 'conv-history',
              },
            },
            conversations: [],
          });
        }
        return response(request, {});
      }),
      subscribe: vi.fn((channel: string, listener: (payload: unknown) => void) => {
        const bucket = subscribers.get(channel) ?? new Set<(payload: unknown) => void>();
        bucket.add(listener);
        subscribers.set(channel, bucket);
        return () => bucket.delete(listener);
      }),
      window: {
        minimize: vi.fn(async () => undefined),
        maximizeOrRestore: vi.fn(async () => ({ isFocused: true, isVisible: true, isMaximized: false, isMinimized: false, isFullScreen: false, isClosing: false, platform: 'darwin' }) as WindowState),
        close: vi.fn(async () => undefined),
        acknowledgeCloseAnimation: vi.fn(async () => undefined),
        getState: vi.fn(async () => ({ isFocused: true, isVisible: true, isMaximized: false, isMinimized: false, isFullScreen: false, isClosing: false, platform: 'darwin' }) as WindowState),
      },
      attachments: {
        saveFromBase64: vi.fn(),
      },
      system: {
        getCapabilities: vi.fn(async () => ({ platform: 'darwin', windowChrome: { trafficLights: false } }) as unknown as SystemCapabilities),
        getLocale: vi.fn(async () => 'tr-TR'),
        openPermissionSettings: vi.fn(async () => true),
      },
      providers: {
        saveSecret: vi.fn(),
        removeSecret: vi.fn(),
        getVaultStatus: vi.fn(async () => ({ available: true, persistent: false, backend: 'test', reason: null, providerIds: [] })),
      },
      dictation: {
        start: vi.fn(async () => undefined),
        stop: vi.fn(async () => undefined),
        cancel: vi.fn(async () => undefined),
        getStatus: vi.fn(async () => ({
          state: 'idle',
          provider: null,
          modelAvailable: false,
          binaryAvailable: false,
          error: null,
          partialTranscript: null,
        })),
      },
    },
  };
});

vi.mock('../../src/renderer/desktop-api', () => ({
  getDesktopApi: () => desktopApiMock.api,
}));

import { App } from '../../src/renderer/App';

describe('App history selection', () => {
  let root: Root | null = null;

  beforeEach(() => {
    vi.stubGlobal('matchMedia', () => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
  });

  afterEach(() => {
    act(() => {
      root?.unmount();
    });
    root = null;
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('persists history clicks through the runtime conversation selection capability', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(createElement(App));
      await Promise.resolve();
      await Promise.resolve();
    });

    const historyButton = container.querySelector('.rail-history__item') as HTMLButtonElement | null;
    expect(historyButton).not.toBeNull();

    await act(async () => {
      historyButton?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(desktopApiMock.api.request).toHaveBeenCalledWith(
      expect.objectContaining({
        capability: 'conversation.select',
        payload: { conversationId: 'conv-history' },
      }),
    );
  });
});
