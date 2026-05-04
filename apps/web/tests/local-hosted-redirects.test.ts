import { describe, expect, it, vi } from 'vitest';

const redirect = vi.fn();

vi.mock('next/navigation', () => ({
  redirect,
}));

describe('local hosted surface redirects', () => {
  it('sends local auth and panel routes to elyan.dev', async () => {
    const authPage = (await import('@/app/auth/page')).default;
    const panelPage = (await import('@/app/panel/page')).default;
    const accountPage = (await import('@/app/panel/account/page')).default;
    const billingPage = (await import('@/app/panel/billing/page')).default;
    const devicesPage = (await import('@/app/panel/devices/page')).default;
    const notificationsPage = (await import('@/app/panel/notifications/page')).default;
    const usagePage = (await import('@/app/panel/usage/page')).default;

    authPage();
    panelPage();
    accountPage();
    billingPage();
    devicesPage();
    notificationsPage();
    usagePage();

    expect(redirect).toHaveBeenCalledWith('https://elyan.dev/auth');
    expect(redirect).toHaveBeenCalledWith('https://elyan.dev/panel');
    expect(redirect).toHaveBeenCalledWith('https://elyan.dev/panel/account');
    expect(redirect).toHaveBeenCalledWith('https://elyan.dev/panel/billing');
    expect(redirect).toHaveBeenCalledWith('https://elyan.dev/panel/sync');
    expect(redirect).toHaveBeenCalledWith('https://elyan.dev/panel/notifications');
    expect(redirect).toHaveBeenCalledWith('https://elyan.dev/panel/usage');
  });
});
