import { randomUUID } from "node:crypto";
import { and, eq, isNull, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { createRemoteJWKSet, jwtVerify, type JWTPayload } from "jose";
import {
  aiProviderCredentials,
  aiProviderInvocations,
  auditLogs,
  authIdentities,
  billingCheckoutSessions,
  billingCreditLedger,
  billingEntitlementEvents,
  billingProfiles,
  billingStoreTransactions,
  billingWebhookEvents,
  brainMemoryEpisodes,
  brainMemoryFacts,
  brainMemoryLinks,
  brainMemoryRuns,
  chatSessions,
  datasetManifests,
  devices,
  integrationConnections,
  knowledgeChunks,
  knowledgeDocuments,
  learningEvents,
  mcpServers,
  modelArtifacts,
  oauthStates,
  operatorRuns,
  pairSessions,
  realtimeEvents,
  runtimeConnections,
  sessions,
  subscriptions,
  tasks,
  trainingJobs,
  usageRecords,
  userAvatars,
  users,
  worldSignals,
} from "../../db/schema.js";
import { hashSecret, verifySecret } from "../../lib/auth-crypto.js";
import { calculateRefreshTokenExpiry, signUserAccessToken, signUserRefreshToken } from "../../lib/auth-tokens.js";
import { AppError, badRequest, conflict, notFound, unauthorized } from "../../lib/errors.js";
import type { UserAuthTokenPayload } from "../../types/auth.js";
import { createAuditLog } from "../audit/service.js";
import {
  buildTrialSubscriptionSeed,
  getBillingSummary,
  shapePublicUsageSnapshot,
} from "../billing/service.js";
import { shapeSubscriptionTruth } from "../billing/subscription-truth.js";
import { getBrainProfile, shapePublicBrainProfile } from "../brain/service.js";
import {
  ensureUserIdentity,
  getTrialQuotaPolicy,
} from "../quota/service.js";
import {
  buildOtpAuthUri,
  createTotpSecret,
  decryptTotpSecret,
  encryptTotpSecret,
  verifyTotpCode,
} from "./totp.js";

type SessionContext = {
  ipAddress?: string;
  userAgent?: string;
};

type PublicUser = {
  id: string;
  email: string;
  displayName: string | null;
};

type AvatarPayload = {
  hasAvatar: boolean;
  avatarVersion: number;
};

type SocialAuthProvider = "google" | "apple";

type LegalAcceptanceInput = {
  legalAcceptance?: {
    termsAccepted?: boolean;
    privacyAccepted?: boolean;
  };
  termsAccepted?: boolean;
  privacyAccepted?: boolean;
};

type VerifiedSocialIdentity = {
  provider: SocialAuthProvider;
  subject: string;
  email: string;
  displayName: string | null;
  claims: JWTPayload;
};

const googleJwks = createRemoteJWKSet(
  new URL("https://www.googleapis.com/oauth2/v3/certs"),
);
const appleJwks = createRemoteJWKSet(
  new URL("https://appleid.apple.com/auth/keys"),
);

function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

function hasRequiredLegalAcceptance(input?: LegalAcceptanceInput): boolean {
  if (!input) {
    return false;
  }

  const nested = input.legalAcceptance;
  return (
    (nested?.termsAccepted === true || input.termsAccepted === true) &&
    (nested?.privacyAccepted === true || input.privacyAccepted === true)
  );
}

function assertRequiredLegalAcceptance(input?: LegalAcceptanceInput) {
  if (!hasRequiredLegalAcceptance(input)) {
    throw badRequest("Kayıt için kullanım koşulları ve gizlilik kabul edilmeli.", {
      reason: "legal_acceptance_required",
    });
  }
}

async function ensureUserSubscriptionSeed(app: FastifyInstance, userId: string) {
  const existingSubscription = await getSubscription(app, userId);
  if (existingSubscription) {
    return existingSubscription;
  }

  await app.db.insert(subscriptions).values({
    userId,
    ...buildTrialSubscriptionSeed(),
  });

  return getSubscription(app, userId);
}

async function reviveSoftDeletedUser(
  app: FastifyInstance,
  input: {
    userId: string;
    email: string;
    passwordHash?: string;
    displayName?: string | null;
  },
) {
  const nextDisplayName = normalizeDisplayName(input.displayName);
  const updatedRows = await app.db
    .update(users)
    .set({
      email: normalizeEmail(input.email),
      ...(input.passwordHash ? { passwordHash: input.passwordHash } : {}),
      ...(nextDisplayName !== null ? { displayName: nextDisplayName } : {}),
      deletedAt: null,
      updatedAt: new Date(),
    })
    .where(eq(users.id, input.userId))
    .returning({
      id: users.id,
      email: users.email,
      displayName: users.displayName,
      deletedAt: users.deletedAt,
    });

  const user = updatedRows[0];
  if (!user) {
    throw badRequest("Bilgileri kontrol et.");
  }

  await ensureUserSubscriptionSeed(app, user.id);
  await ensureUserIdentity(app.db, {
    userId: user.id,
    email: user.email,
  });

  return user;
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

async function getUserAvatarTruth(app: FastifyInstance, userId: string): Promise<AvatarPayload> {
  const rows = await app.db
    .select({
      version: userAvatars.version,
    })
    .from(userAvatars)
    .where(eq(userAvatars.userId, userId))
    .limit(1);
  return shapeAvatarTruth(rows[0] ?? null);
}

function normalizeDisplayName(value: string | null | undefined): string | null {
  const trimmed = value?.trim() ?? "";
  return trimmed.length === 0 ? null : trimmed;
}

function shapeAvatarTruth(row: { version: number } | null | undefined): AvatarPayload {
  return {
    hasAvatar: Boolean(row),
    avatarVersion: Number(row?.version ?? 0),
  };
}

function decodeAvatarBase64(input: string): Buffer {
  const normalized = input.replace(/\s+/g, "");
  const buffer = Buffer.from(normalized, "base64");
  if (!buffer.length) {
    throw badRequest("Geçerli bir görsel yükle.");
  }
  return buffer;
}

function assertAvatarPayload(buffer: Buffer, mimeType: string): void {
  const maxBytes = 1_500_000;
  if (buffer.byteLength > maxBytes) {
    throw badRequest("Profil fotoğrafı çok büyük.");
  }
  if (mimeType === "image/png" && buffer.subarray(0, 8).compare(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])) !== 0) {
    throw badRequest("PNG görseli geçerli değil.");
  }
  if (mimeType === "image/jpeg" && !(buffer[0] === 0xff && buffer[1] === 0xd8)) {
    throw badRequest("JPEG görseli geçerli değil.");
  }
  if (mimeType === "image/webp" && buffer.subarray(0, 4).toString("ascii") !== "RIFF") {
    throw badRequest("WEBP görseli geçerli değil.");
  }
}

