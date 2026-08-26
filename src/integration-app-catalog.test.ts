import assert from "node:assert/strict";
import test from "node:test";
import type { FastifyInstance } from "fastify";
import type { ConnectionProvider } from "./contracts/domain.js";
import { connectionProviderValues } from "./contracts/domain.js";
import { encryptJson } from "./lib/crypto-seal.js";
import {
  getIntegrationMcpApp,
  getIntegrationProvider,
  inferRequestedRemoteMcpApps,
  inferRequestedRemoteMcpAppsSemantic,
  integrationMcpAppCatalog,
} from "./modules/integrations/provider-registry.js";
import {
  resetSemanticComputeWorkerForTests,
  setSemanticComputeDispatcherForTests,
} from "./modules/brain/semantic-compute-client.js";
import {
  listIntegrationApps,
  listRuntimeMcpConnections,
  normalizeOauthRedirectUri,
  resolveRemoteMcpRequestedCapabilities,
} from "./modules/integrations/service.js";

type IntegrationConnectionRow = {
  id: string;
  appId: string | null;
  provider: ConnectionProvider;
  status: "connected";
  displayName: string;
  scopes: string[];
  capabilities: string[];
  metadata: Record<string, unknown>;
  updatedAt: Date;
};

type IntegrationCredentialRow = {
  id: string;
  encryptedPayload: string;
  expiresAt: Date | null;
};

function fakeIntegrationApp(
  queryResults: Array<
    Array<IntegrationConnectionRow | IntegrationCredentialRow>
  >,
): FastifyInstance {
  let selectIndex = 0;
  const db = {
    select() {
      const rows = queryResults[selectIndex++] ?? [];
      const query: any = {};
      query.from = () => query;
      query.where = () => query;
      query.orderBy = () => Promise.resolve(rows);
      query.limit = () => Promise.resolve(rows);
      query.then = (
        onfulfilled?: (
          value: Array<IntegrationConnectionRow | IntegrationCredentialRow>,
        ) => unknown,
        onrejected?: (reason: unknown) => unknown,
      ) => Promise.resolve(rows).then(onfulfilled, onrejected);
      return query;
    },
  };

  return {
    db,
    config: {
      TOKEN_ENCRYPTION_KEY: Buffer.alloc(32, 7).toString("base64url"),
      GMAIL_MCP_CLIENT_ID: "test-client-id",
      GMAIL_MCP_CLIENT_SECRET: "test-client-secret",
    },
  } as unknown as FastifyInstance;
}

function gmailConnection(scopes: string[]): IntegrationConnectionRow {
  return {
    id: "connection_gmail",
    appId: "gmail",
    provider: "google",
    status: "connected",
    displayName: "test@example.com",
    scopes,
    capabilities: ["gmail"],
    metadata: {},
    updatedAt: new Date("2026-07-14T09:20:57.000Z"),
  };
}

function legacyGoogleConnection(
  capabilities: string[],
  scopes: string[],
): IntegrationConnectionRow {
  return {
    id: "connection_google_legacy",
    appId: null,
    provider: "google",
    status: "connected",
    displayName: "legacy@example.com",
    scopes,
    capabilities,
    metadata: {},
    updatedAt: new Date("2026-07-14T09:21:57.000Z"),
  };
}

test("curated MCP app catalog has unique ids and trusted https endpoints", () => {
  const ids = integrationMcpAppCatalog.map((entry) => entry.id);
  assert.equal(new Set(ids).size, ids.length);
  assert.ok(ids.includes("gmail"));
  assert.ok(ids.includes("google-drive"));
  assert.ok(ids.includes("google-calendar"));
  assert.ok(ids.includes("dropbox"));

  for (const entry of integrationMcpAppCatalog) {
    assert.ok(entry.displayName.length > 0);
    assert.ok(entry.capabilities.length > 0);
    if (entry.execution === "remote_mcp") {
      // Only real remote MCP servers carry (and are leased with) a URL.
      const url = new URL(entry.serverUrl);
      assert.equal(url.protocol, "https:");
    } else {
      // server_connector capabilities are served in-server via REST tools and
      // must not advertise a remote MCP URL.
      assert.equal(entry.serverUrl, "");
    }
  }
});

