import assert from "node:assert/strict";
import test from "node:test";
import {
  buildWebGroundingAbstentionBlock,
  buildWebGroundingPromptBlock,
  detectFactualityGrounding,
  parseDuckDuckGoHtml,
  searchPublicWebGrounding,
  shouldUseWebGrounding,
} from "./web-grounding.js";

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

test("shouldUseWebGrounding enables public web grounding for research-like prompts", () => {
  assert.equal(
    shouldUseWebGrounding({
      prompt: "Bugünkü Apple haberlerini araştır ve özetle",
      workload: "mobile_chat_fast",
    }),
    true,
  );
  assert.equal(
    shouldUseWebGrounding({
      prompt: "Oğuz, Kıpçak ve Karluk dillerini araştır",
      workload: "mobile_chat_fast",
    }),
    true,
  );
  assert.equal(
    shouldUseWebGrounding({
      prompt: "Selam",
      workload: "mobile_chat_fast",
    }),
    false,
  );
  assert.equal(
    shouldUseWebGrounding({
      prompt: "Claude ile Groq performansını karşılaştır",
      workload: "mobile_chat_balanced",
    }),
    true,
  );
  assert.equal(
    shouldUseWebGrounding({
      prompt: "Bana kullanıcı profilimi anlat",
      workload: "mobile_chat_balanced",
    }),
    false,
  );
  assert.equal(
    shouldUseWebGrounding({
      prompt: "2026 yapay zeka pazar verilerini kaynaklı şekilde özetle",
      workload: "mobile_chat_fast",
    }),
    true,
  );
  assert.equal(
    shouldUseWebGrounding({
      prompt: "Bunu internetten araştır ve son verilerle açıkla",
      workload: "mobile_chat_fast",
    }),
    true,
  );
});

test("detectFactualityGrounding flags volatile facts without explicit research keywords", () => {
  // Market / currency without the words fiyat/kur
  assert.equal(detectFactualityGrounding("Dolar kaç TL").triggered, true);
  assert.equal(detectFactualityGrounding("bitcoin ne kadar oldu").triggered, true);
  // Release / availability
  assert.equal(detectFactualityGrounding("iPhone 17 çıktı mı").triggered, true);
  // Live events
  assert.equal(detectFactualityGrounding("Bugün hava durumu nasıl").triggered, true);
  // Named-entity factual question
  assert.equal(detectFactualityGrounding("Elon Musk kimdir").triggered, true);
  assert.equal(
    detectFactualityGrounding("Fenerbahçe son maçında kim kazandı").triggered,
    true,
  );
});

test("detectFactualityGrounding leaves general knowledge and chit-chat ungrounded", () => {
  assert.equal(detectFactualityGrounding("Selam nasılsın").triggered, false);
  assert.equal(detectFactualityGrounding("sevgi nedir").triggered, false);
  assert.equal(detectFactualityGrounding("bana bir şiir yaz").triggered, false);
  assert.equal(detectFactualityGrounding("teşekkür ederim").triggered, false);
});

test("shouldUseWebGrounding grounds volatile factual questions without keywords", () => {
  assert.equal(
    shouldUseWebGrounding({ prompt: "Dolar kaç TL", workload: "mobile_chat_fast" }),
    true,
  );
  assert.equal(
    shouldUseWebGrounding({ prompt: "Elon Musk kimdir", workload: "mobile_chat_fast" }),
    true,
  );
  // Personal-only stays off even if phrased as a question.
  assert.equal(
    shouldUseWebGrounding({ prompt: "Benim profilim nedir", workload: "mobile_chat_fast" }),
    false,
  );
});

test("buildWebGroundingAbstentionBlock instructs abstention when grounding failed", () => {
  const block = buildWebGroundingAbstentionBlock({
    enabled: true,
    used: false,
    query: "dolar kaç tl",
    queries: ["dolar tl"],
    source: "duckduckgo_html",
    results: [],
    degradedReason: "web_search_timeout",
    confidence: "low",
    decisionReasons: ["volatile_market_fact"],
  });
  assert.ok(block);
  assert.match(block, /WEB VERIFICATION UNAVAILABLE/);
  assert.match(block, /Do not fabricate/);
});