function syntheticEmail(provider: SocialAuthProvider, subject: string): string {
  const safeSubject = subject.trim().toLowerCase().replace(/[^a-z0-9]+/g, ".");
  return `${provider}.${safeSubject || randomUUID()}@elyan.social`;
}

function readJwtString(claims: JWTPayload, keys: string[]): string | null {
  for (const key of keys) {
    const value = claims[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
}

function socialAuthAudiences(app: FastifyInstance, provider: SocialAuthProvider): string[] {
  const values =
    provider === "google"
      ? [app.config.GOOGLE_CLIENT_ID, app.config.GOOGLE_SERVER_CLIENT_ID]
      : [app.config.APPLE_CLIENT_ID, app.config.APPLE_SERVICE_ID];
  return values.map((value) => value.trim()).filter((value) => value.length > 0);
}

async function verifySocialIdentityToken(
  app: FastifyInstance,
  provider: SocialAuthProvider,
  idToken: string,
): Promise<VerifiedSocialIdentity> {
  const audiences = socialAuthAudiences(app, provider);
  if (audiences.length === 0) {
    throw badRequest("Bilgileri kontrol et.");
  }

  let verification;
  try {
    verification =
      provider === "google"
        ? await jwtVerify(idToken, googleJwks, {
            issuer: ["https://accounts.google.com", "accounts.google.com"],
            audience: audiences,
          })
        : await jwtVerify(idToken, appleJwks, {
            issuer: "https://appleid.apple.com",
            audience: audiences,
          });
  } catch (err: unknown) {
    app.log.warn({ err, provider }, "Social identity token verification failed");
    throw unauthorized("Bilgileri kontrol et.");
  }

  const claims = verification.payload;
  const subject = readJwtString(claims, ["sub"]);
  if (!subject) {
    throw unauthorized(`${provider} sign-in token did not include a subject`);
  }

  const emailFromToken = readJwtString(claims, ["email"]);
  const displayNameFromToken = readJwtString(claims, ["name"]);

  return {
    provider,
    subject,
    email: emailFromToken ?? syntheticEmail(provider, subject),
    displayName: displayNameFromToken,
    claims,
  };
}

async function getOrCreateSocialUser(
  app: FastifyInstance,
  identity: VerifiedSocialIdentity,
  fallbackEmail?: string,
  fallbackDisplayName?: string,
  legalAcceptance?: LegalAcceptanceInput,
) {
  const existingIdentityRows = await app.db
    .select({
      userId: authIdentities.userId,
      identityId: authIdentities.id,
      email: authIdentities.email,
      displayName: authIdentities.displayName,
      userEmail: users.email,
      userDisplayName: users.displayName,
      deletedAt: users.deletedAt,
    })
    .from(authIdentities)
    .innerJoin(users, eq(users.id, authIdentities.userId))
    .where(
      and(
        eq(authIdentities.provider, identity.provider),
        eq(authIdentities.providerSubject, identity.subject),
      ),
    )
    .limit(1);

  const existingIdentity = existingIdentityRows[0];
  if (existingIdentity) {
    if (existingIdentity.deletedAt) {
      assertRequiredLegalAcceptance(legalAcceptance);
    }

    const user =
      existingIdentity.deletedAt
        ? await reviveSoftDeletedUser(app, {
            userId: existingIdentity.userId,
            email: existingIdentity.userEmail,
            displayName:
              normalizeDisplayName(identity.displayName) ??
              normalizeDisplayName(fallbackDisplayName) ??
              existingIdentity.userDisplayName,
          })
        : {
            id: existingIdentity.userId,
            email: existingIdentity.userEmail,
            displayName: existingIdentity.userDisplayName,
          };

    const nextDisplayName =
      normalizeDisplayName(user.displayName) ??
      normalizeDisplayName(identity.displayName) ??
      normalizeDisplayName(fallbackDisplayName);

    if (nextDisplayName && nextDisplayName !== user.displayName) {
      await app.db
        .update(users)
        .set({
          displayName: nextDisplayName,
          updatedAt: new Date(),
        })
        .where(eq(users.id, user.id));
      user.displayName = nextDisplayName;
    }

    await app.db
      .update(authIdentities)
      .set({
        email: normalizeEmail(identity.email ?? fallbackEmail ?? user.email),
        displayName: normalizeDisplayName(identity.displayName ?? fallbackDisplayName),
        metadata: identity.claims,
        updatedAt: new Date(),
      })
      .where(eq(authIdentities.id, existingIdentity.identityId));

    await ensureUserIdentity(app.db, {
      userId: user.id,
      email: user.email,
    });

    return user;
  }

  const normalizedEmail = normalizeEmail(identity.email ?? fallbackEmail ?? syntheticEmail(identity.provider, identity.subject));
  const normalizedDisplayName =
    normalizeDisplayName(identity.displayName) ??
    normalizeDisplayName(fallbackDisplayName) ??
    "Elyan User";

  const existingUserRows = await app.db
    .select({
      id: users.id,
      email: users.email,
      displayName: users.displayName,
      deletedAt: users.deletedAt,
    })
    .from(users)
    .where(eq(users.email, normalizedEmail))
    .limit(1);

  let user = existingUserRows[0];
  if (!user) {
    assertRequiredLegalAcceptance(legalAcceptance);
    const passwordHash = await hashSecret(randomUUID());
    const insertedUsers = await app.db
      .insert(users)
      .values({
        email: normalizedEmail,
        passwordHash,
        displayName: normalizedDisplayName,
      })
      .returning({
        id: users.id,
        email: users.email,
        displayName: users.displayName,
        deletedAt: users.deletedAt,
      });

    user = insertedUsers[0];
    if (!user) {
      throw badRequest("Bilgileri kontrol et.");
    }

    await ensureUserSubscriptionSeed(app, user.id);
    await ensureUserIdentity(app.db, {
      userId: user.id,
      email: user.email,
    });
  } else if (user.deletedAt) {
    assertRequiredLegalAcceptance(legalAcceptance);
    user = await reviveSoftDeletedUser(app, {
      userId: user.id,
      email: normalizedEmail,
      displayName: normalizedDisplayName,
    });
  } else if (!normalizeDisplayName(user.displayName) && normalizedDisplayName) {
    await app.db
      .update(users)
      .set({
        displayName: normalizedDisplayName,
        updatedAt: new Date(),
      })
      .where(eq(users.id, user.id));
    user.displayName = normalizedDisplayName;
  }

  await ensureUserIdentity(app.db, {
    userId: user.id,
    email: user.email,
  });

  await app.db.insert(authIdentities).values({
    userId: user.id,
    provider: identity.provider,
    providerSubject: identity.subject,
    email: normalizedEmail,
    displayName: normalizedDisplayName,
    metadata: identity.claims,
  });

  return user;
}

async function loginWithSocialProvider(
  app: FastifyInstance,
  provider: SocialAuthProvider,
  input: {
    idToken: string;
    email?: string;
    displayName?: string;
    authorizationCode?: string;
  } & LegalAcceptanceInput,
  context: SessionContext,
  verifier: (app: FastifyInstance, provider: SocialAuthProvider, idToken: string) => Promise<VerifiedSocialIdentity> = verifySocialIdentityToken,
) {
  const identity = await verifier(app, provider, input.idToken);
  const user = await getOrCreateSocialUser(
    app,
    identity,
    input.email,
    input.displayName,
    input,
  );
  const tokens = await createUserSession(app, user, context);
  const [subscription, avatar] = await Promise.all([
    getSubscription(app, user.id),
    getUserAvatarTruth(app, user.id),
  ]);

  return {
    user: {
      ...user,
      ...avatar,
    },
    subscription: shapeSubscriptionTruth(subscription),
    tokens,
  };
}

export async function registerUser(
  app: FastifyInstance,
  input: { email: string; password: string; displayName?: string } & LegalAcceptanceInput,
  context: SessionContext,
) {
  assertRequiredLegalAcceptance(input);
  const email = normalizeEmail(input.email);
  const existing = await app.db
    .select({
      id: users.id,
      deletedAt: users.deletedAt,
    })
    .from(users)
    .where(eq(users.email, email))
    .limit(1);

  if (existing[0] && !existing[0].deletedAt) {
    throw conflict("Bilgileri kontrol et.");
  }

  const passwordHash = await hashSecret(input.password);
  const user =
    existing[0]?.deletedAt
      ? await reviveSoftDeletedUser(app, {
          userId: existing[0].id,
          email,
          passwordHash,
          displayName: input.displayName?.trim(),
        })
      : (
          await app.db
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
              deletedAt: users.deletedAt,
            })
        )[0];

  if (!user) {
    throw badRequest("Bilgileri kontrol et.");
  }

  await ensureUserSubscriptionSeed(app, user.id);
  await ensureUserIdentity(app.db, {
    userId: user.id,
    email: user.email,
  });

  const tokens = await createUserSession(app, user, context);
  const subscription = await getSubscription(app, user.id);
  const avatar = await getUserAvatarTruth(app, user.id);

  return {
    user: {
      ...user,
      ...avatar,
    },
    subscription: shapeSubscriptionTruth(subscription),
    tokens,
  };
}

