import assert from "node:assert/strict";
import test from "node:test";
import type { FastifyInstance } from "fastify";
import { maybeGenerateHostedImageArtifact } from "./image-generation.js";

/** Redis olmadan devre-kesici/önbellek/kilit yollarını sürebilmek için küçük
 * bellek-içi ReliabilityStore taklidi. */
function createMemoryStore() {
  const map = new Map<string, { value: string; expiresAt: number | null }>();
  const alive = (key: string) => {
    const record = map.get(key);
    if (!record) {
      return null;
    }
    if (record.expiresAt !== null && record.expiresAt <= Date.now()) {
      map.delete(key);
      return null;
    }
    return record;
  };
  return {
    async get(key: string) {
      return alive(key)?.value ?? null;
    },
    async set(key: string, value: string, ttlMs?: number) {
      map.set(key, { value, expiresAt: ttlMs && ttlMs > 0 ? Date.now() + ttlMs : null });
    },
    async del(key: string) {
      map.delete(key);
    },
    async increment(key: string, ttlMs: number) {
      const record = alive(key);
      const next = (record ? Number(record.value) : 0) + 1;
      map.set(key, {
        value: String(next),
        expiresAt: record ? record.expiresAt : Date.now() + ttlMs,
      });
      return next;
    },
    async acquireLock(key: string, owner: string, ttlMs: number) {
      if (alive(key)) {
        return false;
      }
      map.set(key, { value: owner, expiresAt: ttlMs > 0 ? Date.now() + ttlMs : null });
      return true;
    },
    async releaseLock(key: string, owner: string) {
      const record = alive(key);
      if (record && record.value === owner) {
        map.delete(key);
        return true;
      }
      return false;
    },
  };
}

function appWithConfig(
  config: Record<string, unknown>,
  options: { store?: ReturnType<typeof createMemoryStore> } = {},
): FastifyInstance {
  return {
    config: {
      GEMINI_API_KEY: "",
      GEMINI_BASE_URL: "https://generativelanguage.googleapis.com/v1beta/openai",
      GEMINI_INTERACTIONS_BASE_URL: "https://generativelanguage.googleapis.com/v1beta",
      GEMINI_IMAGE_MODEL: "gemini-3.1-flash-image",
      GEMINI_IMAGE_PRO_MODEL: "gemini-3-pro-image-preview",
      GEMINI_IMAGE_SIZE: "2K",
      OPENAI_API_KEY: "",
      OPENAI_BASE_URL: "https://api.openai.com/v1",
      ...config,
    },
    log: {
      warn: () => undefined,
    },
    services: options.store
      ? { reliability: { store: options.store } }
      : undefined,
  } as unknown as FastifyInstance;
}

