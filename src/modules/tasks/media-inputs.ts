import {
  createCipheriv,
  createDecipheriv,
  createHmac,
  randomBytes,
  randomUUID,
  timingSafeEqual,
} from "node:crypto";
import type { FastifyInstance } from "fastify";
import {
  AppError,
  badRequest,
  notFound,
  serviceUnavailable,
} from "../../lib/errors.js";
import type { EphemeralVisionCarrier } from "../brain/ephemeral-vision.js";
import { MAX_EPHEMERAL_VISION_INPUTS } from "../brain/ephemeral-vision.js";
import type { HostedImageSource } from "../brain/image-generation.js";
import { reserveMediaNormalizationAdmission } from "./media-admission.js";

const MEDIA_INPUT_TTL_SECONDS = 15 * 60;
const MEDIA_INPUT_MAX_BYTES = 12 * 1024 * 1024;
const MEDIA_INPUT_MAX_TOTAL_BYTES = 12 * 1024 * 1024;
const VISION_INPUT_MAX_BYTES = 2_800_000;
const VISION_INPUT_MAX_TOTAL_BYTES = 8 * 1024 * 1024;
const MEDIA_INPUT_RATE_WINDOW_MS = 15 * 60_000;
const MEDIA_INPUT_RATE_MAX_FILES = 12;
const MEDIA_INPUT_RATE_MAX_BYTES = 96 * 1024 * 1024;
const MEDIA_INPUT_GLOBAL_RATE_MAX_FILES = 72;
const MEDIA_CONTEXT_RATE_MAX_FILES = 60;
const MEDIA_CONTEXT_RATE_MAX_BYTES = 48 * 1024 * 1024;
const MEDIA_CONTEXT_MAX_BYTES = 1024 * 1024;
const MEDIA_CONTEXT_MAX_EDGE = 1280;
type MediaInputIntent = "attachment" | "live_camera" | "screen_context";
type MediaTemporalRole = "speech_start" | "speech_sample" | "speech_end";
type MediaTemporalSequence = 0 | 1 | 2;
const ALLOWED_IMAGE_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/heic",
  "image/heif",
]);

type MediaInputTokenPayload = {
  id: string;
  blobId: string;
  userId: string;
  ownerId: string;
  name: string;
  contentType: "image/png" | "image/jpeg" | "image/webp";
  byteLength: number;
  intent?: MediaInputIntent;
  temporalRole?: MediaTemporalRole;
  temporalSequence?: MediaTemporalSequence;
  exp: number;
};

function tokenSecret(app: FastifyInstance): string {
  return String(
    app.config.TOKEN_ENCRYPTION_KEY ||
      app.config.BLOB_HMAC_SECRET ||
      app.config.JWT_SECRET ||
      "",
  ).trim();
}

function legacyTokenSecrets(app: FastifyInstance): string[] {
  return [
    app.config.BLOB_HMAC_SECRET,
    app.config.JWT_SECRET,
    app.config.TOKEN_ENCRYPTION_KEY,
  ]
    .map((value) => String(value || "").trim())
    .filter(
      (value, index, values) =>
        value.length >= 32 && values.indexOf(value) === index,
    );
}

function requireTokenSecret(app: FastifyInstance): string {
  const secret = tokenSecret(app);
  if (secret.length < 32) {
    throw serviceUnavailable("Image input protection is unavailable");
  }
  return secret;
}

function sign(secret: string, payload: string): string {
  return createHmac("sha256", secret).update(payload).digest("base64url");
}

function tokenEncryptionKey(secret: string): Buffer {
  return createHmac("sha256", secret)
    .update("elyan.media_input.token.v2")
    .digest();
}

function equalToken(left: string, right: string): boolean {
  const a = Buffer.from(left);
  const b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
}

function encodeToken(
  app: FastifyInstance,
  payload: MediaInputTokenPayload,
): string {
  const secret = requireTokenSecret(app);
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", tokenEncryptionKey(secret), iv);
  cipher.setAAD(Buffer.from("elyan.media_input.v2", "utf8"));
  const encrypted = Buffer.concat([
    cipher.update(JSON.stringify(payload), "utf8"),
    cipher.final(),
  ]);
  return [
    "v2",
    iv.toString("base64url"),
    encrypted.toString("base64url"),
    cipher.getAuthTag().toString("base64url"),
  ].join(".");
}

