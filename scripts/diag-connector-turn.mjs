/**
 * Tanı (dist varyantı): başarısız "Son mailimi oku" turunu gerçek app
 * bağlamıyla tetikler. Konteyner içinde:
 *   docker exec elyan-backend-backend-1 node scripts/diag-connector-turn.mjs
 */
const { buildApp } = await import("/app/dist/app/build-app.js");
const { generateSharedBrainReply } = await import(
  "/app/dist/modules/brain/inference.js"
);

const USER_ID =
  process.env.DIAG_USER_ID ?? "3d676bd9-9d50-4587-bf05-defed68bcfa6";
const PROMPT = process.env.DIAG_PROMPT ?? "Son mailimi oku";

// Groq 400'ünün gerçek gövdesini yakala: fetch sarmalanır, yalnız groq
// istek/yanıt şekli (auth başlıksız) yazılır.
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, init) => {
  const target = String(url);
  const isGroq = target.includes("api.groq.com");
  if (target.includes("googleapis.com")) {
    // Gerçek Google çağrısı kanıtı: yalnız yol + durum (token asla yazılmaz).
    const r = await realFetch(url, init);
    console.error(
      "GOOGLE_CALL " +
        JSON.stringify({
          path: new URL(target).pathname,
          status: r.status,
        }),
    );
    return r;
  }
  const response = await realFetch(url, init);
  if (isGroq && !response.ok) {
    let requestShape = null;
    try {
      const parsed = JSON.parse(String(init?.body ?? "{}"));
      requestShape = {
        model: parsed.model,
        stream: parsed.stream,
        response_format: parsed.response_format,
        toolCount: Array.isArray(parsed.tools) ? parsed.tools.length : undefined,
        keys: Object.keys(parsed),
      };
    } catch {}
    const body = await response.clone().text();
    console.error(
      "GROQ_FAIL " +
        JSON.stringify({ status: response.status, requestShape, body: body.slice(0, 400) }),
    );
  }
  return response;
};

let app = null;
try {
  app = await buildApp();
  app.log.level = "debug";
  const startedAt = Date.now();
  const deltas = [];
  const result = await generateSharedBrainReply(app, {
    userId: USER_ID,
    prompt: PROMPT,
    route: "shared_brain",
    workload: process.env.DIAG_WORKLOAD || "mobile_chat_fast",
    // Mobil turun gerçek şekli: SSE streaming açık — başarısızlık streaming
    // zarf doğrulama yolundaysa ancak böyle yakalanır.
    onDelta:
      process.env.DIAG_STREAM === "false"
        ? undefined
        : async (chunk) => {
            deltas.push({
              delta: String(chunk?.delta ?? "").slice(0, 120),
              contentLen: String(chunk?.content ?? "").length,
            });
          },
    internalEvaluation: {
      skipUsageValidation: true,
      skipConsentValidation: true,
      skipInvocationLogging: true,
      // skipReviewLogging KASITLI olarak false: agent loop kapısı
      // `!skipReviewLogging` ister — true geçmek araç yürütmesini kapatıp
      // tanıyı gerçek üretim akışından koparıyordu.
      skipReviewLogging: false,
    },
  });
  console.log(
    JSON.stringify(
      {
        ok: true,
        ms: Date.now() - startedAt,
        provider: result.provider,
        model: result.model,
        deltaCount: deltas.length,
        deltas,
        text: String(result.text ?? "").slice(0, 500),
      },
      null,
      2,
    ),
  );
} catch (error) {
  console.log(
    JSON.stringify(
      {
        ok: false,
        errorName: error instanceof Error ? error.name : typeof error,
        errorMessage: error instanceof Error ? error.message : String(error),
        detail: error?.detail ?? null,
      },
      null,
      2,
    ),
  );
} finally {
  await app?.close?.();
  process.exit(0);
}
