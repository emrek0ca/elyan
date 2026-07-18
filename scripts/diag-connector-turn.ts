/**
 * Tanı: başarısız "Son mailimi oku" turunu gerçek app bağlamıyla (DB, redis,
 * sağlayıcılar, connector araçları) birebir tetikler ve sonucu/gerçek hatayı
 * yazar. Backend konteyneri içinde çalıştırılır:
 *   docker exec elyan-backend-backend-1 npx tsx scripts/diag-connector-turn.ts
 */
import { buildApp } from "../src/app/build-app.js";
import { generateSharedBrainReply } from "../src/modules/brain/inference.js";

const USER_ID = process.env.DIAG_USER_ID ?? "3d676bd9-9d50-4587-bf05-defed68bcfa6";
const PROMPT = process.env.DIAG_PROMPT ?? "Son mailimi oku";

let app: Awaited<ReturnType<typeof buildApp>> | null = null;
try {
  app = await buildApp();
  // Teşhiste debug satırları da görünsün (connector reklam/ipucu kararları).
  app.log.level = "debug";
  const startedAt = Date.now();
  const result = await generateSharedBrainReply(app as never, {
    userId: USER_ID,
    prompt: PROMPT,
    route: "shared_brain",
    workload: "mobile_chat_fast",
    internalEvaluation: {
      skipUsageValidation: true,
      skipConsentValidation: true,
      skipInvocationLogging: true,
      skipReviewLogging: true,
    },
  });
  console.log(
    JSON.stringify(
      {
        ok: true,
        ms: Date.now() - startedAt,
        provider: result.provider,
        model: result.model,
        text: String(result.text ?? "").slice(0, 500),
        connectorToolMeta: {
          advertised: result.metadata?.connectorToolContractCount ?? null,
          toolResults: result.metadata?.connectorToolResultCount ?? null,
          toolSuccess: result.metadata?.connectorToolSuccessCount ?? null,
        },
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
        detail: (error as { detail?: unknown })?.detail ?? null,
      },
      null,
      2,
    ),
  );
} finally {
  await app?.close();
  process.exit(0);
}
