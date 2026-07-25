/**
 * Tanı: desktop_plan turunu gerçek app bağlamıyla tetikler ve sağlayıcı
 * 400'lerinin GERÇEK gövdesini yakalar. Konteyner içinde:
 *   docker exec elyan-backend-backend-1 node scripts/diag-desktop-plan.mjs
 * Ortam: DIAG_PROMPT (zarf), DIAG_USER_TEXT (ham cümle), DIAG_USER_ID.
 */
const { buildApp } = await import("/app/dist/app/build-app.js");
const { generateDesktopPlan } = await import(
  "/app/dist/modules/brain/desktop-plan.js"
);

const USER_ID =
  process.env.DIAG_USER_ID ?? "3d676bd9-9d50-4587-bf05-defed68bcfa6";
const USER_TEXT = process.env.DIAG_USER_TEXT ?? "selam, nasılsın bugün?";
const PROMPT =
  process.env.DIAG_PROMPT ??
  `Kullanıcı mesajını ANLAMLANDIR ve SADECE tek JSON nesnesi döndür: {"intent":"chat|task","confidence":0.0}\nDURUM: {"message": ${JSON.stringify(USER_TEXT)}}`;

// Sağlayıcı hatasının gerçek gövdesi: fetch sarmalanır (auth başlığı asla yazılmaz).
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, init) => {
  const target = String(url);
  const response = await realFetch(url, init);
  const isProvider =
    target.includes("api.groq.com") || target.includes("googleapis.com");
  if (isProvider && !response.ok) {
    let requestShape = null;
    try {
      const parsed = JSON.parse(String(init?.body ?? "{}"));
      requestShape = {
        model: parsed.model,
        stream: parsed.stream,
        max_tokens: parsed.max_tokens,
        response_format_type: parsed.response_format?.type,
        reasoning_format: parsed.reasoning_format,
        reasoning_effort: parsed.reasoning_effort,
        messageCount: Array.isArray(parsed.messages) ? parsed.messages.length : 0,
        keys: Object.keys(parsed),
      };
    } catch {}
    const body = await response.clone().text();
    console.error(
      "PROVIDER_FAIL " +
        JSON.stringify({
          host: new URL(target).host,
          status: response.status,
          requestShape,
          body: body.slice(0, 600),
        }),
    );
  }
  return response;
};

let app = null;
try {
  app = await buildApp();
  const startedAt = Date.now();
  const result = await generateDesktopPlan(app, {
    userId: USER_ID,
    prompt: PROMPT,
    contract: "elyan.plan.v2",
    repair: false,
    userText: USER_TEXT,
    requestId: "diag-desktop-plan",
  });
  console.log(
    "RESULT " +
      JSON.stringify({
        ok: result.ok,
        error: result.error ?? null,
        provider: result.provider,
        model: result.model,
        latencyMs: Date.now() - startedAt,
        plan: result.plan ? Object.keys(result.plan) : null,
        text: String(result.text ?? "").slice(0, 300),
      }),
  );
} catch (error) {
  console.error("DIAG_ERROR " + String(error?.stack ?? error).slice(0, 800));
} finally {
  try {
    await app?.close();
  } catch {}
  process.exit(0);
}