function validateTokenPayload(
  payload: MediaInputTokenPayload,
  userId: string,
): MediaInputTokenPayload | null {
  if (
    !payload ||
    typeof payload.id !== "string" ||
    typeof payload.blobId !== "string" ||
    typeof payload.userId !== "string" ||
    typeof payload.ownerId !== "string" ||
    typeof payload.name !== "string" ||
    typeof payload.contentType !== "string" ||
    !Number.isSafeInteger(payload.byteLength) ||
    payload.byteLength <= 0 ||
    payload.byteLength > MEDIA_INPUT_MAX_BYTES ||
    (payload.intent !== undefined &&
      payload.intent !== "attachment" &&
      payload.intent !== "live_camera" &&
      payload.intent !== "screen_context") ||
    (payload.temporalRole !== undefined &&
      payload.temporalRole !== "speech_start" &&
      payload.temporalRole !== "speech_sample" &&
      payload.temporalRole !== "speech_end") ||
    (payload.temporalSequence !== undefined &&
      payload.temporalSequence !== 0 &&
      payload.temporalSequence !== 1 &&
      payload.temporalSequence !== 2) ||
    ((payload.temporalRole === undefined) !==
      (payload.temporalSequence === undefined)) ||
    (payload.temporalRole === "speech_start" &&
      payload.temporalSequence !== 0) ||
    (payload.temporalRole === "speech_sample" &&
      payload.temporalSequence !== 1) ||
    (payload.temporalRole === "speech_end" &&
      payload.temporalSequence !== 2) ||
    (payload.temporalRole !== undefined &&
      payload.intent !== "live_camera" &&
      payload.intent !== "screen_context") ||
    !Number.isSafeInteger(payload.exp) ||
    payload.userId !== userId ||
    payload.exp < Math.floor(Date.now() / 1000) ||
    payload.ownerId !== `${userId}:${payload.id}` ||
    !ALLOWED_IMAGE_TYPES.has(payload.contentType)
  ) {
    return null;
  }
  return payload;
}

function decodeLegacyToken(
  app: FastifyInstance,
  inputRef: string,
  userId: string,
): MediaInputTokenPayload | null {
  const [encoded, signature, extra] = String(inputRef ?? "").split(".");
  if (!encoded || !signature || extra !== undefined) return null;
  const signatureValid = legacyTokenSecrets(app).some((secret) =>
    equalToken(signature, sign(secret, encoded)),
  );
  if (!signatureValid) return null;
  try {
    const payload = JSON.parse(
      Buffer.from(encoded, "base64url").toString("utf8"),
    ) as MediaInputTokenPayload;
    return validateTokenPayload(payload, userId);
  } catch {
    return null;
  }
}

function decodeToken(
  app: FastifyInstance,
  inputRef: string,
  userId: string,
): MediaInputTokenPayload | null {
  const parts = String(inputRef ?? "").split(".");
  if (parts[0] !== "v2") {
    return decodeLegacyToken(app, inputRef, userId);
  }
  if (parts.length !== 4 || tokenSecret(app).length < 32) return null;
  try {
    const iv = Buffer.from(parts[1]!, "base64url");
    const encrypted = Buffer.from(parts[2]!, "base64url");
    const authTag = Buffer.from(parts[3]!, "base64url");
    if (
      iv.byteLength !== 12 ||
      authTag.byteLength !== 16 ||
      !encrypted.byteLength
    ) {
      return null;
    }
    const decipher = createDecipheriv(
      "aes-256-gcm",
      tokenEncryptionKey(tokenSecret(app)),
      iv,
    );
    decipher.setAAD(Buffer.from("elyan.media_input.v2", "utf8"));
    decipher.setAuthTag(authTag);
    const plaintext = Buffer.concat([
      decipher.update(encrypted),
      decipher.final(),
    ]).toString("utf8");
    return validateTokenPayload(
      JSON.parse(plaintext) as MediaInputTokenPayload,
      userId,
    );
  } catch {
    return null;
  }
}

function safeName(value: string, contentType: string): string {
  const extension =
    contentType === "image/png"
      ? ".png"
      : contentType === "image/webp"
        ? ".webp"
        : ".jpg";
  const cleaned = (
    String(value || "image")
      .replace(/[\\/\0\r\n]/g, "_")
      .trim()
      .slice(0, 180) || "image"
  ).replace(/\.(?:heic|heif)$/i, "");
  return /\.(?:png|jpe?g|webp)$/i.test(cleaned)
    ? cleaned
    : `${cleaned}${extension}`;
}

