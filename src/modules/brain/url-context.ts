/**
 * url-context.ts — Kullanıcı mesajındaki URL'leri algılar,
 * içeriklerini Jina AI Reader ile çeker (ücretsiz, temiz markdown).
 *
 * Jina Reader: GET https://r.jina.ai/{url} → temiz markdown
 * Fallback: kendi HTML parser'ımız
 *
 * Max 2 URL, her biri 1000 karakter içerik, timeout 8s.
 * İç IP ve localhost bloklu.
 */

import type { FastifyInstance } from "fastify";
import { Readability } from "@mozilla/readability";
import { parseHTML } from "linkedom";
import { tryAcquireLoadSheddingPermit } from "../../lib/reliability/load-shedding.js";

const URL_PATTERN = /https?:\/\/[^\s\])"'>]{8,}/gi;
const MAX_URLS = 2;
const MAX_CONTENT_CHARS = 1_000;
const JINA_TIMEOUT_MS = 8_000;
const FALLBACK_TIMEOUT_MS = 5_000;
const JINA_BASE = "https://r.jina.ai/";

const BLOCKED_HOSTS = [
  /^localhost$/i,
  /^127\./,
  /^10\./,
  /^172\.(1[6-9]|2\d|3[01])\./,
  /^192\.168\./,
  /^0\./,
  /^::1$/,
  /^r\.jina\.ai$/i,
];

function isAllowedHost(url: string): boolean {
  try {
    const { hostname } = new URL(url);
    return !BLOCKED_HOSTS.some((pattern) => pattern.test(hostname));
  } catch {
    return false;
  }
}

