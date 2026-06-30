import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BootstrapSnapshot } from '../../src/shared/protocol';
import { Workspace } from '../../src/renderer/panels/Workspace';

function createSnapshot(): BootstrapSnapshot {
  return {
    state: {
      conversation: {
        activeId: 'conv-1',
        items: [
          {
            id: 'conv-1',
            title: 'Yeni sohbet',
            preview: 'Merhaba',
            updatedAt: '2030-05-22T15:30:00Z',
            messages: [],
          },
        ],
      },
    },
    workspace: { projects: [] },
    conversations: [],
    runtime: {},
    backend: {},
    localModels: {},
  };
}

function createPermissionSnapshot(): BootstrapSnapshot {
  return {
    state: {
      conversation: {
        activeId: 'conv-1',
        items: [
          {
            id: 'conv-1',
            title: 'Yeni sohbet',
            preview: 'İzin gerekiyor',
            updatedAt: '2030-05-22T15:30:00Z',
            messages: [
              {
                id: 'msg-1',
                role: 'assistant',
                text: 'Tarayıcı ve medya erişimi kapalı.',
                meta: {
                  permissionNeeded: true,
                  permissionReason: 'Tarayıcı ve medya erişimi kapalı. Ayarlar > Gizlilik bölümünden açabilirsin.',
                  permissionKey: 'allow_browser_control',
                  systemPermissionKey: 'accessibility',
                  permissionErrorCode: 'OS_PERMISSION_REQUIRED',
                },
              },
            ],
          },
        ],
      },
    },
    workspace: { projects: [] },
    conversations: [],
    runtime: {},
    backend: {},
    localModels: {},
  };
}

function createTextBlockSnapshot(): BootstrapSnapshot {
  return {
    state: {
      conversation: {
        activeId: 'conv-1',
        items: [
          {
            id: 'conv-1',
            title: 'Yeni sohbet',
            preview: 'Merhaba, Elyan hazır.',
            updatedAt: '2030-05-22T15:30:00Z',
            messages: [
              {
                id: 'msg-1',
                role: 'assistant',
                text: '[object Object]',
                blocks: [
                  {
                    type: 'text',
                    markdown: 'Merhaba, Elyan hazır.',
                    format: 'markdown',
                    version: 1,
                  },
                ],
              },
            ],
          },
        ],
      },
    },
    workspace: { projects: [] },
    conversations: [],
    runtime: {},
    backend: {},
    localModels: {},
  };
}

function createBlankActiveSnapshotWithHistory(): BootstrapSnapshot {
  return {
    state: {
      conversation: {
        activeId: '',
        items: [
          {
            id: 'conv-history',
            title: 'Eski sohbet',
            preview: 'Eski cevap',
            updatedAt: '2030-05-22T15:30:00Z',
            messages: [
              {
                id: 'msg-history',
                role: 'assistant',
                text: 'Eski cevap görünmemeli.',
              },
            ],
          },
        ],
      },
    },
    workspace: { projects: [] },
    conversations: [],
    runtime: {},
    backend: {},
    localModels: {},
  };
}

function createTaskTraceBlockSnapshot(): BootstrapSnapshot {
  return {
    state: {
      conversation: {
        activeId: 'conv-1',
        items: [
          {
            id: 'conv-1',
            title: 'Görev',
            preview: 'Görev yürütülüyor',
            updatedAt: '2030-05-22T15:30:00Z',
            messages: [
              {
                id: 'msg-1',
                role: 'assistant',
                text: '',
                blocks: [
                  {
                    type: 'task_trace',
                    title: 'Görev yürütülüyor',
                    status: 'running',
                    steps: [
                      { id: 'intent', label: 'Niyet anlaşıldı', status: 'completed' },
                      { id: 'response', label: 'Cevap hazırlanıyor', status: 'running' },
                    ],
                  },
                ],
              },
            ],
          },
        ],
      },
    },
    workspace: { projects: [] },
    conversations: [],
    runtime: {},
    backend: {},
    localModels: {},
  };
}

