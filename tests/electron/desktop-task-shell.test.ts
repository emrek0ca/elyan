import { describe, expect, it } from 'vitest';
import type { BootstrapSnapshot } from '../../src/shared/protocol';
import { deriveDesktopTaskShell } from '../../src/renderer/lib/desktop-task-shell';

function createSnapshot(): BootstrapSnapshot {
  return {
    state: {
      taskInbox: {
        pendingCount: 1,
        activeCount: 0,
        items: [
          {
            id: 'task-approval',
            title: 'Mail gönder',
            summary: 'Dış aksiyon onay bekliyor.',
            status: 'waiting_approval',
            routeDecision: { route: 'desktop_runtime' },
            approvalRequest: { kind: 'email_send' },
            artifactCount: 1,
            updatedAt: '2030-05-22T15:31:12Z',
          },
        ],
      },
    },
    workspace: {},
    conversations: [],
    runtime: {
      runtimeReady: true,
      runtimeWebsocketConnected: true,
      runtimeRelayState: 'websocket',
      runtimeCapabilityCount: 42,
      taskInbox: {
        pendingCount: 1,
        activeCount: 0,
        items: [
          {
            id: 'task-approval',
            title: 'Mail gönder',
            summary: 'Dış aksiyon onay bekliyor.',
            status: 'waiting_approval',
            routeDecision: { route: 'desktop_runtime' },
            approvalRequest: { kind: 'email_send' },
            artifactCount: 1,
            updatedAt: '2030-05-22T15:31:12Z',
          },
        ],
      },
      controlPlane: {
        runtimeSession: {
          device: { id: 'desktop-1', name: 'Mac Studio' },
          readiness: { canReceiveTasks: true, targetStatus: 'ready' },
          connection: { status: 'online' },
        },
        brainProfile: {
          chat: { serverBrainName: 'Elyan Quantum' },
          learning: { personalizationEnabled: true, safeLearningEvents: 7 },
          retrieval: { readyDocuments: 3, readyChunks: 19 },
        },
      },
    },
    backend: {},
    localModels: {},
  };
}

describe('desktop task shell view model', () => {
  it('derives mobile-parity desktop readiness and approval truth', () => {
    const shell = deriveDesktopTaskShell(createSnapshot());

    expect(shell.readinessToken).toBe('ready');
    expect(shell.desktopHeadline).toBe('Mac Studio');
    expect(shell.connectionSummary).toContain('1 bekleyen görev');
    expect(shell.approvalTasks).toHaveLength(1);
    expect(shell.approvalTasks[0]?.approvalKind).toBe('email_send');
    expect(shell.approvalTasks[0]?.route).toBe('desktop_runtime');
    expect(shell.modelLabel).toBe('Elyan Quantum');
    expect(shell.learningLabel).toContain('7 güvenli sinyal');
    expect(shell.retrievalLabel).toBe('3 belge · 19 parça');
    expect(shell.powerCapabilityCount).toBe(42);
    expect(shell.canExecuteAssignedTasks).toBe(true);
  });

  it('fails closed when runtime cannot receive desktop tasks', () => {
    const shell = deriveDesktopTaskShell({
      state: {},
      workspace: {},
      conversations: [],
      runtime: {
        runtimeLifecycleState: 'reconnecting',
        controlPlane: {
          runtimeSession: {
            readiness: { canReceiveTasks: false },
            connection: { status: 'offline' },
          },
        },
      },
      backend: {},
      localModels: {},
    });

    expect(shell.readinessToken).toBe('reconnecting');
    expect(shell.canReceiveTasks).toBe(false);
    expect(shell.readinessDetail).toContain('tekrar denenecek');
  });

  it('keeps backend task status wire-compatible while rendering desktop trace state', () => {
    const shell = deriveDesktopTaskShell({
      state: {},
      workspace: {},
      conversations: [],
      runtime: {
        taskInbox: {
          pendingCount: 0,
          activeCount: 1,
          items: [
            {
              id: 'task-verify',
              title: 'Raporu doğrula',
              status: 'running',
              executionTrace: { status: 'verifying' },
              updatedAt: '2030-05-22T15:32:12Z',
            },
          ],
        },
        controlPlane: {
          runtimeSession: {
            readiness: { canReceiveTasks: true, targetStatus: 'ready' },
            connection: { status: 'online' },
          },
        },
      },
      backend: {},
      localModels: {},
    });

    expect(shell.recentTasks[0]?.status).toBe('running');
    expect(shell.recentTasks[0]?.statusLabel).toBe('doğrulanıyor');
    expect(shell.activeRemoteTaskCount).toBe(1);
  });
});
