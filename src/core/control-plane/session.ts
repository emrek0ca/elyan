import type { NextRequest } from 'next/server';
import { getToken } from 'next-auth/jwt';
import { env } from '@/lib/env';
import { ControlPlaneAuthenticationError, ControlPlaneConfigurationError } from './errors';

export type ControlPlaneSessionToken = {
  sub?: string;
  email?: string;
  name?: string;
  accountId?: string;
  ownerType?: string;
  role?: string;
  planId?: string;
};

function requireSessionConfiguration() {
  if (!env.NEXTAUTH_SECRET || !env.DATABASE_URL) {
    throw new ControlPlaneConfigurationError(
      'NEXTAUTH_SECRET and DATABASE_URL are required for hosted control-plane routes'
    );
  }
}

export function isControlPlaneSessionConfigured() {
  return Boolean(env.NEXTAUTH_SECRET && env.DATABASE_URL);
}

export async function getControlPlaneSessionToken(request: NextRequest) {
  requireSessionConfiguration();
  const token = await getToken({ req: request, secret: env.NEXTAUTH_SECRET });
  if (!token?.sub && !token?.email) {
    return null;
  }

  return {
    sub: typeof token.sub === 'string' ? token.sub : undefined,
    email: typeof token.email === 'string' ? token.email : undefined,
    name: typeof token.name === 'string' ? token.name : undefined,
    accountId: typeof token.accountId === 'string' ? token.accountId : undefined,
    ownerType: typeof token.ownerType === 'string' ? token.ownerType : undefined,
    role: typeof token.role === 'string' ? token.role : undefined,
    planId: typeof token.planId === 'string' ? token.planId : undefined,
  } satisfies ControlPlaneSessionToken;
}

export async function requireControlPlaneSession(request: NextRequest) {
  const token = await getControlPlaneSessionToken(request);

  if (!token?.sub || !token.accountId) {
    throw new ControlPlaneAuthenticationError('Control-plane session is required');
  }

  return token;
}

export function assertControlPlaneAccountAccess(token: ControlPlaneSessionToken, accountId: string) {
  if (!token.accountId || token.accountId !== accountId) {
    throw new ControlPlaneAuthenticationError('Session is not bound to the requested account');
  }
}
