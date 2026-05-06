/**
 * Hosted runtime snapshot construction and storage selection.
 * Layer: runtime + control-plane. Critical for deciding postgres vs file-backed mode and reporting readiness.
 */
import path from 'path';
import { env } from '@/lib/env';
import { ControlPlaneService } from './service';

export type ControlPlaneBillingMode = 'sandbox' | 'production';

export type ControlPlaneRuntimeReadiness = {
  database: boolean;
  auth: boolean;
  billing: boolean;
  hosted: boolean;
};

export type ControlPlaneRuntimeSnapshot = {
  surface: 'shared-vps';
  storage: 'file' | 'postgres';
  activeDatabaseMode: 'file_backed' | 'postgres';
  databaseConfigured: boolean;
  authConfigured: boolean;
  billingConfigured: boolean;
  billingMode: ControlPlaneBillingMode;
  callbackUrl: string;
  apiBaseUrl: string;
  hostedReady: boolean;
  missingEnvKeys: string[];
  readiness: ControlPlaneRuntimeReadiness;
};

export type ControlPlaneConnectionSnapshot = {
  storage: 'file' | 'postgres';
  hostedReady: boolean;
  callbackUrl: string;
  apiBaseUrl: string;
  billingMode: ControlPlaneBillingMode;
};

export function resolveConfiguredControlPlaneStorage(): 'file' | 'postgres' {
  if (process.env.NODE_ENV === 'production') {
    return 'postgres';
  }

  return env.DATABASE_URL ? 'postgres' : 'file';
}

export function buildControlPlaneConnectionSnapshot(
  runtime: ControlPlaneRuntimeSnapshot
): ControlPlaneConnectionSnapshot {
  return {
    storage: runtime.storage,
    hostedReady: runtime.hostedReady,
    callbackUrl: runtime.callbackUrl,
    apiBaseUrl: runtime.apiBaseUrl,
    billingMode: runtime.billingMode,
  };
}

function collectMissingHostedEnvKeys(billingMode: ControlPlaneBillingMode) {
  const missing = new Set<string>();

  if (!env.DATABASE_URL) {
    missing.add('DATABASE_URL');
  }

  if (!env.NEXTAUTH_URL) {
    missing.add('NEXTAUTH_URL');
  }

  if (!env.NEXTAUTH_SECRET && !env.AUTH_SECRET) {
    missing.add('NEXTAUTH_SECRET');
  }

  if (!env.SEARXNG_URL) {
    missing.add('SEARXNG_URL');
  }

  if (!env.OLLAMA_URL) {
    missing.add('OLLAMA_URL');
  }

  const billingKeys =
    billingMode === 'sandbox'
      ? ['IYZICO_SANDBOX_API_KEY', 'IYZICO_SANDBOX_SECRET_KEY', 'IYZICO_SANDBOX_MERCHANT_ID']
      : ['IYZICO_API_KEY', 'IYZICO_SECRET_KEY', 'IYZICO_MERCHANT_ID'];

  for (const key of billingKeys) {
    if (!env[key as keyof typeof env]) {
      missing.add(key);
    }
  }

  return Array.from(missing);
}

export function buildControlPlaneRuntimeSnapshot(storage: 'file' | 'postgres'): ControlPlaneRuntimeSnapshot {
  const billingMode: ControlPlaneBillingMode = env.IYZICO_ENV;
  const databaseConfigured = Boolean(env.DATABASE_URL);
  const authConfigured = Boolean(env.NEXTAUTH_SECRET || env.AUTH_SECRET);
  const billingConfigured = Boolean(
    billingMode === 'sandbox'
      ? env.IYZICO_SANDBOX_API_KEY && env.IYZICO_SANDBOX_SECRET_KEY && env.IYZICO_SANDBOX_MERCHANT_ID
      : env.IYZICO_API_KEY && env.IYZICO_SECRET_KEY && env.IYZICO_MERCHANT_ID
  );
  const apiBaseUrl =
    billingMode === 'sandbox' ? env.IYZICO_SANDBOX_API_BASE_URL : env.IYZICO_BASE_URL;
  const callbackUrl = `${env.NEXTAUTH_URL ?? 'http://localhost:3000'}/api/control-plane/billing/iyzico/webhook`;
  const readiness: ControlPlaneRuntimeReadiness = {
    database: databaseConfigured,
    auth: authConfigured,
    billing: billingConfigured,
    hosted: databaseConfigured && authConfigured && billingConfigured,
  };
  const activeDatabaseMode = storage === 'postgres' ? 'postgres' : 'file_backed';

  return {
    surface: 'shared-vps',
    storage,
    activeDatabaseMode,
    databaseConfigured,
    authConfigured,
    billingConfigured,
    billingMode,
    callbackUrl,
    apiBaseUrl,
    hostedReady: readiness.hosted,
    missingEnvKeys: collectMissingHostedEnvKeys(billingMode),
    readiness,
  };
}

let singleton: ControlPlaneService | null = null;

export function getControlPlaneService() {
  if (!singleton) {
    singleton = ControlPlaneService.create(
      path.resolve(process.cwd(), env.ELYAN_CONTROL_PLANE_STATE_PATH),
      env.DATABASE_URL,
      { allowFileFallback: process.env.NODE_ENV !== 'production' }
    );
  }

  return singleton;
}
