import NextAuth from 'next-auth';
import { NextResponse } from 'next/server';
import { assertHostedAuthConfigured, getControlPlaneAuthOptions } from '@/core/control-plane/auth';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

let authHandler: ReturnType<typeof NextAuth> | null = null;
type AuthHandler = ReturnType<typeof NextAuth>;

function getAuthHandler() {
  if (!authHandler) {
    authHandler = NextAuth(getControlPlaneAuthOptions());
  }

  return authHandler;
}

async function guardedAuthHandler(...args: Parameters<AuthHandler>) {
  try {
    assertHostedAuthConfigured();
    return getAuthHandler()(...args);
  } catch (error) {
    const status = error && typeof error === 'object' && 'statusCode' in error ? Number((error as { statusCode: number }).statusCode) || 500 : 500;
    const message = error instanceof Error ? error.message : 'hosted auth is unavailable';
    return NextResponse.json({ ok: false, error: message }, { status });
  }
}

export { guardedAuthHandler as GET, guardedAuthHandler as POST };
