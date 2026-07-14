import assert from "node:assert/strict";
import test from "node:test";
import {
  getIntegrationMcpApp,
  getIntegrationProvider,
  integrationMcpAppCatalog,
} from "./modules/integrations/provider-registry.js";
import { normalizeOauthRedirectUri } from "./modules/integrations/service.js";

test("curated MCP app catalog has unique ids and trusted https endpoints", () => {
  const ids = integrationMcpAppCatalog.map((entry) => entry.id);
  assert.equal(new Set(ids).size, ids.length);
  assert.ok(ids.includes("gmail"));
  assert.ok(ids.includes("google-drive"));
  assert.ok(ids.includes("google-calendar"));

  for (const entry of integrationMcpAppCatalog) {
    const url = new URL(entry.serverUrl);
    assert.equal(url.protocol, "https:");
    assert.ok(entry.displayName.length > 0);
    assert.ok(entry.capabilities.length > 0);
  }
});

test("Gmail app uses the official Google remote MCP endpoint and incremental scopes", () => {
  const gmail = getIntegrationMcpApp("gmail");
  const drive = getIntegrationMcpApp("google-drive");
  const calendar = getIntegrationMcpApp("google-calendar");
  assert.ok(gmail);
  assert.ok(drive);
  assert.ok(calendar);
  assert.equal(gmail.serverUrl, "https://gmailmcp.googleapis.com/mcp/v1");
  assert.ok(gmail.oauthScopes.includes("https://www.googleapis.com/auth/gmail.readonly"));
  assert.ok(gmail.oauthScopes.includes("https://www.googleapis.com/auth/gmail.compose"));
  assert.ok(!gmail.oauthScopes.includes("https://www.googleapis.com/auth/gmail.send"));
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

test("MCP-native OAuth apps stay unavailable until the dedicated client flow exists", () => {
  const notion = getIntegrationMcpApp("notion");
  const github = getIntegrationMcpApp("github");
  const slack = getIntegrationMcpApp("slack");
  assert.ok(notion && github && slack);
  assert.equal(notion.authStrategy, "mcp_oauth");
  assert.equal(notion.stage, "setup_required");
  assert.equal(github.stage, "setup_required");
  assert.equal(slack.stage, "setup_required");
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
});