test("Gmail app is a server-side connector, not a leased remote MCP server", () => {
  const gmail = getIntegrationMcpApp("gmail");
  const drive = getIntegrationMcpApp("google-drive");
  const calendar = getIntegrationMcpApp("google-calendar");
  assert.ok(gmail);
  assert.ok(drive);
  assert.ok(calendar);
  // Google capabilities are read by the shared brain via REST connector tools,
  // so they are served in-server and never leased to the desktop runtime.
  assert.equal(gmail.execution, "server_connector");
  assert.equal(drive.execution, "server_connector");
  assert.equal(calendar.execution, "server_connector");
  assert.ok(
    gmail.oauthScopes.includes(
      "https://www.googleapis.com/auth/gmail.readonly",
    ),
  );
  assert.ok(
    gmail.oauthScopes.includes("https://www.googleapis.com/auth/gmail.send"),
  );
  assert.ok(
    calendar.oauthScopes.includes(
      "https://www.googleapis.com/auth/calendar.events",
    ),
  );
  assert.ok(
    !gmail.oauthScopes.includes(
      "https://www.googleapis.com/auth/gmail.compose",
    ),
  );
  assert.equal(gmail.provider, "google");
  assert.equal(gmail.oauthClientIdEnvKey, "GMAIL_MCP_CLIENT_ID");
  assert.equal(drive.oauthClientIdEnvKey, "GOOGLE_DRIVE_MCP_CLIENT_ID");
  assert.equal(calendar.oauthClientIdEnvKey, "GOOGLE_CALENDAR_MCP_CLIENT_ID");
  assert.equal(
    new Set([
      gmail.oauthClientIdEnvKey,
      drive.oauthClientIdEnvKey,
      calendar.oauthClientIdEnvKey,
    ]).size,
    3,
  );
  assert.equal(
    getIntegrationProvider("google")?.oauth?.extraAuthParams
      ?.include_granted_scopes,
    "true",
  );
});

test("Google canonical userinfo grants mark the app connected; connectors are not leased to runtime", async () => {
  const connection = gmailConnection([
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
  ]);

  const apps = await listIntegrationApps(
    fakeIntegrationApp([[connection]]),
    "user_1",
  );
  const gmail = apps.find((entry) => entry.id === "gmail");
  assert.ok(gmail);
  assert.equal(gmail.connected, true);
  assert.deepEqual(gmail.missingScopes, []);

  // Gmail is a server_connector: the shared brain reads it via REST tools, so
  // it must NOT appear in the desktop runtime MCP lease.
  const runtime = await listRuntimeMcpConnections(
    fakeIntegrationApp([[connection], []]),
    "user_1",
  );
  assert.deepEqual(runtime.servers, []);
});

test("Gmail read-only app connection is connected and excluded from runtime", async () => {
  const connection = gmailConnection([
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
  ]);

  const apps = await listIntegrationApps(
    fakeIntegrationApp([[connection]]),
    "user_1",
  );
  const gmail = apps.find((entry) => entry.id === "gmail");
  assert.ok(gmail);
  assert.equal(gmail.connected, true);
  assert.deepEqual(gmail.missingScopes, []);

  const runtime = await listRuntimeMcpConnections(
    fakeIntegrationApp([[connection]]),
    "user_1",
  );
  assert.deepEqual(runtime.servers, []);
});

