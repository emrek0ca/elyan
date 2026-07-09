import assert from "node:assert/strict";
import test from "node:test";
import {
  extractUrlsFromPrompt,
  fetchUrlContext,
  promptContainsUrl,
} from "./url-context.js";

async function withMockedFetch<T>(
  handler: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response> | Response,
  run: () => Promise<T>,
) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = handler as typeof fetch;
  try {
    return await run();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

test("extractUrlsFromPrompt deduplicates and blocks private hosts", () => {
  assert.deepEqual(
    extractUrlsFromPrompt("Bak: https://example.com/a ve tekrar https://example.com/a localhost http://127.0.0.1:3000/x"),
    ["https://example.com/a"],
  );
  assert.equal(promptContainsUrl("https://example.com/a"), true);
  assert.equal(promptContainsUrl("https://r.jina.ai/https://example.com/a"), false);
});

test("fetchUrlContext uses Jina reader when content is usable", async () => {
  const app = {
    config: { JINA_READER_ENABLED: true },
  } as never;

  const result = await withMockedFetch(
    async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      assert.equal(url, "https://r.jina.ai/https://example.com/article");
      return new Response(
        "Title: Example Article\nURL: https://example.com/article\n\nThis is a useful article body with enough readable content for the URL context adapter.",
        { status: 200, headers: { "content-type": "text/plain" } },
      );
    },
    async () => fetchUrlContext(app, "https://example.com/article"),
  );

  assert.equal(result.source, "jina");
  assert.equal(result.title, "Example Article");
  assert.equal(result.sourceAuthority, "standard");
  assert.ok(result.contentLength > 60);
});

test("fetchUrlContext falls back to HTML when Jina has no usable content", async () => {
  const app = {
    config: { JINA_READER_ENABLED: true },
  } as never;
  const requested: string[] = [];

  const result = await withMockedFetch(
    async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      requested.push(url);
      if (url.startsWith("https://r.jina.ai/")) {
        return new Response("Title: Empty\n\nshort", { status: 200 });
      }
      return new Response(
        `
          <html>
            <head><title>Fallback title</title><meta name="description" content="Fallback description with enough useful content to pass extraction." /></head>
            <body><article><p>Fallback readable article body with enough words to be accepted by the adapter and returned to the model context.</p></article></body>
          </html>
        `,
        { status: 200, headers: { "content-type": "text/html; charset=utf-8" } },
      );
    },
    async () => fetchUrlContext(app, "https://docs.example.com/page"),
  );

  assert.equal(result.source, "html_fallback");
  assert.equal(result.title, "Fallback title");
  assert.equal(result.sourceAuthority, "trusted");
  assert.equal(requested.length, 2);
});

test("fetchUrlContext caches repeated URL reads", async () => {
  const app = {
    config: { JINA_READER_ENABLED: true },
  } as never;
  let requestCount = 0;

  await withMockedFetch(
    async () => {
      requestCount += 1;
      return new Response(
        "Title: Cached\nURL: https://example.com/cached\n\nCached content body with enough text to be stored and reused without another upstream call.",
        { status: 200 },
      );
    },
    async () => {
      const first = await fetchUrlContext(app, "https://example.com/cached");
      const second = await fetchUrlContext(app, "https://example.com/cached");
      assert.equal(first.content, second.content);
      assert.equal(requestCount, 1);
    },
  );
});

test("fetchUrlContext reports non-HTML fallback safely", async () => {
  const app = {
    config: { JINA_READER_ENABLED: false },
  } as never;

  const result = await withMockedFetch(
    async () =>
      new Response("binary-ish", {
        status: 200,
        headers: { "content-type": "application/octet-stream" },
      }),
    async () => fetchUrlContext(app, "https://example.com/file.bin"),
  );

  assert.equal(result.source, "html_fallback");
  assert.equal(result.content, "");
  assert.equal(result.error, "fallback_not_html");
});

test("fetchUrlContext blocks private hosts without upstream fetch", async () => {
  const app = {
    config: { JINA_READER_ENABLED: true },
  } as never;
  let called = false;

  const result = await withMockedFetch(
    async () => {
      called = true;
      return new Response("should not happen");
    },
    async () => fetchUrlContext(app, "http://127.0.0.1:3000/private"),
  );

  assert.equal(called, false);
  assert.equal(result.error, "blocked_host");
});
