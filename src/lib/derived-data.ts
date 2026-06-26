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
  "rawbinary",
]);

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function normalizeKey(rawKey: string): string {
  return rawKey.trim().toLowerCase().replace(/[\s._-]+/g, "");
}

export function hasRawBinaryUploadHint(value: unknown, depth = 0): boolean {
  if (depth > 8 || !isPlainObject(value)) {
    return false;
  }

  for (const [rawKey, nextValue] of Object.entries(value)) {
    const normalizedKey = normalizeKey(rawKey);

    if (normalizedKey === "rawfileuploaded") {
      if (
        nextValue === true ||
        (typeof nextValue === "string" && nextValue.trim().toLowerCase() === "true") ||
        nextValue === 1
      ) {
        return true;
      }
      continue;
    }

    if (rawBinaryUploadHintKeys.has(normalizedKey)) {
      if (typeof nextValue === "string") {
        if (nextValue.trim().length > 0) {
          return true;
        }
      } else if (nextValue != null) {
        return true;
      }
    }

    if (isPlainObject(nextValue) && hasRawBinaryUploadHint(nextValue, depth + 1)) {
      return true;
    }

    if (Array.isArray(nextValue) && nextValue.some((item) => hasRawBinaryUploadHint(item, depth + 1))) {
      return true;
    }
  }

  return false;
}

export function normalizeLocalDerivedMetadata(
  metadata: Record<string, unknown> | undefined | null,
): Record<string, unknown> {
  const normalized = isPlainObject(metadata) ? { ...metadata } : {};
  normalized.raw_file_uploaded = false;
  normalized.data_origin = "local_derived";
  normalized.privacy_level = "local_derived";
  return normalized;
}
