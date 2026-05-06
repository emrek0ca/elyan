/**
 * Control-plane health snapshot wrapper used by /api/control-plane/health.
 * Layer: status + control-plane. Critical diagnostics; no business logic should live here.
 */
import type { ControlPlaneService } from './service';
import {
  buildControlPlaneConnectionSnapshot,
  buildControlPlaneRuntimeSnapshot,
  getControlPlaneService,
  resolveConfiguredControlPlaneStorage,
} from './runtime';
import { buildControlPlaneEvaluationSummary } from './evaluation';
import { buildControlPlaneDatabaseHealthSnapshot, getControlPlanePoolStats } from './database';
import { getRuntimeVersionInfo } from '@/core/runtime-version';

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
    const database = await buildControlPlaneDatabaseHealthSnapshot(runtime.storage, getControlPlanePoolStats());
    const version = getRuntimeVersionInfo();

    return {
      ok: false,
      service: 'elyan-control-plane',
      version: version.version,
      releaseTag: version.releaseTag,
      buildSha: version.buildSha,
      surface: runtime.surface,
      storage: runtime.storage,
      activeDatabaseMode: runtime.activeDatabaseMode,
      databaseConfigured: runtime.databaseConfigured,
      postgresReachable: database.postgresReachable,
      migrationsApplied: database.migrationsApplied,
      schemaReady: database.schemaReady,
      authConfigured: runtime.authConfigured,
      billingConfigured: runtime.billingConfigured,
      billingMode: runtime.billingMode,
      hostedReady: runtime.hostedReady,
      missingEnvKeys: runtime.missingEnvKeys,
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
