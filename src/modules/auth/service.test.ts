import assert from "node:assert/strict";
import test from "node:test";
import { hashSecret } from "../../lib/auth-crypto.js";
import {
  aiProviderCredentials,
  billingStoreTransactions,
  chatSessions,
  devices,
  dialogueStates,
  proactiveTriggers,
  runtimeConnections,
  subscriptions,
  tasks,
  turnMetrics,
  userConsents,
  worldSignals,
} from "../../db/schema.js";
import {
  deleteCurrentUserAccount,
  loginUser,
  loginWithApple,
  loginWithGoogle,
  refreshUserSession,
  registerUser,
} from "./service.js";

function createSelectBuilder(result: unknown) {
  return {
    from() {
      return this;
    },
    leftJoin() {
      return this;
    },
    innerJoin() {
      return this;
    },
    where() {
      return this;
    },
    orderBy() {
      return this;
    },
    limit: async () => result,
  };
}

test("refreshUserSession rotates the refresh session and returns fresh tokens", async () => {
  const revokedSessions: Array<Record<string, unknown>> = [];
  const insertedSessions: Array<Record<string, unknown>> = [];
  const existingRefreshToken = "refresh-token-value";
  const expiresAt = new Date(Date.now() + 60_000);
  const subscriptionRow = {
    userId: "user-1",
    planCode: "free",
    status: "free",
    aiCreditsMonthly: 0,
    taskLimitMonthly: 10,
    periodEndsAt: null,
  };
  const selectResults = [
    [
      {
        sessionId: "session-1",
        userId: "user-1",
        refreshTokenHash: await hashSecret(existingRefreshToken),
        expiresAt,
        revokedAt: null,
        email: "user@example.com",
        displayName: "Emre",
      },
    ],
    [subscriptionRow],
  ];

  const app = {
    config: {
      ACCESS_TOKEN_TTL: "15m",
      REFRESH_TOKEN_TTL: "30d",
    },
    jwt: {
      verify(token: string) {
        assert.equal(token, existingRefreshToken);
        return {
          kind: "user",
          sub: "user-1",
          sessionId: "session-1",
          email: "user@example.com",
        };
      },
      sign(payload: Record<string, unknown>, options: Record<string, unknown>) {
        return `${String(options.expiresIn)}:${String(payload.sessionId ?? "")}`;
      },
    },
    db: {
      select() {
        return createSelectBuilder(selectResults.shift() ?? []);
      },
      update() {
        return {
          set(values: Record<string, unknown>) {
            return {
              where: async () => {
                revokedSessions.push(values);
                return [];
              },
            };
          },
        };
      },
      insert() {
        return {
          values(values: Record<string, unknown>) {
            insertedSessions.push(values);
            return Promise.resolve();
          },
        };
      },
    },
  };

  const result = await refreshUserSession(
    app as never,
    existingRefreshToken,
    {
      ipAddress: "127.0.0.1",
      userAgent: "pytest",
    },
  );

  assert.equal(revokedSessions.length, 1);
  assert.equal(insertedSessions.length, 1);
  assert.equal(result.user.email, "user@example.com");
  assert.equal(result.subscription.planCode, "free");
  assert.equal(result.subscription.status, "free");
  assert.equal(typeof result.tokens.accessToken, "string");
  assert.equal(typeof result.tokens.refreshToken, "string");
  assert.notEqual(result.tokens.accessToken, "");
  assert.notEqual(result.tokens.refreshToken, "");
});

