import type { AppEnv } from "../../config/env.js";
import type { ConnectionProvider, IntegrationAuthType } from "../../contracts/domain.js";

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
  capabilities: string[];
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
    description: "E-postaları ara, oku ve güvenli biçimde taslak oluştur.",
    iconKey: "gmail",
    category: "productivity",
    serverUrl: "https://gmailmcp.googleapis.com/mcp/v1",
    stage: "preview",
    authStrategy: "provider_bearer",
    oauthClientIdEnvKey: "GMAIL_MCP_CLIENT_ID",
    oauthClientSecretEnvKey: "GMAIL_MCP_CLIENT_SECRET",
    oauthScopes: [
      "openid",
      "email",
      "profile",
      "https://www.googleapis.com/auth/gmail.readonly",
      "https://www.googleapis.com/auth/gmail.compose",
    ],
    capabilities: ["gmail"],
  },
  {
    id: "google-drive",
    provider: "google",
    displayName: "Google Drive",
    description: "Drive dosyalarını bul, oku ve izin verilen içerikleri indir.",
    iconKey: "google_drive",
    category: "productivity",
    serverUrl: "https://drivemcp.googleapis.com/mcp/v1",
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
  },
  {
    id: "google-calendar",
    provider: "google",
    displayName: "Google Calendar",
    description: "Takvimleri ve etkinlikleri güvenli, salt okunur biçimde görüntüle.",
    iconKey: "google_calendar",
    category: "productivity",
    serverUrl: "https://calendarmcp.googleapis.com/mcp/v1",
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
    ],
    capabilities: ["calendar"],
  },
  {
    id: "notion",
    provider: "notion",
    displayName: "Notion",
    description: "Yetki verdiğin Notion çalışma alanında ara, oku ve düzenle.",
    iconKey: "notion",
    category: "productivity",
    serverUrl: "https://mcp.notion.com/mcp",
    stage: "setup_required",
    authStrategy: "mcp_oauth",
    oauthScopes: [],
    capabilities: ["notion"],
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
  },
  {
    id: "github",
    provider: "github",
    displayName: "GitHub",
    description: "Repository, issue ve pull request bağlamını kullan.",
    iconKey: "github",
    category: "developer",
    serverUrl: "https://api.githubcopilot.com/mcp/",
    stage: "setup_required",
    authStrategy: "mcp_oauth",
    oauthScopes: ["repo", "read:user", "user:email"],
    capabilities: ["github"],
  },
  {
    id: "slack",
    provider: "slack",
    displayName: "Slack",
    description: "Mesajları ve kanalları bağla; Elyan Slack uygulaması onayı gerekir.",
    iconKey: "slack",
    category: "communication",
    serverUrl: "https://mcp.slack.com/mcp",
    stage: "setup_required",
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
  },
];

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

export function isProviderConfigured(env: AppEnv, provider: ConnectionProvider): boolean {
  const entry = getIntegrationProvider(provider);

  if (!entry?.oauth) {
    return entry?.authType !== "oauth2";
  }

  return Boolean(env[entry.oauth.clientIdEnvKey] && env[entry.oauth.clientSecretEnvKey]);
}