test("legacy provider-level Google grants still mark server connector apps connected", async () => {
  const connection = legacyGoogleConnection(
    ["gmail"],
    [
      "openid",
      "https://www.googleapis.com/auth/userinfo.email",
      "https://www.googleapis.com/auth/userinfo.profile",
      "https://www.googleapis.com/auth/gmail.readonly",
    ],
  );

  const apps = await listIntegrationApps(
    fakeIntegrationApp([[connection]]),
    "user_1",
  );
  const gmail = apps.find((entry) => entry.id === "gmail");
  assert.ok(gmail);
  assert.equal(gmail.connected, true);
  assert.equal(gmail.connectionId, "connection_google_legacy");
  assert.equal(gmail.accountLabel, "legacy@example.com");
  assert.deepEqual(gmail.missingScopes, []);

  const runtime = await listRuntimeMcpConnections(
    fakeIntegrationApp([[connection]]),
    "user_1",
  );
  assert.deepEqual(runtime.servers, []);
});

test("missing Gmail read scope remains disconnected and excluded from runtime", async () => {
  const connection = gmailConnection([
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
  ]);

  const apps = await listIntegrationApps(
    fakeIntegrationApp([[connection]]),
    "user_1",
  );
  const gmail = apps.find((entry) => entry.id === "gmail");
  assert.ok(gmail);
  assert.equal(gmail.connected, false);
  assert.deepEqual(gmail.missingScopes, [
    "https://www.googleapis.com/auth/gmail.readonly",
  ]);

  const runtime = await listRuntimeMcpConnections(
    fakeIntegrationApp([[connection]]),
    "user_1",
  );
  assert.deepEqual(runtime.servers, []);
});

test("MCP-native OAuth apps are available once provider credentials are configured", () => {
  const notion = getIntegrationMcpApp("notion");
  const github = getIntegrationMcpApp("github");
  const slack = getIntegrationMcpApp("slack");
  assert.ok(notion && github && slack);
  assert.equal(notion.authStrategy, "mcp_oauth");
  assert.equal(notion.stage, "available");
  assert.equal(github.stage, "available");
  assert.equal(slack.stage, "available");
});

test("connected MCP-native OAuth apps are leased to the desktop runtime", async () => {
  const tokenEnv = {
    TOKEN_ENCRYPTION_KEY: Buffer.alloc(32, 7).toString("base64url"),
  };
  const connection: IntegrationConnectionRow = {
    id: "connection_github",
    appId: "github",
    provider: "github",
    status: "connected",
    displayName: "octocat",
    scopes: ["repo", "read:user", "user:email"],
    capabilities: ["github"],
    metadata: {},
    updatedAt: new Date("2026-07-15T09:20:57.000Z"),
  };
  const credential: IntegrationCredentialRow = {
    id: "credential_github",
    encryptedPayload: encryptJson(tokenEnv as never, {
      accessToken: "github-access-token",
      refreshToken: null,
    }),
    expiresAt: new Date("2099-01-01T00:00:00.000Z"),
  };

  const runtime = await listRuntimeMcpConnections(
    fakeIntegrationApp([[connection], [], [credential]]),
    "user_1",
  );

  assert.equal(runtime.servers.length, 1);
  assert.equal(runtime.servers[0]?.appId, "github");
  assert.equal(runtime.servers[0]?.authType, "bearer");
  assert.equal(runtime.servers[0]?.accessToken, "github-access-token");
  assert.equal(runtime.servers[0]?.enabled, true);
});

test("remote MCP routing requires an explicit connected account-data request", () => {
  assert.deepEqual(
    inferRequestedRemoteMcpApps("GitHub repolarımı göster", ["github"]).map(
      (entry) => entry.id,
    ),
    ["github"],
  );
  assert.deepEqual(
    inferRequestedRemoteMcpApps("GitHub nedir?", ["github"]),
    [],
  );
  assert.deepEqual(
    inferRequestedRemoteMcpApps("Bana GitHub'ın ne olduğunu anlat", ["github"]),
    [],
  );
  assert.deepEqual(
    inferRequestedRemoteMcpApps("GitHub özelliklerini göster", ["github"]),
    [],
  );
  assert.deepEqual(
    inferRequestedRemoteMcpApps("GitHub issue'larımı listele", ["github"]).map(
      (entry) => entry.id,
    ),
    ["github"],
  );
  assert.deepEqual(
    inferRequestedRemoteMcpApps("GitHub repolarımı göster", ["notion"]),
    [],
  );
});