test("loginWithGoogle links identities and returns a session", async () => {
  const insertedAuthIdentities: Array<Record<string, unknown>> = [];
  const insertedSessions: Array<Record<string, unknown>> = [];
  const updatedUsers: Array<Record<string, unknown>> = [];
  let insertCallIndex = 0;
  let updateCallIndex = 0;
  const selectResults = [
    [],
    [
      {
        id: "user-1",
        email: "user@example.com",
        displayName: null,
        deletedAt: null,
      },
    ],
    [
      {
        userId: "user-1",
        email: "user@example.com",
        identityId: "identity-1",
        deletedAt: null,
        planCode: "free",
      },
    ],
    [
      {
        id: "identity-1",
        normalizedEmail: "user@example.com",
        firstUserId: "user-1",
        latestUserId: "user-1",
      },
    ],
    [
      {
        userId: "user-1",
        planCode: "free",
        status: "free",
        aiCreditsMonthly: 0,
        taskLimitMonthly: 10,
        periodEndsAt: null,
      },
    ],
    [],
  ];

  const app = {
    config: {
      ACCESS_TOKEN_TTL: "15m",
      REFRESH_TOKEN_TTL: "30d",
      GOOGLE_CLIENT_ID: "google-client",
      GOOGLE_SERVER_CLIENT_ID: "",
      APPLE_CLIENT_ID: "",
      APPLE_SERVICE_ID: "",
    },
    jwt: {
      sign(payload: Record<string, unknown>, options: Record<string, unknown>) {
        return `${String(options.expiresIn)}:${String(payload.sessionId ?? "")}`;
      },
    },
    db: {
      select() {
        return createSelectBuilder(selectResults.shift() ?? []);
      },
      insert(table: unknown) {
        return {
          values(values: Record<string, unknown>) {
            insertCallIndex += 1;
            if (insertCallIndex === 1) {
              insertedAuthIdentities.push(values);
            }
            if (insertCallIndex === 2) {
              insertedSessions.push(values);
            }
            return Promise.resolve();
          },
        };
      },
      update(table: Record<string, unknown>) {
        return {
          set(values: Record<string, unknown>) {
            return {
              where: async () => {
                updateCallIndex += 1;
                if (updateCallIndex === 1) {
                  updatedUsers.push(values);
                }
                return [];
              },
            };
          },
        };
      },
    },
  };

  const result = await loginWithGoogle(
    app as never,
    {
      idToken: "google-id-token",
      email: "user@example.com",
      displayName: "Google User",
    },
    {
      ipAddress: "127.0.0.1",
      userAgent: "pytest",
    },
    async (_app, provider, idToken) => {
      assert.equal(provider, "google");
      assert.equal(idToken, "google-id-token");
      return {
        provider: "google",
        subject: "google-subject-1",
        email: "user@example.com",
        displayName: "Google User",
        claims: {
          sub: "google-subject-1",
          email: "user@example.com",
          name: "Google User",
        },
      };
    },
  );

  assert.equal(result.user.id, "user-1");
  assert.equal(result.user.email, "user@example.com");
  assert.equal(result.user.displayName, "Google User");
  assert.equal(insertedAuthIdentities.length, 1);
  assert.equal(insertedAuthIdentities[0].provider, "google");
  assert.equal(insertedAuthIdentities[0].providerSubject, "google-subject-1");
  assert.equal(insertedSessions.length, 1);
  assert.equal(typeof result.tokens.accessToken, "string");
  assert.equal(typeof result.tokens.refreshToken, "string");
  assert.equal(updatedUsers.length, 1);
});

