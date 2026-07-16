import type { AppEnv } from "../../config/env.js";
import type {
  ConnectionProvider,
  IntegrationAuthType,
} from "../../contracts/domain.js";
import { rankSemanticTextCandidates } from "../../core/understanding/intent-semantic.js";

export type ProviderCatalogEntry = {
  code: ConnectionProvider;
  displayName: string;
  authType: IntegrationAuthType;
  capabilities: string[];
  oauth?: {
    clientIdEnvKey:
      | "GOOGLE_CLIENT_ID"
      | "NOTION_CLIENT_ID"
      | "SLACK_CLIENT_ID"
      | "DISCORD_CLIENT_ID"
      | "GITHUB_CLIENT_ID"
      | "LINEAR_CLIENT_ID"
      | "DROPBOX_CLIENT_ID"
      | "TRELLO_CLIENT_ID"
      | "JIRA_CLIENT_ID"
      | "CLICKUP_CLIENT_ID";
    clientSecretEnvKey:
      | "GOOGLE_CLIENT_SECRET"
      | "NOTION_CLIENT_SECRET"
      | "SLACK_CLIENT_SECRET"
      | "DISCORD_CLIENT_SECRET"
      | "GITHUB_CLIENT_SECRET"
      | "LINEAR_CLIENT_SECRET"
      | "DROPBOX_CLIENT_SECRET"
      | "TRELLO_CLIENT_SECRET"
      | "JIRA_CLIENT_SECRET"
      | "CLICKUP_CLIENT_SECRET";
    authUrl: string;
    tokenUrl: string;
    defaultScopes: string[];
    scopeSeparator?: string;
    usePkce?: boolean;
    tokenRequestStyle?: "form" | "json" | "json_basic";
    extraAuthParams?: Record<string, string>;
  };
};

export type IntegrationMcpAppCatalogEntry = {
  id: string;
  provider: ConnectionProvider;
  displayName: string;
  description: string;
  iconKey: string;
  category: "productivity" | "developer" | "communication";
  serverUrl: string;
  stage: "available" | "preview" | "setup_required";
  authStrategy: "provider_bearer" | "mcp_oauth";
  oauthClientIdEnvKey?: keyof AppEnv;
  oauthClientSecretEnvKey?: keyof AppEnv;
  oauthScopes: string[];
  /** Minimum scopes that keep an existing connection usable for read tools. */
  connectionScopes?: string[];
  capabilities: string[];
  /**
   * How the connected capability is actually served:
   * - "server_connector": the shared brain reads it directly via first-party
   *   REST connector tools (no remote MCP server). Works for mobile-only users
   *   and is never leased to the desktop runtime.
   * - "remote_mcp": a real remote MCP server the desktop runtime connects to;
   *   included in the runtime lease.
   */
  execution: "server_connector" | "remote_mcp";
};

