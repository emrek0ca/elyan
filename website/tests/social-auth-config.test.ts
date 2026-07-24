import { describe, expect, it } from 'vitest';
import { validAppleServiceId, validGoogleClientId, validHttpsUrl } from '../src/lib/client/auth-social';

describe('social auth public config validation', () => {
  it('does not treat deployment placeholders as active Google or Apple providers', () => {
    expect(validGoogleClientId('google-client-id')).toBe('');
    expect(validGoogleClientId('playwright-google-client-id.apps.googleusercontent.com')).toBe('');
    expect(validAppleServiceId('apple-service-id')).toBe('');
    expect(validHttpsUrl('http://elyan.dev/app/login')).toBe('');
  });

  it('accepts real provider-shaped public values', () => {
    const google = '762420924659-heq7v2qm19kqt9tj8tt14fef9u7s4dgh.apps.googleusercontent.com';
    expect(validGoogleClientId(google)).toBe(google);
    expect(validAppleServiceId('com.elyan.web')).toBe('com.elyan.web');
    expect(validHttpsUrl('https://elyan.dev/app/login')).toBe('https://elyan.dev/app/login');
  });
});
