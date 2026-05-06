import { mkdir } from 'fs/promises';
import { z } from 'zod';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';
import { loadBrowserStorageState, persistBrowserStorageState } from '@/core/dispatch/runtime/browser-session';
import { appendJsonLine, readJsonFile } from '@/core/dispatch/runtime/workspace';

type Page = import('playwright').Page;
type BrowserContext = import('playwright').BrowserContext;

type BrowserSnapshotLink = {
  href: string;
  text: string;
};

type BrowserActionTrace = {
  timestamp: string;
  kind: 'browser';
  taskId: string;
  status: 'running' | 'success' | 'failure';
  note: string;
  data?: Record<string, unknown>;
};

class BrowserCapabilityError extends Error {
  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'BrowserCapabilityError';

    if (cause !== undefined) {
      (this as Error & { cause?: unknown }).cause = cause;
    }
  }
}

const browserSnapshotSchema = z.object({
  url: z.string().url(),
  title: z.string(),
  text: z.string(),
  links: z.array(
    z.object({
      href: z.string(),
      text: z.string(),
    })
  ),
});

const webReadDynamicInputSchema = z.object({
  url: z.string().url(),
  settleMs: z.number().int().min(0).max(5000).default(300),
});

const webReadDynamicOutputSchema = browserSnapshotSchema;

const browserActionSchema = z.discriminatedUnion('type', [
  z.object({
    type: z.literal('click'),
    selector: z.string().min(1),
  }),
  z.object({
    type: z.literal('fill'),
    selector: z.string().min(1),
    value: z.string(),
  }),
  z.object({
    type: z.literal('press'),
    key: z.string().min(1),
  }),
  z.object({
    type: z.literal('waitForText'),
    text: z.string().min(1),
  }),
  z.object({
    type: z.literal('waitForSelector'),
    selector: z.string().min(1),
  }),
]);

const browserAutomationInputSchema = z.object({
  url: z.string().url(),
  actions: z.array(browserActionSchema).min(1).max(20),
  settleMs: z.number().int().min(0).max(5000).default(150),
});

const browserAutomationOutputSchema = browserSnapshotSchema.extend({
  actionsApplied: z.number().int().nonnegative(),
});

function compareStrings(left: string, right: string) {
  if (left < right) {
    return -1;
  }

  if (left > right) {
    return 1;
  }

  return 0;
}

function compareLinks(left: BrowserSnapshotLink, right: BrowserSnapshotLink) {
  return compareStrings(left.href, right.href) || compareStrings(left.text, right.text);
}

function dedupeLinks(links: BrowserSnapshotLink[]) {
  const seen = new Set<string>();

  return links.filter((link) => {
    const key = `${link.href}\u0000${link.text}`;
    if (seen.has(key)) {
      return false;
    }

    seen.add(key);
    return true;
  });
}

function normalizeHost(url: string) {
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return '';
  }
}

function isSensitiveBrowserHost(hostname: string) {
  return [
    'accounts.google.com',
    'login.microsoftonline.com',
    'paypal.com',
    'stripe.com',
    'iyzipay.com',
    'iyzico.com',
    'bank',
    'billing',
    'checkout',
    'payment',
  ].some((pattern) => hostname === pattern || hostname.endsWith(`.${pattern}`) || hostname.includes(pattern));
}

async function readApprovalState(runtime: CapabilityExecutionContext['runtime']) {
  if (!runtime?.approvalCheckpointPath) {
    return undefined;
  }

  const state = await readJsonFile<{ approval?: { state?: string; required?: boolean } }>(runtime.approvalCheckpointPath);
  return state?.approval;
}

async function recordBrowserTrace(runtime: CapabilityExecutionContext['runtime'], status: BrowserActionTrace['status'], note: string, data?: Record<string, unknown>) {
  if (!runtime?.tracePath) {
    return;
  }

  await appendJsonLine(runtime.tracePath, {
    timestamp: new Date().toISOString(),
    kind: 'browser',
    taskId: runtime.taskId ?? 'unknown',
    status,
    note,
    data,
  } satisfies BrowserActionTrace).catch(() => undefined);
}

async function persistReplaySnapshot(
  page: Page,
  runtime: CapabilityExecutionContext['runtime'],
  label: string,
  extra?: Record<string, unknown>
) {
  if (!runtime?.workspacePath) {
    return;
  }

  const replayPath = `${runtime.workspacePath}/browser/replay.jsonl`;
  const snapshot = {
    timestamp: new Date().toISOString(),
    label,
    url: page.url(),
    title: await page.title().catch(() => ''),
    extra,
  };

  await appendJsonLine(replayPath, snapshot).catch(() => undefined);
}