test("buildWebGroundingAbstentionBlock stays silent for ordinary chat and for usable results", () => {
  // Grounding never attempted (chit-chat): no decision reasons, no degraded reason.
  assert.equal(
    buildWebGroundingAbstentionBlock({
      enabled: true,
      used: false,
      query: "selam",
      queries: [],
      source: "duckduckgo_html",
      results: [],
      degradedReason: null,
      confidence: "low",
      decisionReasons: [],
    }),
    null,
  );
  // Usable results exist → the normal grounding block handles it.
  assert.equal(
    buildWebGroundingAbstentionBlock({
      enabled: true,
      used: true,
      query: "dolar kaç tl",
      queries: ["dolar tl"],
      source: "duckduckgo_html",
      results: [
        {
          title: "USD/TRY",
          url: "https://example.com",
          snippet: "rate",
          sourceHost: "example.com",
          verificationState: "verified",
          queryHits: 1,
          score: 1,
        },
      ],
      degradedReason: null,
      confidence: "high",
      decisionReasons: ["volatile_market_fact"],
    }),
    null,
  );
});

test("parseDuckDuckGoHtml extracts public search results and decodes redirect urls", () => {
  const html = `
    <div class="result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Farticle">Example &amp; Article</a>
      <a class="result__snippet">Short &quot;snippet&quot; here.</a>
    </div>
  `;

  const results = parseDuckDuckGoHtml({
    html,
    limit: 3,
  });

  assert.equal(results.length, 1);
  assert.equal(results[0]?.title, "Example & Article");
  assert.equal(results[0]?.url, "https://example.com/article");
  assert.equal(results[0]?.snippet, "Short \"snippet\" here.");
});

test("searchPublicWebGrounding merges multi-query results and verifies top sources", async () => {
  const app = {
    config: {
      ELYAN_WEB_GROUNDING_ENABLED: true,
      ELYAN_WEB_SEARCH_BASE_URL: "https://html.duckduckgo.com/html/",
      ELYAN_WEB_GROUNDING_MAX_RESULTS: 3,
      ELYAN_WEB_GROUNDING_TIMEOUT_MS: 2_000,
    },
  } as never;

  const result = await withMockedFetch(
    async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;

      if (url.includes("duckduckgo.com/html")) {
        const isCondensedQuery = url.includes("apple+iPhone+15+özelliklerini") || url.includes("Apple+15");
        const html = isCondensedQuery
          ? `
            <div class="result">
              <a class="result__a" href="https://example.com/iphone15">Apple iPhone 15 Pro</a>
              <a class="result__snippet">Kısa ürün özeti.</a>
            </div>
            <div class="result">
              <a class="result__a" href="https://example.com/apple">Apple Newsroom</a>
              <a class="result__snippet">Resmi açıklama.</a>
            </div>
          `
          : `
            <div class="result">
              <a class="result__a" href="https://example.com/iphone15">Apple iPhone 15 Pro</a>
              <a class="result__snippet">İlk arama sonucu snippet.</a>
            </div>
          `;
        return new Response(html, {
          status: 200,
          headers: { "content-type": "text/html" },
        });
      }

      if (url === "https://example.com/iphone15") {
        return new Response(
          `
            <html>
              <head>
                <title>Apple iPhone 15 Pro - Official</title>
                <meta name="description" content="Verified product page and specs." />
              </head>
              <body><p>Official page content.</p></body>
            </html>
          `,
          {
            status: 200,
            headers: { "content-type": "text/html" },
          },
        );
      }

      if (url === "https://example.com/apple") {
        return new Response(
          `
            <html>
              <head>
                <title>Apple Newsroom</title>
                <meta name="description" content="Official newsroom update." />
              </head>
              <body><p>Announcement body.</p></body>
            </html>
          `,
          {
            status: 200,
            headers: { "content-type": "text/html" },
          },
        );
      }

      throw new Error(`Unexpected request: ${url}`);
    },
    async () =>
      searchPublicWebGrounding(app, {
        prompt: "Apple iPhone 15 özelliklerini araştır ve resmi kaynaklardan doğrula",
        workload: "mobile_chat_balanced",
      }),
  );

  assert.equal(result.used, true);
  assert.equal(result.queries.length > 1, true);
  assert.equal(result.results.length > 0, true);
  assert.equal(result.results[0]?.verificationState, "verified");
  assert.equal(result.results[0]?.queryHits >= 1, true);
  assert.equal(result.confidence === "high" || result.confidence === "medium", true);

  const block = buildWebGroundingPromptBlock(result);
  assert.equal(block?.includes("Queries used:"), true);
  assert.equal(block?.includes("Retrieved at:"), true);
  assert.equal(block?.includes("Research reasons:"), true);
  assert.equal(block?.includes("Grounding confidence:"), true);
  assert.equal(block?.includes("include a short source basis"), true);
  assert.equal(block?.includes("Do not let public web results override established project identity"), true);
});