function createStructuredBlockSnapshot(): BootstrapSnapshot {
  return {
    state: {
      conversation: {
        activeId: 'conv-1',
        items: [
          {
            id: 'conv-1',
            title: 'Bloklar',
            preview: 'Yapılandırılmış cevap',
            updatedAt: '2030-05-22T15:30:00Z',
            messages: [
              {
                id: 'msg-structured',
                role: 'assistant',
                text: '',
                blocks: [
                  {
                    type: 'code',
                    language: 'python',
                    filename: 'analysis.py',
                    code: 'print("elyan")',
                  },
                  {
                    type: 'table',
                    title: 'Sonuç tablosu',
                    columns: ['Kategori', 'Değer'],
                    rows: [
                      ['Algoritma', 'Tamam'],
                      ['Bellek', 'Hazır<br>Güvenli'],
                    ],
                  },
                  {
                    type: 'chart',
                    title: 'Dağılım',
                    chartType: 'bar',
                    points: [
                      { label: 'PDF', value: 3 },
                      { label: 'Görsel', value: 2 },
                    ],
                  },
                  {
                    type: 'file',
                    name: 'rapor.pdf',
                    mimeType: 'application/pdf',
                    sizeBytes: 2048,
                    preview: 'Özet çıkarıldı.',
                  },
                  {
                    type: 'formula',
                    content: '$$E=mc^2$$',
                    format: 'latex',
                  },
                  {
                    type: 'artifact',
                    artifactType: 'image',
                    url: 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==',
                    title: 'Grafik görseli',
                    mime: 'image/gif',
                  },
                  {
                    type: 'colored_table',
                    data: {
                      rows: [
                        { Durum: 'Güvenli', Sonuç: 'Tamam' },
                      ],
                      highlightRules: [
                        { column: 'Durum', match: 'Güvenli', tone: 'success' },
                      ],
                    },
                  },
                ],
              },
            ],
          },
        ],
      },
    },
    workspace: { projects: [] },
    conversations: [],
    runtime: {},
    backend: {},
    localModels: {},
  };
}

function createIncompleteBlockFallbackSnapshot(): BootstrapSnapshot {
  return {
    state: {
      conversation: {
        activeId: 'conv-1',
        items: [
          {
            id: 'conv-1',
            title: 'Tam cevap',
            preview: 'Cevap tamamlandı',
            updatedAt: '2030-05-22T15:30:00Z',
            messages: [
              {
                id: 'msg-incomplete',
                role: 'assistant',
                text: 'Atatürk’ün inkılapları eğitim, hukuk, ekonomi ve toplumsal yaşam alanlarında Türkiye’nin modernleşmesini hızlandıran kapsamlı reformlardır.',
                blocks: [
                  {
                    type: 'text',
                    markdown: 'Atatürk’ün inkılapları eğitim',
                  },
                ],
              },
            ],
          },
        ],
      },
    },
    workspace: { projects: [] },
    conversations: [],
    runtime: {},
    backend: {},
    localModels: {},
  };
}

function createUnknownBlockSnapshot(): BootstrapSnapshot {
  return {
    state: {
      conversation: {
        activeId: 'conv-1',
        items: [
          {
            id: 'conv-1',
            title: 'Bilinmeyen blok',
            preview: 'Güvenli fallback',
            updatedAt: '2030-05-22T15:30:00Z',
            messages: [
              {
                id: 'msg-unknown',
                role: 'assistant',
                content: 'Legacy fallback görünmemeli.',
                text: 'Legacy fallback görünmemeli.',
                blocks: [
                  {
                    type: 'quantum_widget_v9',
                    title: 'Quantum widget',
                    summary: 'Bu blok mobil/desktop ortak sözleşmesinde henüz desteklenmiyor.',
                    mobileFallback: {
                      type: 'text',
                      markdown: 'Bu işlem bağlı masaüstü cihazında yürütüldü.',
                    },
                  },
                ],
              },
            ],
          },
        ],
      },
    },
    workspace: { projects: [] },
    conversations: [],
    runtime: {},
    backend: {},
    localModels: {},
  };
}

async function renderWorkspace(locked: boolean): Promise<{ container: HTMLDivElement; root: Root }> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      createElement(Workspace, {
        snapshot: createSnapshot(),
        selectedConversationId: 'conv-1',
        composer: '',
        composerAttachments: [],
        skillItems: [],
        busy: false,
        lastError: '',
        chatLocked: locked,
        chatLockTitle: 'Günlük limit doldu',
        chatLockDetail: 'Yeni mesaj göndermek için günlük limitin yenilenmesini bekle.',
        logoUrl: 'elyan://logo',
        userName: 'Operator',
        onComposerChange: vi.fn(),
        onClearComposer: vi.fn(),
        onCreateConversation: vi.fn(),
        onPasteFiles: vi.fn(),
        onRemoveComposerAttachment: vi.fn(),
        onSend: vi.fn(),
        onConfirmPlan: vi.fn(),
        onOpenPermissionSettings: vi.fn(),
        onToggleShortcutHelp: vi.fn(),
        onCreatePairingSession: vi.fn(),
      }),
    );
    await Promise.resolve();
  });
  return { container, root };
}