async function consumeMediaInputUploadBudget(
  app: FastifyInstance,
  userId: string,
  byteLength: number,
  intent: MediaInputIntent,
): Promise<void> {
  const store = app.services?.reliability?.store;
  if (!store) {
    throw serviceUnavailable("Image upload protection is unavailable");
  }
  const ownerHash = createHmac("sha256", tokenSecret(app))
    .update(userId)
    .digest("hex")
    .slice(0, 24);
  const prefix = `media-input:${ownerHash}`;
  const scopedPrefix = `${prefix}:${intent}`;
  const [globalFileCount, globalByteCount, fileCount, byteCount] =
    await Promise.all([
      store.increment(`${prefix}:all:files`, MEDIA_INPUT_RATE_WINDOW_MS),
      store.incrementBy(
        `${prefix}:all:bytes`,
        byteLength,
        MEDIA_INPUT_RATE_WINDOW_MS,
      ),
      store.increment(`${scopedPrefix}:files`, MEDIA_INPUT_RATE_WINDOW_MS),
      store.incrementBy(
        `${scopedPrefix}:bytes`,
        byteLength,
        MEDIA_INPUT_RATE_WINDOW_MS,
      ),
    ]).catch(() => {
      throw serviceUnavailable("Image upload protection is unavailable");
    });
  const contextIntent = intent !== "attachment";
  const scopedMaxFiles = contextIntent
    ? MEDIA_CONTEXT_RATE_MAX_FILES
    : MEDIA_INPUT_RATE_MAX_FILES;
  const scopedMaxBytes = contextIntent
    ? MEDIA_CONTEXT_RATE_MAX_BYTES
    : MEDIA_INPUT_RATE_MAX_BYTES;
  if (
    globalFileCount > MEDIA_INPUT_GLOBAL_RATE_MAX_FILES ||
    globalByteCount > MEDIA_INPUT_RATE_MAX_BYTES ||
    fileCount > scopedMaxFiles ||
    byteCount > scopedMaxBytes
  ) {
    throw new AppError(
      429,
      "media_input_rate_limited",
      "Çok fazla görsel yüklendi. Lütfen kısa süre sonra tekrar dene.",
      { retryAfterMs: MEDIA_INPUT_RATE_WINDOW_MS },
    );
  }
}

async function normalizeMediaInput(
  body: Uint8Array,
  declaredContentType: string,
  options?: { maxEdge?: number; jpegQuality?: number },
): Promise<{
  body: Buffer;
  contentType: MediaInputTokenPayload["contentType"];
}> {
  try {
    const { default: sharp } = await import("sharp");
    const source = sharp(Buffer.from(body), {
      failOn: "warning",
      limitInputPixels: 100_000_000,
    });
    const metadata = await source.metadata();
    const detectedContentType =
      metadata.format === "png"
        ? "image/png"
        : metadata.format === "webp"
          ? "image/webp"
          : metadata.format === "jpeg"
            ? "image/jpeg"
            : metadata.format === "heif"
              ? "image/heif"
              : null;
    const declaredMatches =
      detectedContentType === declaredContentType ||
      (detectedContentType === "image/heif" &&
        ["image/heic", "image/heif"].includes(declaredContentType));
    if (!detectedContentType || !declaredMatches) {
      throw badRequest("Image content does not match its declared type");
    }
    const oriented = source.rotate().resize({
      width: options?.maxEdge ?? 4096,
      height: options?.maxEdge ?? 4096,
      fit: "inside",
      withoutEnlargement: true,
    });
    const normalized =
      detectedContentType === "image/png"
        ? await oriented.png({ compressionLevel: 9 }).toBuffer()
        : detectedContentType === "image/webp"
          ? await oriented
              .webp({ quality: 95, smartSubsample: true })
              .toBuffer()
          : await oriented
              .jpeg({
                quality: options?.jpegQuality ?? 95,
                chromaSubsampling: "4:4:4",
              })
              .toBuffer();
    if (
      !normalized.byteLength ||
      normalized.byteLength > MEDIA_INPUT_MAX_BYTES
    ) {
      throw badRequest("Normalized image exceeds the 12 MB limit");
    }
    return {
      body: normalized,
      contentType:
        detectedContentType === "image/heif"
          ? "image/jpeg"
          : detectedContentType,
    };
  } catch (error) {
    if (error && typeof error === "object" && "statusCode" in error)
      throw error;
    throw badRequest("Image input could not be decoded");
  }
}

