import { describe, expect, it } from 'vitest';
import type { BootstrapSnapshot } from '../../src/shared/protocol';
import { desktopRuntimeReady } from '../../src/renderer/lib/data';

describe('renderer data helpers', () => {
  it('treats a live runtime websocket as desktop-ready without requiring backend health truth', () => {
    const snapshot: BootstrapSnapshot = {
      state: {},
      workspace: {},
      conversations: [],
      runtime: {
        runtimeWebsocketConnected: true,
        controlPlane: {
          runtimeSession: {
            readiness: { canReceiveTasks: false },
          },
        },
      },
      backend: {
        health: {
          ok: true,
          data: {
            network: {
              externalClientsCanReachAdvertisedBaseUrl: false,
            },
          },
        },
      },
      localModels: {},
    };

    expect(desktopRuntimeReady(snapshot)).toBe(true);
  });
});
