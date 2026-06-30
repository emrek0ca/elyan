import { expect, test } from '@playwright/test';

test('renders the Elyan desktop shell in browser preview mode', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Elyan', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Giriş', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Kayıt', exact: true })).toBeVisible();
  await expect(page.getByPlaceholder('E-posta')).toBeVisible();
  await expect(page.getByPlaceholder('Şifre')).toBeVisible();
});