export async function storeMediaInput(
  app: FastifyInstance,
  input: {
    userId: string;
    body: Uint8Array;
    contentType: string;
    name: string;
    intent?: string;
    temporalRole?: string;
    temporalSequence?: string | number;
  },
) {
  requireTokenSecret(app);
  const intent = normalizeMediaInputIntent(input.intent);
  const temporal = normalizeMediaTemporalContext(
    intent,
    input.temporalRole,
    input.temporalSequence,
  );
  const contentType = input.contentType.toLowerCase().split(";", 1)[0]!.trim();
  if (!ALLOWED_IMAGE_TYPES.has(contentType))
    throw badRequest("Unsupported image type");
  const maxInputBytes =
    intent === "attachment" ? MEDIA_INPUT_MAX_BYTES : MEDIA_CONTEXT_MAX_BYTES;
  if (!input.body.byteLength || input.body.byteLength > maxInputBytes) {
    throw badRequest(
      intent === "attachment"
        ? "Image input must be between 1 byte and 12 MB"
        : "Visual context input must be between 1 byte and 1 MB",
    );
  }
  const admission = await reserveMediaNormalizationAdmission(app, input.userId);
  try {
    // Capacity rejection is transient and must not consume the user's
    // 15-minute media allowance. Route-level IP/user budgets still protect
    // this admission attempt before any image decoding work begins.
    await consumeMediaInputUploadBudget(
      app,
      input.userId,
      input.body.byteLength,
      intent,
    );
    const normalized = await normalizeMediaInput(
      input.body,
      contentType,
      intent === "attachment"
        ? undefined
        : { maxEdge: MEDIA_CONTEXT_MAX_EDGE, jpegQuality: 82 },
    );
    if (
      intent !== "attachment" &&
      normalized.body.byteLength > MEDIA_CONTEXT_MAX_BYTES
    ) {
      throw badRequest(
        "Visual context input exceeds the 1 MB normalized limit",
      );
    }
    const id = randomUUID();
    const ownerId = `${input.userId}:${id}`;
    const exp = Math.floor(Date.now() / 1000) + MEDIA_INPUT_TTL_SECONDS;
    const stored = await app.services?.blobs?.storeBinary({
      ownerType: "media_input",
      ownerId,
      userId: input.userId,
      slot: "body",
      scope: "task_input_image",
      value: normalized.body,
      contentType: normalized.contentType,
      expiresAt: new Date(exp * 1000),
    });
    if (!stored?.blobId) throw badRequest("Image input could not be stored");
    const payload: MediaInputTokenPayload = {
      id,
      blobId: stored.blobId,
      userId: input.userId,
      ownerId,
      name: safeName(input.name, normalized.contentType),
      contentType: normalized.contentType,
      byteLength: stored.byteLength,
      intent,
      ...temporal,
      exp,
    };
    return {
      inputRef: encodeToken(app, payload),
      name: payload.name,
      contentType: payload.contentType,
      byteLength: payload.byteLength,
      expiresAt: new Date(exp * 1000).toISOString(),
      ...(payload.intent !== "attachment" ? { mediaIntent: payload.intent } : {}),
      ...(payload.temporalRole
        ? {
            temporalRole: payload.temporalRole,
            temporalSequence: payload.temporalSequence,
          }
        : {}),
    };
  } finally {
    await admission.release();
  }
}

function normalizeMediaInputIntent(value: unknown): MediaInputIntent {
  const normalized = String(value ?? "attachment")
    .trim()
    .toLowerCase();
  if (
    normalized === "attachment" ||
    normalized === "live_camera" ||
    normalized === "screen_context"
  ) {
    return normalized;
  }
  throw badRequest("Unsupported media input intent");
}

