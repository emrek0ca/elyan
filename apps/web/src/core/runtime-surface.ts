export type RuntimeSurfaceKey = 'local' | 'shared' | 'hosted';

export type RuntimeSurfaceStatus = {
  key: RuntimeSurfaceKey;
  label: string;
  ready: boolean;
  summary: string;
  detail: string;
};

export type RuntimeSurfaceSnapshot = {
  surfaces: Record<RuntimeSurfaceKey, RuntimeSurfaceStatus>;
  nextSteps: string[];
};

type RuntimeSurfaceInput = {
  localModelCount: number;
  searchEnabled: boolean;
  searchAvailable: boolean;
  controlPlaneReady: boolean;
  hostedAuthConfigured: boolean;
  hostedBillingConfigured: boolean;
};

function createSurface(
  key: RuntimeSurfaceKey,
  label: string,
  ready: boolean,
  summary: string,
  detail: string
): RuntimeSurfaceStatus {
  return {
    key,
    label,
    ready,
    summary,
    detail,
  };
}

export function buildRuntimeSurfaceSnapshot(input: RuntimeSurfaceInput): RuntimeSurfaceSnapshot {
  const hostedReady = input.hostedAuthConfigured && input.hostedBillingConfigured;

  return {
    surfaces: {
      local: createSurface(
        'local',
        'Local runtime',
        input.localModelCount > 0,
        input.localModelCount > 0 ? `${input.localModelCount} model source(s) ready` : 'No model source is ready yet',
        input.searchEnabled
          ? input.searchAvailable
            ? 'Optional search is available for live retrieval.'
            : 'Search is enabled but currently offline.'
          : 'Search is disabled in runtime settings.'
      ),
      shared: createSurface(
        'shared',
        'Shared control plane',
        input.controlPlaneReady,
        input.controlPlaneReady ? 'Optional hosted control-plane reachable' : 'Optional hosted control-plane unavailable',
        input.controlPlaneReady
          ? 'Accounts, plans, entitlements, and hosted usage accounting are available when you need them.'
          : 'Local runtime is unaffected. Hosted management stays optional.'
      ),
      hosted: createSurface(
        'hosted',
        'Hosted surface',
        hostedReady,
        hostedReady ? 'Hosted auth and billing wired' : 'Hosted auth or billing not configured',
        hostedReady
          ? 'elyan.dev can expose hosted access with metered accounting.'
          : 'Hosted access stays optional until auth and billing are configured.'
      ),
    },
    nextSteps: [
      input.localModelCount > 0
        ? 'Ask a real question in chat.'
        : 'Start Ollama or provide a cloud key, then ask a real question.',
      input.searchEnabled
        ? input.searchAvailable
          ? 'Search is ready for live retrieval.'
          : 'Search is enabled but offline.'
        : 'Search is disabled in runtime settings.',
      input.controlPlaneReady
        ? 'Use the manage dashboard or `elyan status` to inspect optional hosted state.'
        : 'Ignore hosted state unless you are actively using the shared control plane.',
    ],
  };
}