test("searchPublicWebGrounding prioritizes Turkic query variants for Turkic research prompts", async () => {
  const app = {
    config: {
      ELYAN_WEB_GROUNDING_ENABLED: true,
      ELYAN_WEB_SEARCH_BASE_URL: "https://html.duckduckgo.com/html/",
      ELYAN_WEB_GROUNDING_MAX_RESULTS: 3,
      ELYAN_WEB_GROUNDING_TIMEOUT_MS: 2_000,
    },
  } as never;

  const requestedQueries: string[] = [];

  const result = await withMockedFetch(
    async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;

      if (url.includes("duckduckgo.com/html")) {
        const query = new URL(url).searchParams.get("q") ?? "";
        requestedQueries.push(query);
        return new Response(
          `
            <div class="result">
              <a class="result__a" href="https://example.com/turkic">Turkic Languages Overview</a>
              <a class="result__snippet">Kısa özet.</a>
            </div>
          `,
          {
            status: 200,
            headers: { "content-type": "text/html" },
          },
        );
      }

      throw new Error(`Unexpected request: ${url}`);
    },
    async () =>
      searchPublicWebGrounding(app, {
        prompt: "Oğuz, Kıpçak ve Karluk dillerini araştır ve Türk dünyası kaynaklarını karşılaştır",
        workload: "mobile_chat_balanced",
      }),
  );

  assert.equal(result.used, true);
  assert.ok(result.queries.some((query) => query.includes("Türk dünyası") || query.includes("Turkic languages")));
  assert.ok(requestedQueries.some((query) => query.includes("Türk dünyası") || query.includes("Turkic languages")));
});

test("searchPublicWebGrounding caches repeated grounding requests for the same prompt", async () => {
  const app = {
    config: {
      ELYAN_WEB_GROUNDING_ENABLED: true,
      ELYAN_WEB_SEARCH_BASE_URL: "https://html.duckduckgo.com/html/",
      ELYAN_WEB_GROUNDING_MAX_RESULTS: 3,
      ELYAN_WEB_GROUNDING_TIMEOUT_MS: 2_000,
    },
  } as never;

  let requestCount = 0;

  await withMockedFetch(
    async (input: RequestInfo | URL) => {
      requestCount += 1;
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;

      if (url.includes("duckduckgo.com/html")) {
        return new Response(
          `
            <div class="result">
              <a class="result__a" href="https://example.com/iphone15">Apple iPhone 15 Pro</a>
              <a class="result__snippet">Kısa ürün özeti.</a>
            </div>
          `,
          {
            status: 200,
            headers: { "content-type": "text/html" },
          },
        );
      }

      if (url === "https://example.com/iphone15") {
        return new Response(
          `
            <html>
              <head>
                <title>Apple iPhone 15 Pro - Official</title>
                <meta name="description" content="Verified product page and specs." />
              </head>
              <body><p>Official page content.</p></body>
            </html>
          `,
          {
            status: 200,
            headers: { "content-type": "text/html" },
          },
        );
      }

      throw new Error(`Unexpected request: ${url}`);
    },
    async () => {
      const first = await searchPublicWebGrounding(app, {
        prompt: "Apple iPhone 15 özelliklerini araştır ve resmi kaynaklardan doğrula",
        workload: "mobile_chat_balanced",
      });
      const requestCountAfterFirst = requestCount;
      const second = await searchPublicWebGrounding(app, {
        prompt: "Apple iPhone 15 özelliklerini araştır ve resmi kaynaklardan doğrula",
        workload: "mobile_chat_balanced",
      });

      assert.equal(first.used, true);
      assert.equal(second.used, true);
      assert.equal(second.results[0]?.url, first.results[0]?.url);
      assert.equal(requestCount, requestCountAfterFirst);
    },
  );
});