test("loginWithApple links identities and returns a session", async () => {
  const insertedAuthIdentities: Array<Record<string, unknown>> = [];
  const insertedSessions: Array<Record<string, unknown>> = [];
  const selectResults = [
    [],
    [
      {
        id: "user-2",
        email: "apple@example.com",
        displayName: null,
        deletedAt: null,
      },
    ],
    [
      {
        userId: "user-2",
        email: "apple@example.com",
        identityId: "identity-2",
        deletedAt: null,
        planCode: "free",
      },
    ],
    [
      {
        id: "identity-2",
        normalizedEmail: "apple@example.com",
        firstUserId: "user-2",
        latestUserId: "user-2",
      },
    ],
    [
      {
        userId: "user-2",
        planCode: "free",
        status: "free",
        aiCreditsMonthly: 0,
        taskLimitMonthly: 10,
        periodEndsAt: null,
      },
    ],
    [],
  ];

  const app = {
    config: {
      ACCESS_TOKEN_TTL: "15m",
      REFRESH_TOKEN_TTL: "30d",
      GOOGLE_CLIENT_ID: "",
      GOOGLE_SERVER_CLIENT_ID: "",
      APPLE_CLIENT_ID: "com.elyan.elyanMobile",
      APPLE_SERVICE_ID: "",
    },
    jwt: {
      sign(payload: Record<string, unknown>, options: Record<string, unknown>) {
        return `${String(options.expiresIn)}:${String(payload.sessionId ?? "")}`;
      },
    },
    db: {
      select() {
        return createSelectBuilder(selectResults.shift() ?? []);
      },
      insert() {
        return {
          values(values: Record<string, unknown>) {
            if (insertedAuthIdentities.length === 0) {
              insertedAuthIdentities.push(values);
            } else {
              insertedSessions.push(values);
            }
            return Promise.resolve();
          },
        };
      },
      update() {
        return {
          set() {
            return {
              where() {
                return {
                  returning: async () => [
                    {
                      id: "identity-4",
                      normalizedEmail: "social@example.com",
                      firstUserId: "user-4",
                      latestUserId: "user-4",
                    },
                  ],
                };
              },
            };
          },
        };
      },
    },
  };

  const result = await loginWithApple(
    app as never,
    {
      idToken: "apple-id-token",
      email: "apple@example.com",
      displayName: "Apple User",
    },
    {
      ipAddress: "127.0.0.1",
      userAgent: "pytest",
    },
    async (_app, provider, idToken) => {
      assert.equal(provider, "apple");
      assert.equal(idToken, "apple-id-token");
      return {
        provider: "apple",
        subject: "apple-subject-1",
        email: "apple@example.com",
        displayName: "Apple User",
        claims: {
          sub: "apple-subject-1",
          email: "apple@example.com",
          name: "Apple User",
        },
      };
    },
  );

  assert.equal(result.user.id, "user-2");
  assert.equal(result.user.email, "apple@example.com");
  assert.equal(result.user.displayName, "Apple User");
  assert.equal(insertedAuthIdentities.length, 1);
  assert.equal(insertedAuthIdentities[0].provider, "apple");
  assert.equal(insertedAuthIdentities[0].providerSubject, "apple-subject-1");
  assert.equal(insertedSessions.length, 1);
  assert.equal(typeof result.tokens.accessToken, "string");
  assert.equal(typeof result.tokens.refreshToken, "string");
});

test("loginUser returns a short user-facing error message", async () => {
  const app = {
    config: {
      ACCESS_TOKEN_TTL: "15m",
      REFRESH_TOKEN_TTL: "30d",
    },
    db: {
      select() {
        return {
          from() {
            return this;
          },
          where() {
            return this;
          },
          limit: async () => [],
        };
      },
    },
    jwt: {
      sign() {
        return "token";
      },
    },
  };

  await assert.rejects(
    () =>
      loginUser(app as never, { email: "user@example.com", password: "wrong" }, { ipAddress: "127.0.0.1" }),
    (error: unknown) => {
      assert.equal((error as { message?: string }).message, "Şifre yanlış.");
      return true;
    },
  );
});