export const integrationProviderCatalog: ProviderCatalogEntry[] = [
  {
    code: "google",
    displayName: "Google",
    authType: "oauth2",
    capabilities: ["gmail", "drive", "calendar"],
    oauth: {
      clientIdEnvKey: "GOOGLE_CLIENT_ID",
      clientSecretEnvKey: "GOOGLE_CLIENT_SECRET",
      authUrl: "https://accounts.google.com/o/oauth2/v2/auth",
      tokenUrl: "https://oauth2.googleapis.com/token",
      defaultScopes: [
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events",
      ],
      scopeSeparator: " ",
      usePkce: true,
      extraAuthParams: {
        access_type: "offline",
        prompt: "consent",
        include_granted_scopes: "true",
      },
    },
  },
  {
    code: "notion",
    displayName: "Notion",
    authType: "oauth2",
    capabilities: ["notion"],
    oauth: {
      clientIdEnvKey: "NOTION_CLIENT_ID",
      clientSecretEnvKey: "NOTION_CLIENT_SECRET",
      authUrl: "https://api.notion.com/v1/oauth/authorize",
      tokenUrl: "https://api.notion.com/v1/oauth/token",
      defaultScopes: [],
      scopeSeparator: " ",
      usePkce: false,
      tokenRequestStyle: "json_basic",
    },
  },
  {
    code: "slack",
    displayName: "Slack",
    authType: "oauth2",
    capabilities: ["slack"],
    oauth: {
      clientIdEnvKey: "SLACK_CLIENT_ID",
      clientSecretEnvKey: "SLACK_CLIENT_SECRET",
      authUrl: "https://slack.com/oauth/v2/authorize",
      tokenUrl: "https://slack.com/api/oauth.v2.access",
      defaultScopes: ["channels:read", "chat:write", "users:read"],
      scopeSeparator: ",",
      usePkce: false,
    },
  },
  {
    code: "discord",
    displayName: "Discord",
    authType: "oauth2",
    capabilities: ["discord"],
    oauth: {
      clientIdEnvKey: "DISCORD_CLIENT_ID",
      clientSecretEnvKey: "DISCORD_CLIENT_SECRET",
      authUrl: "https://discord.com/oauth2/authorize",
      tokenUrl: "https://discord.com/api/oauth2/token",
      defaultScopes: ["identify", "guilds"],
      scopeSeparator: " ",
      usePkce: true,
    },
  },
  {
    code: "github",
    displayName: "GitHub",
    authType: "oauth2",
    capabilities: ["github"],
    oauth: {
      clientIdEnvKey: "GITHUB_CLIENT_ID",
      clientSecretEnvKey: "GITHUB_CLIENT_SECRET",
      authUrl: "https://github.com/login/oauth/authorize",
      tokenUrl: "https://github.com/login/oauth/access_token",
      defaultScopes: ["repo", "read:user", "user:email"],
      scopeSeparator: " ",
      usePkce: true,
    },
  },
  {
    code: "linear",
    displayName: "Linear",
    authType: "oauth2",
    capabilities: ["linear"],
    oauth: {
      clientIdEnvKey: "LINEAR_CLIENT_ID",
      clientSecretEnvKey: "LINEAR_CLIENT_SECRET",
      authUrl: "https://linear.app/oauth/authorize",
      tokenUrl: "https://api.linear.app/oauth/token",
      defaultScopes: ["read", "write"],
      scopeSeparator: ",",
      usePkce: true,
    },
  },
  {
    code: "dropbox",
    displayName: "Dropbox",
    authType: "oauth2",
    capabilities: ["dropbox"],
    oauth: {
      clientIdEnvKey: "DROPBOX_CLIENT_ID",
      clientSecretEnvKey: "DROPBOX_CLIENT_SECRET",
      authUrl: "https://www.dropbox.com/oauth2/authorize",
      tokenUrl: "https://api.dropboxapi.com/oauth2/token",
      defaultScopes: [],
      scopeSeparator: " ",
      usePkce: true,
      extraAuthParams: {
        token_access_type: "offline",
      },
    },
  },
  {
    code: "jira",
    displayName: "Jira",
    authType: "oauth2",
    capabilities: ["jira"],
    oauth: {
      clientIdEnvKey: "JIRA_CLIENT_ID",
      clientSecretEnvKey: "JIRA_CLIENT_SECRET",
      authUrl: "https://auth.atlassian.com/authorize",
      tokenUrl: "https://auth.atlassian.com/oauth/token",
      defaultScopes: ["read:jira-user", "read:jira-work", "offline_access"],
      scopeSeparator: " ",
      usePkce: true,
      tokenRequestStyle: "json",
      extraAuthParams: {
        audience: "api.atlassian.com",
        prompt: "consent",
      },
    },
  },
  {
    code: "clickup",
    displayName: "ClickUp",
    authType: "oauth2",
    capabilities: ["clickup"],
    oauth: {
      clientIdEnvKey: "CLICKUP_CLIENT_ID",
      clientSecretEnvKey: "CLICKUP_CLIENT_SECRET",
      authUrl: "https://app.clickup.com/api",
      tokenUrl: "https://api.clickup.com/api/v2/oauth/token",
      defaultScopes: [],
      scopeSeparator: " ",
      usePkce: false,
      tokenRequestStyle: "json",
    },
  },
];

/**
 * Curated, first-party remote MCP catalog. Users never need to paste these
 * URLs; adding another app is deliberately a reviewed data change here.
 */
