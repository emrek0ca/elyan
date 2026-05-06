/**
 * NextAuth route handler for hosted control-plane authentication.
 * Layer: auth API. Critical entrypoint for login, session cookies, and CSRF-backed credentials flow.
 */
import NextAuth from 'next-auth';
import { NextResponse } from 'next/server';
import { getControlPlaneAuthOptions, isHostedAuthConfigured } from '@/core/control-plane/auth';
import { createApiErrorResponse, normalizeApiError } from '@/core/http/api-errors';

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
    const normalized = normalizeApiError(error, {
      status: 500,
      code: 'hosted_auth_unavailable',
      message: 'hosted auth is unavailable',
    });
    return createApiErrorResponse(normalized);
  }
}

export { guardedAuthHandler as GET, guardedAuthHandler as POST };