async function collectLinksFromPage(page: Page) {
  const links = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('a[href]'))
      .map((anchor) => {
        const element = anchor as HTMLAnchorElement;
        return {
          href: element.href,
          text: (element.textContent || '').replace(/\s+/g, ' ').trim(),
        };
      })
      .filter((link) => link.href.length > 0);
  });

  return dedupeLinks(links.sort(compareLinks)).slice(0, 20);
}

async function collectSnapshot(page: Page, includeLinks = true) {
  const [title, text] = await Promise.all([
    page.title(),
    page.evaluate(() => (document.body?.innerText || document.documentElement?.innerText || '').replace(/\s+/g, ' ').trim()),
  ]);

  const links = includeLinks ? await collectLinksFromPage(page) : [];

  return {
    url: page.url(),
    title: title.trim(),
    text: text.slice(0, 8000),
    links,
  };
}

async function withBrowserPage<T>(
  runtime: CapabilityExecutionContext['runtime'],
  signal: AbortSignal,
  run: (page: Page) => Promise<T>
): Promise<T> {
  const { chromium } = await import('playwright');
  if (signal.aborted) {
    throw new Error('Browser operation aborted.');
  }
  await recordBrowserTrace(runtime, 'running', 'Launching isolated browser page.');
  const browser = await chromium.launch({ headless: true });
  const storageState = await loadBrowserStorageState(runtime);
  const context = await browser.newContext(
    storageState
      ? {
          storageState,
        }
      : {}
  );

  try {
    const page = await context.newPage();
    const downloadDir = runtime?.workspacePath ? `${runtime.workspacePath}/browser/downloads` : undefined;
    const abortBrowser = () => {
      void browser.close().catch(() => undefined);
    };
    signal.addEventListener('abort', abortBrowser, { once: true });
    page.on('download', async (download) => {
      if (!downloadDir) {
        return;
      }

      try {
        await mkdir(downloadDir, { recursive: true });
        const suggested = download.suggestedFilename().replace(/[^a-zA-Z0-9._-]+/g, '_');
        await download.saveAs(`${downloadDir}/${Date.now()}-${suggested}`);
        await recordBrowserTrace(runtime, 'running', 'Captured browser download.', {
          suggestedFilename: suggested,
        });
      } catch {
        await recordBrowserTrace(runtime, 'failure', 'Browser download could not be saved.');
      }
    });
    try {
      return await run(page);
    } finally {
      signal.removeEventListener('abort', abortBrowser);
    }
  } finally {
    await persistBrowserStorageState(context as BrowserContext, runtime).catch(() => undefined);
    await context.close().catch(() => undefined);
    await browser.close().catch(() => undefined);
  }
}

async function loadDynamicPage(
  url: string,
  settleMs: number,
  runtime: CapabilityExecutionContext['runtime'],
  signal: AbortSignal
) {
  return await withBrowserPage(runtime, signal, async (page) => {
    try {
      const hostname = normalizeHost(url);
      const approval = await readApprovalState(runtime);
      if (isSensitiveBrowserHost(hostname) && approval?.state !== 'approved') {
        throw new BrowserCapabilityError(`Sensitive browser target requires approval: ${hostname}`);
      }

      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 12_000 });
      if (signal.aborted) {
        throw new BrowserCapabilityError('Browser operation aborted.');
      }
      await page.waitForLoadState('networkidle', { timeout: 2_500 }).catch(() => undefined);
      if (settleMs > 0) {
        await page.waitForTimeout(settleMs);
      }
      const snapshot = await collectSnapshot(page, true);
      await persistReplaySnapshot(page, runtime, 'dynamic-read', {
        url,
        links: snapshot.links.length,
      });
      await recordBrowserTrace(runtime, 'success', `Read dynamic page ${url}`, {
        url,
        title: snapshot.title,
        linkCount: snapshot.links.length,
      });
      return snapshot;
    } catch (error) {
      await recordBrowserTrace(runtime, 'failure', `Unable to read dynamic page: ${url}`, {
        error: error instanceof Error ? error.message : String(error),
      });
      throw new BrowserCapabilityError(`Unable to read dynamic page: ${url}`, error);
    }
  });
}