export const integrationMcpAppCatalog: IntegrationMcpAppCatalogEntry[] = [
  {
    id: "gmail",
    provider: "google",
    displayName: "Gmail",
    description:
      "E-postaları ara, oku; yalnız açık onaydan sonra e-posta gönder.",
    iconKey: "gmail",
    category: "productivity",
    serverUrl: "",
    stage: "preview",
    authStrategy: "provider_bearer",
    oauthClientIdEnvKey: "GMAIL_MCP_CLIENT_ID",
    oauthClientSecretEnvKey: "GMAIL_MCP_CLIENT_SECRET",
    oauthScopes: [
      "openid",
      "email",
      "profile",
      "https://www.googleapis.com/auth/gmail.readonly",
      "https://www.googleapis.com/auth/gmail.send",
    ],
    connectionScopes: [
      "openid",
      "email",
      "profile",
      "https://www.googleapis.com/auth/gmail.readonly",
    ],
    capabilities: ["gmail"],
    execution: "server_connector",
  },
  {
    id: "google-drive",
    provider: "google",
    displayName: "Google Drive",
    description: "Drive dosyalarını bul, oku ve izin verilen içerikleri indir.",
    iconKey: "google_drive",
    category: "productivity",
    serverUrl: "",
    stage: "preview",
    authStrategy: "provider_bearer",
    oauthClientIdEnvKey: "GOOGLE_DRIVE_MCP_CLIENT_ID",
    oauthClientSecretEnvKey: "GOOGLE_DRIVE_MCP_CLIENT_SECRET",
    oauthScopes: [
      "openid",
      "email",
      "profile",
      "https://www.googleapis.com/auth/drive.readonly",
    ],
    capabilities: ["drive"],
    execution: "server_connector",
  },
  {
    id: "google-calendar",
    provider: "google",
    displayName: "Google Calendar",
    description: "Takvimi oku; yalnız açık onaydan sonra etkinlik oluştur.",
    iconKey: "google_calendar",
    category: "productivity",
    serverUrl: "",
    stage: "preview",
    authStrategy: "provider_bearer",
    oauthClientIdEnvKey: "GOOGLE_CALENDAR_MCP_CLIENT_ID",
    oauthClientSecretEnvKey: "GOOGLE_CALENDAR_MCP_CLIENT_SECRET",
    oauthScopes: [
      "openid",
      "email",
      "profile",
      "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
      "https://www.googleapis.com/auth/calendar.events.freebusy",
      "https://www.googleapis.com/auth/calendar.events.readonly",
      "https://www.googleapis.com/auth/calendar.events",
    ],
    connectionScopes: [
      "openid",
      "email",
      "profile",
      "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
      "https://www.googleapis.com/auth/calendar.events.freebusy",
      "https://www.googleapis.com/auth/calendar.events.readonly",
    ],
    capabilities: ["calendar"],
    execution: "server_connector",
  },
  {
    id: "notion",
    provider: "notion",
    displayName: "Notion",
    description: "Yetki verdiğin Notion çalışma alanında ara, oku ve düzenle.",
    iconKey: "notion",
    category: "productivity",
    serverUrl: "https://mcp.notion.com/mcp",
    stage: "available",
    authStrategy: "mcp_oauth",
    oauthScopes: [],
    capabilities: ["notion"],
    execution: "remote_mcp",
  },
  {
    id: "dropbox",
    provider: "dropbox",
    displayName: "Dropbox",
    description: "Dropbox dosyalarını güvenli, salt okunur biçimde bul ve oku.",
    iconKey: "dropbox",
    category: "productivity",
    serverUrl: "",
    stage: "preview",
    authStrategy: "provider_bearer",
    oauthScopes: [
      "account_info.read",
      "files.metadata.read",
      "files.content.read",
    ],
    capabilities: ["dropbox"],
    execution: "server_connector",
  },
  {
    id: "linear",
    provider: "linear",
    displayName: "Linear",
    description: "Issue, proje ve yorumları Elyan görevlerine bağla.",
    iconKey: "linear",
    category: "developer",
    serverUrl: "https://mcp.linear.app/mcp",
    stage: "available",
    authStrategy: "provider_bearer",
    oauthScopes: ["read", "write"],
    capabilities: ["linear"],
    execution: "remote_mcp",
  },
  {
    id: "github",
    provider: "github",
    displayName: "GitHub",
    description: "Repository, issue ve pull request bağlamını kullan.",
    iconKey: "github",
    category: "developer",
    serverUrl: "https://api.githubcopilot.com/mcp/",
    stage: "available",
    authStrategy: "mcp_oauth",
    oauthScopes: ["repo", "read:user", "user:email"],
    capabilities: ["github"],
    execution: "remote_mcp",
  },
  {
    id: "slack",
    provider: "slack",
    displayName: "Slack",
    description:
      "Mesajları ve kanalları bağla; Elyan Slack uygulaması onayı gerekir.",
    iconKey: "slack",
    category: "communication",
    serverUrl: "https://mcp.slack.com/mcp",
    stage: "available",
    authStrategy: "mcp_oauth",
    oauthScopes: [
      "search:read.public",
      "search:read.private",
      "search:read.im",
      "search:read.mpim",
      "files:read",
      "users:read",
      "chat:write",
    ],
    capabilities: ["slack"],
    execution: "remote_mcp",
  },
];