test("remote MCP routing uses semantic catalog intent instead of requiring a phrase pattern", async () => {
  resetSemanticComputeWorkerForTests();
  const vector = (index: number) => {
    const value = new Array<number>(384).fill(0);
    value[index] = 1;
    return value;
  };
  setSemanticComputeDispatcherForTests(async ({ texts }) =>
    texts.map((text) => {
      const normalized = text.toLowerCase();
      if (normalized.startsWith("query:")) {
        return normalized.includes("sdk") ? vector(2) : vector(0);
      }
      if (normalized.includes("read, search")) return vector(0);
      if (normalized.includes("create, send")) return vector(1);
      if (normalized.includes("explain what")) return vector(2);
      if (normalized.includes("draft, rewrite")) return vector(3);
      return vector(4);
    }),
  );

  try {
    assert.deepEqual(
      inferRequestedRemoteMcpApps(
        "GitHub'daki bana ait çalışma öğelerini dök",
        ["github"],
      ),
      [],
      "legacy phrase matcher should not know this paraphrase",
    );
    assert.deepEqual(
      (
        await inferRequestedRemoteMcpAppsSemantic(
          "GitHub'daki bana ait çalışma öğelerini dök",
          ["github"],
        )
      ).map((entry) => entry.id),
      ["github"],
    );
    assert.deepEqual(
      await inferRequestedRemoteMcpAppsSemantic(
        "GitHub SDK'sını açıkla",
        ["github"],
      ),
      [],
    );
    assert.deepEqual(
      await inferRequestedRemoteMcpAppsSemantic(
        "GitHub'daki bana ait çalışma öğelerini dök",
        ["notion"],
      ),
      [],
    );
  } finally {
    resetSemanticComputeWorkerForTests();
  }
});

test("remote MCP capability resolution binds semantic intent to a connected app", async () => {
  resetSemanticComputeWorkerForTests();
  const vector = (index: number) => {
    const value = new Array<number>(384).fill(0);
    value[index] = 1;
    return value;
  };
  setSemanticComputeDispatcherForTests(async ({ texts }) =>
    texts.map((text) => {
      const normalized = text.toLowerCase();
      if (normalized.startsWith("query:")) {
        return normalized.includes("sdk") ? vector(2) : vector(0);
      }
      if (normalized.includes("read, search")) return vector(0);
      if (normalized.includes("create, send")) return vector(1);
      if (normalized.includes("explain what")) return vector(2);
      if (normalized.includes("draft, rewrite")) return vector(3);
      return vector(4);
    }),
  );
  const connection: IntegrationConnectionRow = {
    id: "connection_github",
    appId: "github",
    provider: "github",
    status: "connected",
    displayName: "octocat",
    scopes: ["repo", "read:user", "user:email"],
    capabilities: ["github"],
    metadata: {},
    updatedAt: new Date("2026-07-15T09:20:57.000Z"),
  };

  try {
    assert.deepEqual(
      await resolveRemoteMcpRequestedCapabilities(
        fakeIntegrationApp([[connection]]),
        {
          userId: "user_1",
          prompt: "GitHub'daki bana ait çalışma öğelerini dök",
          requestedCapabilities: [],
        },
      ),
      ["mcp_call_tool"],
    );
    assert.deepEqual(
      await resolveRemoteMcpRequestedCapabilities(fakeIntegrationApp([]), {
        userId: "user_1",
        prompt: "GitHub SDK'sını açıkla",
        requestedCapabilities: [],
      }),
      [],
    );
    assert.deepEqual(
      await resolveRemoteMcpRequestedCapabilities(
        fakeIntegrationApp([[{ ...connection, capabilities: ["notion"] }]]),
        {
          userId: "user_1",
          prompt: "GitHub'daki bana ait çalışma öğelerini dök",
          requestedCapabilities: [],
        },
      ),
      [],
    );
  } finally {
    resetSemanticComputeWorkerForTests();
  }
});