test("maybeGenerateHostedImageArtifact prefers Gemini and returns widget-renderable image metadata", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<{
    url: string;
    geminiKey: string | null;
    body: Record<string, unknown>;
  }> = [];
  const jpegBase64 = Buffer.from("fake-jpeg").toString("base64");

  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    requests.push({
      url: String(input),
      geminiKey: new Headers(init?.headers).get("x-goog-api-key"),
      body: JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>,
    });
    return Response.json({
      output_image: {
        data: jpegBase64,
        mime_type: "image/jpeg",
      },
    });
  };

  try {
    const result = await maybeGenerateHostedImageArtifact(
      appWithConfig({
        GEMINI_API_KEY: "gemini-test-key",
        OPENAI_API_KEY: "openai-test-key",
      }),
      {
        prompt: "Yeni sürüm için poster oluştur",
        responseText: "Poster hazırlanıyor.",
      },
    );

    assert.ok(result);
    assert.equal(requests.length, 1);
    assert.equal(
      requests[0]?.url,
      "https://generativelanguage.googleapis.com/v1beta/interactions",
    );
    assert.equal(requests[0]?.geminiKey, "gemini-test-key");
    assert.equal(requests[0]?.body.model, "gemini-3-pro-image-preview");
    assert.deepEqual(requests[0]?.body.response_format, {
      type: "image",
      mime_type: "image/jpeg",
      aspect_ratio: "2:3",
      image_size: "2K",
    });
    assert.equal(result.previewText, "Görsel hazır.");
    assert.equal(result.mimeType, "image/jpeg");
    assert.equal(result.artifact.contentType, "image/jpeg");
    assert.equal(result.artifact.name, "elyan-poster.jpg");
    assert.equal(result.artifact.metadata?.provider, undefined);
    assert.equal(result.artifact.metadata?.model, undefined);
    assert.equal(result.artifact.metadata?.viewerHint, "image");
    assert.equal(result.artifact.metadata?.contentFamily, "image");
    assert.equal(result.artifact.payload?.source, "elyan_image_generation");
    assert.equal(result.artifact.payload?.model, undefined);
    assert.deepEqual([...result.binaryBody], [...Buffer.from("fake-jpeg")]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("maybeGenerateHostedImageArtifact falls back to OpenAI when standard Gemini request fails", async () => {
  const originalFetch = globalThis.fetch;
  const requests: string[] = [];

  globalThis.fetch = async (input: RequestInfo | URL) => {
    const url = String(input);
    requests.push(url);
    if (url.includes("generativelanguage.googleapis.com")) {
      return new Response("unavailable", { status: 503 });
    }
    return Response.json({
      data: [{ b64_json: Buffer.from("openai-png").toString("base64") }],
    });
  };

  try {
    const result = await maybeGenerateHostedImageArtifact(
      appWithConfig({
        GEMINI_API_KEY: "gemini-test-key",
        OPENAI_API_KEY: "openai-test-key",
      }),
      {
        prompt: "Basit görsel üret",
        responseText: "",
      },
    );

    assert.ok(result);
    assert.equal(requests.length, 2);
    assert.equal(result.artifact.metadata?.provider, undefined);
    assert.equal(result.artifact.payload?.source, "elyan_image_generation");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("maybeGenerateHostedImageArtifact falls back from premium Gemini to Flash for high-quality prompts", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<Record<string, unknown>> = [];
  const jpegBase64 = Buffer.from("flash-after-pro").toString("base64");

  globalThis.fetch = async (_input: RequestInfo | URL, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
    requests.push(body);
    if (body.model === "gemini-3-pro-image-preview") {
      return new Response("busy", { status: 429 });
    }
    return Response.json({
      output_image: {
        data: jpegBase64,
        mime_type: "image/jpeg",
      },
    });
  };

  try {
    const result = await maybeGenerateHostedImageArtifact(
      appWithConfig({
        GEMINI_API_KEY: "gemini-test-key",
      }),
      {
        prompt: "Profesyonel kapak görseli oluştur",
        responseText: "",
      },
    );

    assert.ok(result);
    assert.deepEqual(
      requests.map((request) => request.model),
      ["gemini-3-pro-image-preview", "gemini-3.1-flash-image"],
    );
    assert.equal(result.mimeType, "image/jpeg");
    assert.deepEqual([...result.binaryBody], [...Buffer.from("flash-after-pro")]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("maybeGenerateHostedImageArtifact treats Turkish draw prompts as image generation", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<Record<string, unknown>> = [];
  const jpegBase64 = Buffer.from("dog-jpeg").toString("base64");

  globalThis.fetch = async (_input: RequestInfo | URL, init?: RequestInit) => {
    requests.push(JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>);
    return Response.json({
      output: [
        {
          output_image: {
            data: jpegBase64,
            mime_type: "image/jpeg",
          },
        },
      ],
    });
  };

  try {
    const result = await maybeGenerateHostedImageArtifact(
      appWithConfig({
        GEMINI_API_KEY: "gemini-test-key",
      }),
      {
        prompt: "Köpek resmi çiz",
        responseText: "Adım adım köpek çizimi...",
      },
    );

    assert.ok(result);
    assert.deepEqual(
      requests.map((request) => request.model),
      ["gemini-3.1-flash-image"],
    );
    assert.equal(result.previewText, "Görsel hazır.");
    assert.equal(result.artifact.textContent, "Görsel hazır.");
    assert.deepEqual([...result.binaryBody], [...Buffer.from("dog-jpeg")]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("detects bare imperative draw command without an explicit image noun", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  const jpegBase64 = Buffer.from("red-car").toString("base64");

  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({ output_image: { data: jpegBase64, mime_type: "image/jpeg" } });
  };

  try {
    for (const prompt of [
      "Bana kırmızı bir araba çiz",
      "bir kedi çiz",
      "araba çizer misin",
      "draw me a red car",
    ]) {
      calls = 0;
      const result = await maybeGenerateHostedImageArtifact(
        appWithConfig({ GEMINI_API_KEY: "gemini-test-key" }),
        { prompt, responseText: "" },
      );
      assert.ok(result, `prompt should trigger image generation: ${prompt}`);
      assert.equal(calls, 1, `prompt should make one upstream call: ${prompt}`);
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("does not treat non-drawing 'çiz*' words as image generation", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;

  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({ output_image: { data: "x", mime_type: "image/jpeg" } });
  };

  try {
    for (const prompt of [
      "bana güzel çizgi film önerileri ver",
      "haftalık çizelge hazırla",
      "bu paragrafı özetle",
    ]) {
      const result = await maybeGenerateHostedImageArtifact(
        appWithConfig({ GEMINI_API_KEY: "gemini-test-key" }),
        { prompt, responseText: "" },
      );
      assert.equal(result, null, `prompt must not trigger image generation: ${prompt}`);
    }
    assert.equal(calls, 0, "no upstream image call for non-drawing prompts");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("repeat identical prompt is served from cache without a second upstream call", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  const jpegBase64 = Buffer.from("cached-dog").toString("base64");

  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({ output_image: { data: jpegBase64, mime_type: "image/jpeg" } });
  };

  try {
    const app = appWithConfig(
      { GEMINI_API_KEY: "gemini-test-key" },
      { store: createMemoryStore() },
    );
    const input = { prompt: "Köpek resmi çiz", responseText: "", userId: "user-1" };

    const first = await maybeGenerateHostedImageArtifact(app, input);
    const second = await maybeGenerateHostedImageArtifact(app, input);

    assert.ok(first);
    assert.ok(second);
    assert.equal(calls, 1, "second identical request must hit the cache");
    assert.deepEqual([...second.binaryBody], [...Buffer.from("cached-dog")]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("provider circuit opens after repeated failures and skips further upstream calls", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;

  globalThis.fetch = async () => {
    calls += 1;
    // 429 prepayment/quota — kredi bitmiş sağlayıcı senaryosu.
    return new Response("prepayment credits are depleted", { status: 429 });
  };

  try {
    const app = appWithConfig(
      { GEMINI_API_KEY: "gemini-test-key" },
      { store: createMemoryStore() },
    );
    const input = { prompt: "Basit görsel üret", responseText: "", userId: "user-2" };

    const first = await maybeGenerateHostedImageArtifact(app, input);
    const second = await maybeGenerateHostedImageArtifact(app, input);
    const third = await maybeGenerateHostedImageArtifact(app, input);

    // İlk iki istek Flash'ı dener (429), eşik dolunca devre açılır; üçüncü
    // istek dış çağrı yapmadan hızlıca null döner.
    assert.equal(first, null);
    assert.equal(second, null);
    assert.equal(third, null);
    assert.equal(calls, 2, "third request must be short-circuited by the open circuit");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("concurrent identical prompts collapse into a single upstream call (single-flight)", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  const jpegBase64 = Buffer.from("shared-image").toString("base64");

  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({ output_image: { data: jpegBase64, mime_type: "image/jpeg" } });
  };

  try {
    const app = appWithConfig(
      { GEMINI_API_KEY: "gemini-test-key" },
      { store: createMemoryStore() },
    );
    const input = { prompt: "Kedi resmi çiz", responseText: "", userId: "user-3" };

    const [a, b] = await Promise.all([
      maybeGenerateHostedImageArtifact(app, input),
      maybeGenerateHostedImageArtifact(app, input),
    ]);

    assert.ok(a);
    assert.ok(b);
    assert.equal(calls, 1, "concurrent identical requests must share one upstream call");
    assert.deepEqual([...a.binaryBody], [...Buffer.from("shared-image")]);
    assert.deepEqual([...b.binaryBody], [...Buffer.from("shared-image")]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