async function renderPermissionWorkspace(): Promise<{ container: HTMLDivElement; root: Root }> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      createElement(Workspace, {
        snapshot: createPermissionSnapshot(),
        selectedConversationId: 'conv-1',
        composer: '',
        composerAttachments: [],
        skillItems: [],
        busy: false,
        lastError: '',
        chatLocked: false,
        chatLockTitle: '',
        chatLockDetail: '',
        logoUrl: 'elyan://logo',
        userName: 'Operator',
        onComposerChange: vi.fn(),
        onClearComposer: vi.fn(),
        onCreateConversation: vi.fn(),
        onPasteFiles: vi.fn(),
        onRemoveComposerAttachment: vi.fn(),
        onSend: vi.fn(),
        onConfirmPlan: vi.fn(),
        onOpenPermissionSettings: vi.fn(),
        onToggleShortcutHelp: vi.fn(),
        onCreatePairingSession: vi.fn(),
      }),
    );
    await Promise.resolve();
  });
  return { container, root };
}

async function renderTaskShellWorkspace(): Promise<{ container: HTMLDivElement; root: Root }> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      createElement(Workspace, {
        snapshot: createSnapshot(),
        selectedConversationId: 'conv-1',
        composer: '',
        composerAttachments: [],
        taskShell: {
          readinessToken: 'ready',
          readinessLabel: 'Desktop görev almaya hazır',
          readinessDetail: 'Mobil görevleri bu runtime alabilir.',
          readinessTone: 'success',
          desktopHeadline: 'Mac Studio',
          connectionSummary: 'Desktop görev almaya hazır · 1 bekleyen görev',
          modelLabel: 'Elyan Quantum',
          learningLabel: 'Kişiselleştirme açık · 7 güvenli sinyal',
          retrievalLabel: '3 belge · 19 parça',
          pendingRemoteTaskCount: 1,
          activeRemoteTaskCount: 0,
          approvalTasks: [
            {
              id: 'task-approval',
              title: 'Mail gönder',
              summary: 'Dış aksiyon onay bekliyor.',
              status: 'waiting_approval',
              statusLabel: 'onay bekliyor',
              statusTone: 'warning',
              route: 'desktop_runtime',
              updatedAt: '2030-05-22T15:31:12Z',
              approvalKind: 'email_send',
              requiresApproval: true,
              artifactCount: 1,
            },
          ],
          recentTasks: [],
          canReceiveTasks: true,
          canExecuteAssignedTasks: true,
          powerCapabilityCount: 42,
          blockedCapabilityCount: 2,
        },
        skillItems: [],
        busy: false,
        lastError: '',
        chatLocked: false,
        chatLockTitle: '',
        chatLockDetail: '',
        logoUrl: 'elyan://logo',
        userName: 'Operator',
        onComposerChange: vi.fn(),
        onClearComposer: vi.fn(),
        onCreateConversation: vi.fn(),
        onPasteFiles: vi.fn(),
        onRemoveComposerAttachment: vi.fn(),
        onSend: vi.fn(),
        onConfirmPlan: vi.fn(),
        onOpenPermissionSettings: vi.fn(),
        onToggleShortcutHelp: vi.fn(),
        onCreatePairingSession: vi.fn(),
        onOpenTasks: vi.fn(),
        onExecuteAssignedTasks: vi.fn(),
        onApproveTask: vi.fn(),
      }),
    );
    await Promise.resolve();
  });
  return { container, root };
}

async function renderTextBlockWorkspace(): Promise<{ container: HTMLDivElement; root: Root }> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      createElement(Workspace, {
        snapshot: createTextBlockSnapshot(),
        selectedConversationId: 'conv-1',
        composer: '',
        composerAttachments: [],
        skillItems: [],
        busy: false,
        lastError: '',
        chatLocked: false,
        chatLockTitle: '',
        chatLockDetail: '',
        logoUrl: 'elyan://logo',
        userName: 'Operator',
        onComposerChange: vi.fn(),
        onClearComposer: vi.fn(),
        onCreateConversation: vi.fn(),
        onPasteFiles: vi.fn(),
        onRemoveComposerAttachment: vi.fn(),
        onSend: vi.fn(),
        onConfirmPlan: vi.fn(),
        onOpenPermissionSettings: vi.fn(),
        onToggleShortcutHelp: vi.fn(),
        onCreatePairingSession: vi.fn(),
      }),
    );
    await Promise.resolve();
  });
  return { container, root };
}

