import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4321',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run build && node dist/server/entry.mjs',
    url: 'http://127.0.0.1:4321',
    reuseExistingServer: false,
    env: {
      ELYAN_API_BASE_URL: 'https://api.elyan.dev',
      ELYAN_WEB_ORIGIN: 'http://127.0.0.1:4321',
      ELYAN_WEB_SESSION_SECRET: 'playwright-session-secret-with-at-least-32-characters',
      PUBLIC_GOOGLE_CLIENT_ID: 'playwright-google-client-id.apps.googleusercontent.com',
      PUBLIC_APPLE_SERVICE_ID: 'dev.elyan.playwright',
      PUBLIC_APPLE_REDIRECT_URI: 'http://127.0.0.1:4321/app/login',
      HOST: '127.0.0.1',
      PORT: '4321',
    },
  },
  projects: [
    { name: 'desktop-chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'mobile-chromium', use: { ...devices['iPhone 13'], browserName: 'chromium', viewport: { width: 375, height: 812 } } },
  ],
});