test("deleteCurrentUserAccount revokes sessions, audits, and removes account-owned rows", async () => {
  const updatedRows: Array<Record<string, unknown>> = [];
  const insertedRows: Array<Record<string, unknown>> = [];
  const deletedTables: unknown[] = [];

  const app = {
    db: {
      select() {
        return createSelectBuilder([{ id: "user-1" }]);
      },
      update() {
        return {
          set(values: Record<string, unknown>) {
            return {
              where: async () => {
                updatedRows.push(values);
                return [];
              },
            };
          },
        };
      },
      insert() {
        return {
          values(values: Record<string, unknown>) {
            insertedRows.push(values);
            return Promise.resolve();
          },
        };
      },
      delete(table: unknown) {
        return {
          where: async () => {
            deletedTables.push(table);
            return [];
          },
        };
      },
    },
  };

  const result = await deleteCurrentUserAccount(app as never, {
    userId: "user-1",
    sessionId: "session-1",
    ipAddress: "127.0.0.1",
    userAgent: "pytest",
    requestId: "req-1",
  });

  assert.equal(result.ok, true);
  assert.equal(result.deleted, true);
  assert.equal(updatedRows.length, 2);
  assert.ok(updatedRows[0].revokedAt instanceof Date);
  assert.ok(updatedRows[0].lastUsedAt instanceof Date);
  assert.ok(updatedRows[1].deletedAt instanceof Date);
  assert.equal(typeof updatedRows[1].passwordHash, "string");
  assert.equal(insertedRows.length, 1);
  assert.equal(insertedRows[0].action, "auth.account.delete");
  assert.equal(insertedRows[0].resourceType, "user");
  assert.equal(insertedRows[0].status, "success");
  assert.deepEqual(insertedRows[0].payload, {
    requestedBySessionId: "session-1",
    cascade: "user_private_data",
  });
  assert.ok(deletedTables.length >= 20);
  assert.ok(deletedTables.includes(worldSignals));
  assert.ok(deletedTables.includes(proactiveTriggers));
  assert.ok(deletedTables.includes(dialogueStates));
  assert.ok(deletedTables.includes(turnMetrics));
  assert.ok(deletedTables.includes(chatSessions));
  assert.ok(deletedTables.includes(tasks));
  assert.ok(deletedTables.includes(runtimeConnections));
  assert.ok(deletedTables.includes(billingStoreTransactions));
  assert.ok(deletedTables.includes(subscriptions));
  assert.ok(deletedTables.includes(aiProviderCredentials));
  assert.ok(deletedTables.includes(devices));
});

test("deleteCurrentUserAccount returns a safe error when the user is already gone", async () => {
  const app = {
    db: {
      select() {
        return createSelectBuilder([]);
      },
    },
  };

  await assert.rejects(
    () =>
      deleteCurrentUserAccount(app as never, {
        userId: "missing-user",
        sessionId: "session-1",
      }),
    (error: unknown) => {
      assert.equal((error as { message?: string }).message, "Bilgileri kontrol et.");
      return true;
    },
  );
});

test("registerUser returns a short conflict message", async () => {
  const app = {
    config: {
      ACCESS_TOKEN_TTL: "15m",
      REFRESH_TOKEN_TTL: "30d",
    },
    db: {
      select() {
        return {
          from() {
            return this;
          },
          where() {
            return {
              limit: async () => [{ id: "user-1" }],
            };
          },
        };
      },
      insert() {
        return {
          values() {
            return {
              returning: async () => [],
            };
          },
        };
      },
    },
    jwt: {
      sign() {
        return "token";
      },
    },
  };

  await assert.rejects(
    () =>
      registerUser(
        app as never,
        {
          email: "user@example.com",
          password: "secret1234",
          legalAcceptance: {
            termsAccepted: true,
            privacyAccepted: true,
          },
        },
        { ipAddress: "127.0.0.1" },
      ),
    (error: unknown) => {
      assert.equal((error as { message?: string }).message, "Bilgileri kontrol et.");
      return true;
    },
  );
});

test("registerUser rejects account creation without legal acceptance", async () => {
  await assert.rejects(
    () =>
      registerUser(
        {} as never,
        { email: "user@example.com", password: "secret1234" },
        { ipAddress: "127.0.0.1" },
      ),
    (error: unknown) => {
      assert.equal(
        (error as { message?: string }).message,
        "Kayıt için kullanım koşulları ve gizlilik kabul edilmeli.",
      );
      return true;
    },
  );
});

