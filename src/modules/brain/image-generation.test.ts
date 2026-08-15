import assert from "node:assert/strict";
import test from "node:test";
import type { FastifyInstance } from "fastify";
import {
  isHostedImageEditIntent,
  isHostedImageGenerationRequest,
  maybeGenerateHostedImageArtifact,
} from "./image-generation.js";
import {
  buildVisualIntentContract,
  isVisualImageRequested,
  latestImageArtifactFromMetadata,
} from "./visual-intent-contract.js";

async function createTestJpeg(seed = 40) {
  const { default: sharp } = await import("sharp");
  return sharp({
    create: {
      width: 48,
      height: 48,
      channels: 3,
      background: { r: seed % 255, g: 80, b: 60 },
    },
  })
    .jpeg()
    .toBuffer();
}

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
      GEMINI_IMAGE_MODEL: "gemini-3.1-flash-image-preview",
      GEMINI_IMAGE_PRO_MODEL: "gemini-3-pro-image-preview",
      GEMINI_IMAGE_SIZE: "1K",
      GEMINI_IMAGE_PRO_ENABLED: false,
      GEMINI_IMAGE_DAILY_GLOBAL_LIMIT: 50,
      GEMINI_IMAGE_PRO_DAILY_GLOBAL_LIMIT: 5,
      GEMINI_IMAGE_4K_DAILY_GLOBAL_LIMIT: 2,
      OPENAI_API_KEY: "",
      OPENAI_BASE_URL: "https://api.openai.com/v1",
      ...config,
    },
    log: {
      warn: () => undefined,
      error: () => undefined,
    },
    services: { reliability: { store: options.store ?? createMemoryStore() } },
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
  const jpegBody = await createTestJpeg(40);
  const jpegBase64 = jpegBody.toString("base64");

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
    assert.equal(requests[0]?.body.store, false);
    const responseFormat = requests[0]?.body.response_format as Record<
      string,
      unknown
    >;
    assert.equal(responseFormat.type, "image");
    // Gemini yalnız image/jpeg kabul ediyor; image/png her modelde 400 üretiyordu.
    assert.equal(responseFormat.mime_type, "image/jpeg");
    const providerInput = requests[0]?.body.input as Array<Record<string, unknown>>;
    assert.equal(providerInput[0]?.type, "text");
    assert.match(String(providerInput[0]?.text ?? ""), /VISUAL INTENT CONTRACT/);
    assert.match(String(providerInput[0]?.text ?? ""), /"intent": "image_generate"/);
    assert.match(String(providerInput[0]?.text ?? ""), /Requested aspect ratio: 2:3/);
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
    assert.notDeepEqual([...result.binaryBody], [...jpegBody]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("maybeGenerateHostedImageArtifact does not fall back to billed OpenAI when Gemini fails", async () => {
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
        prompt: "Kedi resmi çiz",
        responseText: "",
      },
    );

    assert.equal(result, null);
    // Testin amacı: Gemini düşünce ÜCRETLİ OpenAI'ye geçilmesin. Gemini
    // içinde birden çok modelin denenmesi (fallback zinciri) beklenen
    // davranış; sayıyı sabitlemek yerine sağlayıcıyı doğruluyoruz.
    assert.ok(requests.length > 0);
    assert.ok(
      requests.every((url) => url.includes("generativelanguage.googleapis.com")),
      `OpenAI'ye düşülmemeli, çağrılan adresler: ${requests.join(", ")}`,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("maybeGenerateHostedImageArtifact records provider quota failures safely", async () => {
  const originalFetch = globalThis.fetch;
  const metadata: Record<string, unknown> = {};

  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        error: {
          message: "You exceeded your current quota, please check your plan and billing details.",
        },
      }),
      { status: 429, headers: { "content-type": "application/json" } },
    );

  try {
    const result = await maybeGenerateHostedImageArtifact(
      appWithConfig({ GEMINI_API_KEY: "gemini-test-key" }),
      {
        prompt: "Kırmızı bir Mercedes çiz",
        responseText: "",
        metadata,
      },
    );

    assert.equal(result, null);
    assert.equal(metadata.imageGenerationBlockedReason, "image_generation_provider_quota");
    assert.equal(
      (metadata.imageGenerationBlockedDetails as Record<string, unknown>)
        .retryAfterSeconds,
      300,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("canonicalizes retired image aliases and uses the single Gemini key", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ model: string; key: string | null }> = [];
  const jpegBase64 = (await createTestJpeg(40)).toString("base64");

  globalThis.fetch = async (_input: RequestInfo | URL, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
    requests.push({
      model: String(body.model ?? ""),
      key: new Headers(init?.headers).get("x-goog-api-key"),
    });
    return Response.json({
      output_image: { data: jpegBase64, mime_type: "image/jpeg" },
    });
  };

  try {
    const result = await maybeGenerateHostedImageArtifact(
      appWithConfig({
        GEMINI_API_KEY: "gemini-key",
        GEMINI_IMAGE_MODEL: "gemini-2.5-flash-image-preview",
      }),
      { prompt: "Bana bir kedi çiz", responseText: "" },
    );

    assert.ok(result);
    // Emekli `gemini-2.5-flash-image-preview` artık varsayılan ucuz uca
    // (`gemini-3.1-flash-lite-image`) kanonikleşiyor.
    assert.deepEqual(requests, [
      { model: "gemini-3.1-flash-lite-image", key: "gemini-key" },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("surfaces provider access denial instead of the generic image fallback", async () => {
  const originalFetch = globalThis.fetch;
  const metadata: Record<string, unknown> = {};

  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        error: {
          status: "PERMISSION_DENIED",
          message: "Your project has been denied access.",
        },
      }),
      { status: 403, headers: { "content-type": "application/json" } },
    );

  try {
    const result = await maybeGenerateHostedImageArtifact(
      appWithConfig({ GEMINI_API_KEY: "gemini-test-key" }),
      { prompt: "Bana üstünde Elyan yazan bir kedi çiz", responseText: "", metadata },
    );

    assert.equal(result, null);
    assert.equal(
      metadata.imageGenerationBlockedReason,
      "image_generation_provider_access_denied",
    );
    const details = metadata.imageGenerationBlockedDetails as Record<string, unknown>;
    // Ucuz uç yedeği zincire eklendiği için 403 iki modelde de görülüyor;
    // sabitlenen şey sebebin genel "sonra tekrar dene"ye düşmemesi.
    assert.deepEqual(details.attemptedModels, [
      "gemini-3.1-flash-image",
      "gemini-3.1-flash-lite-image",
    ]);
    // Tek 403: erişim reddi yeniden denenebilir bir hata değil, zincir orada
    // duruyor (kota/ağ hatasından farkı bu).
    assert.deepEqual(details.statuses, [403]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("maybeGenerateHostedImageArtifact falls back from the quality image model to the cheap one", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<Record<string, unknown>> = [];
  const jpegBody = await createTestJpeg(41);
  const jpegBase64 = jpegBody.toString("base64");

  globalThis.fetch = async (_input: RequestInfo | URL, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
    requests.push(body);
    // Kaliteli ucu düşür: testin konusu "kaliteli uç tükenince ucuz uca
    // düşme". Ayrı bir `gemini-3-pro-image` ucu artık yok — kalite ve premium
    // aynı model (`gemini-3.1-flash-image`), ucuz uç ise
    // `gemini-3.1-flash-lite-image`.
    if (String(body.model) === "gemini-3.1-flash-image") {
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
    const db = new FakeDb([
      [
        {
          userId: "pro-user",
          planCode: "pro",
          status: "active",
          taskLimitMonthly: 1_000,
          aiCreditsMonthly: 3_000,
          currentPeriodStartedAt: new Date("2030-01-01T00:00:00.000Z"),
          periodEndsAt: new Date("2030-02-01T00:00:00.000Z"),
        },
      ],
      [{ used: 0 }],
      [{ used: 0 }],
      [{ used: 0 }],
      [{ granted: 0, used: 0 }],
      [],
    ]);
    const result = await maybeGenerateHostedImageArtifact(
      appWithConfig(
        {
          GEMINI_API_KEY: "gemini-test-key",
          GEMINI_IMAGE_PRO_ENABLED: true,
        },
        { db },
      ),
      {
        prompt: "Profesyonel kapak görseli oluştur",
        responseText: "",
        userId: "pro-user",
      },
    );

    assert.ok(result);
    // Sıra: önce kaliteli uç, sonra ucuz uç. Kaç varyant denendiği
    // yapılandırmaya bağlı; sabitlenen şey KALİTELİ ÖNCE, UCUZ SONRA kuralı.
    const attempted = requests.map((request) => String(request.model ?? ""));
    assert.equal(attempted[0], "gemini-3.1-flash-image");
    assert.ok(
      attempted.indexOf("gemini-3.1-flash-lite-image") > 0,
      `kaliteli uç tükenince ucuz uç denenmeli, denenenler: ${attempted.join(", ")}`,
    );
    assert.equal(result.mimeType, "image/jpeg");
    assert.notDeepEqual([...result.binaryBody], [...jpegBody]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("maybeGenerateHostedImageArtifact treats Turkish draw prompts as image generation", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<Record<string, unknown>> = [];
  const jpegBody = await createTestJpeg(42);
  const jpegBase64 = jpegBody.toString("base64");

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
    assert.notDeepEqual([...result.binaryBody], [...jpegBody]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("detects bare imperative draw command without an explicit image noun", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  const jpegBase64 = (await createTestJpeg(43)).toString("base64");

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
  const jpegBody = await createTestJpeg(44);
  const jpegBase64 = jpegBody.toString("base64");

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
    assert.deepEqual([...second.binaryBody], [...first.binaryBody]);
    assert.notDeepEqual([...second.binaryBody], [...jpegBody]);
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
  const jpegBase64 = (await createTestJpeg(45)).toString("base64");

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
  const jpegBase64 = (await createTestJpeg(46)).toString("base64");
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
    const input = { prompt: "Kedi resmi çiz", responseText: "", userId: "user-2" };

    const first = await maybeGenerateHostedImageArtifact(app, input);
    const second = await maybeGenerateHostedImageArtifact(app, input);
    const callsBeforeThird = calls;
    const third = await maybeGenerateHostedImageArtifact(app, input);

    // İlk iki istek yapılandırılmış model zincirini dener (429); her
    // sağlayıcı+model için eşik dolunca devre açılır. Üçüncü istek HİÇ dış
    // çağrı yapmamalı. Toplam çağrı sayısı zincirin uzunluğuna bağlı olduğu
    // için sabitlenmiyor; sabitlenen şey üçüncü isteğin sıfır çağrı yapması.
    assert.equal(first, null);
    assert.equal(second, null);
    assert.equal(third, null);
    assert.ok(callsBeforeThird > 0, "ilk iki istek dış çağrı yapmalı");
    assert.equal(
      calls,
      callsBeforeThird,
      "third request must be short-circuited by the open circuit",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("concurrent identical prompts collapse into a single upstream call (single-flight)", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  const jpegBody = await createTestJpeg(47);
  const jpegBase64 = jpegBody.toString("base64");

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
    assert.deepEqual([...a.binaryBody], [...b.binaryBody]);
    assert.notDeepEqual([...a.binaryBody], [...jpegBody]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("premium prompts stay on Flash while GEMINI_IMAGE_PRO_ENABLED is off (cost guard)", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<Record<string, unknown>> = [];
  const jpegBase64 = (await createTestJpeg(48)).toString("base64");

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
  const jpegBase64 = (await createTestJpeg(49)).toString("base64");

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

    const textPrompts = requests.map((request) => {
      const input = request.input as Array<Record<string, unknown>>;
      return String(input[0]?.text ?? "");
    });
    assert.deepEqual(textPrompts.map((prompt) => prompt.includes("Requested image size: 2K.")), [
      true,
      false,
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("generated images are validated and branded as real image bytes", async () => {
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
    assert.notDeepEqual([...result.binaryBody], [...realJpeg]);
    const meta = await sharp(Buffer.from(result.binaryBody)).metadata();
    assert.equal(meta.format, "jpeg");
    assert.equal(meta.width, 256);
    assert.equal(meta.height, 256);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("visual intent contract carries the latest image into Turkish continuation requests", () => {
  const contract = buildVisualIntentContract({
    prompt: "yanına bir tane daha çiz",
    metadata: {
      sessionArtifacts: [
        {
          artifactId: "artifact-horse-1",
          artifactType: "image",
          contentFamily: "image",
          revisedPrompt: "A single horse in a field, watercolor style.",
          metadata: {
            visualIntent: {
              intent: "image_generate",
              subject: ["horse"],
              count: 1,
              add: [],
              remove: [],
              preserve: [],
              style: "watercolor",
              spatialInstruction: null,
              sourceArtifactId: null,
              negativeConstraints: [],
            },
          },
        },
      ],
    },
  });

  assert.deepEqual(contract, {
    intent: "image_continue",
    subject: ["horse"],
    count: 1,
    add: ["one more horse"],
    remove: [],
    preserve: ["existing horse", "same style", "same background", "same composition"],
    style: "watercolor",
    spatialInstruction: "beside existing subject",
    sourceArtifactId: "artifact-horse-1",
    negativeConstraints: [
      "do not replace the existing horse",
      "do not change the existing scene",
      "do not create an unrelated image",
      "do not add a child unless explicitly requested",
    ],
  });
});

test("visual intent contract keeps forbidden people out of requested subjects", () => {
  const contract = buildVisualIntentContract({
    prompt: "Bir at çiz. Sadece at olsun, çocuk veya insan olmasın.",
  });

  assert.equal(contract.intent, "image_generate");
  assert.deepEqual(contract.subject, ["horse"]);
  assert.deepEqual(contract.remove, []);
  assert.match(contract.negativeConstraints.join("\n"), /do not add child/);
  assert.match(contract.negativeConstraints.join("\n"), /do not add person/);
});

test("visual intent contract does not execute explicitly negated visual actions", () => {
  const prompt =
    "Bu sohbeti iki kısa cümleyle özetle. Görsel oluşturma veya düzenleme yapma.";
  const contract = buildVisualIntentContract({
    prompt,
    metadata: {
      lastVisualArtifact: {
        id: "artifact-horse-negated",
        artifactType: "image",
        contentFamily: "image",
      },
    },
  });

  assert.equal(contract.intent, "image_generate");
  assert.equal(contract.sourceArtifactId, null);
  assert.equal(isVisualImageRequested(contract, prompt), false);
  assert.equal(isHostedImageGenerationRequest(prompt), false);
  assert.equal(isHostedImageEditIntent(prompt), false);
});

test("visual intent contract does not turn unrelated follow-ups into image edits", () => {
  const contract = buildVisualIntentContract({
    prompt: "Tarayıcıdan api.elyan.dev sağlık durumuna bak ve sonucu bildir.",
    metadata: {
      lastVisualArtifact: {
        id: "artifact-horse-2",
        artifactType: "image",
        contentFamily: "image",
        visualIntent: {
          intent: "image_generate",
          subject: ["horse"],
          count: 1,
          add: [],
          remove: [],
          preserve: [],
          style: null,
          spatialInstruction: null,
          sourceArtifactId: null,
          negativeConstraints: [],
        },
      },
    },
  });

  assert.equal(contract.intent, "image_generate");
  assert.equal(contract.sourceArtifactId, null);
  assert.equal(
    isVisualImageRequested(
      contract,
      "Tarayıcıdan api.elyan.dev sağlık durumuna bak ve sonucu bildir.",
    ),
    false,
  );
});

test("visual intent contract reads lastVisualArtifact as the continuation source", () => {
  const contract = buildVisualIntentContract({
    prompt: "rengini değiştir",
    metadata: {
      lastVisualArtifact: {
        id: "artifact-horse-2",
        taskId: "task-horse-2",
        artifactType: "image",
        contentFamily: "image",
        prompt: "at çiz",
        revisedPrompt: "A horse on a plain background.",
        visualSummary: "A horse on a plain background.",
        detectedSubject: ["horse"],
        style: "minimal",
        sourceSessionId: "session-1",
        visualIntent: {
          intent: "image_generate",
          subject: ["horse"],
          count: 1,
          add: [],
          remove: [],
          preserve: [],
          style: "minimal",
          spatialInstruction: null,
          sourceArtifactId: null,
          negativeConstraints: [],
        },
      },
    },
  });

  assert.equal(contract.intent, "image_edit");
  assert.equal(contract.sourceArtifactId, "artifact-horse-2");
  assert.deepEqual(contract.subject, ["horse"]);
  assert.equal(contract.style, "minimal");
  assert.ok(contract.preserve.includes("existing horse"));
});

test("hosted image continuation prompt uses visual intent contract and preserves prior image", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<Record<string, unknown>> = [];
  const jpegBase64 = (await createTestJpeg(50)).toString("base64");

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
      {
        prompt: "yanına bir tane daha çiz",
        responseText: "",
        sourceImages: [{ base64Data: jpegBase64, mimeType: "image/jpeg" }],
        metadata: {
          sessionArtifacts: [
            {
              artifactId: "artifact-horse-1",
              artifactType: "image",
              contentFamily: "image",
              revisedPrompt: "A single horse in a green field.",
              metadata: {
                visualIntent: {
                  intent: "image_generate",
                  subject: ["horse"],
                  count: 1,
                  add: [],
                  remove: [],
                  preserve: [],
                  style: null,
                  spatialInstruction: null,
                  sourceArtifactId: null,
                  negativeConstraints: [],
                },
              },
            },
          ],
        },
      },
    );

    assert.ok(result);
    assert.equal(requests.length, 1);
    const input = requests[0]?.input as Array<Record<string, unknown>>;
    const prompt = String(input[0]?.text ?? "");
    assert.match(prompt, /VISUAL INTENT CONTRACT/);
    assert.match(prompt, /"intent": "image_continue"/);
    assert.match(prompt, /"sourceArtifactId": "artifact-horse-1"/);
    assert.match(prompt, /one more horse/);
    assert.match(prompt, /do not add a child unless explicitly requested/);
    assert.match(prompt, /A single horse in a green field/);
    assert.equal(
      (result.artifact.metadata?.visualIntent as Record<string, unknown> | undefined)?.intent,
      "image_continue",
    );
    assert.deepEqual(
      (result.artifact.payload?.visualIntent as Record<string, unknown> | undefined)?.add,
      ["one more horse"],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("hosted image continuation fails soft instead of generating unrelated output when source image is missing", async () => {
  const originalFetch = globalThis.fetch;
  const metadata: Record<string, unknown> = {
    lastVisualArtifact: {
      id: "artifact-horse-3",
      taskId: "task-horse-3",
      artifactType: "image",
      contentFamily: "image",
      visualIntent: {
        intent: "image_generate",
        subject: ["horse"],
        count: 1,
        add: [],
        remove: [],
        preserve: [],
        style: null,
        spatialInstruction: null,
        sourceArtifactId: null,
        negativeConstraints: [],
      },
    },
  };
  let called = false;
  globalThis.fetch = async () => {
    called = true;
    return Response.json({});
  };

  try {
    const result = await maybeGenerateHostedImageArtifact(
      appWithConfig({ GEMINI_API_KEY: "gemini-test-key" }),
      {
        prompt: "yanına bir tane daha çiz",
        responseText: "",
        metadata,
      },
    );

    assert.equal(result, null);
    assert.equal(called, false);
    assert.equal(metadata.imageGenerationBlockedReason, "image_edit_source_missing");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

// RC-3 — Görsel niyet artık HER TUR semantik çözülür, ama SADECE görsel bağlam
// varken (yapısal kontrol, prompt-regex değil). `latestImageArtifactFromMetadata`
// bu kapının girdisidir: oturumda önceki bir görsel varsa semantik yol açılır;
// yoksa saf sohbet turu fazladan model çağrısı üretmez.
test("latestImageArtifactFromMetadata detects a prior session image (opens semantic path)", () => {
  const found = latestImageArtifactFromMetadata({
    lastVisualArtifact: {
      id: "artifact-train-1",
      artifactType: "image",
      contentFamily: "image",
    },
  });
  assert.ok(found);
  assert.equal(found?.id, "artifact-train-1");
});

test("latestImageArtifactFromMetadata finds an image inside sessionArtifacts", () => {
  const found = latestImageArtifactFromMetadata({
    sessionArtifacts: [
      { artifactId: "doc-1", artifactType: "document" },
      { artifactId: "img-1", artifactType: "image", contentFamily: "image" },
    ],
  });
  assert.ok(found);
  assert.equal(found?.artifactId, "img-1");
});

test("latestImageArtifactFromMetadata returns null for a text-only turn (no wasteful semantic call)", () => {
  assert.equal(latestImageArtifactFromMetadata({}), null);
  assert.equal(
    latestImageArtifactFromMetadata({
      sessionArtifacts: [{ artifactId: "doc-1", artifactType: "document" }],
    }),
    null,
  );
});

test("latestImageArtifactFromMetadata ignores a non-image lastVisualArtifact", () => {
  assert.equal(
    latestImageArtifactFromMetadata({
      lastVisualArtifact: { id: "chart-1", artifactType: "chart" },
    }),
    null,
  );
});
