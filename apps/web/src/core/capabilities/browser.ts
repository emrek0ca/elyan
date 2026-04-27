import { z } from 'zod';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';

type Page = import('playwright').Page;

type BrowserSnapshotLink = {
  href: string;
  text: string;
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

async function withBrowserPage<T>(run: (page: Page) => Promise<T>): Promise<T> {
  const { chromium } = await import('playwright');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();

  try {
    const page = await context.newPage();
    return await run(page);
  } finally {
    await context.close();
    await browser.close();
  }
}

async function loadDynamicPage(url: string, settleMs: number) {
  return await withBrowserPage(async (page) => {
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 12_000 });
      await page.waitForLoadState('networkidle', { timeout: 2_500 }).catch(() => undefined);
      if (settleMs > 0) {
        await page.waitForTimeout(settleMs);
      }
      return await collectSnapshot(page, true);
    } catch (error) {
      throw new BrowserCapabilityError(`Unable to read dynamic page: ${url}`, error);
    }
  });
}

export async function automateBrowser(url: string, actions: z.output<typeof browserAutomationInputSchema>['actions'], settleMs: number) {
  return await withBrowserPage(async (page) => {
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 12_000 });

      for (const action of actions) {
        switch (action.type) {
          case 'click':
            await page.locator(action.selector).click({ timeout: 5_000 });
            break;
          case 'fill':
            await page.locator(action.selector).fill(action.value, { timeout: 5_000 });
            break;
          case 'press':
            await page.keyboard.press(action.key);
            break;
          case 'waitForText':
            await page.getByText(action.text, { exact: false }).first().waitFor({ state: 'visible', timeout: 5_000 });
            break;
          case 'waitForSelector':
            await page.locator(action.selector).waitFor({ state: 'visible', timeout: 5_000 });
            break;
        }
      }

      await page.waitForLoadState('networkidle', { timeout: 2_500 }).catch(() => undefined);
      if (settleMs > 0) {
        await page.waitForTimeout(settleMs);
      }

      return {
        ...(await collectSnapshot(page, true)),
        actionsApplied: actions.length,
      };
    } catch (error) {
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
    void _context;
    return loadDynamicPage(input.url, input.settleMs);
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
    void _context;
    return automateBrowser(input.url, input.actions, input.settleMs);
  },
};