async function renderBlankActiveWorkspace(): Promise<{ container: HTMLDivElement; root: Root }> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      createElement(Workspace, {
        snapshot: createBlankActiveSnapshotWithHistory(),
        selectedConversationId: '',
        composer: '',
        composerAttachments: [],
        skillItems: [],
        busy: false,
        lastError: '',
        chatLocked: false,
        chatLockTitle: '',
        chatLockDetail: '',
        logoUrl: 'elyan://logo',
        userName: 'Operator',
        onComposerChange: vi.fn(),
        onClearComposer: vi.fn(),
        onCreateConversation: vi.fn(),
        onPasteFiles: vi.fn(),
        onRemoveComposerAttachment: vi.fn(),
        onSend: vi.fn(),
        onConfirmPlan: vi.fn(),
        onOpenPermissionSettings: vi.fn(),
        onToggleShortcutHelp: vi.fn(),
        onCreatePairingSession: vi.fn(),
      }),
    );
    await Promise.resolve();
  });
  return { container, root };
}

async function renderTaskTraceBlockWorkspace(): Promise<{ container: HTMLDivElement; root: Root }> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      createElement(Workspace, {
        snapshot: createTaskTraceBlockSnapshot(),
        selectedConversationId: 'conv-1',
        composer: '',
        composerAttachments: [],
        skillItems: [],
        busy: false,
        lastError: '',
        chatLocked: false,
        chatLockTitle: '',
        chatLockDetail: '',
        logoUrl: 'elyan://logo',
        userName: 'Operator',
        onComposerChange: vi.fn(),
        onClearComposer: vi.fn(),
        onCreateConversation: vi.fn(),
        onPasteFiles: vi.fn(),
        onRemoveComposerAttachment: vi.fn(),
        onSend: vi.fn(),
        onConfirmPlan: vi.fn(),
        onOpenPermissionSettings: vi.fn(),
        onToggleShortcutHelp: vi.fn(),
        onCreatePairingSession: vi.fn(),
      }),
    );
    await Promise.resolve();
  });
  return { container, root };
}

async function renderStructuredBlockWorkspace(): Promise<{ container: HTMLDivElement; root: Root }> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      createElement(Workspace, {
        snapshot: createStructuredBlockSnapshot(),
        selectedConversationId: 'conv-1',
        composer: '',
        composerAttachments: [],
        skillItems: [],
        busy: false,
        lastError: '',
        chatLocked: false,
        chatLockTitle: '',
        chatLockDetail: '',
        logoUrl: 'elyan://logo',
        userName: 'Operator',
        onComposerChange: vi.fn(),
        onClearComposer: vi.fn(),
        onCreateConversation: vi.fn(),
        onPasteFiles: vi.fn(),
        onRemoveComposerAttachment: vi.fn(),
        onSend: vi.fn(),
        onConfirmPlan: vi.fn(),
        onOpenPermissionSettings: vi.fn(),
        onToggleShortcutHelp: vi.fn(),
        onCreatePairingSession: vi.fn(),
      }),
    );
    await Promise.resolve();
  });
  return { container, root };
}

async function renderIncompleteBlockFallbackWorkspace(): Promise<{ container: HTMLDivElement; root: Root }> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      createElement(Workspace, {
        snapshot: createIncompleteBlockFallbackSnapshot(),
        selectedConversationId: 'conv-1',
        composer: '',
        composerAttachments: [],
        skillItems: [],
        busy: false,
        lastError: '',
        chatLocked: false,
        chatLockTitle: '',
        chatLockDetail: '',
        logoUrl: 'elyan://logo',
        userName: 'Operator',
        onComposerChange: vi.fn(),
        onClearComposer: vi.fn(),
        onCreateConversation: vi.fn(),
        onPasteFiles: vi.fn(),
        onRemoveComposerAttachment: vi.fn(),
        onSend: vi.fn(),
        onConfirmPlan: vi.fn(),
        onOpenPermissionSettings: vi.fn(),
        onToggleShortcutHelp: vi.fn(),
        onCreatePairingSession: vi.fn(),
      }),
    );
    await Promise.resolve();
  });
  return { container, root };
}

async function renderUnknownBlockWorkspace(): Promise<{ container: HTMLDivElement; root: Root }> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      createElement(Workspace, {
        snapshot: createUnknownBlockSnapshot(),
        selectedConversationId: 'conv-1',
        composer: '',
        composerAttachments: [],
        skillItems: [],
        busy: false,
        lastError: '',
        chatLocked: false,
        chatLockTitle: '',
        chatLockDetail: '',
        logoUrl: 'elyan://logo',
        userName: 'Operator',
        onComposerChange: vi.fn(),
        onClearComposer: vi.fn(),
        onCreateConversation: vi.fn(),
        onPasteFiles: vi.fn(),
        onRemoveComposerAttachment: vi.fn(),
        onSend: vi.fn(),
        onConfirmPlan: vi.fn(),
        onOpenPermissionSettings: vi.fn(),
        onToggleShortcutHelp: vi.fn(),
        onCreatePairingSession: vi.fn(),
      }),
    );
    await Promise.resolve();
  });
  return { container, root };
}