function normalizeMediaTemporalContext(
  intent: MediaInputIntent,
  roleValue: unknown,
  sequenceValue: unknown,
): {
  temporalRole?: MediaTemporalRole;
  temporalSequence?: MediaTemporalSequence;
} {
  const role = String(roleValue ?? "").trim().toLowerCase();
  const rawSequence = String(sequenceValue ?? "").trim();
  if (!role && !rawSequence) return {};
  if (intent === "attachment") {
    throw badRequest("Temporal metadata requires visual context input");
  }
  const sequence = Number(rawSequence);
  if (
    (role !== "speech_start" &&
      role !== "speech_sample" &&
      role !== "speech_end") ||
    !Number.isInteger(sequence) ||
    (sequence !== 0 && sequence !== 1 && sequence !== 2) ||
    (role === "speech_start" && sequence !== 0) ||
    (role === "speech_sample" && sequence !== 1) ||
    (role === "speech_end" && sequence !== 2)
  ) {
    throw badRequest("Invalid visual temporal metadata");
  }
  return {
    temporalRole: role,
    temporalSequence: sequence as MediaTemporalSequence,
  };
}

/** Convert an authorized legacy inline carrier into the durable V2 media store. */
export async function materializeLegacyVisionForDurableQueue(
  app: FastifyInstance,
  userId: string,
  carrier: EphemeralVisionCarrier | undefined,
): Promise<EphemeralVisionCarrier | undefined> {
  if (!carrier || carrier.version === 2) return carrier;

  try {
    const inputRefs: Awaited<ReturnType<typeof storeMediaInput>>[] = [];
    for (const [index, image] of carrier.images.entries()) {
      inputRefs.push(
        await storeMediaInput(app, {
          userId,
          body: Buffer.from(image.base64Data, "base64"),
          contentType: image.mimeType,
          name: `${image.imageId || `legacy-image-${index + 1}`}.${
            image.mimeType === "image/png"
              ? "png"
              : image.mimeType === "image/webp"
                ? "webp"
                : "jpg"
          }`,
        }),
      );
    }
    return {
      version: 2,
      retention: "request_ephemeral",
      privacy: carrier.privacy,
      inputRefs,
      images: [] as never[],
    };
  } finally {
    for (const image of carrier.images) image.base64Data = "";
    carrier.images.length = 0;
  }
}

export async function resolveMediaInput(
  app: FastifyInstance,
  inputRef: string,
  userId: string,
) {
  const payload = decodeToken(app, inputRef, userId);
  if (!payload) throw notFound("Media input not found");
  const body = await app.services?.blobs?.hydrateBytesForOwner({
    blobId: payload.blobId,
    userId,
    ownerType: "media_input",
    ownerId: payload.ownerId,
  });
  if (
    !body ||
    body.byteLength !== payload.byteLength ||
    body.byteLength > MEDIA_INPUT_MAX_BYTES
  ) {
    throw notFound("Media input not found");
  }
  return { descriptor: payload, body };
}

export async function resolveMediaInputSources(
  app: FastifyInstance,
  userId: string,
  metadata: Record<string, unknown>,
): Promise<HostedImageSource[]> {
  const refs = Array.isArray(metadata.mediaInputRefs)
    ? metadata.mediaInputRefs
    : [];
  const sources: HostedImageSource[] = [];
  let totalBytes = 0;
  for (const item of refs.slice(0, MAX_EPHEMERAL_VISION_INPUTS)) {
    const record =
      item && typeof item === "object" && !Array.isArray(item)
        ? (item as Record<string, unknown>)
        : {};
    const inputRef = typeof record.inputRef === "string" ? record.inputRef : "";
    if (!inputRef) continue;
    let resolved: Awaited<ReturnType<typeof resolveMediaInput>>;
    try {
      resolved = await resolveMediaInput(app, inputRef, userId);
    } catch (error) {
      // A request-scoped token can expire while a queued task is starting.
      // Let vision validation or the image-edit source gate handle the
      // missing input instead of turning the whole task into a server error.
      if (error instanceof AppError && error.statusCode === 404) continue;
      throw error;
    }
    totalBytes += resolved.body.byteLength;
    if (totalBytes > MEDIA_INPUT_MAX_TOTAL_BYTES) {
      throw badRequest("Combined image inputs exceed the 12 MB request limit");
    }
    sources.push({
      base64Data: Buffer.from(resolved.body).toString("base64"),
      mimeType: resolved.descriptor.contentType,
    });
  }
  return sources;
}

export async function resolveMediaInputVisionCarrier(
  app: FastifyInstance,
  userId: string,
  carrier: EphemeralVisionCarrier | undefined,
): Promise<EphemeralVisionCarrier | undefined> {
  if (!carrier || carrier.version !== 2) return carrier;
  const admission = await reserveMediaNormalizationAdmission(app, userId);
  try {
    return await materializeMediaInputVisionCarrier(app, userId, carrier);
  } finally {
    await admission.release();
  }
}