test("registerUser seeds a free plan for a new user (gifted pro trial removed)", async () => {
  const insertedSubscriptions: Array<Record<string, unknown>> = [];
  let insertCallIndex = 0;
  const createdAt = Date.now();
  const trialEndsAt = new Date(createdAt + 30 * 24 * 60 * 60 * 1000);
  const selectResults = [
    [],
    [],
    [
      {
        userId: "user-3",
        planCode: "free",
        status: "free",
        aiCreditsMonthly: 0,
        taskLimitMonthly: 25,
        periodEndsAt: trialEndsAt,
        trialEndsAt,
      },
    ],
    [
      {
        userId: "user-3",
        email: "trial@example.com",
        identityId: null,
        deletedAt: null,
        planCode: "free",
      },
    ],
    [],
    [
      {
        userId: "user-3",
        planCode: "free",
        status: "free",
        aiCreditsMonthly: 0,
        taskLimitMonthly: 25,
        periodEndsAt: trialEndsAt,
        trialEndsAt,
      },
    ],
    [],
  ];

  const app = {
    config: {
      ACCESS_TOKEN_TTL: "15m",
      REFRESH_TOKEN_TTL: "30d",
    },
    db: {
      select() {
        return createSelectBuilder(selectResults.shift() ?? []);
      },
      insert(table: unknown) {
        return {
          values(values: Record<string, unknown>) {
            if (table === userConsents) {
              return {
                onConflictDoUpdate: async () => [],
                returning: async () => [],
              };
            }
            insertCallIndex += 1;
            if (insertCallIndex === 1) {
              return {
                returning: async () => [
                  {
                    id: "user-3",
                    email: "trial@example.com",
                    displayName: "Trial User",
                  },
                ],
              };
            }
            if (insertCallIndex === 2) {
              insertedSubscriptions.push(values);
              return {
                returning: async () => [],
              };
            }
            if (insertCallIndex === 3) {
              return {
                returning: async () => [
                  {
                    id: "identity-3",
                    normalizedEmail: "trial@example.com",
                    firstUserId: "user-3",
                    latestUserId: "user-3",
                  },
                ],
              };
            }
            return {
              returning: async () => [],
            };
          },
        };
      },
      update() {
        return {
          set() {
            return {
              where() {
                return {
                  returning: async () => [
                    {
                      id: "identity-4",
                      normalizedEmail: "social@example.com",
                      firstUserId: "user-4",
                      latestUserId: "user-4",
                    },
                  ],
                };
              },
            };
          },
        };
      },
    },
    jwt: {
      sign(payload: Record<string, unknown>, options: Record<string, unknown>) {
        return `${String(options.expiresIn)}:${String(payload.sessionId ?? "")}`;
      },
    },
  };

  const result = await registerUser(
    app as never,
    {
      email: "trial@example.com",
      password: "secret1234",
      displayName: "Trial User",
      legalAcceptance: {
        termsAccepted: true,
        privacyAccepted: true,
      },
    },
    { ipAddress: "127.0.0.1", userAgent: "pytest" },
  );

  assert.equal(result.subscription.status, "free");
  // Hediye Pro denemesi kaldırıldı: yeni kullanıcı ücretsiz başlar.
  assert.equal(insertedSubscriptions.length, 1);
  assert.equal(insertedSubscriptions[0].planCode, "free");
  assert.equal(insertedSubscriptions[0].status, "free");
  assert.ok(insertedSubscriptions[0].currentPeriodStartedAt instanceof Date);
  assert.equal(insertedSubscriptions[0].trialEndsAt, null);
  assert.equal(insertedSubscriptions[0].periodEndsAt, null);
});