export async function loginUser(
  app: FastifyInstance,
  input: { email: string; password: string; twoFactorCode?: string },
  context: SessionContext,
) {
  const email = normalizeEmail(input.email);
  const rows = await app.db
    .select({
      id: users.id,
      email: users.email,
      displayName: users.displayName,
      passwordHash: users.passwordHash,
      twoFactorEnabled: users.twoFactorEnabled,
      twoFactorSecretEncrypted: users.twoFactorSecretEncrypted,
      deletedAt: users.deletedAt,
    })
    .from(users)
    .where(eq(users.email, email))
    .limit(1);

  const user = rows[0];

  if (!user || user.deletedAt || !(await verifySecret(input.password, user.passwordHash))) {
    throw unauthorized("Şifre yanlış.");
  }

  if (user.twoFactorEnabled) {
    if (!user.twoFactorSecretEncrypted) {
      throw new AppError(409, "two_factor_misconfigured", "2FA yapılandırması tamamlanmamış.");
    }
    if (!input.twoFactorCode) {
      throw new AppError(401, "two_factor_required", "İki faktörlü doğrulama kodu gerekli.");
    }
    const secret = decryptTotpSecret(user.twoFactorSecretEncrypted, app.config.JWT_SECRET);
    if (!verifyTotpCode({ secret, code: input.twoFactorCode })) {
      throw new AppError(401, "two_factor_invalid", "2FA kodu yanlış.");
    }
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
  const [subscription, avatar] = await Promise.all([
    getSubscription(app, user.id),
    getUserAvatarTruth(app, user.id),
  ]);

  return {
    user: {
      id: user.id,
      email: user.email,
      displayName: user.displayName,
      ...avatar,
    },
    subscription: shapeSubscriptionTruth(subscription),
    tokens,
  };
}

export async function loginWithGoogle(
  app: FastifyInstance,
  input: {
    idToken: string;
    email?: string;
    displayName?: string;
    authorizationCode?: string;
  } & LegalAcceptanceInput,
  context: SessionContext,
  verifier?: (app: FastifyInstance, provider: SocialAuthProvider, idToken: string) => Promise<VerifiedSocialIdentity>,
) {
  return loginWithSocialProvider(app, "google", input, context, verifier);
}

export async function loginWithApple(
  app: FastifyInstance,
  input: {
    idToken: string;
    email?: string;
    displayName?: string;
    authorizationCode?: string;
  } & LegalAcceptanceInput,
  context: SessionContext,
  verifier?: (app: FastifyInstance, provider: SocialAuthProvider, idToken: string) => Promise<VerifiedSocialIdentity>,
) {
  return loginWithSocialProvider(app, "apple", input, context, verifier);
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
      deletedAt: users.deletedAt,
    })
    .from(sessions)
    .innerJoin(users, eq(users.id, sessions.userId))
    .where(and(eq(sessions.id, payload.sessionId), eq(sessions.userId, payload.sub)))
    .limit(1);

  const session = rows[0];

  if (!session) {
    throw unauthorized("Bilgileri kontrol et.");
  }

  if (session.deletedAt) {
    throw unauthorized("Bilgileri kontrol et.");
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
  const [subscription, avatar] = await Promise.all([
    getSubscription(app, session.userId),
    getUserAvatarTruth(app, session.userId),
  ]);

  return {
    user: {
      id: session.userId,
      email: session.email,
      displayName: session.displayName,
      ...avatar,
    },
    subscription: shapeSubscriptionTruth(subscription),
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

export async function deleteCurrentUserAccount(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId: string;
    ipAddress?: string;
    userAgent?: string;
    requestId?: string;
  },
) {
  const userRows = await app.db
    .select({
      id: users.id,
      email: users.email,
      deletedAt: users.deletedAt,
    })
    .from(users)
    .where(eq(users.id, input.userId))
    .limit(1);
  const user = userRows[0];
  if (!user || user.deletedAt) {
    throw unauthorized("Bilgileri kontrol et.");
  }

  const now = new Date();
  const deletedPasswordHash = await hashSecret(randomUUID());
  const runInTransaction = async <T>(
    work: (tx: typeof app.db) => Promise<T>,
  ): Promise<T> => {
    if (typeof app.db.transaction === "function") {
      return app.db.transaction(work);
    }
    return work(app.db);
  };

  await runInTransaction(async (tx) => {
    await tx
      .update(sessions)
      .set({
        revokedAt: now,
        lastUsedAt: now,
      })
      .where(eq(sessions.userId, input.userId));

    await tx.insert(auditLogs).values({
      userId: input.userId,
      actorType: "user",
      actorId: input.userId,
      action: "auth.account.delete",
      resourceType: "user",
      resourceId: input.userId,
      status: "success",
      ipAddress: input.ipAddress,
      userAgent: input.userAgent,
      requestId: input.requestId,
      payload: {
        requestedBySessionId: input.sessionId,
        cascade: "user_private_data",
      },
    });

    await tx.delete(pairSessions).where(eq(pairSessions.claimedByUserId, input.userId));
    await tx.delete(worldSignals).where(eq(worldSignals.userId, input.userId));
    await tx.delete(chatSessions).where(eq(chatSessions.userId, input.userId));
    await tx.delete(tasks).where(eq(tasks.userId, input.userId));
    await tx.delete(operatorRuns).where(eq(operatorRuns.userId, input.userId));
    await tx.delete(runtimeConnections).where(eq(runtimeConnections.userId, input.userId));
    await tx.delete(realtimeEvents).where(eq(realtimeEvents.userId, input.userId));
    await tx.delete(billingCreditLedger).where(eq(billingCreditLedger.userId, input.userId));
    await tx.delete(billingEntitlementEvents).where(eq(billingEntitlementEvents.userId, input.userId));
    await tx.delete(billingCheckoutSessions).where(eq(billingCheckoutSessions.userId, input.userId));
    await tx.delete(billingWebhookEvents).where(eq(billingWebhookEvents.userId, input.userId));
    await tx.delete(billingStoreTransactions).where(eq(billingStoreTransactions.userId, input.userId));
    await tx.delete(billingProfiles).where(eq(billingProfiles.userId, input.userId));
    await tx.delete(subscriptions).where(eq(subscriptions.userId, input.userId));
    await tx.delete(aiProviderInvocations).where(eq(aiProviderInvocations.userId, input.userId));
    await tx.delete(aiProviderCredentials).where(eq(aiProviderCredentials.userId, input.userId));
    await tx.delete(learningEvents).where(eq(learningEvents.userId, input.userId));
    await tx.delete(brainMemoryLinks).where(eq(brainMemoryLinks.userId, input.userId));
    await tx.delete(brainMemoryFacts).where(eq(brainMemoryFacts.userId, input.userId));
    await tx.delete(brainMemoryEpisodes).where(eq(brainMemoryEpisodes.userId, input.userId));
    await tx.delete(brainMemoryRuns).where(eq(brainMemoryRuns.userId, input.userId));
    await tx.delete(integrationConnections).where(eq(integrationConnections.userId, input.userId));
    await tx.delete(oauthStates).where(eq(oauthStates.userId, input.userId));
    await tx.delete(mcpServers).where(eq(mcpServers.userId, input.userId));
    await tx.delete(usageRecords).where(eq(usageRecords.userId, input.userId));
    await tx.delete(knowledgeChunks).where(eq(knowledgeChunks.ownerUserId, input.userId));
    await tx.delete(knowledgeDocuments).where(eq(knowledgeDocuments.ownerUserId, input.userId));
    await tx.delete(modelArtifacts).where(eq(modelArtifacts.ownerUserId, input.userId));
    await tx.delete(trainingJobs).where(eq(trainingJobs.ownerUserId, input.userId));
    await tx.delete(datasetManifests).where(eq(datasetManifests.ownerUserId, input.userId));
    await tx.delete(devices).where(eq(devices.userId, input.userId));
    await tx.delete(authIdentities).where(eq(authIdentities.userId, input.userId));
    await tx.delete(userAvatars).where(eq(userAvatars.userId, input.userId));
    await tx.delete(sessions).where(eq(sessions.userId, input.userId));

    await tx
      .update(users)
      .set({
        deletedAt: now,
        passwordHash: deletedPasswordHash,
        updatedAt: now,
      })
      .where(eq(users.id, input.userId));
  });

  return {
    ok: true,
    deleted: true,
  };
}

export async function getCurrentUserProfile(app: FastifyInstance, userId: string) {
  const userRows = await app.db
    .select({
      id: users.id,
      email: users.email,
      displayName: users.displayName,
      createdAt: users.createdAt,
      deletedAt: users.deletedAt,
    })
    .from(users)
    .where(eq(users.id, userId))
    .limit(1);

  const user = userRows[0];

  if (!user || user.deletedAt) {
    throw unauthorized("Bilgileri kontrol et.");
  }

  const [billing, brain, avatar] = await Promise.all([
    getBillingSummary(app, userId),
    getBrainProfile(app, userId),
    getUserAvatarTruth(app, userId),
  ]);
  const runtimeCounts = await app.db
    .select({
      desktopCount: sql<number>`count(*)`,
    })
    .from(devices)
    .where(and(eq(devices.userId, userId), eq(devices.type, "desktop")));

  return {
    user: {
      ...user,
      ...avatar,
    },
    billingState: billing.billingState,
    quota: getTrialQuotaPolicy(),
    subscription: shapeSubscriptionTruth({
      planCode: billing.subscription.planCode,
      status: billing.subscription.status,
      aiCreditsMonthly: billing.entitlements.aiCreditsMonthly,
      taskLimitMonthly: billing.entitlements.taskLimitMonthly,
      brainProfile: billing.subscription.brainProfile,
      periodEndsAt: billing.subscription.periodEndsAt,
      trialEndsAt: billing.subscription.trialEndsAt,
      creditBalance: billing.usage.creditBalance,
      tokenBalance: billing.usage.tokenBalance,
      creditGrantedThisPeriod: billing.usage.creditGrantedThisPeriod,
      tokensGrantedThisPeriod: billing.usage.tokensGrantedThisPeriod,
      creditPeriodEndsAt: billing.usage.creditPeriodEndsAt,
      tokenPeriodEndsAt: billing.usage.tokenPeriodEndsAt,
      billingProvider: billing.subscription.billingProvider,
      subscriptionSource: billing.usage.subscriptionSource,
      manageSubscriptionHint: billing.usage.manageSubscriptionHint,
      creditStatus: billing.usage.creditStatus,
      tokenStatus: billing.usage.tokenStatus,
      trialOffer: billing.subscription.trialOffer,
    }),
    metrics: {
      desktopCount: Number(runtimeCounts[0]?.desktopCount ?? 0),
    },
    usage: shapePublicUsageSnapshot({
      usage: billing.usage,
      subscription: billing.subscription,
    }),
    brain: shapePublicBrainProfile(brain),
  };
}

export async function updateCurrentUserProfile(
  app: FastifyInstance,
  input: {
    userId: string;
    displayName: string;
    ipAddress?: string;
    userAgent?: string;
    requestId?: string;
  },
) {
  const displayName = normalizeDisplayName(input.displayName);
  if (!displayName) {
    throw badRequest("Geçerli bir ad gir.");
  }
  const rows = await app.db
    .update(users)
    .set({
      displayName,
      updatedAt: new Date(),
    })
    .where(eq(users.id, input.userId))
    .returning({
      id: users.id,
    });
  if (!rows[0]) {
    throw unauthorized("Bilgileri kontrol et.");
  }
  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "auth.profile.update",
    resourceType: "user",
    resourceId: input.userId,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {
      fields: ["displayName"],
    },
  });
  return getCurrentUserProfile(app, input.userId);
}

