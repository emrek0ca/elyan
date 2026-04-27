import NextAuth from 'next-auth';
import { NextResponse } from 'next/server';
import { getControlPlaneAuthOptions, isHostedAuthConfigured } from '@/core/control-plane/auth';

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
    if (!isHostedAuthConfigured()) {
      return NextResponse.json(
        {
          ok: false,
          error: 'Hosted identity is disabled in local mode',
          code: 'hosted_identity_unavailable',
        },
        { status: 503 }
      );
    }

    return getAuthHandler()(...args);
  } catch (error) {
    const status = error && typeof error === 'object' && 'statusCode' in error ? Number((error as { statusCode: number }).statusCode) || 500 : 500;
    const message = error instanceof Error ? error.message : 'hosted auth is unavailable';
    return NextResponse.json({ ok: false, error: message }, { status });
  }
}

export { guardedAuthHandler as GET, guardedAuthHandler as POST };
