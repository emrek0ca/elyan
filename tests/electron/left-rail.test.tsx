import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BootstrapSnapshot } from '../../src/shared/protocol';
import { LeftRail } from '../../src/renderer/panels/LeftRail';
import type { ListSurfaceItem } from '../../src/renderer/panels/ListSurface';

function createSnapshot(): BootstrapSnapshot {
  return {
    state: {
      conversation: {
        activeId: 'conv-1',
        items: [],
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
            email: 'operator@example.com',
            displayName: 'Operator',
          },
          subscription: {
            planCode: 'pro',
            status: 'active',
            aiCreditsMonthly: 2000,
            creditBalance: 742,
            creditGrantedThisPeriod: 2000,
          },
          usage: {
            dailyRemaining: 4,
            weeklyRemaining: 22,
            trialActive: false,
            accessMode: 'paid',
            planLabelSource: 'subscription',
          },
        },
      },
    },
    localModels: {},
  };
}

async function renderLeftRail(): Promise<{ container: HTMLDivElement; root: Root; callbacks: Record<string, ReturnType<typeof vi.fn>> }> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  const callbacks = {
    onToggleRail: vi.fn(),
    onCreateConversation: vi.fn(),
    onOpenApps: vi.fn(),
    onOpenSettings: vi.fn(),
    onOpenArchives: vi.fn(),
    onSelectConversation: vi.fn(),
    onRenameConversation: vi.fn(),
    onArchiveConversation: vi.fn(),
    onDeleteConversation: vi.fn(),
  };
  const historyItems: ListSurfaceItem[] = [
    {
      id: 'conv-1',
      title: 'Geçmiş sohbet',
      subtitle: 'Son mesaj',
      meta: '2030-05-22T15:31:12Z',
    },
  ];
  await act(async () => {
    root.render(
      createElement(LeftRail, {
        snapshot: createSnapshot(),
        logoUrl: 'elyan://logo',
        userName: 'Operator',
        userEmail: 'operator@example.com',
        hasTrafficLights: false,
        activeSurface: 'chat',
        historyItems,
        selectedConversationId: 'conv-1',
        isOpen: true,
        isCompactViewport: false,
        ...callbacks,
      }),
    );
    await Promise.resolve();
  });
  return { container, root, callbacks };
}

describe('left rail', () => {
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('opens the history context menu and routes actions to callbacks', async () => {
    const { container, root, callbacks } = await renderLeftRail();
    expect(container.textContent).toContain('Pro');
    expect(container.textContent).toContain('742 token bakiye');
    const historyButton = container.querySelector('.rail-history__item') as HTMLButtonElement | null;
    expect(historyButton).not.toBeNull();

    await act(async () => {
      historyButton?.dispatchEvent(
        new MouseEvent('contextmenu', {
          bubbles: true,
          cancelable: true,
          clientX: 120,
          clientY: 120,
        }),
      );
      await Promise.resolve();
    });

    expect(container.querySelector('.context-menu')).not.toBeNull();

    const menuButtons = Array.from(container.querySelectorAll('.context-menu button')) as HTMLButtonElement[];
    expect(menuButtons.map((button) => button.textContent?.trim())).toEqual(['Aç', 'Yeniden adlandır', 'Arşivle', 'Sil']);

    await act(async () => {
      menuButtons[0]?.click();
      await Promise.resolve();
    });
    expect(callbacks.onSelectConversation).toHaveBeenCalledWith('conv-1');

    await act(async () => {
      historyButton?.dispatchEvent(
        new MouseEvent('contextmenu', {
          bubbles: true,
          cancelable: true,
          clientX: 120,
          clientY: 120,
        }),
      );
      await Promise.resolve();
    });
    const renameButton = Array.from(container.querySelectorAll('.context-menu button')).at(1) as HTMLButtonElement;
    await act(async () => {
      renameButton?.click();
      await Promise.resolve();
    });
    expect(callbacks.onRenameConversation).toHaveBeenCalledWith('conv-1', 'Geçmiş sohbet');

    await act(async () => {
      historyButton?.dispatchEvent(
        new MouseEvent('contextmenu', {
          bubbles: true,
          cancelable: true,
          clientX: 120,
          clientY: 120,
        }),
      );
      await Promise.resolve();
    });
    const archiveButton = Array.from(container.querySelectorAll('.context-menu button')).at(2) as HTMLButtonElement;
    await act(async () => {
      archiveButton?.click();
      await Promise.resolve();
    });
    expect(callbacks.onArchiveConversation).toHaveBeenCalledWith('conv-1');

    await act(async () => {
      historyButton?.dispatchEvent(
        new MouseEvent('contextmenu', {
          bubbles: true,
          cancelable: true,
          clientX: 120,
          clientY: 120,
        }),
      );
      await Promise.resolve();
    });
    const deleteButton = Array.from(container.querySelectorAll('.context-menu button')).at(3) as HTMLButtonElement;
    await act(async () => {
      deleteButton?.click();
      await Promise.resolve();
    });
    expect(callbacks.onDeleteConversation).toHaveBeenCalledWith('conv-1');

    await act(async () => {
      root.unmount();
    });
  });
});
