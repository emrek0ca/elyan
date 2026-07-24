import { describe, expect, it } from 'vitest';
import { matchBffRule } from '../src/lib/server/bff-allowlist';
import { generatedIdempotencyKey, validIdempotencyKey } from '../src/lib/server/backend';

describe('BFF allowlist', () => {
  it('allows only known methods and Elyan paths', () => {
    expect(matchBffRule('POST', 'chat/messages')).toMatchObject({ idempotent: true });
    expect(matchBffRule('POST', 'pairing/sessions/claim-by-code')).toBeTruthy();
    expect(matchBffRule('GET', 'integrations/providers')).toBeTruthy();
    expect(matchBffRule('GET', 'integrations/connections')).toBeTruthy();
    expect(matchBffRule('POST', 'integrations/oauth/google/start')).toMatchObject({ idempotent: true });
    expect(matchBffRule('GET', 'mcp/servers')).toBeTruthy();
    expect(matchBffRule('POST', 'mcp/servers')).toMatchObject({ idempotent: true });
    expect(matchBffRule('PATCH', 'mcp/servers/00000000-0000-4000-8000-000000000001')).toMatchObject({ idempotent: true });
    expect(matchBffRule('POST', 'brain/connector-writes/11111111-1111-4111-8111-111111111111.22222222-2222-4222-8222-222222222222')).toMatchObject({ idempotent: true });
    expect(matchBffRule('GET', 'https://evil.invalid')).toBeNull();
    expect(matchBffRule('POST', 'billing/plans')).toBeNull();
    expect(matchBffRule('POST', 'integrations/gmail/send')).toBeNull();
    expect(matchBffRule('GET', 'integrations/runtime/mcp')).toBeNull();
    expect(matchBffRule('GET', '../auth/me')).toBeNull();
  });

  it('accepts bounded idempotency keys and generates scoped values', () => {
    expect(validIdempotencyKey('web:chat:12345678')).toBe('web:chat:12345678');
    expect(validIdempotencyKey('bad key')).toBeNull();
    expect(generatedIdempotencyKey('chat')).toMatch(/^web:chat:/);
  });
});
