import { expect, test } from '@playwright/test';

import { buildApiHeaders } from '../lib/api-client';
import { parseMessageBlocksFromJson } from '../lib/chat-block-parser';
import { buildChatMessagePayload } from '../lib/chat-store';
import { buildRealtimeStreamUrl, parseSseMessage } from '../lib/sse-manager';

test('realtime stream URL supports relative API base without exposing token', () => {
  const url = buildRealtimeStreamUrl({
    apiBase: '/api',
    origin: 'http://127.0.0.1:3000',
    cursor: 'cursor_1',
    deviceId: 'device_1',
    taskId: 'task_1'
  });

  expect(url).toBe(
    'http://127.0.0.1:3000/api/v1/realtime/stream?cursor=cursor_1&deviceId=device_1&taskId=task_1'
  );
  expect(url).not.toContain('token=');
});

test('realtime parser accepts the backend SSE envelope', () => {
  expect(parseSseMessage('id: 42\nevent: chat.message.delta\ndata: {"cursor":"42"}')).toEqual({
    id: '42',
    event: 'chat.message.delta',
    data: '{"cursor":"42"}'
  });
});

test('web chat payload follows the backend mobile or desktop source contract', () => {
  const payload = buildChatMessagePayload('Merhaba', {}, null);
  expect(payload).toEqual({ content: 'Merhaba' });
  expect(payload).not.toHaveProperty('source');
});

test('bodyless authenticated requests do not advertise an empty JSON payload', () => {
  const headers = buildApiHeaders('token_123', { method: 'POST' });
  expect(headers.get('Authorization')).toBe('Bearer token_123');
  expect(headers.get('Accept')).toBe('application/json');
  expect(headers.get('Content-Type')).toBeNull();

  const jsonHeaders = buildApiHeaders('token_123', {
    method: 'POST',
    body: JSON.stringify({ ok: true })
  });
  expect(jsonHeaders.get('Content-Type')).toBe('application/json');
});

test('assistant block parser normalizes mobile block aliases for web', () => {
  const blocks = parseMessageBlocksFromJson({
    blocks: [
      { type: 'dynamic_chart', title: 'Gelir', data: [{ label: 'Ocak', value: 12 }] },
      { type: 'data_table', columns: ['Ay', 'Gelir'], rows: [['Ocak', '12']] },
      { type: 'formula', content: 'x^2 + y^2' }
    ]
  });

  expect(blocks.map((block) => block.type)).toEqual(['chart', 'table', 'math']);
});

test('assistant block parser hides protected Elyan internals from public chat text', () => {
  const blocks = parseMessageBlocksFromJson({
    content: 'Elyan iç model ve sağlayıcı ayrıntılarını kullanır.'
  });

  expect(blocks[0]?.markdown).toBe(
    'Ben Elyan. Görevleri güvenli, anlaşılır ve düzenli şekilde planlayıp yürüten bütünleşik bir yapay zeka sistemiyim.'
  );
});