test("loginWithGoogle seeds a free plan for first-time social signup", async () => {
  const insertedSubscriptions: Array<Record<string, unknown>> = [];
  let insertCallIndex = 0;
  const trialEndsAt = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000);
  const selectResults = [
    [],
    [],
    [],
    [
      {
        userId: "user-4",
        planCode: "free",
        status: "free",
        aiCreditsMonthly: 0,
        taskLimitMonthly: 25,
        periodEndsAt: trialEndsAt,
        trialEndsAt,
      },
    ],
    [
      {
        userId: "user-4",
        email: "social@example.com",
        identityId: null,
        deletedAt: null,
        planCode: "free",
      },
    ],
    [],
    [
      {
        userId: "user-4",
        email: "social@example.com",
        identityId: "identity-4",
        deletedAt: null,
        planCode: "free",
      },
    ],
    [
      {
        id: "identity-4",
        normalizedEmail: "social@example.com",
        firstUserId: "user-4",
        latestUserId: "user-4",
      },
    ],
    [
      {
        userId: "user-4",
        planCode: "free",
        status: "free",
        aiCreditsMonthly: 0,
        taskLimitMonthly: 25,
        periodEndsAt: trialEndsAt,
        trialEndsAt,
      },
    ],
    [],
  ];

  const app = {
    config: {
      ACCESS_TOKEN_TTL: "15m",
      REFRESH_TOKEN_TTL: "30d",
      GOOGLE_CLIENT_ID: "google-client",
      GOOGLE_SERVER_CLIENT_ID: "",
      APPLE_CLIENT_ID: "",
      APPLE_SERVICE_ID: "",
    },
    jwt: {
      sign(payload: Record<string, unknown>, options: Record<string, unknown>) {
        return `${String(options.expiresIn)}:${String(payload.sessionId ?? "")}`;
      },
    },
    db: {
      select() {
        return createSelectBuilder(selectResults.shift() ?? []);
      },
      insert(table: unknown) {
        return {
          values(values: Record<string, unknown>) {
            if (table === userConsents) {
              return {
                onConflictDoUpdate: async () => [],
                returning: async () => [],
              };
            }
            insertCallIndex += 1;
            if (insertCallIndex === 1) {
              return {
                returning: async () => [
                  {
                    id: "user-4",
                    email: "social@example.com",
                    displayName: "Social User",
                  },
                ],
              };
            }
            if (insertCallIndex === 2) {
              insertedSubscriptions.push(values);
              return {
                returning: async () => [],
              };
            }
            if (insertCallIndex === 3) {
              return {
                returning: async () => [
                  {
                    id: "identity-4",
                    normalizedEmail: "social@example.com",
                    firstUserId: "user-4",
                    latestUserId: "user-4",
                  },
                ],
              };
            }
            if (insertCallIndex > 3) {
              return {
                returning: async () => [
                  {
                    id: "identity-4",
                    normalizedEmail: "social@example.com",
                    firstUserId: "user-4",
                    latestUserId: "user-4",
                  },
                ],
              };
            }
            return {
              returning: async () => [],
            };
          },
        };
      },
      update() {
        return {
          set() {
            return {
              where() {
                return {
                  returning: async () => [
                    {
                      id: "identity-4",
                      normalizedEmail: "social@example.com",
                      firstUserId: "user-4",
                      latestUserId: "user-4",
                    },
                  ],
                };
              },
            };
          },
        };
      },
    },
  };

  const result = await loginWithGoogle(
    app as never,
    {
      idToken: "google-first-id-token",
      email: "social@example.com",
      displayName: "Social User",
      legalAcceptance: {
        termsAccepted: true,
        privacyAccepted: true,
      },
    },
    {
      ipAddress: "127.0.0.1",
      userAgent: "pytest",
    },
    async () => ({
      provider: "google",
      subject: "google-first-user",
      email: "social@example.com",
      displayName: "Social User",
      claims: {
        sub: "google-first-user",
        email: "social@example.com",
        name: "Social User",
      },
    }),
  );

  assert.equal(result.subscription.status, "free");
  assert.equal(insertedSubscriptions.length, 1);
  assert.equal(insertedSubscriptions[0].planCode, "free");
  assert.equal(insertedSubscriptions[0].status, "free");
  assert.equal(insertedSubscriptions[0].trialEndsAt, null);
});