export async function changeCurrentUserPassword(
  app: FastifyInstance,
  input: {
    userId: string;
    currentPassword: string;
    nextPassword: string;
    ipAddress?: string;
    userAgent?: string;
    requestId?: string;
  },
) {
  const rows = await app.db
    .select({
      id: users.id,
      passwordHash: users.passwordHash,
    })
    .from(users)
    .where(eq(users.id, input.userId))
    .limit(1);
  const user = rows[0];
  if (!user || !(await verifySecret(input.currentPassword, user.passwordHash))) {
    throw unauthorized("Şifre yanlış.");
  }
  await app.db
    .update(users)
    .set({
      passwordHash: await hashSecret(input.nextPassword),
      updatedAt: new Date(),
    })
    .where(eq(users.id, input.userId));
  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "auth.password.change",
    resourceType: "user",
    resourceId: input.userId,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {},
  });
  return {
    ok: true,
    changed: true,
  };
}

async function getUserTwoFactorRow(app: FastifyInstance, userId: string) {
  const rows = await app.db
    .select({
      id: users.id,
      email: users.email,
      twoFactorEnabled: users.twoFactorEnabled,
      twoFactorSecretEncrypted: users.twoFactorSecretEncrypted,
      twoFactorConfirmedAt: users.twoFactorConfirmedAt,
      deletedAt: users.deletedAt,
    })
    .from(users)
    .where(eq(users.id, userId))
    .limit(1);
  const user = rows[0];
  if (!user || user.deletedAt) {
    throw unauthorized("Bilgileri kontrol et.");
  }
  return user;
}

