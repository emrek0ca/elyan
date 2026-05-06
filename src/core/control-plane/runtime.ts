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
  databaseConfigured: boolean;
  authConfigured: boolean;
  billingConfigured: boolean;
  billingMode: ControlPlaneBillingMode;
  callbackUrl: string;
  apiBaseUrl: string;
  hostedReady: boolean;
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

export function buildControlPlaneRuntimeSnapshot(storage: 'file' | 'postgres'): ControlPlaneRuntimeSnapshot {
  const billingMode: ControlPlaneBillingMode = env.IYZICO_ENV;
  const databaseConfigured = Boolean(env.DATABASE_URL);
  const authConfigured = Boolean(env.NEXTAUTH_SECRET);
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

  return {
    surface: 'shared-vps',
    storage,
    databaseConfigured,
    authConfigured,
    billingConfigured,
    billingMode,
    callbackUrl,
    apiBaseUrl,
    hostedReady: readiness.hosted,
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
