import assert from "node:assert/strict";
import test from "node:test";
import {
  buildWebGroundingAbstentionBlock,
  buildWebGroundingPromptBlock,
  classifyWebGroundingDecision,
  detectFactualityGrounding,
  extractDateFromText,
  extractNumericEvidenceFromGrounding,
  parseDuckDuckGoHtml,
  parseLocalizedNumber,
  searchPublicWebGrounding,
  shouldUseWebGrounding,
} from "./web-grounding.js";

function makeFreshData(sourceCount: number, sufficient = sourceCount > 0) {
  return {
    schemaVersion: "elyan.fresh_data.v1" as const,
    domain: "market" as const,
    status: sourceCount > 0 ? "fresh" as const : "unavailable" as const,
    freshnessRequired: true,
    requestedAt: "2026-07-09T12:00:00.000Z",
    retrievedAt: "2026-07-09T12:00:00.000Z",
    freshUntil: "2026-07-09T12:00:30.000Z",
    staleUntil: "2026-07-09T12:02:30.000Z",
    ageMs: 0,
    cache: { state: "miss" as const, shared: false },
    evidence: {
      sourceCount,
      freshSourceCount: sourceCount,
      verifiedSourceCount: sourceCount,
      freshVerifiedSourceCount: sourceCount,
      datedSourceCount: sourceCount,
      freshDatedSourceCount: sourceCount,
      independentHostCount: sourceCount,
      minimumSources: 1,
      minimumVerifiedSources: 1,
      minimumDatedSources: 0,
      numericCorroborated: null,
      sufficient,
    },
    reasons: ["test"],
  };
}

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