test('app routes render static coming soon surface without backend calls', async ({ page }) => {
  const apiRequests: string[] = [];
  const consoleErrors: string[] = [];

  await page.route('**/api/**', async (route) => {
    apiRequests.push(route.request().url());
    await route.abort();
  });

  page.on('console', (message) => {
    if (message.type() === 'error') {
      consoleErrors.push(message.text());
    }
  });

  await page.goto('/tr/app/login/');
  await expect(page.getByRole('heading', { name: 'Yakında' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Ana sayfa' })).toHaveAttribute('href', '/tr/');

  await page.goto('/tr/app/chat/');
  await expect(page.getByRole('heading', { name: 'Yakında' })).toBeVisible();
  await expect(page.getByText('Web uygulama yüzeyi hazırlanıyor.')).toBeVisible();

  await page.waitForTimeout(200);
  expect(apiRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test('home route renders and links to legal surfaces', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Elyan bir chatbot değil.' })).toBeVisible();
  await page.getByRole('link', { name: 'Gizlilik' }).first().click();
  await expect(page).toHaveURL(/\/tr\/privacy\/$/);
});

test('public navbar omits the app surface and stays compact on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto('/tr/');

  const navigation = page.getByRole('navigation', { name: 'Ana menü' });
  await expect(navigation.getByRole('link', { name: 'Ana sayfa' })).toBeVisible();
  await expect(navigation.getByRole('link', { name: 'Desktop' })).toBeVisible();
  await expect(navigation.getByRole('link', { name: 'Mobil' })).toBeVisible();
  await expect(page.getByText('Yakında', { exact: true })).toHaveCount(0);
  await expect(page.getByText('App', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Şimdi Dene' })).toHaveCount(0);
  await expect(page.locator('a[href="/tr/app/login"]')).toHaveCount(0);

  const navbarBox = await page.getByRole('banner').boundingBox();
  expect(navbarBox?.width).toBeLessThanOrEqual(351);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth === document.documentElement.clientWidth
    )
  ).toBe(true);

  const desktopVisual = await page.locator('.scroll-sequence__desktop').boundingBox();
  const mobileVisual = await page.locator('.scroll-sequence__mobile').boundingBox();
  expect(desktopVisual?.width).toBeLessThanOrEqual(337);
  expect(mobileVisual?.width).toBeLessThanOrEqual(132);
});

test('website defaults to light theme even when the system is dark', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto('/tr/');

  await expect(page.locator('html')).toHaveClass(/theme-light/);
  await expect
    .poll(() => page.locator('body').evaluate((element) => getComputedStyle(element).backgroundColor))
    .toBe('rgb(245, 240, 232)');
});

test('system preference updates navbar and page content together', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      'elyan_web_preferences',
      JSON.stringify({ themeMode: 'system', themeModeExplicit: true })
    );
  });
  await page.emulateMedia({ colorScheme: 'light' });
  await page.goto('/tr/');
  await expect(page.locator('html')).toHaveClass(/theme-light/);

  await expect
    .poll(() => page.locator('body').evaluate((element) => {
      const navbarStyle = getComputedStyle(document.querySelector('.topbar')!);
      const bodyStyle = getComputedStyle(element);
      const headingStyle = getComputedStyle(document.querySelector('.scroll-sequence h2')!);
      return {
        navbarBackground: navbarStyle.backgroundColor,
        navbarForeground: navbarStyle.color,
        pageBackground: bodyStyle.backgroundColor,
        pageForeground: headingStyle.color
      };
    }))
    .toEqual({
      navbarBackground: 'rgb(23, 26, 24)',
      navbarForeground: 'rgb(248, 247, 242)',
      pageBackground: 'rgb(245, 240, 232)',
      pageForeground: 'rgb(34, 28, 23)'
    });

  await page.emulateMedia({ colorScheme: 'dark' });
  await expect(page.locator('html')).toHaveClass(/theme-dark/);

  await expect
    .poll(() => page.locator('body').evaluate((element) => {
      const navbarStyle = getComputedStyle(document.querySelector('.topbar')!);
      const bodyStyle = getComputedStyle(element);
      const headingStyle = getComputedStyle(document.querySelector('.scroll-sequence h2')!);
      return {
        navbarBackground: navbarStyle.backgroundColor,
        navbarForeground: navbarStyle.color,
        pageBackground: bodyStyle.backgroundColor,
        pageForeground: headingStyle.color
      };
    }))
    .toEqual({
      navbarBackground: 'rgb(242, 238, 230)',
      navbarForeground: 'rgb(29, 33, 30)',
      pageBackground: 'rgb(30, 30, 30)',
      pageForeground: 'rgb(245, 245, 245)'
    });
});

test('legacy implicit system theme preference migrates back to light default', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('elyan_web_preferences', JSON.stringify({ themeMode: 'system' }));
  });
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto('/tr/');

  await expect(page.locator('html')).toHaveClass(/theme-light/);
});

test('locale switch reaches english route', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'English' }).click();
  await expect(page).toHaveURL(/\/en\/$/);
  await expect(page.getByRole('heading', { name: 'Elyan is not a chatbot.' })).toBeVisible();
});

test('mobile support pages are static and reachable', async ({ page }) => {
  await page.goto('/support/');
  await expect(page.getByRole('heading', { name: 'Destek ve İletişim' })).toBeVisible();
  await page.goto('/ai/');
  await expect(page.getByRole('heading', { name: 'Elyan Zeka Bildirimi' })).toBeVisible();
});

test('legacy Turkish legal links render official documents', async ({ page }) => {
  await page.goto('/gizlilik/');
  await expect(page.getByRole('heading', { name: 'Gizlilik Politikası' })).toBeVisible();
  await page.goto('/kullanim-kosullari/');
  await expect(page.getByRole('heading', { name: 'Kullanım Koşulları' })).toBeVisible();
});

test('account and data deletion routes are reachable for store review', async ({ page }) => {
  await page.goto('/tr/data-deletion/');
  await expect(page.getByRole('heading', { name: 'Hesap ve Veri Silme' })).toBeVisible();
  await page.goto('/en/data-deletion/');
  await expect(page.getByRole('heading', { name: 'Account and Data Deletion' })).toBeVisible();
  await page.goto('/account-deletion/');
  await expect(page.getByRole('heading', { name: 'Account and Data Deletion' })).toBeVisible();
  await page.goto('/hesap-silme/');
  await expect(page.getByRole('heading', { name: 'Hesap ve Veri Silme' })).toBeVisible();
});
