import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/electron/smoke',
  timeout: 30000,
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://127.0.0.1:5173',
  },
  webServer: {
    command: 'npm run dev:renderer',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 30000,
  },
});
