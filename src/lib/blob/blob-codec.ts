import { createHash } from "node:crypto";

export type BlobBodyKind = "json" | "text" | "binary";
export type BlobCompression = "identity" | "zstd";

export type EncodedBlob = {
  bodyKind: BlobBodyKind;
  contentType: string;
  compression: BlobCompression;
  rawBytes: Uint8Array;
  storedBytes: Uint8Array;
  rawSize: number;
  storedSize: number;
  sha256: string;
};

type ZstdModule = typeof import("@bokuweb/zstd-wasm");

let zstdModulePromise: Promise<ZstdModule | null> | null = null;

function normalizeContentType(value: string, fallback: string): string {
  const normalized = String(value ?? "")
    .trim()
    .toLowerCase()
    .split(";")[0]
    ?.trim();
  return normalized || fallback;
}

function shouldCompress(contentType: string, bodyKind: BlobBodyKind): boolean {
  if (bodyKind === "binary") {
    return false;
  }

  return (
    contentType.startsWith("text/") ||
    contentType === "application/json" ||
    contentType.endsWith("+json") ||
    contentType === "application/xml" ||
    contentType.endsWith("+xml") ||
    contentType === "text/csv"
  );
}

function normalizeJsonValue(value: unknown): unknown {
  if (value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return value;
  }

  if (Array.isArray(value)) {
    return value.map((item) => normalizeJsonValue(item));
  }

  if (value instanceof Date) {
    return value.toISOString();
  }

  if (!value || typeof value !== "object") {
    return null;
  }

  return Object.keys(value as Record<string, unknown>)
    .sort()
    .reduce<Record<string, unknown>>((accumulator, key) => {
      const normalized = normalizeJsonValue((value as Record<string, unknown>)[key]);
      if (normalized !== undefined) {
        accumulator[key] = normalized;
      }
      return accumulator;
    }, {});
}

function stableSerializeJson(value: unknown): string {
  return JSON.stringify(normalizeJsonValue(value));
}

async function loadZstdModule(): Promise<ZstdModule | null> {
  if (!zstdModulePromise) {
    zstdModulePromise = (async () => {
      try {
        const mod = await import("@bokuweb/zstd-wasm");
        const init = mod.default as unknown as (() => Promise<void> | void) | undefined;
        if (typeof init === "function") {
          await init();
        }
        return mod;
      } catch {
        return null;
      }
    })();
  }

  return zstdModulePromise;
}

async function maybeCompress(rawBytes: Uint8Array, contentType: string, bodyKind: BlobBodyKind): Promise<{
  compression: BlobCompression;
  storedBytes: Uint8Array;
}> {
  if (!shouldCompress(contentType, bodyKind)) {
    return {
      compression: "identity",
      storedBytes: rawBytes,
    };
  }

  const zstd = await loadZstdModule();
  if (!zstd?.compress) {
    return {
      compression: "identity",
      storedBytes: rawBytes,
    };
  }

  try {
    const compressed = zstd.compress(rawBytes, 10);
    if (!compressed || compressed.length <= 0 || compressed.length >= rawBytes.length) {
      return {
        compression: "identity",
        storedBytes: rawBytes,
      };
    }
    return {
      compression: "zstd",
      storedBytes: compressed,
    };
  } catch {
    return {
      compression: "identity",
      storedBytes: rawBytes,
    };
  }
}

export async function encodeJsonBlob(value: unknown, contentType = "application/json"): Promise<EncodedBlob> {
  const normalizedContentType = normalizeContentType(contentType, "application/json");
  const text = stableSerializeJson(value);
  const rawBytes = Buffer.from(text, "utf8");
  const compressed = await maybeCompress(rawBytes, normalizedContentType, "json");
  return {
    bodyKind: "json",
    contentType: normalizedContentType,
    compression: compressed.compression,
    rawBytes,
    storedBytes: compressed.storedBytes,
    rawSize: rawBytes.byteLength,
    storedSize: compressed.storedBytes.byteLength,
    sha256: createHash("sha256").update(rawBytes).digest("hex"),
  };
}

export async function encodeTextBlob(value: string, contentType = "text/plain"): Promise<EncodedBlob> {
  const normalizedContentType = normalizeContentType(contentType, "text/plain");
  const rawBytes = Buffer.from(String(value ?? ""), "utf8");
  const compressed = await maybeCompress(rawBytes, normalizedContentType, "text");
  return {
    bodyKind: "text",
    contentType: normalizedContentType,
    compression: compressed.compression,
    rawBytes,
    storedBytes: compressed.storedBytes,
    rawSize: rawBytes.byteLength,
    storedSize: compressed.storedBytes.byteLength,
    sha256: createHash("sha256").update(rawBytes).digest("hex"),
  };
}

export async function encodeBinaryBlob(bytes: Uint8Array, contentType: string): Promise<EncodedBlob> {
  const normalizedContentType = normalizeContentType(contentType, "application/octet-stream");
  const rawBytes = bytes instanceof Uint8Array ? bytes : Uint8Array.from(bytes);
  return {
    bodyKind: "binary",
    contentType: normalizedContentType,
    compression: "identity",
    rawBytes,
    storedBytes: rawBytes,
    rawSize: rawBytes.byteLength,
    storedSize: rawBytes.byteLength,
    sha256: createHash("sha256").update(rawBytes).digest("hex"),
  };
}

export async function decodeBlobBytes(input: {
  storedBytes: Uint8Array;
  compression: BlobCompression | string | null | undefined;
}): Promise<Uint8Array> {
  const compression = input.compression === "zstd" ? "zstd" : "identity";
  if (compression === "identity") {
    return input.storedBytes;
  }

  const zstd = await loadZstdModule();
  if (!zstd?.decompress) {
    throw new Error("zstd codec unavailable");
  }

  return zstd.decompress(input.storedBytes);
}

export async function decodeTextBlob(input: {
  storedBytes: Uint8Array;
  compression: BlobCompression | string | null | undefined;
}): Promise<string> {
  const bytes = await decodeBlobBytes(input);
  return Buffer.from(bytes).toString("utf8");
}

export async function decodeJsonBlob<T>(input: {
  storedBytes: Uint8Array;
  compression: BlobCompression | string | null | undefined;
}): Promise<T> {
  const text = await decodeTextBlob(input);
  return JSON.parse(text) as T;
}
