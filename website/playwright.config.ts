import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  retries: 0,
  use: {
    baseURL: 'http://127.0.0.1:3000'
  },
  webServer: {
    command: 'npm run dev',
    port: 3000,
    reuseExistingServer: true,
    timeout: 120000
  }
});