export async function getCurrentUserTwoFactorStatus(app: FastifyInstance, userId: string) {
  const user = await getUserTwoFactorRow(app, userId);
  return {
    enabled: Boolean(user.twoFactorEnabled),
    confirmedAt: user.twoFactorConfirmedAt,
  };
}

export async function startCurrentUserTwoFactorSetup(
  app: FastifyInstance,
  input: {
    userId: string;
    ipAddress?: string;
    userAgent?: string;
    requestId?: string;
  },
) {
  const user = await getUserTwoFactorRow(app, input.userId);
  const secret = createTotpSecret();
  const encryptedSecret = encryptTotpSecret(secret, app.config.JWT_SECRET);
  await app.db
    .update(users)
    .set({
      twoFactorEnabled: false,
      twoFactorSecretEncrypted: encryptedSecret,
      twoFactorConfirmedAt: null,
      updatedAt: new Date(),
    })
    .where(eq(users.id, input.userId));
  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "auth.2fa.setup.start",
    resourceType: "user",
    resourceId: input.userId,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {},
  });
  return {
    enabled: false,
    secret,
    otpauthUri: buildOtpAuthUri({
      issuer: "Elyan",
      accountName: user.email,
      secret,
    }),
  };
}

export async function enableCurrentUserTwoFactor(
  app: FastifyInstance,
  input: {
    userId: string;
    code: string;
    ipAddress?: string;
    userAgent?: string;
    requestId?: string;
  },
) {
  const user = await getUserTwoFactorRow(app, input.userId);
  if (!user.twoFactorSecretEncrypted) {
    throw new AppError(409, "two_factor_setup_required", "Önce 2FA kurulumu başlatılmalı.");
  }
  const secret = decryptTotpSecret(user.twoFactorSecretEncrypted, app.config.JWT_SECRET);
  if (!verifyTotpCode({ secret, code: input.code })) {
    throw new AppError(401, "two_factor_invalid", "2FA kodu yanlış.");
  }
  const confirmedAt = new Date();
  await app.db
    .update(users)
    .set({
      twoFactorEnabled: true,
      twoFactorConfirmedAt: confirmedAt,
      updatedAt: confirmedAt,
    })
    .where(eq(users.id, input.userId));
  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "auth.2fa.enable",
    resourceType: "user",
    resourceId: input.userId,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {},
  });
  return {
    enabled: true,
    confirmedAt,
  };
}

