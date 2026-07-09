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
  options: { store?: ReturnType<typeof createMemoryStore>; db?: unknown } = {},
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
    ...(options.db ? { db: options.db } : {}),
  } as unknown as FastifyInstance;
}

class FakeQuery<T> {
  constructor(private readonly result: T) {}

  from() {
    return this;
  }

  where() {
    return this;
  }

  orderBy() {
    return this;
  }

  limit() {
    return this;
  }

  then<TResult1 = T, TResult2 = never>(
    resolve?: ((value: T) => TResult1 | PromiseLike<TResult1>) | null,
    reject?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
  ) {
    return Promise.resolve(this.result).then(resolve, reject);
  }
}

class FakeDb {
  public readonly inserted: Array<Record<string, unknown>> = [];

  constructor(private readonly selectResults: unknown[]) {}

  select() {
    return new FakeQuery(this.selectResults.shift() ?? []);
  }

  insert() {
    const inserted = this.inserted;
    const builder = {
      values(values: Record<string, unknown>) {
        inserted.push(values);
        return builder;
      },
      onConflictDoNothing() {
        return Promise.resolve();
      },
    };
    return builder;
  }
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
    // Maliyet politikası: "poster" tek başına artık premium değil (Pro flag
    // default kapalı) ve açık çözünürlük istenmedikçe 1K üretilir.
    assert.equal(requests[0]?.body.model, "gemini-3.1-flash-image");
    assert.deepEqual(requests[0]?.body.response_format, {
      type: "image",
      mime_type: "image/jpeg",
      aspect_ratio: "2:3",
      image_size: "1K",
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
        GEMINI_IMAGE_PRO_ENABLED: true,
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

test("plan image limit blocks hosted generation before any provider call", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  const metadata: Record<string, unknown> = {};

  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({ output_image: { data: "x", mime_type: "image/jpeg" } });
  };

  try {
    const db = new FakeDb([
      [],
      [{ used: 0 }],
      [{ used: 0 }],
      [{ used: 3 }],
      [{ granted: 0, used: 0 }],
      [],
    ]);
    const result = await maybeGenerateHostedImageArtifact(
      appWithConfig(
        { GEMINI_API_KEY: "gemini-test-key" },
        { db },
      ),
      {
        prompt: "Kedi resmi çiz",
        responseText: "",
        userId: "free-user",
        taskId: "task-1",
        metadata,
      },
    );

    assert.equal(result, null);
    assert.equal(calls, 0, "quota-blocked image generation must not call Gemini/OpenAI");
    assert.equal(metadata.imageGenerationBlockedReason, "image_generation_limit_reached");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("successful hosted generation records plan-scoped image usage", async () => {
  const originalFetch = globalThis.fetch;
  const jpegBase64 = Buffer.from("recorded-image").toString("base64");

  globalThis.fetch = async () =>
    Response.json({ output_image: { data: jpegBase64, mime_type: "image/jpeg" } });

  try {
    const db = new FakeDb([
      [
        {
          userId: "solo-user",
          planCode: "solo",
          status: "active",
          taskLimitMonthly: 200,
          aiCreditsMonthly: 600,
          currentPeriodStartedAt: new Date("2030-01-01T00:00:00.000Z"),
          periodEndsAt: new Date("2030-02-01T00:00:00.000Z"),
        },
      ],
      [{ used: 0 }],
      [{ used: 0 }],
      [{ used: 4 }],
      [{ granted: 0, used: 0 }],
      [],
    ]);

    const result = await maybeGenerateHostedImageArtifact(
      appWithConfig(
        { GEMINI_API_KEY: "gemini-test-key" },
        { db },
      ),
      {
        prompt: "Kedi resmi çiz",
        responseText: "",
        userId: "solo-user",
        taskId: "task-2",
        metadata: {},
      },
    );

    assert.ok(result);
    assert.equal(db.inserted.length, 1);
    assert.equal(db.inserted[0]?.metric, "subscription_image_generation");
    assert.equal(db.inserted[0]?.imageUnits, 1);
    assert.equal(db.inserted[0]?.taskId, "task-2");
    assert.deepEqual(db.inserted[0]?.planSnapshot, {
      planCode: "solo",
      limit: 10,
      usedBefore: 4,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("hosted image rate limit blocks burst traffic before provider calls", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  const jpegBase64 = Buffer.from("rate-limited-image").toString("base64");
  const metadata: Record<string, unknown> = {};

  globalThis.fetch = async () => {
    calls += 1;
    return Response.json({ output_image: { data: jpegBase64, mime_type: "image/jpeg" } });
  };

  try {
    const app = appWithConfig(
      { GEMINI_API_KEY: "gemini-test-key" },
      { store: createMemoryStore() },
    );

    const first = await maybeGenerateHostedImageArtifact(app, {
      prompt: "Kedi resmi çiz",
      responseText: "",
      userId: "rate-user",
      metadata,
    });
    const second = await maybeGenerateHostedImageArtifact(app, {
      prompt: "Köpek resmi çiz",
      responseText: "",
      userId: "rate-user",
      metadata,
    });
    const third = await maybeGenerateHostedImageArtifact(app, {
      prompt: "Kuş resmi çiz",
      responseText: "",
      userId: "rate-user",
      metadata,
    });

    assert.ok(first);
    assert.ok(second);
    assert.equal(third, null);
    assert.equal(calls, 2, "rate-limited request must not call the image provider");
    assert.equal(metadata.imageGenerationBlockedReason, "image_generation_rate_limited");
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

test("premium prompts stay on Flash while GEMINI_IMAGE_PRO_ENABLED is off (cost guard)", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<Record<string, unknown>> = [];
  const jpegBase64 = Buffer.from("cheap-flash").toString("base64");

  globalThis.fetch = async (_input: RequestInfo | URL, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
    requests.push(body);
    return Response.json({
      output_image: { data: jpegBase64, mime_type: "image/jpeg" },
    });
  };

  try {
    const result = await maybeGenerateHostedImageArtifact(
      appWithConfig({ GEMINI_API_KEY: "gemini-test-key" }),
      { prompt: "En kaliteli profesyonel ürün görseli çiz", responseText: "" },
    );

    assert.ok(result);
    assert.deepEqual(
      requests.map((request) => request.model),
      ["gemini-3.1-flash-image"],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("explicit high-resolution prompts get the configured max size, others stay 1K", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<Record<string, unknown>> = [];
  const jpegBase64 = Buffer.from("size-test").toString("base64");

  globalThis.fetch = async (_input: RequestInfo | URL, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
    requests.push(body);
    return Response.json({
      output_image: { data: jpegBase64, mime_type: "image/jpeg" },
    });
  };

  try {
    const app = appWithConfig({ GEMINI_API_KEY: "gemini-test-key", GEMINI_IMAGE_SIZE: "2K" });
    await maybeGenerateHostedImageArtifact(app, {
      prompt: "4k çözünürlükte bir dağ manzarası çiz",
      responseText: "",
    });
    await maybeGenerateHostedImageArtifact(app, {
      prompt: "bir dağ manzarası çiz",
      responseText: "",
    });

    const sizes = requests.map(
      (request) => (request.response_format as Record<string, unknown>).image_size,
    );
    assert.deepEqual(sizes, ["2K", "1K"]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("generated images carry the embedded Elyan watermark (real jpeg grows, fake bytes fail open)", async () => {
  const originalFetch = globalThis.fetch;
  // 256x256 gerçek bir JPEG üret — sharp compose edebilsin.
  const sharp = (await import("sharp")).default;
  const realJpeg = await sharp({
    create: { width: 256, height: 256, channels: 3, background: { r: 40, g: 80, b: 60 } },
  })
    .jpeg()
    .toBuffer();

  globalThis.fetch = async () =>
    Response.json({
      output_image: { data: realJpeg.toString("base64"), mime_type: "image/jpeg" },
    });

  try {
    const result = await maybeGenerateHostedImageArtifact(
      appWithConfig({ GEMINI_API_KEY: "gemini-test-key" }),
      { prompt: "orman manzarası çiz", responseText: "" },
    );

    assert.ok(result);
    // Filigran gömüldüyse çıktı bayt dizisi orijinalden farklıdır ve hâlâ
    // geçerli bir JPEG'dir (sharp ile açılabilir).
    assert.notDeepEqual([...result.binaryBody], [...realJpeg]);
    const meta = await sharp(Buffer.from(result.binaryBody)).metadata();
    assert.equal(meta.format, "jpeg");
    assert.equal(meta.width, 256);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
