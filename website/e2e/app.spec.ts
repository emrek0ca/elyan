import { expect, test, type Page } from '@playwright/test';

declare global {
  interface Window {
    __elyanGoogleCallback?: (response: Record<string, unknown>) => void;
    google?: { accounts: { id: { initialize(config: Record<string, unknown>): void; renderButton(node: HTMLElement, config: Record<string, unknown>): void } } };
    AppleID?: { auth: { init(config: Record<string, unknown>): void; signIn(): Promise<Record<string, unknown>> } };
  }
}

const sessionId = '00000000-0000-4000-8000-000000000001';

async function blockProviders(page: Page) {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.addInitScript(() => {
    window.google = {
      accounts: {
        id: {
          initialize(config: Record<string, unknown>) {
            window.__elyanGoogleCallback = config.callback as ((response: Record<string, unknown>) => void);
          },
          renderButton(node: HTMLElement, _config: Record<string, unknown>) {
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = 'Continue with Google';
            button.addEventListener('click', () => window.__elyanGoogleCallback?.({ credential: 'google-id-token' }));
            node.replaceChildren(button);
          },
        },
      },
    };
    window.AppleID = {
      auth: {
        init(_config: Record<string, unknown>) {},
        async signIn() {
          return { authorization: { id_token: 'header.eyJub25jZSI6ImFwcGxlLW5vbmNlIn0.signature', code: 'apple-code', state: 'apple-state' } };
        },
      },
    };
  });
  await page.route(/accounts\.google\.com|appleid\.cdn-apple\.com/, (route) => route.abort());
}

async function authenticate(page: Page) {
  await page.context().addCookies([{ name: 'elyan-access', value: 'e2e-access', url: 'http://127.0.0.1:4321', httpOnly: true, sameSite: 'Lax' }]);
}

async function mockBootstrap(page: Page) {
  await page.route('**/app/api/auth/session', (route) => route.fulfill({ json: {
    user: { id: 'user-1', email: 'emre@example.com', displayName: 'Emre Koca' },
    subscription: { planCode: 'pro', status: 'active' },
    brain: { ready: true }, devices: [], summary: { pendingApprovals: 0, activeTasks: 0, connectedDesktops: 1 },
  } }));
}

test.describe('public homepage', () => {
  test('shows product entry points for web, mobile and desktop', async ({ page }) => {
    await page.route('https://api.github.com/repos/emrek0ca/elyan/releases/latest', (route) => route.fulfill({ json: {
      tag_name: 'v9.9.9',
      assets: [
        { name: 'elyan-darwin-universal.dmg', browser_download_url: 'https://github.com/emrek0ca/elyan/releases/download/v9.9.9/elyan-darwin-universal.dmg' },
        { name: 'elyan-windows-x64.exe', browser_download_url: 'https://github.com/emrek0ca/elyan/releases/download/v9.9.9/elyan-windows-x64.exe' },
        { name: 'elyan-linux-x64.AppImage', browser_download_url: 'https://github.com/emrek0ca/elyan/releases/download/v9.9.9/elyan-linux-x64.AppImage' },
      ],
    } }));
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /İşlerin/ })).toBeVisible();
    await expect(page.getByText('Ben Elyan. Web, mobil ve desktop runtime')).toBeVisible();
    await expect(page.getByText('İşi dağıtmam, işi toparlarım.')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Dene', exact: true })).toHaveAttribute('href', '/app');
    await expect(page.getByRole('link', { name: /App Store/ }).first()).toHaveAttribute('href', 'https://apps.apple.com/tr/app/elyan/id6779045459');
    await expect(page.getByText('npm install -g elyan').first()).toBeVisible();
    await expect(page.getByRole('link', { name: 'macOS' })).toHaveAttribute('href', 'https://github.com/emrek0ca/elyan/releases/download/v9.9.9/elyan-darwin-universal.dmg');
    await expect(page.getByRole('link', { name: 'Windows' })).toHaveAttribute('href', 'https://github.com/emrek0ca/elyan/releases/download/v9.9.9/elyan-windows-x64.exe');
    await expect(page.getByRole('link', { name: 'Linux' })).toHaveAttribute('href', 'https://github.com/emrek0ca/elyan/releases/download/v9.9.9/elyan-linux-x64.AppImage');
    await expect(page.locator('a[href="https://www.npmjs.com/package/elyan"]')).toHaveCount(0);
    await page.getByRole('link', { name: 'İndir' }).click();
    await expect(page.locator('#download')).toBeInViewport();
  });
});

