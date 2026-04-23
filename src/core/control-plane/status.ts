import type { ControlPlaneService } from './service';
import {
  buildControlPlaneConnectionSnapshot,
  buildControlPlaneRuntimeSnapshot,
  getControlPlaneService,
  resolveConfiguredControlPlaneStorage,
} from './runtime';

function describeError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return 'control-plane health check failed';
}

export async function readControlPlaneHealthSnapshot(service?: ControlPlaneService) {
  try {
    const activeService = service ?? getControlPlaneService();
    return await activeService.health();
  } catch (error) {
    const runtime = buildControlPlaneRuntimeSnapshot(resolveConfiguredControlPlaneStorage());

    return {
      ok: false,
      service: 'elyan-control-plane',
      surface: runtime.surface,
      storage: runtime.storage,
      databaseConfigured: runtime.databaseConfigured,
      authConfigured: runtime.authConfigured,
      billingConfigured: runtime.billingConfigured,
      billingMode: runtime.billingMode,
      hostedReady: runtime.hostedReady,
      iyzicoConfigured: runtime.billingConfigured,
      readiness: runtime.readiness,
      runtime,
      connection: buildControlPlaneConnectionSnapshot(runtime),
      error: describeError(error),
    };
  }
}
