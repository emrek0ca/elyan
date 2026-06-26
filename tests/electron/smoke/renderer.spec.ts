import { expect, test } from '@playwright/test';

test('renders the Elyan desktop shell in browser preview mode', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Elyan', { exact: true })).toBeVisible();
  await expect(page.getByText('Yerel runtime hazırlanıyor')).toBeVisible();
  await expect(page.getByText('Runtime hazırlanıyor', { exact: true })).toBeVisible();
  await expect(page.getByText('Yerel Elyan bağlantısı kurulduğunda giriş kutuları açılacak.')).toBeVisible();
});
