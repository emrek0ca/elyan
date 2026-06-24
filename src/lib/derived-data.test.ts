import assert from "node:assert/strict";
import test from "node:test";
import { hasRawBinaryUploadHint, normalizeLocalDerivedMetadata } from "./derived-data.js";

test("hasRawBinaryUploadHint detects raw upload hints and respects explicit local flags", () => {
  assert.equal(
    hasRawBinaryUploadHint({
      attachment: {
        storageKey: "elyan://raw/example.pdf",
      },
    }),
    true,
  );

  assert.equal(
    hasRawBinaryUploadHint({
      attachment: {
        raw_file_uploaded: true,
      },
    }),
    true,
  );

  assert.equal(
    hasRawBinaryUploadHint({
      attachment: {
        raw_file_uploaded: false,
        data_origin: "local_derived",
      },
    }),
    false,
  );
});

test("normalizeLocalDerivedMetadata keeps derived data flags stable", () => {
  const normalized = normalizeLocalDerivedMetadata({
    source_device_id: "device-1",
    content_hash: "hash-1",
  });

  assert.equal(normalized.source_device_id, "device-1");
  assert.equal(normalized.content_hash, "hash-1");
  assert.equal(normalized.raw_file_uploaded, false);
  assert.equal(normalized.data_origin, "local_derived");
  assert.equal(normalized.privacy_level, "local_derived");
});

test("normalizeLocalDerivedMetadata strips raw and heavy derived fields recursively", () => {
  const normalized = normalizeLocalDerivedMetadata({
    source_device_id: "device-1",
    fastPreview: {
      summary: "ready",
      ocrLines: [{ text: "secret dump" }],
      blocks: [
        {
          pageNumber: 1,
          bbox: { x: 1, y: 2 },
          content: "kept",
        },
      ],
    },
    deepContext: {
      content: "kept too",
      previewImage: "base64-preview",
      nested: {
        localPath: "/tmp/file.pdf",
        renderHints: {
          format: "pdf",
        },
      },
    },
    imageBase64: "raw-image",
    raw_file_uploaded: true,
  });

  assert.equal(normalized.source_device_id, "device-1");
  assert.equal(normalized.raw_file_uploaded, false);
  assert.equal(normalized.data_origin, "local_derived");
  assert.equal(normalized.privacy_level, "local_derived");
  assert.deepEqual(normalized.fastPreview, {
    summary: "ready",
    blocks: [{ pageNumber: 1, content: "kept" }],
  });
  assert.deepEqual(normalized.deepContext, {
    content: "kept too",
    nested: {
      renderHints: {
        format: "pdf",
      },
    },
  });
  assert.equal("imageBase64" in normalized, false);
});
