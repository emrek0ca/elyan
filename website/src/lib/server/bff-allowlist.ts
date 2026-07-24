type Rule = { method: string; path: RegExp; idempotent?: boolean };

const uuid = '[0-9a-fA-F-]{36}';
const appId = '[a-z0-9-]{1,80}';
const provider = '[a-z0-9_-]{1,80}';
const connectorWriteToken = '[A-Za-z0-9._-]{16,512}';

export const BFF_RULES: Rule[] = [
  { method: 'GET', path: /^web\/bootstrap$/ },
  { method: 'POST', path: /^web\/warmup$/, idempotent: true },
  { method: 'GET', path: /^auth\/me$/ },
  { method: 'PATCH', path: /^auth\/me$/ },
  { method: 'DELETE', path: /^auth\/me$/ },
  { method: 'POST', path: /^auth\/password$/ },
  { method: 'GET', path: /^auth\/2fa\/status$/ },
  { method: 'POST', path: /^auth\/2fa\/(setup|enable|disable)$/ },
  { method: 'GET', path: /^chat\/sessions$/ },
  { method: 'POST', path: /^chat\/sessions$/, idempotent: true },
  { method: 'DELETE', path: /^chat\/sessions$/ },
  { method: 'GET', path: new RegExp(`^chat/sessions/${uuid}$`) },
  { method: 'PATCH', path: new RegExp(`^chat/sessions/${uuid}$`) },
  { method: 'DELETE', path: new RegExp(`^chat/sessions/${uuid}$`) },
  { method: 'GET', path: new RegExp(`^chat/sessions/${uuid}/messages$`) },
  { method: 'POST', path: /^chat\/messages$/, idempotent: true },
  { method: 'GET', path: /^tasks$/ },
  { method: 'GET', path: new RegExp(`^tasks/${uuid}$`) },
  { method: 'POST', path: new RegExp(`^tasks/${uuid}/(cancel|approval|feedback)$`), idempotent: true },
  { method: 'GET', path: new RegExp(`^tasks/${uuid}/artifacts/${uuid}$`) },
  { method: 'GET', path: new RegExp(`^tasks/${uuid}/artifacts/${uuid}/content$`) },
  { method: 'GET', path: /^devices$/ },
  { method: 'POST', path: new RegExp(`^devices/${uuid}/deactivate$`), idempotent: true },
  { method: 'POST', path: /^pairing\/sessions\/claim-by-code$/, idempotent: true },
  { method: 'GET', path: /^billing\/(plans|summary|profile)$/ },
  { method: 'PUT', path: /^billing\/profile$/ },
  { method: 'POST', path: /^billing\/checkout\/init$/, idempotent: true },
  { method: 'GET', path: new RegExp(`^billing/checkouts/${uuid}$`) },
  { method: 'POST', path: /^billing\/subscription\/(change-plan|cancel)$/, idempotent: true },
  { method: 'POST', path: /^billing\/trials\/pro\/claim$/, idempotent: true },
  { method: 'GET', path: /^integrations\/apps$/ },
  { method: 'GET', path: /^integrations\/providers$/ },
  { method: 'GET', path: /^integrations\/connections$/ },
  { method: 'POST', path: new RegExp(`^integrations/apps/${appId}/oauth/start$`), idempotent: true },
  { method: 'POST', path: new RegExp(`^integrations/apps/${appId}/probe$`), idempotent: true },
  { method: 'DELETE', path: new RegExp(`^integrations/apps/${appId}$`), idempotent: true },
  { method: 'POST', path: new RegExp(`^integrations/oauth/${provider}/start$`), idempotent: true },
  { method: 'DELETE', path: new RegExp(`^integrations/connections/${uuid}$`), idempotent: true },
  { method: 'GET', path: /^mcp\/servers$/ },
  { method: 'POST', path: /^mcp\/servers$/, idempotent: true },
  { method: 'PATCH', path: new RegExp(`^mcp/servers/${uuid}$`), idempotent: true },
  { method: 'POST', path: new RegExp(`^brain/connector-writes/${connectorWriteToken}$`), idempotent: true },
];

export function matchBffRule(method: string, path: string): Rule | null {
  if (!/^[A-Za-z0-9/_.-]+$/.test(path) || path.includes('..') || path.startsWith('/')) return null;
  return BFF_RULES.find((rule) => rule.method === method.toUpperCase() && rule.path.test(path)) || null;
}