const REMOTE_MCP_DATA_ACTION_PATTERN =
  /\b(göster|goster|listele|list|ara|search|bul|find|oku|read|kontrol et|check|son|latest|recent)\b/i;
const REMOTE_MCP_OWNED_DATA_PATTERN =
  /\b(repolar[ıi]m|repositorylerim|issue(?:lar)?[ıi]m|pull requestlerim|pr(?:'ler)?im|mesajlar[ıi]m|kanallar[ıi]m|sayfalar[ıi]m|projelerim|işlerim|islerim|tasks?ım|hesabımdaki|hesabimdaki|my (?:repos(?:itories)?|issues|pull requests|messages|channels|pages|projects|tasks|account))\b/i;
const REMOTE_MCP_APP_DATA_NOUN_PATTERN =
  /\b(repo(?:sitory)?|repolar|repositories|issues?|pull requests?|prs?|mesajlar|messages|kanallar|channels|sayfalar|pages|projeler|projects|tasks?|workspace)\b/i;

/** Connected remote MCP app explicitly requested as account data, not merely mentioned. */
export function inferRequestedRemoteMcpApps(
  prompt: string,
  connectedCapabilities: string[],
): IntegrationMcpAppCatalogEntry[] {
  const normalized = prompt
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase("tr-TR");
  const hasOwnedData = REMOTE_MCP_OWNED_DATA_PATTERN.test(normalized);
  const hasExplicitAppDataOperation =
    REMOTE_MCP_DATA_ACTION_PATTERN.test(normalized) &&
    REMOTE_MCP_APP_DATA_NOUN_PATTERN.test(normalized);
  if (!normalized || (!hasOwnedData && !hasExplicitAppDataOperation)) {
    return [];
  }
  const connected = new Set(
    connectedCapabilities.map((capability) => capability.trim().toLowerCase()),
  );
  return integrationMcpAppCatalog.filter((entry) => {
    if (
      entry.execution !== "remote_mcp" ||
      !entry.capabilities.some((capability) => connected.has(capability))
    ) {
      return false;
    }
    const names = [entry.id, entry.provider, entry.displayName].map((value) =>
      value.toLocaleLowerCase("tr-TR"),
    );
    return names.some((name) => normalized.includes(name));
  });
}

const CONNECTED_DATA_OPERATION_CANDIDATES = [
  {
    id: "read_account_data",
    description:
      "Read, search, find, list, check, retrieve or summarize the user's own data inside a connected application. Bağlı uygulamadaki kullanıcı verilerini oku, ara, bul, listele, kontrol et, getir veya özetle.",
  },
  {
    id: "write_account_data",
    description:
      "Create, send, update, modify or delete data inside the user's connected application. Bağlı uygulamada gönder, oluştur, ekle, güncelle, değiştir veya sil.",
  },
  {
    id: "explain_application",
    description:
      "Explain what an application, API, integration or concept is without accessing the user's account. Kullanıcı hesabına erişmeden uygulamayı, API'yi veya kavramı açıkla.",
  },
  {
    id: "compose_without_access",
    description:
      "Draft, rewrite or design content about an application without reading or changing the connected account. Bağlı hesaba erişmeden metin, kod, taslak veya tasarım hazırla.",
  },
  {
    id: "general_conversation",
    description:
      "General conversation or an unrelated request that does not need connected account data. Bağlı hesap verisi gerektirmeyen genel sohbet veya ilgisiz istek.",
  },
] as const;

function normalizedCatalogName(value: string): string {
  return value
    .toLocaleLowerCase("tr-TR")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function explicitlyNamedRemoteMcpApps(
  prompt: string,
  entries: IntegrationMcpAppCatalogEntry[],
): IntegrationMcpAppCatalogEntry[] {
  const normalized = ` ${normalizedCatalogName(prompt)} `;
  return entries.filter((entry) => {
    const names = [entry.id, entry.displayName]
      .map(normalizedCatalogName)
      .filter((name) => name.length >= 3);
    return names.some((name) => normalized.includes(` ${name} `));
  });
}

/**
 * Semantic counterpart of the legacy phrase matcher above. The operation and
 * app are selected from the live MCP catalog descriptions, not from a list of
 * user utterances. Only high-confidence transformer matches can broaden the
 * legacy route; hash-only mode falls back to the conservative matcher.
 */
export async function inferRequestedRemoteMcpAppsSemantic(
  prompt: string,
  connectedCapabilities: string[],
): Promise<IntegrationMcpAppCatalogEntry[]> {
  const connected = new Set(
    connectedCapabilities.map((capability) => capability.trim().toLowerCase()),
  );
  const eligible = integrationMcpAppCatalog.filter(
    (entry) =>
      entry.execution === "remote_mcp" &&
      entry.capabilities.some((capability) => connected.has(capability)),
  );
  if (!prompt.trim() || eligible.length === 0) return [];

  // Remote MCP execution is private desktop work. Require one unambiguous app
  // identity before paying for semantic action classification; a bare
  // "mesajlarımı göster" could refer to several connected services and must
  // clarify rather than guessing.
  const explicitlyNamed = explicitlyNamedRemoteMcpApps(prompt, eligible);
  if (explicitlyNamed.length !== 1) {
    return inferRequestedRemoteMcpApps(prompt, connectedCapabilities);
  }

  const operation = await rankSemanticTextCandidates(
    prompt,
    [...CONNECTED_DATA_OPERATION_CANDIDATES],
    {
      transformerMinScore: 0.64,
      transformerMinMargin: 0.02,
      hashMinScore: 0.22,
      hashMinMargin: 0.06,
    },
  );
  if (
    !operation ||
    operation.source !== "transformer" ||
    (operation.id !== "read_account_data" &&
      operation.id !== "write_account_data")
  ) {
    return inferRequestedRemoteMcpApps(prompt, connectedCapabilities);
  }
  return explicitlyNamed;
}

export function getIntegrationProvider(provider: ConnectionProvider) {
  return integrationProviderCatalog.find((entry) => entry.code === provider);
}

export function getIntegrationMcpApp(appId: string) {
  return integrationMcpAppCatalog.find((entry) => entry.id === appId);
}

export function isIntegrationMcpAppConfigured(
  env: AppEnv,
  entry: IntegrationMcpAppCatalogEntry,
): boolean {
  if (entry.oauthClientIdEnvKey || entry.oauthClientSecretEnvKey) {
    const clientId = entry.oauthClientIdEnvKey
      ? env[entry.oauthClientIdEnvKey]
      : undefined;
    const clientSecret = entry.oauthClientSecretEnvKey
      ? env[entry.oauthClientSecretEnvKey]
      : undefined;
    return Boolean(clientId && clientSecret);
  }
  return isProviderConfigured(env, entry.provider);
}

export function isProviderConfigured(
  env: AppEnv,
  provider: ConnectionProvider,
): boolean {
  const entry = getIntegrationProvider(provider);

  if (!entry?.oauth) {
    return entry?.authType !== "oauth2";
  }

  return Boolean(
    env[entry.oauth.clientIdEnvKey] && env[entry.oauth.clientSecretEnvKey],
  );
}
