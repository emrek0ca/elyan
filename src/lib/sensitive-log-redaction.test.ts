import assert from "node:assert/strict";
import test from "node:test";
import { VISION_LOG_REDACTION_PATHS } from "./sensitive-log-redaction.js";

test("vision request payloads are covered by central logger redaction", () => {
  assert.ok(VISION_LOG_REDACTION_PATHS.includes("req.body.ephemeralVision"));
  assert.ok(VISION_LOG_REDACTION_PATHS.some((path) => path.includes("base64Thumbnail")));
  assert.ok(VISION_LOG_REDACTION_PATHS.some((path) => path.endsWith("visionImages[*].base64")));
  assert.doesNotMatch(JSON.stringify(VISION_LOG_REDACTION_PATHS), /contentHash|imageId/iu);
});