export async function automateBrowser(
  url: string,
  actions: z.output<typeof browserAutomationInputSchema>['actions'],
  settleMs: number,
  runtime: CapabilityExecutionContext['runtime'],
  signal: AbortSignal
) {
  return await withBrowserPage(runtime, signal, async (page) => {
    try {
      const hostname = normalizeHost(url);
      const approval = await readApprovalState(runtime);
      if (isSensitiveBrowserHost(hostname) && approval?.state !== 'approved') {
        throw new BrowserCapabilityError(`Sensitive browser target requires approval: ${hostname}`);
      }

      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 12_000 });
      if (signal.aborted) {
        throw new BrowserCapabilityError('Browser operation aborted.');
      }

      const performAction = async (label: string, action: () => Promise<void>, selector?: string) => {
        if (signal.aborted) {
          throw new BrowserCapabilityError('Browser operation aborted.');
        }
        const attempt = async () => {
          await action();
        };

        try {
          await attempt();
        } catch (error) {
          if (!selector) {
            throw error;
          }

          await page.locator(selector).waitFor({ state: 'visible', timeout: 2_500 }).catch(() => undefined);
          await attempt();
        } finally {
          await recordBrowserTrace(runtime, 'running', `Applied browser action: ${label}`, {
            url,
            selector,
          });
        }
      };

      for (const action of actions) {
        switch (action.type) {
          case 'click':
            await performAction(`click ${action.selector}`, () => page.locator(action.selector).click({ timeout: 5_000 }), action.selector);
            break;
          case 'fill':
            await performAction(`fill ${action.selector}`, () => page.locator(action.selector).fill(action.value, { timeout: 5_000 }), action.selector);
            break;
          case 'press':
            await performAction(`press ${action.key}`, () => page.keyboard.press(action.key));
            break;
          case 'waitForText':
            await performAction(`waitForText ${action.text}`, () => page.getByText(action.text, { exact: false }).first().waitFor({ state: 'visible', timeout: 5_000 }));
            break;
          case 'waitForSelector':
            await performAction(`waitForSelector ${action.selector}`, () => page.locator(action.selector).waitFor({ state: 'visible', timeout: 5_000 }), action.selector);
            break;
        }
      }

      await page.waitForLoadState('networkidle', { timeout: 2_500 }).catch(() => undefined);
      if (settleMs > 0) {
        await page.waitForTimeout(settleMs);
      }

      const snapshot = {
        ...(await collectSnapshot(page, true)),
        actionsApplied: actions.length,
      };
      await persistReplaySnapshot(page, runtime, 'automation', {
        url,
        actionsApplied: actions.length,
        fileInputs: await page.locator('input[type="file"]').count().catch(() => 0),
      });
      await recordBrowserTrace(runtime, 'success', `Automated browser page ${url}`, {
        url,
        actionsApplied: actions.length,
      });
      return snapshot;
    } catch (error) {
      await recordBrowserTrace(runtime, 'failure', `Unable to automate browser: ${url}`, {
        error: error instanceof Error ? error.message : String(error),
      });
      throw new BrowserCapabilityError(`Unable to automate browser: ${url}`, error);
    }
  });
}

export const webReadDynamicCapability: CapabilityDefinition<
  typeof webReadDynamicInputSchema,
  typeof webReadDynamicOutputSchema
> = {
  id: 'web_read_dynamic',
  title: 'Web Read Dynamic',
  description: 'Loads a rendered page with Playwright and extracts the visible content.',
  library: 'playwright',
  enabled: true,
  timeoutMs: 30_000,
  inputSchema: webReadDynamicInputSchema,
  outputSchema: webReadDynamicOutputSchema,
  run: async (input: z.output<typeof webReadDynamicInputSchema>, _context: CapabilityExecutionContext) => {
    return loadDynamicPage(input.url, input.settleMs, _context.runtime, _context.signal);
  },
};

export const browserAutomationCapability: CapabilityDefinition<
  typeof browserAutomationInputSchema,
  typeof browserAutomationOutputSchema
> = {
  id: 'browser_automation',
  title: 'Browser Automation',
  description: 'Runs a short, auditable Playwright action sequence.',
  library: 'playwright',
  enabled: true,
  timeoutMs: 30_000,
  inputSchema: browserAutomationInputSchema,
  outputSchema: browserAutomationOutputSchema,
  run: async (input: z.output<typeof browserAutomationInputSchema>, _context: CapabilityExecutionContext) => {
    return automateBrowser(input.url, input.actions, input.settleMs, _context.runtime, _context.signal);
  },
};
