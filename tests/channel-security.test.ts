import { createHmac } from 'crypto';
import { describe, expect, it } from 'vitest';
import { verifyWhatsappCloudSignature } from '@/core/channels';

describe('Channel security', () => {
  it('verifies WhatsApp Cloud webhook signatures', () => {
    const body = JSON.stringify({ entry: [] });
    const secret = 'test-secret';
    const signature = `sha256=${createHmac('sha256', secret).update(body).digest('hex')}`;

    expect(verifyWhatsappCloudSignature(body, signature, secret)).toBe(true);
    expect(verifyWhatsappCloudSignature(body, 'sha256=bad', secret)).toBe(false);
  });

  it('allows unsigned WhatsApp payloads only when app secret is not configured', () => {
    expect(verifyWhatsappCloudSignature('{}', null, undefined)).toBe(true);
    expect(verifyWhatsappCloudSignature('{}', null, 'secret')).toBe(false);
  });
});
