export type LocalDerivedMetadata = Record<string, unknown> & {
  raw_file_uploaded?: boolean;
  data_origin?: string;
  privacy_level?: string;
};

const rawBinaryUploadHintKeys = new Set([
  "bytes",
  "rawbytes",
  "filebytes",
  "imagebytes",
  "documentbytes",
  "binary",
  "blob",
  "buffer",
  "arraybuffer",
  "base64",
  "base64data",
  "dataurl",
  "datauri",
  "downloadurl",
  "filepath",
  "fileuri",
  "gcskey",
  "localpath",
  "multipart",
  "objectkey",
  "presignedurl",
  "storagekey",
  "s3key",
  "signedurl",
  "uploadurl",
  "rawbinary",
  "base64thumbnail",
  "visionimagejpeg",
  "imagethumbnail",
  "thumbnailbase64",
]);

const heavyDerivedDiagnosticKeys = new Set([
  "bbox",
  "boundingbox",
  "bounds",
  "boxes",
  "coordinates",
  "geometry",
  "imagebase64",
  "imagebytes",
  "imagepreview",
  "lineboxes",
  "localpreview",
  "ocrlines",
  "ocrdump",
  "pagelines",
  "previewbytes",
  "previewimage",
  "rawlines",
  "textlines",
  "visionlines",
]);

function normalizeKey(key: string): string {
  return key.trim().toLowerCase().replace(/[\s._-]+/g, "");
}

function isExplicitTrue(value: unknown): boolean {
  return value === true || value === "true" || value === 1;
}

function isExplicitFalse(value: unknown): boolean {
  return value === false || value === "false" || value === 0;
}

function isLikelyDataUri(value: string): boolean {
  return /^data:[a-z0-9.+-]+\/[a-z0-9.+-]+;base64,[a-z0-9+/=\s]+$/i.test(value.trim());
}

function shouldDropDerivedKey(normalizedKey: string): boolean {
  return rawBinaryUploadHintKeys.has(normalizedKey) || heavyDerivedDiagnosticKeys.has(normalizedKey);
}

function sanitizeDerivedValue(value: unknown, depth = 0): unknown {
  if (depth > 8 || value == null) {
    return value;
  }

  if (Array.isArray(value)) {
    return value
      .map((item) => sanitizeDerivedValue(item, depth + 1))
      .filter((item) => item !== undefined);
  }

  if (typeof value !== "object") {
    return value;
  }

  const record = value as Record<string, unknown>;
  const next: Record<string, unknown> = {};
  for (const [rawKey, rawValue] of Object.entries(record)) {
    const normalizedKey = normalizeKey(rawKey);
    if (normalizedKey === "rawfileuploaded") {
      continue;
    }
    if (normalizedKey === "visionblock") {
      const sanitizedVision = sanitizeVisionBlockValue(rawValue, depth + 1);
      if (sanitizedVision !== undefined) {
        next[rawKey] = sanitizedVision;
      }
      continue;
    }
    if (shouldDropDerivedKey(normalizedKey)) {
      continue;
    }
    const sanitized = sanitizeDerivedValue(rawValue, depth + 1);
    if (sanitized !== undefined) {
      next[rawKey] = sanitized;
    }
  }
  return next;
}

function sanitizeVisionBlockValue(value: unknown, depth = 0): unknown {
  if (depth > 8 || value == null) {
    return value;
  }
  if (Array.isArray(value)) {
    return value
      .map((item) => sanitizeVisionBlockValue(item, depth + 1))
      .filter((item) => item !== undefined);
  }
  if (typeof value !== "object") {
    return value;
  }
  const record = value as Record<string, unknown>;
  const next: Record<string, unknown> = {};
  for (const [rawKey, rawValue] of Object.entries(record)) {
    const normalizedKey = normalizeKey(rawKey);
    if (rawBinaryUploadHintKeys.has(normalizedKey)) {
      continue;
    }
    const sanitized = sanitizeVisionBlockValue(rawValue, depth + 1);
    if (sanitized !== undefined) {
      next[rawKey] = sanitized;
    }
  }
  return next;
}

export function hasRawBinaryUploadHint(value: unknown, depth = 0): boolean {
  if (depth > 8 || !value || typeof value !== "object") {
    return false;
  }

  if (Array.isArray(value)) {
    return value.some((item) => hasRawBinaryUploadHint(item, depth + 1));
  }

  const record = value as Record<string, unknown>;
  for (const [rawKey, nextValue] of Object.entries(record)) {
    const normalizedKey = normalizeKey(rawKey);

    if (normalizedKey === "rawfileuploaded") {
      if (isExplicitTrue(nextValue)) {
        return true;
      }
      if (isExplicitFalse(nextValue)) {
        continue;
      }
    }

    if (rawBinaryUploadHintKeys.has(normalizedKey)) {
      if (typeof nextValue === "string") {
        if (nextValue.trim().length > 0) {
          if (isLikelyDataUri(nextValue)) {
            return true;
          }
          return true;
        }
        continue;
      }
      if (nextValue != null) {
        return true;
      }
    }

    if (nextValue && typeof nextValue === "object") {
      if (hasRawBinaryUploadHint(nextValue, depth + 1)) {
        return true;
      }
    }
  }

  return false;
}

export function normalizeLocalDerivedMetadata(metadata: Record<string, unknown> | undefined): LocalDerivedMetadata {
  const sanitized = sanitizeDerivedValue(metadata ?? {}) as Record<string, unknown>;
  return {
    ...(sanitized && typeof sanitized === "object" && !Array.isArray(sanitized) ? sanitized : {}),
    raw_file_uploaded: false,
    data_origin: "local_derived",
    privacy_level: "local_derived",
  };
}