test("shouldUseWebGrounding enables public web grounding only for required prompts", () => {
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
    false,
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
    false,
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
  assert.equal(
    shouldUseWebGrounding({
      prompt: "Oğuz, Kıpçak ve Karluk dillerini kaynaklı şekilde araştır",
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

test("shouldUseWebGrounding avoids web for self-contained tasks unless explicitly requested", () => {
  const prompts = [
    "Bana kedi resmi çiz",
    "X için kısa bir paylaşım metni yaz",
    "Bu Python kodundaki hatayı açıkla",
    "İki sayının toplamı 10, farkı 4 ise bu sayılar kaçtır?",
    "Aşağıdaki metni Türkçeye çevir",
    "Bugün biraz bunaldım",
    "Bugün için kısa bir motivasyon cümlesi yaz",
    "Güncel misin?",
  ];
  for (const prompt of prompts) {
    assert.equal(
      shouldUseWebGrounding({ prompt, workload: "planning" }),
      false,
      prompt,
    );
  }
  assert.equal(
    shouldUseWebGrounding({
      prompt: "Flutter son sürüm migration guide webden bak",
      workload: "mobile_chat_balanced",
    }),
    true,
  );
});

test("classifyWebGroundingDecision separates no-web, optional and required cases", () => {
  assert.deepEqual(
    classifyWebGroundingDecision({
      prompt: "Bana kedi resmi çiz",
      workload: "mobile_chat_fast",
    }).mode,
    "no_web_needed",
  );
  assert.deepEqual(
    classifyWebGroundingDecision({
      prompt: "Bugünkü dolar kaç TL?",
      workload: "mobile_chat_fast",
    }).mode,
    "web_required",
  );
  assert.deepEqual(
    classifyWebGroundingDecision({
      prompt: "Flutter son sürümde breaking change var mı?",
      workload: "mobile_chat_balanced",
    }).mode,
    "web_required",
  );
  assert.deepEqual(
    classifyWebGroundingDecision({
      prompt: "Yapay zeka eğitim yaklaşımlarını karşılaştır",
      workload: "planning",
    }).mode,
    "web_optional",
  );
  assert.equal(
    classifyWebGroundingDecision({
      prompt: "Oğuz, Kıpçak ve Karluk dillerini araştır",
      workload: "mobile_chat_fast",
    }).mode,
    "web_optional",
  );
  assert.equal(
    classifyWebGroundingDecision({
      prompt: "Oğuz dillerini kaynaklı şekilde araştır",
      workload: "mobile_chat_fast",
    }).mode,
    "web_required",
  );
  assert.equal(
    shouldUseWebGrounding({
      prompt: "Yapay zeka eğitim yaklaşımlarını karşılaştır",
      workload: "planning",
    }),
    false,
  );
});

test("classifyWebGroundingDecision keeps short referential rewrites offline", () => {
  assert.equal(
    classifyWebGroundingDecision({
      prompt: "Aynı hayvandan bahsediyorum; bunu daha kısa, sıcak ve doğru şekilde anlatır mısın?",
      workload: "mobile_chat_balanced",
    }).mode,
    "no_web_needed",
  );
});

test("detectFactualityGrounding does not ground generic how-to without freshness signal", () => {
  assert.equal(
    detectFactualityGrounding("Flutter ile liste nasıl yapılır?").triggered,
    false,
  );
  assert.equal(
    shouldUseWebGrounding({
      prompt: "Flutter ile liste nasıl yapılır?",
      workload: "mobile_chat_balanced",
    }),
    false,
  );
  assert.equal(
    shouldUseWebGrounding({
      prompt: "Flutter son sürümde liste performansı için güncel best practice nedir?",
      workload: "mobile_chat_balanced",
    }),
    true,
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
    freshData: makeFreshData(0, false),
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
      freshData: makeFreshData(0, false),
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
          sourceAuthority: "standard",
          verificationState: "verified",
          queryHits: 1,
          score: 1,
          sourceTrustScore: 0.62,
          observedAt: "2026-07-09T12:00:00.000Z",
          freshnessStatus: "fresh",
        },
      ],
      degradedReason: null,
      confidence: "high",
      decisionReasons: ["volatile_market_fact"],
      freshData: makeFreshData(1),
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
  assert.equal(result.queries.length, 1);
  assert.equal(result.results.length > 0, true);
  assert.equal(result.results[0]?.verificationState, "verified");
  assert.equal(result.results[0]?.queryHits >= 1, true);
  assert.equal(result.confidence === "high" || result.confidence === "medium", true);

  const block = buildWebGroundingPromptBlock(result);
  assert.equal(block?.includes("Query:"), true);
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

test("searchPublicWebGrounding falls back to one secondary provider", async () => {
  const app = {
    config: {
      ELYAN_WEB_GROUNDING_ENABLED: true,
      ELYAN_SEARCH_PROVIDER: "searxng",
      SEARXNG_BASE_URL: "https://search.example",
      ELYAN_WEB_SEARCH_BASE_URL: "https://html.duckduckgo.com/html/",
      ELYAN_WEB_GROUNDING_MAX_RESULTS: 3,
      ELYAN_WEB_GROUNDING_TIMEOUT_MS: 2_000,
    },
  } as never;

  const result = await withMockedFetch(
    async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.startsWith("https://search.example/")) {
        return new Response("unavailable", { status: 503 });
      }
      if (url.includes("duckduckgo.com/html")) {
        return new Response(
          `
            <div class="result">
              <a class="result__a" href="https://example.com/current">Current source</a>
              <a class="result__snippet">Current verified information.</a>
            </div>
          `,
          { status: 200, headers: { "content-type": "text/html" } },
        );
      }
      if (url === "https://example.com/current") {
        return new Response(
          "<html><head><title>Current source</title><meta name=\"description\" content=\"Current verified information.\" /></head></html>",
          { status: 200, headers: { "content-type": "text/html" } },
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    },
    () => searchPublicWebGrounding(app, {
      prompt: "Güncel resmi bilgiyi doğrula",
      workload: "mobile_chat_balanced",
    }),
  );

  assert.equal(result.used, true);
  assert.equal(result.source, "duckduckgo_html");
  assert.match(result.degradedReason ?? "", /searxng_http_503/u);
});

/* ── Structured numeric evidence extraction ─────────────────────────────── */

function makeGroundingResult(
  results: Array<{ snippet: string; pageContent?: string; url?: string; sourceHost?: string }>,
): Parameters<typeof buildWebGroundingPromptBlock>[0] {
  return {
    enabled: true,
    used: results.length > 0,
    query: "test",
    queries: ["test"],
    source: "duckduckgo_html",
    results: results.map((result, index) => ({
      title: `Result ${index + 1}`,
      url: result.url ?? `https://example.com/${index + 1}`,
      snippet: result.snippet,
      pageContent: result.pageContent,
      sourceHost: result.sourceHost ?? "example.com",
      sourceAuthority: "standard",
      verificationState: "verified",
      queryHits: 1,
      score: 1.5,
      sourceTrustScore: 0.62,
      observedAt: "2026-07-09T12:00:00.000Z",
      freshnessStatus: "fresh",
    })),
    degradedReason: null,
    confidence: "high",
    freshData: makeFreshData(results.length),
  };
}

test("parseLocalizedNumber handles TR and EN number formats", () => {
  assert.equal(parseLocalizedNumber("4.250,75"), 4250.75);
  assert.equal(parseLocalizedNumber("4,250.75"), 4250.75);
  assert.equal(parseLocalizedNumber("4250.75"), 4250.75);
  assert.equal(parseLocalizedNumber("4,25"), 4.25);
  assert.equal(parseLocalizedNumber("4.250"), 4250);
  assert.equal(parseLocalizedNumber("1.234.567"), 1234567);
  assert.equal(parseLocalizedNumber("42"), 42);
  assert.equal(parseLocalizedNumber(""), null);
  assert.equal(parseLocalizedNumber("abc"), null);
});

test("source authority affects ranking and prompt evidence", async () => {
  const app = {
    config: {
      ELYAN_WEB_GROUNDING_ENABLED: true,
      ELYAN_WEB_SEARCH_BASE_URL: "https://html.duckduckgo.com/html/",
      ELYAN_WEB_GROUNDING_MAX_RESULTS: 3,
      ELYAN_WEB_GROUNDING_TIMEOUT_MS: 2_000,
      JINA_READER_ENABLED: false,
    },
  } as never;

  const result = await withMockedFetch(
    async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("duckduckgo.com/html")) {
        return new Response(
          `
            <div class="result">
              <a class="result__a" href="https://random-low.example/post">Random post</a>
              <a class="result__snippet">Unofficial copied summary.</a>
            </div>
            <div class="result">
              <a class="result__a" href="https://developer.apple.com/documentation">Official docs</a>
              <a class="result__snippet">Official documentation summary.</a>
            </div>
          `,
          { status: 200, headers: { "content-type": "text/html" } },
        );
      }
      if (url === "https://random-low.example/post") {
        return new Response("<html><title>Random post</title><p>Copied summary only.</p></html>", {
          status: 200,
          headers: { "content-type": "text/html" },
        });
      }
      if (url === "https://developer.apple.com/documentation") {
        return new Response("<html><title>Official docs</title><p>Official documentation content.</p></html>", {
          status: 200,
          headers: { "content-type": "text/html" },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    },
    async () =>
      searchPublicWebGrounding(app, {
        prompt: "Apple developer documentation kaynaklı araştır",
        workload: "mobile_chat_balanced",
      }),
  );

  assert.equal(result.used, true);
  assert.equal(result.results[0]?.sourceAuthority, "official");
  assert.match(buildWebGroundingPromptBlock(result) ?? "", /Source authority: official/);
});

test("weather grounding uses structured REST data before web search", async () => {
  const requestedUrls: string[] = [];
  const app = {
    config: {
      ELYAN_WEB_GROUNDING_ENABLED: true,
      ELYAN_WEB_SEARCH_BASE_URL: "https://html.duckduckgo.com/html/",
      ELYAN_WEB_GROUNDING_MAX_RESULTS: 3,
      ELYAN_WEB_GROUNDING_TIMEOUT_MS: 2_000,
      JINA_READER_ENABLED: false,
    },
  } as never;

  const result = await withMockedFetch(
    async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      requestedUrls.push(url);
      const parsed = new URL(url);
      if (parsed.hostname === "geocoding-api.open-meteo.com") {
        if (parsed.searchParams.get("name") !== "kırıkhan") {
          return Response.json({ results: [] });
        }
        return Response.json({
          results: [{
            name: "Kırıkhan",
            admin1: "Hatay",
            country: "Türkiye",
            latitude: 36.49939,
            longitude: 36.35755,
            timezone: "Europe/Istanbul",
          }],
        });
      }
      if (parsed.hostname === "api.open-meteo.com") {
        return Response.json({
          current: {
            time: "2026-07-10T11:00",
            temperature_2m: 31,
            apparent_temperature: 33.8,
            relative_humidity_2m: 45,
            precipitation: 0,
            weather_code: 0,
            cloud_cover: 3,
            wind_speed_10m: 11.4,
          },
          hourly: {
            time: ["2026-07-10T11:00"],
            precipitation_probability: [0],
          },
          daily: {
            temperature_2m_max: [36.2],
            temperature_2m_min: [23.7],
            precipitation_probability_max: [0],
          },
        });
      }
      throw new Error(`Unexpected web-search request: ${url}`);
    },
    async () =>
      searchPublicWebGrounding(app, {
        prompt: "Hatay kırıkhan hava durumu",
        workload: "mobile_chat_fast",
        bypassCache: true,
      }),
  );

  assert.equal(result.source, "open_meteo");
  assert.equal(result.used, true);
  assert.equal(result.confidence, "high");
  assert.equal(result.freshData.evidence.sufficient, true);
  assert.equal(result.results[0]?.verificationState, "verified");
  assert.match(result.results[0]?.snippet ?? "", /sıcaklık 31 °C/iu);
  assert.match(result.results[0]?.snippet ?? "", /hissedilen 33\.8 °C/iu);
  assert.ok(requestedUrls.every((url) => url.includes("open-meteo.com")));
  assert.doesNotMatch(buildWebGroundingPromptBlock(result) ?? "", /EVIDENCE GUARD/iu);
});

test("fiat grounding uses structured JSON REST data before web search", async () => {
  const requestedUrls: string[] = [];
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
      requestedUrls.push(url);
      const parsed = new URL(url);
      if (parsed.hostname !== "api.frankfurter.app") {
        throw new Error(`Unexpected web-search request: ${url}`);
      }
      return Response.json({
        amount: 1,
        base: "USD",
        date: new Date().toISOString().slice(0, 10),
        rates: { TRY: 42.75 },
      });
    },
    () => searchPublicWebGrounding(app, {
      prompt: "Bugünkü dolar kaç TL?",
      workload: "mobile_chat_fast",
      bypassCache: true,
    }),
  );
  assert.equal(result.source, "frankfurter");
  assert.equal(result.used, true);
  assert.match(result.results[0]?.snippet ?? "", /1 USD = 42\.75 TRY/u);
  assert.ok(requestedUrls.every((url) => url.includes("api.frankfurter.app")));
});

test("crypto grounding uses structured JSON REST data before web search", async () => {
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
      if (!url.includes("api.coingecko.com/api/v3/simple/price")) {
        throw new Error(`Unexpected web-search request: ${url}`);
      }
      return Response.json({
        bitcoin: {
          try: 4_100_000,
          usd: 95_000,
          last_updated_at: Math.floor(Date.now() / 1_000),
        },
      });
    },
    () => searchPublicWebGrounding(app, {
      prompt: "Şu an bitcoin kaç TL?",
      workload: "mobile_chat_fast",
      bypassCache: true,
    }),
  );
  assert.equal(result.source, "coingecko");
  assert.equal(result.used, true);
  assert.match(result.results[0]?.snippet ?? "", /BTC\/TRY 4100000/u);
});

test("extractDateFromText finds ISO, dotted and named Turkish dates", () => {
  assert.equal(extractDateFromText("kapanış 2024-05-22 itibarıyla"), "2024-05-22");
  assert.equal(extractDateFromText("22.05.2024 tarihli veri"), "2024-05-22");
  assert.equal(extractDateFromText("22 Mayıs 2024 kapanışı"), "2024-05-22");
  assert.equal(extractDateFromText("hiç tarih yok burada"), null);
});

test("extractNumericEvidenceFromGrounding pulls value/date pairs from snippets", () => {
  const grounding = makeGroundingResult([
    {
      snippet: "Gram altın 22.05.2024 tarihinde 2.450,75 TL seviyesinde işlem gördü.",
      pageContent: "Gram altın 23.05.2024 kapanışı 2.470,10 TL oldu.",
    },
  ]);
  const evidence = extractNumericEvidenceFromGrounding(grounding);
  assert.equal(evidence.hasNumericFacts, true);
  assert.equal(evidence.hasChartableSeries, true);
  const values = evidence.points.map((point) => point.value);
  assert.ok(values.includes(2450.75));
  assert.ok(values.includes(2470.1));
  const dates = evidence.points.map((point) => point.date);
  assert.ok(dates.includes("2024-05-22"));
  assert.ok(dates.includes("2024-05-23"));
});

test("extractNumericEvidenceFromGrounding reports no facts for link-farm snippets", () => {
  const grounding = makeGroundingResult([
    { snippet: "Altın fiyat grafiğini canlı olarak sitemizde bulabilirsiniz." },
    { snippet: "Güncel kur bilgisi için tıklayın." },
  ]);
  const evidence = extractNumericEvidenceFromGrounding(grounding);
  assert.equal(evidence.hasNumericFacts, false);
  assert.equal(evidence.hasChartableSeries, false);
});

test("buildWebGroundingPromptBlock includes numeric evidence when present", () => {
  const grounding = makeGroundingResult([
    { snippet: "Dolar/TL 22.05.2024 itibarıyla 32,45 TL, önceki gün 32,10 TL idi." },
  ]);
  const block = buildWebGroundingPromptBlock(grounding);
  assert.ok(block);
  assert.ok(block.includes("STRUCTURED NUMERIC EVIDENCE"));
  assert.ok(block.includes("32.45 TL"));
  assert.ok(!block.includes("NUMERIC DATA UNAVAILABLE"));
});

test("buildWebGroundingPromptBlock signals no-data honestly when snippets carry no numbers", () => {
  const grounding = makeGroundingResult([
    { snippet: "Altın fiyat grafiğini canlı olarak sitemizde bulabilirsiniz." },
  ]);
  const block = buildWebGroundingPromptBlock(grounding);
  assert.ok(block);
  assert.ok(block.includes("NUMERIC DATA UNAVAILABLE"));
  assert.ok(block.includes("Do NOT invent numbers"));
});

test("numeric extraction skips bare years and URL fragments", () => {
  const grounding = makeGroundingResult([
    {
      snippet: "2024 yılında piyasalar dalgalıydı. Detay: https://example.com/2023/11/rapor-4500",
    },
  ]);
  const evidence = extractNumericEvidenceFromGrounding(grounding);
  assert.equal(evidence.hasNumericFacts, false);
});

test("numeric evidence requires matching units from independent hosts", () => {
  const grounding = makeGroundingResult([
    {
      snippet: "Gram altın 4.250,75 TL.",
      sourceHost: "market-a.example",
      url: "https://market-a.example/gold",
    },
    {
      snippet: "Gram altın 4.252,10 TL.",
      sourceHost: "market-b.example",
      url: "https://market-b.example/gold",
    },
  ]);
  const evidence = extractNumericEvidenceFromGrounding(grounding);
  assert.equal(evidence.hasIndependentCorroboration, true);
  assert.deepEqual(evidence.corroboratedUnits, ["TL"]);
});

/* ── Web grounding circuit breaker ──────────────────────────────────────── */

class FakeReliabilityStore {
  private readonly memory = new Map<string, string>();

  async get(key: string) {
    return this.memory.get(key) ?? null;
  }

  async set(key: string, value: string, _ttlMs?: number) {
    this.memory.set(key, value);
  }

  async acquireLock() {
    return true;
  }

  async releaseLock() {
    return true;
  }
}

test("searchPublicWebGrounding opens the circuit after repeated provider failures", async () => {
  const store = new FakeReliabilityStore();
  const app = {
    config: {
      ELYAN_WEB_GROUNDING_ENABLED: true,
      ELYAN_WEB_SEARCH_BASE_URL: "https://html.duckduckgo.com/html/",
      ELYAN_WEB_GROUNDING_MAX_RESULTS: 3,
      ELYAN_WEB_GROUNDING_TIMEOUT_MS: 500,
      BRAIN_CIRCUIT_FAILURE_THRESHOLD: 2,
      BRAIN_CIRCUIT_OPEN_MS: 30_000,
    },
    services: { reliability: { store } },
  } as never;

  await withMockedFetch(
    async () => {
      throw new Error("connection refused");
    },
    async () => {
      const first = await searchPublicWebGrounding(app, {
        prompt: "Bugünkü dolar kurunu araştır lütfen bir",
        workload: "mobile_chat_balanced",
      });
      assert.equal(first.used, false);
      await new Promise((resolve) => setTimeout(resolve, 25));

      const second = await searchPublicWebGrounding(app, {
        prompt: "Bugünkü euro kurunu araştır lütfen iki",
        workload: "mobile_chat_balanced",
      });
      assert.equal(second.used, false);
      await new Promise((resolve) => setTimeout(resolve, 25));

      // Eşik (2) aşıldı — devre açık: arama hiç denenmez, anında degrade olur.
      const third = await searchPublicWebGrounding(app, {
        prompt: "Bugünkü altın fiyatını araştır lütfen üç",
        workload: "mobile_chat_balanced",
      });
      assert.equal(third.used, false);
      assert.equal(third.degradedReason, "web_grounding_circuit_open");
    },
  );
});

test("pure math word problems do not trigger factuality grounding", () => {
  assert.equal(
    detectFactualityGrounding("İki sayının toplamı 10, farkı 4 ise bu sayılar kaçtır?").triggered,
    false,
  );
  assert.equal(
    shouldUseWebGrounding({
      prompt: "İki sayının toplamı 10, farkı 4 ise bu sayılar kaçtır?",
      workload: "mobile_chat_balanced",
    }),
    false,
  );
  // Gerçek özel isimli soru hâlâ grounding almalı
  assert.equal(detectFactualityGrounding("Elon Musk kimdir").triggered, true);
});
