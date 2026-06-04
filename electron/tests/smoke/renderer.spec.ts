import { expect, test } from '@playwright/test';

test('renders the Elyan desktop shell in browser preview mode', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Elyan', { exact: true })).toBeVisible();
  await expect(page.getByText('Giriş veya hesap')).toBeVisible();
  await expect(page.getByText('Giriş', { exact: true })).toBeVisible();
  await expect(page.getByText('Kayıt', { exact: true })).toBeVisible();
  await expect(page.getByText('Devam et')).toBeVisible();
});