describe('workspace', () => {
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('replaces the composer with a quota lock card when usage is exhausted', async () => {
    const { container, root } = await renderWorkspace(true);

    expect(container.textContent).toContain('Günlük limit doldu');
    expect(container.textContent).toContain('Yeni mesaj göndermek için günlük limitin yenilenmesini bekle.');
    expect(container.querySelector('textarea')).toBeNull();

    await act(async () => {
      root.unmount();
    });
  });

  it('shows a permission card when the assistant requests local access', async () => {
    const { container, root } = await renderPermissionWorkspace();

    expect(container.textContent).toContain('Sistem izni gerekiyor');
    expect(container.textContent).toContain('Tarayıcı ve medya erişimi kapalı.');
    expect(container.textContent).toContain('İzinleri aç');

    await act(async () => {
      root.unmount();
    });
  });

  it('renders assistant text blocks instead of raw message objects', async () => {
    const { container, root } = await renderTextBlockWorkspace();

    expect(container.textContent).toContain('Merhaba, Elyan hazır.');
    expect(container.textContent).not.toContain('[object Object]');

    await act(async () => {
      root.unmount();
    });
  });

  it('keeps the desktop task shell out of the composer surface', async () => {
    const { container, root } = await renderTaskShellWorkspace();

    expect(container.querySelector('.desktop-task-shell')).toBeNull();
    expect(container.querySelector('.desktop-approval-card')).toBeNull();
    expect(container.querySelector('.composer')).not.toBeNull();
    expect(container.textContent).not.toContain('Kuyruğu Al');

    await act(async () => {
      root.unmount();
    });
  });

  it('keeps new chat blank even when history exists', async () => {
    const { container, root } = await renderBlankActiveWorkspace();

    expect(container.querySelector('.timeline--empty')).not.toBeNull();
    expect(container.textContent).not.toContain('Eski cevap görünmemeli.');

    await act(async () => {
      root.unmount();
    });
  });

  it('renders task trace blocks as compact status rows', async () => {
    const { container, root } = await renderTaskTraceBlockWorkspace();

    expect(container.textContent).toContain('Görev yürütülüyor');
    expect(container.textContent).toContain('Niyet anlaşıldı');
    expect(container.textContent).toContain('tamamlandı');
    expect(container.textContent).toContain('Cevap hazırlanıyor');
    expect(container.textContent).toContain('sürüyor');
    expect(container.textContent).not.toContain('[object Object]');

    await act(async () => {
      root.unmount();
    });
  });

  it('renders mobile-compatible structured assistant blocks on desktop', async () => {
    const { container, root } = await renderStructuredBlockWorkspace();

    expect(container.textContent).toContain('analysis.py');
    expect(container.textContent).toContain('print("elyan")');
    expect(container.textContent).toContain('Sonuç tablosu');
    expect(container.textContent).toContain('Algoritma');
    expect(container.textContent).toContain('Güvenli');
    expect(container.textContent).toContain('Dağılım');
    expect(container.textContent).toContain('PDF');
    expect(container.textContent).toContain('rapor.pdf');
    expect(container.textContent).toContain('Özet çıkarıldı.');
    expect(container.textContent).toContain('E=mc^2');
    expect(container.textContent).toContain('Grafik görseli');
    expect(container.textContent).toContain('Durum');
    expect(container.querySelector('.message-block__tone--success')).not.toBeNull();
    expect(container.textContent).not.toContain('[object Object]');

    await act(async () => {
      root.unmount();
    });
  });

  it('prefers blocks over legacy content when blocks are present', async () => {
    const { container, root } = await renderIncompleteBlockFallbackWorkspace();

    expect(container.textContent).toContain('Atatürk’ün inkılapları eğitim');
    expect(container.textContent).not.toContain('kapsamlı reformlardır.');

    await act(async () => {
      root.unmount();
    });
  });

  it('renders unknown blocks with a safe fallback instead of crashing', async () => {
    const { container, root } = await renderUnknownBlockWorkspace();

    expect(container.textContent).toContain('Quantum widget');
    expect(container.textContent).toContain('Bu blok mobil/desktop ortak sözleşmesinde henüz desteklenmiyor.');
    expect(container.textContent).not.toContain('Legacy fallback görünmemeli.');

    await act(async () => {
      root.unmount();
    });
  });
});
