import assert from "node:assert/strict";
import test from "node:test";
import {
  buildHostedImageProviderRequest,
  extractHostedGeneratedImage,
} from "./hosted-image-adapter.js";

test("Gemini image adapter defaults to the cost-safe 1K Interactions request", () => {
  const request = buildHostedImageProviderRequest({
    config: {
      provider: "gemini",
      apiKey: "secret-test-key",
      baseUrl: "https://generativelanguage.googleapis.com/v1beta",
      model: "gemini-3.1-flash-image",
      source: "test",
    },
    prompt: "Warm editorial illustration",
    aspectRatio: "3:2",
    openAiSize: "1536x1024",
  });

  assert.equal(request.path, "/interactions");
  assert.equal(request.headers["x-goog-api-key"], "secret-test-key");
  assert.deepEqual(request.body.response_format, {
    type: "image",
    mime_type: "image/jpeg",
    aspect_ratio: "3:2",
    image_size: "1K",
  });
  assert.doesNotMatch(JSON.stringify(request.body), /secret-test-key/u);
});

test("hosted image adapter normalizes Gemini inline image output", () => {
  const result = extractHostedGeneratedImage({
    outputs: [
      {
        inline_data: {
          mime_type: "image/jpeg",
          data: "YWJjZA==",
        },
        text: "Refined prompt",
      },
    ],
  });

  assert.deepEqual(result, {
    base64: "YWJjZA==",
    mimeType: "image/jpeg",
    revisedPrompt: "Refined prompt",
  });
});
