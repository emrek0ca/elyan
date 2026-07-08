import { randomUUID } from "node:crypto";
import { rm } from "node:fs/promises";
import assert from "node:assert/strict";
import test from "node:test";
import { BlobStore } from "./blob-store.js";

test("BlobStore stores and reads objects locally when S3 is not configured", async () => {
  const store = new BlobStore({
    BLOB_STORAGE_BUCKET: "",
    BLOB_STORAGE_REGION: "",
    BLOB_STORAGE_ENDPOINT: "",
    BLOB_STORAGE_ACCESS_KEY_ID: "",
    BLOB_STORAGE_SECRET_ACCESS_KEY: "",
    BLOB_STORAGE_FORCE_PATH_STYLE: false,
    BLOB_STORAGE_SIGNED_URL_TTL_SECONDS: 600,
  });
  const storageKey = `test/${randomUUID()}/image.bin`;
  const body = Buffer.from("elyan-image-bytes");

  assert.equal(store.isConfigured(), true);
  await store.putObject({
    storageKey,
    body,
    contentType: "image/jpeg",
  });

  assert.equal(await store.objectExists(storageKey), true);
  assert.equal(Buffer.from((await store.getObjectBytes(storageKey)) ?? []).toString("utf8"), "elyan-image-bytes");
  assert.equal(await store.createDownloadUrl({ storageKey }), null);

  await rm(".blob-store/test", { recursive: true, force: true });
});