test("OAuth completion redirects are limited to Elyan-owned destinations", () => {
  assert.equal(
    normalizeOauthRedirectUri(
      "elyan://connections?appId=gmail",
      "https://api.elyan.dev",
    ),
    "elyan://connections",
  );
  assert.equal(
    normalizeOauthRedirectUri(
      "elyan://integrations?appId=gmail",
      "https://api.elyan.dev",
    ),
    "elyan://integrations",
  );
  assert.equal(
    normalizeOauthRedirectUri(
      "elyan://connections?appId=gmail&flow=0123456789abcdef0123456789abcdef",
      "https://api.elyan.dev",
    ),
    "elyan://connections?flow=0123456789abcdef0123456789abcdef",
  );
  assert.equal(
    normalizeOauthRedirectUri(
      "https://api.elyan.dev/oauth/complete",
      "https://api.elyan.dev",
    ),
    "https://api.elyan.dev/oauth/complete",
  );
  assert.throws(
    () =>
      normalizeOauthRedirectUri(
        "https://evil.example/oauth/complete",
        "https://api.elyan.dev",
      ),
    /not allowed/i,
  );
  assert.throws(
    () =>
      normalizeOauthRedirectUri(
        "elyan://connections?flow=guessable",
        "https://api.elyan.dev",
      ),
    /correlation token/i,
  );
});

test("official remote MCP servers connect without a per-provider connector", () => {
  // Bu katalogun asıl vaadi: hazır bir MCP sunucusu eklemek KOD yazmayı
  // gerektirmemeli. Bunu mümkün kılan şey `mcp_oauth` yolunun jenerik
  // olması — RFC 9728 kaynak keşfi + RFC 7591 dinamik istemci kaydı + PKCE.
  // Dinamik kayıt sayesinde sağlayıcıya özel client id/secret gerekmez.
  //
  // Uçlar canlı olarak doğrulandı (2026-08-26): mcp.sentry.dev,
  // mcp.cloudflare.com ve mcp.notion.com üçü de keşfi ve dinamik kaydı
  // destekliyor.
  //
  // Bir girdi env anahtarı istemeye başlarsa vaat bozulmuş demektir: o
  // uygulama artık "ekle ve çalışsın" değil, kurulum gerektiren bir iştir.
  for (const id of ["sentry", "cloudflare", "notion", "supabase", "vercel"]) {
    const entry = getIntegrationMcpApp(id);
    assert.ok(entry, `${id} katalogda olmalı`);
    assert.equal(entry?.authStrategy, "mcp_oauth", `${id} jenerik OAuth kullanmalı`);
    assert.equal(entry?.execution, "remote_mcp", `${id} gerçek uzak MCP olmalı`);
    assert.equal(
      entry?.oauthClientIdEnvKey,
      undefined,
      `${id} sağlayıcıya özel client id istememeli`,
    );
    assert.equal(
      entry?.oauthClientSecretEnvKey,
      undefined,
      `${id} sağlayıcıya özel secret istememeli`,
    );
    assert.match(entry?.serverUrl ?? "", /^https:\/\//u);
  }
});

test("every catalog provider exists in the connection provider enum", () => {
  // `integrationConnections.provider` bir pgEnum. Katalogda enum'da olmayan
  // bir sağlayıcı bırakmak, bağlanma denemesini ÇALIŞMA ZAMANINDA veritabanı
  // hatasına düşürür — derleme sessiz kalır çünkü tip `ConnectionProvider`
  // olarak yazılır. Bu iddia, migration'ı unutmayı testte yakalar.
  for (const entry of integrationMcpAppCatalog) {
    assert.ok(
      (connectionProviderValues as readonly string[]).includes(entry.provider),
      `${entry.id} sağlayıcısı (${entry.provider}) enum'da yok — ` +
        "drizzle/0057_mcp_provider_catalog.sql ve bootstrap-v18 ile eklenmeli",
    );
  }
});
