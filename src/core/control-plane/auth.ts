import CredentialsProvider from 'next-auth/providers/credentials';
import type { NextAuthOptions } from 'next-auth';
import PostgresAdapter from '@auth/pg-adapter';
import { env } from '@/lib/env';
import { ControlPlaneAuthenticationError, ControlPlaneConfigurationError } from './errors';
import { getControlPlanePool } from './database';
import { getControlPlaneService } from './runtime';
import { normalizeIdentityEmail } from './identity';

type ElyanAuthUser = {
  id: string;
  email: string;
  name: string;
};

function requireAuthConfiguration() {
  if (!env.NEXTAUTH_SECRET) {
    throw new ControlPlaneConfigurationError(
      'NEXTAUTH_SECRET is required to use hosted identity and session handling'
    );
  }

  if (!env.DATABASE_URL) {
    throw new ControlPlaneConfigurationError(
      'DATABASE_URL is required for hosted Auth.js PostgreSQL session storage'
    );
  }
}

export function isHostedAuthConfigured() {
  return Boolean(env.NEXTAUTH_SECRET && env.DATABASE_URL);
}

export function getControlPlaneAuthOptions(): NextAuthOptions {
  requireAuthConfiguration();
  const secureCookies = Boolean(env.NEXTAUTH_URL?.startsWith('https://'));
  const sameSite = secureCookies ? 'none' : 'lax';

  return {
    adapter: PostgresAdapter(getControlPlanePool(env.DATABASE_URL)) as NextAuthOptions['adapter'],
    providers: [
      CredentialsProvider({
        name: 'Elyan account',
        credentials: {
          email: { label: 'Email', type: 'email' },
          password: { label: 'Password', type: 'password' },
        },
        async authorize(credentials) {
          const email = normalizeIdentityEmail(String(credentials?.email ?? ''));
          const password = String(credentials?.password ?? '');

          if (!email || !password) {
            throw new ControlPlaneAuthenticationError('Missing email or password');
          }

          const identity = await getControlPlaneService().authenticateIdentity(email, password);
          if (!identity) {
            return null;
          }

          return {
            id: identity.user.userId,
            email: identity.user.email,
            name: identity.user.displayName,
          } satisfies ElyanAuthUser;
        },
      }),
    ],
    session: {
      strategy: 'jwt',
    },
    cookies: {
      sessionToken: {
        name: secureCookies ? '__Secure-next-auth.session-token' : 'next-auth.session-token',
        options: {
          httpOnly: true,
          sameSite,
          path: '/',
          secure: secureCookies,
        },
      },
      csrfToken: {
        name: secureCookies ? '__Host-next-auth.csrf-token' : 'next-auth.csrf-token',
        options: {
          httpOnly: true,
          sameSite,
          path: '/',
          secure: secureCookies,
        },
      },
      callbackUrl: {
        name: secureCookies ? '__Secure-next-auth.callback-url' : 'next-auth.callback-url',
        options: {
          sameSite,
          path: '/',
          secure: secureCookies,
        },
      },
    },
    secret: env.NEXTAUTH_SECRET,
    callbacks: {
      async jwt({ token, user }) {
        if (user?.email) {
          const identity = await getControlPlaneService().getIdentityByEmail(user.email);
          const account = await getControlPlaneService().getAccount(identity.accountId);
          token.sub = identity.userId;
          token.email = identity.email;
          token.name = identity.name;
          token.accountId = identity.accountId;
          token.ownerType = identity.ownerType;
          token.role = identity.role;
          token.planId = identity.planId;
          token.accountStatus = account.status;
          token.subscriptionStatus = account.subscription.status;
          token.subscriptionSyncState = account.subscription.syncState;
          token.hostedAccess = account.entitlements.hostedAccess;
          token.hostedUsageAccounting = account.entitlements.hostedUsageAccounting;
        }

        return token;
      },
      async session({ session, token }) {
        if (!session.user) {
          return session;
        }

        session.user.id = String(token.sub ?? '');
        session.user.email = typeof token.email === 'string' ? token.email : session.user.email;
        session.user.name = typeof token.name === 'string' ? token.name : session.user.name;
        session.user.accountId = typeof token.accountId === 'string' ? token.accountId : undefined;
        session.user.ownerType = typeof token.ownerType === 'string' ? token.ownerType : undefined;
        session.user.role = typeof token.role === 'string' ? token.role : undefined;
        session.user.planId = typeof token.planId === 'string' ? token.planId : undefined;
        session.user.accountStatus =
          typeof token.accountStatus === 'string' ? token.accountStatus : undefined;
        session.user.subscriptionStatus =
          typeof token.subscriptionStatus === 'string' ? token.subscriptionStatus : undefined;
        session.user.subscriptionSyncState =
          typeof token.subscriptionSyncState === 'string' ? token.subscriptionSyncState : undefined;
        session.user.hostedAccess =
          typeof token.hostedAccess === 'boolean' ? token.hostedAccess : undefined;
        session.user.hostedUsageAccounting =
          typeof token.hostedUsageAccounting === 'boolean' ? token.hostedUsageAccounting : undefined;
        return session;
      },
    },
    pages: {
      signIn: '/auth',
    },
    useSecureCookies: secureCookies,
  };
}

export function assertHostedAuthConfigured() {
  requireAuthConfiguration();
}