function extractUrlsFromPrompt(prompt: string): string[] {
  const re = new RegExp(URL_PATTERN.source, "gi");
  const seen = new Set<string>();
  const result: string[] = [];
  let match: RegExpExecArray | null;
  while ((match = re.exec(prompt)) !== null) {
    const clean = match[0].replace(/[.,;!?)"']+$/, "");
    /* Skip Jina URLs themselves to avoid loops */
    if (clean.startsWith(JINA_BASE)) continue;
    try {
      const normalized = new URL(clean).toString();
      if (!seen.has(normalized) && isAllowedHost(normalized)) {
        seen.add(normalized);
        result.push(normalized);
      }
    } catch {
      /* skip malformed */
    }
    if (result.length >= MAX_URLS) break;
  }
  return result;
}

/* ── Jina AI Reader ───────────────────────────────────────────────────── */

async function fetchViaJina(url: string): Promise<{ content: string; title: string; error?: string }> {
  const jinaUrl = `${JINA_BASE}${url}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), JINA_TIMEOUT_MS);
  try {
    const response = await fetch(jinaUrl, {
      method: "GET",
      signal: controller.signal,
      headers: {
        "Accept": "text/plain,text/markdown",
        "X-Return-Format": "markdown",
        "User-Agent": "Mozilla/5.0 (compatible; ElyanBot/1.0)",
      },
    });

    if (!response.ok) {
      return { content: "", title: url, error: `jina_http_${response.status}` };
    }

    const text = await response.text();
    /* Jina returns: Title: ... \n URL: ... \n \n content... */
    const titleMatch = text.match(/^Title:\s*(.+)$/m);
    const title = titleMatch?.[1]?.trim() || url;

    /* Strip metadata header lines */
    const contentStart = text.indexOf("\n\n");
    const raw = contentStart >= 0 ? text.slice(contentStart + 2) : text;

    /* Trim to max chars, prefer sentence boundary */
    let content = raw.replace(/\n{3,}/g, "\n\n").trim().slice(0, MAX_CONTENT_CHARS);
    const lastSentence = content.lastIndexOf(".");
    if (lastSentence > MAX_CONTENT_CHARS * 0.7) {
      content = content.slice(0, lastSentence + 1);
    }

    return { content, title };
  } catch (error) {
    return {
      content: "",
      title: url,
      error: error instanceof Error && error.name === "AbortError" ? "jina_timeout" : "jina_failed",
    };
  } finally {
    clearTimeout(timer);
  }
}

/* ── HTML fallback (when Jina fails) — Readability-powered ───────────── */

async function fetchViaHtmlFallback(url: string): Promise<{ content: string; title: string; error?: string }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FALLBACK_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      method: "GET",
      signal: controller.signal,
      headers: {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Accept": "text/html,application/xhtml+xml",
      },
    });
    if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) {
      return { content: "", title: url, error: "fallback_not_html" };
    }
    const html = await response.text();

    /* Readability: Firefox-quality article extraction */
    try {
      const { document } = parseHTML(html);
      const article = new Readability(document as unknown as Document).parse();
      if (article && article.textContent && article.textContent.length > 60) {
        const content = article.textContent.replace(/\s{2,}/g, " ").trim().slice(0, MAX_CONTENT_CHARS);
        const title = (article.title ?? "").slice(0, 120) || url;
        return { content, title };
      }
    } catch {
      /* fall through to meta extraction */
    }

    /* Last-resort: meta description only */
    const titleMatch = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
    const title = (titleMatch?.[1] ?? "").replace(/<[^>]+>/g, " ").replace(/\s{2,}/g, " ").trim().slice(0, 120) || url;
    const descMatch = html.match(/<meta[^>]+(?:name|property)=["'](?:description|og:description)["'][^>]+content=["']([^"']{20,})["']/i);
    const content = descMatch?.[1] ? descMatch[1].trim().slice(0, MAX_CONTENT_CHARS) : "";
    return { content, title, error: content ? undefined : "no_content" };
  } catch (error) {
    return { content: "", title: url, error: error instanceof Error && error.name === "AbortError" ? "timeout" : "failed" };
  } finally {
    clearTimeout(timer);
  }
}

/* ── Main ─────────────────────────────────────────────────────────────── */

export type UrlContextResult = {
  url: string;
  title: string;
  content: string;
  source: "jina" | "html_fallback";
  error?: string;
};

async function fetchUrlContext(app: FastifyInstance, url: string): Promise<UrlContextResult> {
  /* Try Jina first when enabled */
  if (app.config.JINA_READER_ENABLED) {
    const jinaResult = await fetchViaJina(url);
    if (jinaResult.content.length > 60) {
      return { url, title: jinaResult.title, content: jinaResult.content, source: "jina" };
    }
  }

  /* Fallback to direct HTML fetch */
  const htmlResult = await fetchViaHtmlFallback(url);
  return {
    url,
    title: htmlResult.title,
    content: htmlResult.content,
    source: "html_fallback",
    error: htmlResult.error,
  };
}

/**
 * Kullanıcı mesajında URL varsa hepsini çek (paralel, max 2).
 * Sonuçları model context bloğu olarak formatla.
 * Hiç URL yoksa null döner.
 */
export async function buildUrlContextBlock(
  app: FastifyInstance,
  prompt: string,
): Promise<string | null> {
  const urls = extractUrlsFromPrompt(prompt);
  if (urls.length === 0) return null;

  // Load shedding: URL fetch zenginleştirmesi opsiyoneldir. Sunucu doygunken
  // permit alınamazsa cevabı bloklamak yerine URL bağlamı atlanır.
  const permit = await tryAcquireLoadSheddingPermit(app, {
    namespace: "url_context_fetch",
    maxConcurrent: 16,
    ttlMs: 20_000,
    salt: prompt.slice(0, 64),
  }).catch(() => null);
  if (!permit) {
    return null;
  }

  try {
    return await buildUrlContextBlockWithPermit(app, urls);
  } finally {
    await permit.release().catch(() => undefined);
  }
}

async function buildUrlContextBlockWithPermit(
  app: FastifyInstance,
  urls: string[],
): Promise<string | null> {
  const results = await Promise.all(urls.map((url) => fetchUrlContext(app, url)));
  const usable = results.filter((r) => r.content.length > 40);
  if (usable.length === 0) return null;

  const lines = [
    "USER-PROVIDED URL CONTENT",
    "The user's message contains the following URL(s). Content was fetched automatically to help you answer accurately.",
    "Use this content to answer. If content is partial or missing, say so instead of guessing.",
    ...usable.map(
      (r, i) => `\n${i + 1}. ${r.title}\nURL: ${r.url}\nContent:\n${r.content}`,
    ),
    "\nDo not fabricate details not present in the fetched content.",
  ];

  return lines.join("\n");
}

/** Hızlı kontrol: mesajda HTTP(S) URL var mı? */
export function promptContainsUrl(prompt: string): boolean {
  const re = new RegExp(URL_PATTERN.source, "i");
  return re.test(prompt) && !prompt.match(new RegExp(URL_PATTERN.source, "i"))?.[0]?.startsWith(JINA_BASE);
}