export async function disableCurrentUserTwoFactor(
  app: FastifyInstance,
  input: {
    userId: string;
    code: string;
    ipAddress?: string;
    userAgent?: string;
    requestId?: string;
  },
) {
  const user = await getUserTwoFactorRow(app, input.userId);
  if (!user.twoFactorEnabled || !user.twoFactorSecretEncrypted) {
    return { enabled: false };
  }
  const secret = decryptTotpSecret(user.twoFactorSecretEncrypted, app.config.JWT_SECRET);
  if (!verifyTotpCode({ secret, code: input.code })) {
    throw new AppError(401, "two_factor_invalid", "2FA kodu yanlış.");
  }
  await app.db
    .update(users)
    .set({
      twoFactorEnabled: false,
      twoFactorSecretEncrypted: null,
      twoFactorConfirmedAt: null,
      updatedAt: new Date(),
    })
    .where(eq(users.id, input.userId));
  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "auth.2fa.disable",
    resourceType: "user",
    resourceId: input.userId,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {},
  });
  return {
    enabled: false,
  };
}

export async function upsertCurrentUserAvatar(
  app: FastifyInstance,
  input: {
    userId: string;
    mimeType: "image/png" | "image/jpeg" | "image/webp";
    dataBase64: string;
    ipAddress?: string;
    userAgent?: string;
    requestId?: string;
  },
) {
  const buffer = decodeAvatarBase64(input.dataBase64);
  assertAvatarPayload(buffer, input.mimeType);
  const existingRows = await app.db
    .select({
      id: userAvatars.id,
      version: userAvatars.version,
    })
    .from(userAvatars)
    .where(eq(userAvatars.userId, input.userId))
    .limit(1);
  const existing = existingRows[0];
  const payload = {
    mimeType: input.mimeType,
    dataBase64: buffer.toString("base64"),
    byteLength: buffer.byteLength,
    version: Number(existing?.version ?? 0) + 1,
    updatedAt: new Date(),
  };
  if (existing) {
    await app.db
      .update(userAvatars)
      .set(payload)
      .where(eq(userAvatars.id, existing.id));
  } else {
    await app.db.insert(userAvatars).values({
      id: randomUUID(),
      userId: input.userId,
      createdAt: new Date(),
      ...payload,
    });
  }
  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "auth.avatar.upsert",
    resourceType: "user_avatar",
    resourceId: input.userId,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {
      mimeType: input.mimeType,
      byteLength: buffer.byteLength,
    },
  });
  return getCurrentUserProfile(app, input.userId);
}

export async function getCurrentUserAvatar(app: FastifyInstance, userId: string) {
  const rows = await app.db
    .select({
      mimeType: userAvatars.mimeType,
      dataBase64: userAvatars.dataBase64,
      version: userAvatars.version,
    })
    .from(userAvatars)
    .where(eq(userAvatars.userId, userId))
    .limit(1);
  const avatar = rows[0];
  if (!avatar) {
    throw notFound("Profil fotoğrafı bulunamadı.");
  }
  return avatar;
}

export async function deleteCurrentUserAvatar(
  app: FastifyInstance,
  input: {
    userId: string;
    ipAddress?: string;
    userAgent?: string;
    requestId?: string;
  },
) {
  await app.db.delete(userAvatars).where(eq(userAvatars.userId, input.userId));
  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "auth.avatar.delete",
    resourceType: "user_avatar",
    resourceId: input.userId,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {},
  });
  return getCurrentUserProfile(app, input.userId);
}