test.describe('public auth cards', () => {
  test.beforeEach(async ({ page }) => blockProviders(page));

  test('login preserves the Elyan card and keyboard flow', async ({ page }, testInfo) => {
    const response = await page.goto('/app/login');
    expect(response?.headers()['content-security-policy']).toContain('https://accounts.google.com');
    await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
    await expect(page.getByLabel('Email')).not.toHaveAttribute('placeholder', /.+/);
    await expect(page.getByLabel('Password')).not.toHaveAttribute('placeholder', /.+/);
    await expect(page.getByRole('button', { name: 'Continue with Google' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign in with Apple' })).toBeVisible();
    await page.getByLabel('Email').fill('user@example.com');
    await page.getByLabel('Password').fill('password123');
    await page.keyboard.press('Tab');
    await expect(page.getByRole('button', { name: 'Sign In', exact: true })).toBeFocused();
    await expect(page).toHaveScreenshot(`login-${testInfo.project.name}.png`, { animations: 'disabled', fullPage: true });
  });

  test('register requires real legal acceptance', async ({ page }, testInfo) => {
    await page.goto('/app/register');
    await expect(page.getByRole('heading', { name: 'Create Account' })).toBeVisible();
    await expect(page.getByLabel('Full Name')).not.toHaveAttribute('placeholder', /.+/);
    await expect(page.getByLabel('Email')).not.toHaveAttribute('placeholder', /.+/);
    await expect(page.getByLabel('Password')).not.toHaveAttribute('placeholder', /.+/);
    await expect(page.getByRole('checkbox', { name: /Terms of Use/ })).toHaveAttribute('required', '');
    await expect(page.getByRole('checkbox', { name: /Privacy Policy/ })).toHaveAttribute('required', '');
    await expect(page).toHaveScreenshot(`register-${testInfo.project.name}.png`, { animations: 'disabled', fullPage: true });
  });

  test('Google and Apple sign-in submit through the website BFF', async ({ page }) => {
    let googleCompleted = false;
    let appleCompleted = false;
    await page.route('**/app/api/auth/oauth/google', async (route) => {
      const body = route.request().postDataJSON();
      expect(body.credential).toBe('google-id-token');
      expect(body.register).toBe(false);
      googleCompleted = true;
      await route.fulfill({ json: { ok: true } });
    });
    await page.route('**/app/api/auth/oauth/apple-transaction', (route) => route.fulfill({ json: { state: 'apple-state', nonce: 'apple-nonce' } }));
    await page.route('**/app/api/auth/oauth/apple', async (route) => {
      const body = route.request().postDataJSON();
      expect(body.authorizationCode).toBe('apple-code');
      expect(body.state).toBe('apple-state');
      expect(body.register).toBe(false);
      appleCompleted = true;
      await route.fulfill({ json: { ok: true } });
    });
    await page.goto('/app/login');
    await page.getByRole('button', { name: 'Continue with Google' }).click();
    await expect.poll(() => googleCompleted).toBe(true);
    await page.goto('/app/login');
    await page.getByRole('button', { name: 'Sign in with Apple' }).click();
    await expect.poll(() => appleCompleted).toBe(true);
  });
});

test.describe('authenticated web app', () => {
  test.beforeEach(async ({ page }) => { await page.emulateMedia({ reducedMotion: 'reduce' }); await authenticate(page); await mockBootstrap(page); });

  test('chat loads backend history and sends a web block message', async ({ page }, testInfo) => {
    const consoleErrors: string[] = [];
    page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
    await page.route('**/app/api/backend/web/warmup', (route) => route.fulfill({ status: 202, json: { queued: true } }));
    await page.route((url) => url.pathname === '/app/api/backend/chat/sessions', (route) => {
      const archived = new URL(route.request().url()).searchParams.get('status') === 'archived';
      return route.fulfill({ json: { sessions: archived ? [] : [{ id: sessionId, title: 'Elyan Web Integration', status: 'active' }], hasMore: false, nextCursor: null } });
    });
    await page.route((url) => url.pathname === `/app/api/backend/chat/sessions/${sessionId}/messages`, (route) => route.fulfill({ json: { messages: [
      { id: 'user-message', role: 'user', content: 'Connect me to Elyan.' },
      { id: 'assistant-message', role: 'assistant', status: 'completed', blocks: [{ type: 'text', version: 1, blockId: 'b1', source: 'elyan', visibility: 'user_visible', renderHints: {}, data: { markdown: 'Elyan brain is **ready**.' } }] },
    ], hasMore: false, nextCursor: null } }));
    await page.route('**/app/api/realtime/stream*', (route) => route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'event: connected\ndata: {"type":"connected"}\n\n' }));
    await page.route('**/app/api/backend/chat/messages', async (route) => {
      const body = route.request().postDataJSON(); expect(body.source).toBe('web'); expect(body.blocks[0]).toMatchObject({ type: 'text', markdown: 'Run a web task', version: 1, source: 'web', visibility: 'user_visible', renderHints: {}, data: { markdown: 'Run a web task' } });
      expect(body.metadata.blockProtocol).toBe('elyan_blocks.v2'); expect(body.metadata.blockSchemaDigest).toBeTruthy();
      await route.fulfill({ json: { session: { id: sessionId }, userMessage: { id: 'sent-user', role: 'user', content: body.blocks[0].markdown }, assistantMessage: { id: 'sent-assistant', role: 'assistant', content: 'Received by Elyan.', status: 'completed' } } });
    });
    const response = await page.goto('/app');
    expect(response?.headers()['content-security-policy']).not.toContain('iyzipay.com');
    expect(response?.headers()['content-security-policy']).not.toContain('accounts.google.com');
    await expect(page.getByText('Elyan brain is ready.')).toBeVisible();
    await page.getByLabel('Message Elyan').fill('Run a web task'); await page.getByRole('button', { name: 'Send message' }).click();
    await expect(page.getByText('Received by Elyan.')).toBeVisible();
    expect(consoleErrors.join('\n')).not.toMatch(/require is not defined|Outdated Optimize Dep/);
    await expect(page).toHaveScreenshot(`chat-${testInfo.project.name}.png`, { animations: 'disabled' });
  });

  test('composer attaches derived file context and capability hints', async ({ page }) => {
    await page.route('**/app/api/backend/web/warmup', (route) => route.fulfill({ status: 202, json: { queued: true } }));
    await page.route((url) => url.pathname === '/app/api/backend/chat/sessions', (route) => route.fulfill({ json: { sessions: [], hasMore: false } }));
    await page.route('**/app/api/realtime/stream*', (route) => route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'event: connected\ndata: {"type":"connected"}\n\n' }));
    await page.route('**/app/api/backend/chat/messages', async (route) => {
      const body = route.request().postDataJSON();
      expect(body.requestedCapabilities).toContain('documents');
      expect(body.blocks[0].markdown).toContain('Readable preview from plan.md');
      expect(body.blocks[0].markdown).toContain('Elyan web attachment');
      expect(body.metadata.attachments[0]).toMatchObject({
        fileName: 'plan.md',
        mimeType: 'text/markdown',
        raw_file_uploaded: false,
        hasReadableText: true,
      });
      expect(JSON.stringify(body.metadata.attachments)).not.toMatch(/base64|raw_file_uploaded\":true/);
      await route.fulfill({ json: { session: { id: sessionId }, userMessage: { id: 'sent-file', role: 'user', content: 'Use this file' }, assistantMessage: { id: 'sent-file-assistant', role: 'assistant', content: 'Attachment received.', status: 'completed' } } });
    });
    await page.goto('/app');
    await page.locator('#composer-menu-button').click();
    const fileChooser = page.waitForEvent('filechooser');
    await page.getByRole('menuitem', { name: 'Attach files' }).click();
    await (await fileChooser).setFiles({ name: 'plan.md', mimeType: 'text/markdown', buffer: Buffer.from('Elyan web attachment') });
    await expect(page.getByText('plan.md')).toBeVisible();
    await page.locator('#composer-menu-button').click();
    await page.getByRole('menuitem').filter({ hasText: 'Documents' }).click();
    await expect(page.getByText(/Documents ×/)).toBeVisible();
    await page.getByLabel('Message Elyan').fill('Use this file');
    await page.getByRole('button', { name: 'Send message' }).click();
    await expect(page.getByText('Attachment received.')).toBeVisible();
  });


  test('settings loads profile and real security controls', async ({ page }, testInfo) => {
    await page.route('**/app/api/backend/auth/2fa/status', (route) => route.fulfill({ json: { twoFactor: { enabled: false } } }));
    await page.route('**/app/api/backend/auth/2fa/setup', (route) => route.fulfill({ json: { twoFactor: { enabled: false, secret: 'TEST-SECRET' } } }));
    await page.route('**/app/api/backend/auth/2fa/enable', (route) => route.fulfill({ json: { twoFactor: { enabled: true } } }));
    await page.route('**/app/api/auth/logout', async (route) => { await page.context().clearCookies({ name: 'elyan-access' }); await route.fulfill({ json: { ok: true } }); });
    await page.goto('/app/settings');
    await expect(page.getByLabel('Display Name')).toHaveValue('Emre Koca');
    await expect(page.getByRole('button', { name: 'Set up 2FA' })).toBeVisible();
    await expect(page).toHaveScreenshot(`settings-${testInfo.project.name}.png`, { animations: 'disabled', fullPage: true });
    await page.getByRole('button', { name: 'Set up 2FA' }).click();
    await page.getByLabel('Authenticator code').fill('123456');
    await page.getByRole('button', { name: 'Enable 2FA' }).click();
    await expect(page.getByText('Enabled', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Sign Out' }).click();
    await expect(page).toHaveURL(/\/app\/login$/);
  });

  test('sidebar profile link opens settings without relying on chat initialization', async ({ page }) => {
    await page.route('**/app/api/backend/web/warmup', (route) => route.fulfill({ status: 202, json: { queued: true } }));
    await page.route('**/app/api/backend/chat/sessions**', (route) => route.fulfill({ json: { sessions: [], hasMore: false } }));
    await page.route('**/app/api/realtime/stream*', (route) => route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'event: connected\ndata: {"type":"connected"}\n\n' }));
    await page.goto('/app');
    await expect(page.locator('#sidebar-profile')).toHaveAttribute('href', '/app/settings');
    const sidebarProfile = page.locator('#sidebar-profile');
    if (await sidebarProfile.isVisible()) await sidebarProfile.click();
    else await page.getByRole('link', { name: 'Open settings' }).click();
    await expect(page).toHaveURL(/\/app\/settings$/);
  });

  test('billing renders plans and token truth without overflow', async ({ page }, testInfo) => {
    let cancellationRequested = false;
    await page.route('**/app/api/backend/billing/summary', (route) => route.fulfill({ json: { billing: { billingState: { plan: { code: 'pro', status: 'active', source: 'iyzico' }, usage: { tokens: { used: 200, limit: 2000 }, tasks: { used: 12, limit: 2000 }, imageGeneration: { used: 2, limit: 20 } }, welcomePro: { eligible: false }, actions: { canCancel: true } }, subscription: { planCode: 'pro' } } } }));
    await page.route('**/app/api/backend/billing/plans', (route) => route.fulfill({ json: { currentPlanCode: 'pro', plans: [
      { code: 'free', label: 'Free', monthlyPrice: 0, currencyCode: 'USD' }, { code: 'solo', label: 'Solo', monthlyPrice: 6.99, currencyCode: 'USD' }, { code: 'pro', label: 'Pro', monthlyPrice: 17.99, currencyCode: 'USD', current: true },
    ] } }));
    await page.route('**/app/api/backend/billing/profile', (route) => route.fulfill({ json: { profile: { isComplete: false, profile: { email: 'emre@example.com' } } } }));
    await page.route('**/app/api/backend/billing/subscription/cancel', async (route) => { cancellationRequested = true; expect(route.request().headers()['idempotency-key']).toMatch(/^web:/); await route.fulfill({ json: { billing: { status: 'canceled' } } }); });
    await page.goto('/app/settings/billing');
    await expect(page.getByText('Elyan Pro')).toBeVisible(); await expect(page.getByText('200 / 2000')).toBeVisible();
    await expect(page.locator('body')).not.toHaveCSS('overflow-x', 'scroll');
    await expect(page).toHaveScreenshot(`billing-${testInfo.project.name}.png`, { animations: 'disabled', fullPage: true });
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: 'Cancel Subscription' }).click();
    await expect(page.getByText('Subscription cancellation scheduled.')).toBeVisible(); expect(cancellationRequested).toBe(true);
  });

  test('restores a pending approval from chat history and submits an idempotent decision', async ({ page }) => {
    const taskId = '00000000-0000-4000-8000-000000000009';
    await page.route('**/app/api/backend/web/warmup', (route) => route.fulfill({ status: 202, json: { queued: true } }));
    await page.route((url) => url.pathname === '/app/api/backend/chat/sessions', (route) => {
      const archived = new URL(route.request().url()).searchParams.get('status') === 'archived';
      return route.fulfill({ json: { sessions: archived ? [] : [{ id: sessionId, title: 'Approval task', status: 'active' }], hasMore: false } });
    });
    await page.route((url) => url.pathname === `/app/api/backend/chat/sessions/${sessionId}/messages`, (route) => route.fulfill({ json: { messages: [{
      id: 'approval-message', role: 'assistant', taskId, status: 'running', blocks: [{ type: 'task_trace', version: 1, blockId: 'approval-block', source: 'elyan', visibility: 'user_visible', renderHints: {}, data: { taskId, status: 'waiting_approval', title: 'Approval needed', steps: [{ title: 'Confirm action', status: 'waiting_approval' }] } }],
    }], hasMore: false } }));
    await page.route('**/app/api/realtime/stream*', (route) => route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'event: connected\ndata: {"type":"connected"}\n\n' }));
    let approved = false;
    await page.route(`**/app/api/backend/tasks/${taskId}/approval`, async (route) => {
      approved = route.request().postDataJSON().approved === true;
      expect(route.request().headers()['idempotency-key']).toMatch(/^web:/);
      await route.fulfill({ json: { ok: true } });
    });
    await page.goto('/app');
    await expect(page.getByText('Approval needed')).toBeVisible();
    await page.getByRole('button', { name: 'Approve' }).click();
    expect(approved).toBe(true);
  });

  test('pairs a desktop and completes integration OAuth through bounded popup polling', async ({ page }) => {
    let paired = false; let oauthStarted = false;
    await page.route('**/app/api/backend/devices', (route) => route.fulfill({ json: { devices: paired ? [{ id: '00000000-0000-4000-8000-000000000010', type: 'desktop', label: 'Elyan Desktop', isActive: true, runtime: { isConnected: true } }] : [] } }));
    await page.route('**/app/api/backend/pairing/sessions/claim-by-code', async (route) => { paired = route.request().postDataJSON().pairingCode === 'ABC123'; await route.fulfill({ json: { paired: true } }); });
    await page.goto('/app/settings/devices');
    await page.getByLabel('Pairing code').fill('ABC123'); await page.getByRole('button', { name: 'Pair Desktop' }).click();
    await expect(page.getByText('Elyan Desktop')).toBeVisible(); expect(paired).toBe(true);

    await page.addInitScript(() => { window.open = (() => { let closed = false; return { get closed() { return closed; }, close() { closed = true; } }; }) as typeof window.open; });
    await page.route('**/app/api/backend/integrations/apps**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/oauth/start')) {
        expect(route.request().postDataJSON()).toEqual({}); oauthStarted = true;
        await route.fulfill({ json: { authUrl: 'https://accounts.google.com/o/oauth2/v2/auth' } }); return;
      }
      await route.fulfill({ json: { apps: [{ id: 'gmail', displayName: 'Gmail', description: 'Mail access', available: true, connected: oauthStarted }] } });
    });
    await page.goto('/app/settings/integrations');
    await page.getByRole('button', { name: 'Connect' }).click();
    await expect(page.getByText('Integration connected.')).toBeVisible({ timeout: 5000 });
  });
});
