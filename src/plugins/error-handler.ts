import fp from "fastify-plugin";
import { ZodError } from "zod";
import { AppError } from "../lib/errors.js";
import { serializeZodError } from "../lib/http.js";
import { sanitizePublicErrorDetails } from "../lib/public-error-details.js";

/**
 * Makine kodu mu, insana yazılmış cümle mi?
 *
 * `snake_case`, boşluksuz, tek parça bir dize kullanıcıya gösterilmek üzere
 * yazılmamıştır. Kod tabanında onlarca yerde `conflict("apple_product_mismatch")`
 * gibi çağrılar var: `AppError.message` doğrudan istemciye yayınlandığı için
 * kullanıcı ekranda ham kodu görüyordu (canlı örnek: abonelik ekranında
 * "apple_subscription_owned_by_another_user" yazan bir uyarı kutusu).
 *
 * Her çağrı yerini tek tek düzeltmek hem büyük hem de yarın eklenecek yeni
 * bir `throw` için işe yaramaz. Kural TEK SINIRDA duruyor: makine kodu gibi
 * görünen bir mesaj kullanıcıya çıkmaz.
 */
function looksLikeMachineCode(message: string): boolean {
  const compact = message.trim();
  if (!compact || compact.length > 80 || /\s/.test(compact)) {
    return false;
  }
  return /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/.test(compact);
}

/**
 * Kullanıcıya gösterilebilir karşılıklar. Listede olmayan kod, güvenli genel
 * mesaja düşer — ham kod HİÇBİR koşulda sızmaz. Makine kodu kaybolmaz:
 * `details.reason` içinde taşınır (telemetri ve istemci mantığı için).
 */
const USER_FACING_ERROR_MESSAGES: Record<string, string> = {
  apple_subscription_owned_by_another_user:
    "Bu App Store aboneliği başka bir Elyan hesabına bağlı. Aboneliği aldığın hesapla giriş yap ya da destek ekibine yaz.",
  store_transaction_owned_by_another_user:
    "Bu satın alma başka bir Elyan hesabına bağlı. Satın almayı yaptığın hesapla giriş yap.",
  active_apple_subscription_provider_locked:
    "Hesabında etkin bir App Store aboneliği var. Ödeme yöntemini değiştirmek için önce mevcut aboneliği App Store üzerinden iptal et.",
  apple_plan_product_mismatch:
    "Seçilen plan ile App Store ürünü eşleşmiyor. Uygulamayı güncelleyip tekrar dene.",
  apple_product_mismatch:
    "Seçilen plan ile App Store ürünü eşleşmiyor. Uygulamayı güncelleyip tekrar dene.",
  checkout_initialization_in_progress:
    "Ödeme başlatma işlemin sürüyor. Birkaç saniye sonra tekrar dene.",
};

function toUserFacingMessage(message: string): {
  message: string;
  reason?: string;
} {
  if (!looksLikeMachineCode(message)) {
    return { message };
  }
  const code = message.trim();
  return {
    message:
      USER_FACING_ERROR_MESSAGES[code] ??
      "İşlem tamamlanamadı. Biraz sonra tekrar dener misin?",
    reason: code,
  };
}

function readRetryAfterSeconds(details: unknown): number | null {
  if (!details || typeof details !== "object" || Array.isArray(details)) {
    return null;
  }

  const value = (details as Record<string, unknown>).retryAfterSeconds;
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

export const errorHandlerPlugin = fp(async (app) => {
  app.setErrorHandler((error, request, reply) => {
    reply.header("x-request-id", request.id);

    if (error instanceof ZodError) {
      reply.status(400).send({
        error: "validation_error",
        message: "Invalid request payload",
        details: serializeZodError(error),
        requestId: request.id,
      });
      return;
    }

    if (error instanceof AppError) {
      const retryAfterSeconds =
        error.statusCode === 429 || error.statusCode === 503
          ? readRetryAfterSeconds(error.details)
          : null;
      if (retryAfterSeconds != null) {
        reply.header("retry-after", String(retryAfterSeconds));
      }
      if (error.statusCode === 409) {
        app.log.warn({ err: { code: error.code, message: error.message, details: error.details }, requestId: request.id, url: request.url }, "409 app error");
      }
      const publicDetails = sanitizePublicErrorDetails(error.details);
      // Ham makine kodu kullanıcıya ÇIKMAZ; koda karşılık gelen insan cümlesi
      // gider ve kodun kendisi `details.reason`'da korunur.
      const userFacing = toUserFacingMessage(error.message);
      const detailsObject =
        typeof publicDetails === "object" && publicDetails && !Array.isArray(publicDetails)
          ? (publicDetails as Record<string, unknown>)
          : null;
      const mergedDetails =
        retryAfterSeconds == null && userFacing.reason == null
          ? publicDetails
          : {
              ...(detailsObject ?? {}),
              ...(userFacing.reason ? { reason: userFacing.reason } : {}),
              ...(retryAfterSeconds != null
                ? { retryAfterMs: retryAfterSeconds * 1000 }
                : {}),
            };
      reply.status(error.statusCode).send({
        error: error.code,
        message: userFacing.message,
        details: mergedDetails,
        requestId: request.id,
      });
      return;
    }

    if (typeof error === "object" && error && "code" in error && error.code === "23505") {
      app.log.warn({ err: error, requestId: request.id, url: request.url }, "409 unique constraint violation");
      reply.status(409).send({
        error: "conflict",
        message: "Resource already exists",
        requestId: request.id,
      });
      return;
    }

    if (isHttpClientError(error)) {
      const statusCode = Number((error as { statusCode: number }).statusCode);
      app.log.warn({ err: error, requestId: request.id, url: request.url }, "client request error");
      reply.status(statusCode).send({
        error: "invalid_request",
        message: "Invalid request payload",
        requestId: request.id,
      });
      return;
    }

    if (
      typeof error === "object" &&
      error &&
      "statusCode" in error &&
      error.statusCode === 429
    ) {
      const retryAfterSeconds = parseRetryAfterSeconds(
        "message" in error ? String(error.message) : "",
      );
      if (retryAfterSeconds != null) {
        reply.header("retry-after", String(retryAfterSeconds));
      }
      reply.status(429).send({
        error: "rate_limited",
        message: "Rate limit exceeded",
        details:
          retryAfterSeconds == null
            ? undefined
            : { retryAfterMs: retryAfterSeconds * 1000 },
        requestId: request.id,
      });
      return;
    }

    app.log.error({ err: error, requestId: request.id }, "request failed");

    reply.status(500).send({
      error: "internal_error",
      message: "Internal server error",
      requestId: request.id,
    });
  });
});

function isHttpClientError(error: unknown): boolean {
  if (!error || typeof error !== "object" || !("statusCode" in error)) {
    return false;
  }
  const statusCode = Number((error as { statusCode?: unknown }).statusCode);
  return Number.isInteger(statusCode) && statusCode >= 400 && statusCode < 500 && statusCode !== 429;
}

function parseRetryAfterSeconds(message: string): number | null {
  const match = /retry in\s+(\d+)\s+seconds?/i.exec(message);
  if (!match) {
    return null;
  }
  const value = Number.parseInt(match[1] ?? "", 10);
  return Number.isFinite(value) && value > 0 ? value : null;
}
