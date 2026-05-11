import { randomUUID } from "node:crypto";
import { and, eq, isNull, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { devices, sessions, subscriptions, users } from "../../db/schema.js";
import { hashSecret, verifySecret } from "../../lib/auth-crypto.js";
import { calculateRefreshTokenExpiry, signUserAccessToken, signUserRefreshToken } from "../../lib/auth-tokens.js";
import { badRequest, conflict, unauthorized } from "../../lib/errors.js";
import type { UserAuthTokenPayload } from "../../types/auth.js";

type SessionContext = {
  ipAddress?: string;
  userAgent?: string;
};

type PublicUser = {
  id: string;
  email: string;
  displayName: string | null;
};

function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

async function createUserSession(
  app: FastifyInstance,
  user: PublicUser,
  context: SessionContext,
): Promise<{
  accessToken: string;
  refreshToken: string;
  accessTokenTtl: string;
  refreshTokenTtl: string;
}> {
  const sessionId = randomUUID();
  const tokenPayload: UserAuthTokenPayload = {
    kind: "user",
    sub: user.id,
    sessionId,
    email: user.email,
  };
  const accessToken = await signUserAccessToken(app, tokenPayload);
  const refreshToken = await signUserRefreshToken(app, tokenPayload);
  const refreshTokenHash = await hashSecret(refreshToken);

  await app.db.insert(sessions).values({
    id: sessionId,
    userId: user.id,
    refreshTokenHash,
    expiresAt: calculateRefreshTokenExpiry(app.config.REFRESH_TOKEN_TTL),
    ipAddress: context.ipAddress,
    userAgent: context.userAgent,
  });

  return {
    accessToken,
    refreshToken,
    accessTokenTtl: app.config.ACCESS_TOKEN_TTL,
    refreshTokenTtl: app.config.REFRESH_TOKEN_TTL,
  };
}

async function getSubscription(app: FastifyInstance, userId: string) {
  const rows = await app.db.select().from(subscriptions).where(eq(subscriptions.userId, userId)).limit(1);
  return rows[0] ?? null;
}

export async function registerUser(
  app: FastifyInstance,
  input: { email: string; password: string; displayName?: string },
  context: SessionContext,
) {
  const email = normalizeEmail(input.email);
  const existing = await app.db.select({ id: users.id }).from(users).where(eq(users.email, email)).limit(1);

  if (existing[0]) {
    throw conflict("Email is already registered");
  }

  const passwordHash = await hashSecret(input.password);
  const insertedUsers = await app.db
    .insert(users)
    .values({
      email,
      passwordHash,
      displayName: input.displayName?.trim(),
    })
    .returning({
      id: users.id,
      email: users.email,
      displayName: users.displayName,
    });

  const user = insertedUsers[0];

  if (!user) {
    throw badRequest("Unable to create user");
  }

  await app.db.insert(subscriptions).values({
    userId: user.id,
  });

  const tokens = await createUserSession(app, user, context);
  const subscription = await getSubscription(app, user.id);

  return {
    user,
    subscription,
    tokens,
  };
}

export async function loginUser(
  app: FastifyInstance,
  input: { email: string; password: string },
  context: SessionContext,
) {
  const email = normalizeEmail(input.email);
  const rows = await app.db
    .select({
      id: users.id,
      email: users.email,
      displayName: users.displayName,
      passwordHash: users.passwordHash,
    })
    .from(users)
    .where(eq(users.email, email))
    .limit(1);

  const user = rows[0];

  if (!user || !(await verifySecret(input.password, user.passwordHash))) {
    throw unauthorized("Invalid email or password");
  }

  const tokens = await createUserSession(
    app,
    {
      id: user.id,
      email: user.email,
      displayName: user.displayName,
    },
    context,
  );
  const subscription = await getSubscription(app, user.id);

  return {
    user: {
      id: user.id,
      email: user.email,
      displayName: user.displayName,
    },
    subscription,
    tokens,
  };
}

export async function refreshUserSession(app: FastifyInstance, refreshToken: string, context: SessionContext) {
  const payload = (await app.jwt.verify(refreshToken)) as UserAuthTokenPayload;

  if (payload.kind !== "user") {
    throw unauthorized("Refresh token must belong to a user session");
  }

  const rows = await app.db
    .select({
      sessionId: sessions.id,
      userId: sessions.userId,
      refreshTokenHash: sessions.refreshTokenHash,
      expiresAt: sessions.expiresAt,
      revokedAt: sessions.revokedAt,
      email: users.email,
      displayName: users.displayName,
    })
    .from(sessions)
    .innerJoin(users, eq(users.id, sessions.userId))
    .where(and(eq(sessions.id, payload.sessionId), eq(sessions.userId, payload.sub)))
    .limit(1);

  const session = rows[0];

  if (!session) {
    throw unauthorized("Session not found");
  }

  if (session.revokedAt || session.expiresAt.getTime() <= Date.now()) {
    throw unauthorized("Refresh token is no longer valid");
  }

  const refreshTokenMatches = await verifySecret(refreshToken, session.refreshTokenHash);

  if (!refreshTokenMatches) {
    throw unauthorized("Refresh token does not match the active session");
  }

  await app.db
    .update(sessions)
    .set({
      revokedAt: new Date(),
      lastUsedAt: new Date(),
    })
    .where(eq(sessions.id, session.sessionId));

  const tokens = await createUserSession(
    app,
    {
      id: session.userId,
      email: session.email,
      displayName: session.displayName,
    },
    context,
  );
  const subscription = await getSubscription(app, session.userId);

  return {
    user: {
      id: session.userId,
      email: session.email,
      displayName: session.displayName,
    },
    subscription,
    tokens,
  };
}

export async function revokeUserSession(app: FastifyInstance, sessionId: string): Promise<void> {
  await app.db
    .update(sessions)
    .set({
      revokedAt: new Date(),
      lastUsedAt: new Date(),
    })
    .where(and(eq(sessions.id, sessionId), isNull(sessions.revokedAt)));
}

export async function getCurrentUserProfile(app: FastifyInstance, userId: string) {
  const userRows = await app.db
    .select({
      id: users.id,
      email: users.email,
      displayName: users.displayName,
      createdAt: users.createdAt,
    })
    .from(users)
    .where(eq(users.id, userId))
    .limit(1);

  const user = userRows[0];

  if (!user) {
    throw unauthorized("User not found");
  }

  const subscription = await getSubscription(app, userId);
  const runtimeCounts = await app.db
    .select({
      desktopCount: sql<number>`count(*)`,
    })
    .from(devices)
    .where(and(eq(devices.userId, userId), eq(devices.type, "desktop")));

  return {
    user,
    subscription,
    metrics: {
      desktopCount: Number(runtimeCounts[0]?.desktopCount ?? 0),
    },
  };
}