async function materializeMediaInputVisionCarrier(
  app: FastifyInstance,
  userId: string,
  carrier: Extract<EphemeralVisionCarrier, { version: 2 }>,
): Promise<EphemeralVisionCarrier | undefined> {
  const { default: sharp } = await import("sharp");
  const images: Array<{
    imageId: string;
    label: string;
    kind: "full_frame";
    mimeType: "image/webp";
    base64Data: string;
    width: number;
    height: number;
    contentHash: string;
    mediaIntent?: "live_camera" | "screen_context";
    temporalRole?: MediaTemporalRole;
    temporalSequence?: MediaTemporalSequence;
  }> = [];
  let totalBytes = 0;

  for (const ref of carrier.inputRefs.slice(0, MAX_EPHEMERAL_VISION_INPUTS)) {
    let resolved: Awaited<ReturnType<typeof resolveMediaInput>>;
    try {
      resolved = await resolveMediaInput(app, ref.inputRef, userId);
    } catch (error) {
      if (error instanceof AppError && error.statusCode === 404) continue;
      throw error;
    }
    let output: {
      data: Buffer;
      info: { width: number; height: number };
    } | null = null;

    for (const [edge, quality] of [
      [2048, 92],
      [1600, 84],
      [1280, 76],
    ] as const) {
      const candidate = await sharp(Buffer.from(resolved.body), {
        failOn: "warning",
        limitInputPixels: 100_000_000,
      })
        .rotate()
        .resize({
          width: edge,
          height: edge,
          fit: "inside",
          withoutEnlargement: true,
        })
        .webp({ quality, smartSubsample: true, effort: 4 })
        .toBuffer({ resolveWithObject: true });
      output = {
        data: candidate.data,
        info: { width: candidate.info.width, height: candidate.info.height },
      };
      if (candidate.data.byteLength <= VISION_INPUT_MAX_BYTES) break;
    }

    if (!output || output.data.byteLength > VISION_INPUT_MAX_BYTES) {
      throw badRequest("Image input exceeds the cloud vision budget");
    }
    totalBytes += output.data.byteLength;
    if (totalBytes > VISION_INPUT_MAX_TOTAL_BYTES) {
      throw badRequest("Combined image inputs exceed the cloud vision budget");
    }
    images.push({
      imageId: resolved.descriptor.id,
      label: resolved.descriptor.name,
      kind: "full_frame",
      mimeType: "image/webp",
      base64Data: output.data.toString("base64"),
      width: output.info.width,
      height: output.info.height,
      contentHash: createHmac("sha256", tokenSecret(app))
        .update(output.data)
        .digest("hex"),
      ...(resolved.descriptor.intent === "live_camera" ||
      resolved.descriptor.intent === "screen_context"
        ? { mediaIntent: resolved.descriptor.intent }
        : {}),
      ...(resolved.descriptor.temporalRole
        ? {
            temporalRole: resolved.descriptor.temporalRole,
            temporalSequence: resolved.descriptor.temporalSequence,
          }
        : {}),
    });
  }

  if (images.length === 0) return undefined;
  return {
    version: 1,
    retention: "request_ephemeral",
    privacy: carrier.privacy,
    images,
  };
}

export async function releaseMediaInputsFromMetadata(
  app: FastifyInstance,
  userId: string,
  metadata: Record<string, unknown>,
): Promise<void> {
  const refs = Array.isArray(metadata.mediaInputRefs)
    ? metadata.mediaInputRefs
    : [];
  await releaseMediaInputRefs(app, userId, refs);
}

export async function releaseMediaInputRefs(
  app: FastifyInstance,
  userId: string,
  refs: readonly unknown[],
): Promise<void> {
  await Promise.all(
    refs.map(async (item) => {
      const record =
        item && typeof item === "object" && !Array.isArray(item)
          ? (item as Record<string, unknown>)
          : {};
      const payload =
        typeof record.inputRef === "string"
          ? decodeToken(app, record.inputRef, userId)
          : null;
      if (!payload) return;
      await app.services?.blobs?.deleteOwnedReference({
        blobId: payload.blobId,
        userId,
        ownerType: "media_input",
        ownerId: payload.ownerId,
      });
    }),
  );
}
