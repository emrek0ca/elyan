import assert from "node:assert/strict";
import test from "node:test";
import { materializeLegacyVisionForDurableQueue } from "./media-inputs.js";

test("legacy inline vision is materialized into durable V2 refs and bytes are cleared", async () => {
  const storedBodies: Uint8Array[] = [];
  const app = {
    config: {
      TOKEN_ENCRYPTION_KEY: "t".repeat(48),
      BLOB_HMAC_SECRET: "b".repeat(48),
      JWT_SECRET: "j".repeat(48),
    },
    services: {
      reliability: {
        store: {
          increment: async () => 1,
          incrementBy: async () => 100,
        },
      },
      blobs: {
        storeBinary: async (input: { value: Uint8Array }) => {
          storedBodies.push(input.value);
          return { blobId: "blob-1", byteLength: input.value.byteLength };
        },
      },
    },
  };
  const carrier = {
    version: 1 as const,
    retention: "request_ephemeral" as const,
    privacy: {
      metadataStripped: true as const,
      userAuthorizedCloud: true as const,
      localSensitivity: "personal" as const,
    },
    images: [{
      imageId: "legacy-1",
      kind: "full_frame" as const,
      mimeType: "image/png" as const,
      base64Data: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
      width: 1,
      height: 1,
    }],
  };

  const result = await materializeLegacyVisionForDurableQueue(
    app as never,
    "00000000-0000-4000-8000-000000000001",
    carrier,
  );

  assert.equal(result?.version, 2);
  assert.equal(result?.inputRefs.length, 1);
  assert.ok(result?.inputRefs[0]?.inputRef.startsWith("v2."));
  assert.equal(storedBodies.length, 1);
  assert.ok(storedBodies[0]!.byteLength > 0);
  assert.equal(carrier.images.length, 0);
});
