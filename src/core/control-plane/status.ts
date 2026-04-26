import type { ControlPlaneService } from './service';
import {
  buildControlPlaneConnectionSnapshot,
  buildControlPlaneRuntimeSnapshot,
  getControlPlaneService,
  resolveConfiguredControlPlaneStorage,
} from './runtime';
import { buildControlPlaneEvaluationSummary } from './evaluation';
import { getControlPlanePoolStats } from './database';

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
    const database = runtime.storage === 'postgres' ? getControlPlanePoolStats() : undefined;

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
      database,
      evaluationSummary: buildControlPlaneEvaluationSummary([]),
      runtime,
      connection: buildControlPlaneConnectionSnapshot(runtime),
      error: describeError(error),
    };
  }
}
