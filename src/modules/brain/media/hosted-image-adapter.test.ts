import assert from "node:assert/strict";
import test from "node:test";
import {
  buildHostedImageProviderRequest,
  extractHostedGeneratedImage,
} from "./hosted-image-adapter.js";

test("Gemini image adapter builds a minimal Interactions text-to-image request", () => {
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
  });

  assert.equal(request.path, "/interactions");
  assert.equal(request.headers["x-goog-api-key"], "secret-test-key");
  assert.deepEqual(request.body.input, [
    {
      type: "text",
      text: "Warm editorial illustration\n\nRequested aspect ratio: 3:2.",
    },
  ]);
  assert.equal("response_format" in request.body, false);
  assert.equal("store" in request.body, false);
  assert.equal("system_instruction" in request.body, false);
  assert.doesNotMatch(JSON.stringify(request.body), /secret-test-key/u);
});

test("Gemini image adapter sends exact prompt and source image for editing", () => {
  const request = buildHostedImageProviderRequest({
    config: {
      provider: "gemini",
      apiKey: "secret-test-key",
      baseUrl: "https://generativelanguage.googleapis.com/v1beta",
      model: "gemini-3-pro-image-preview",
      source: "test",
      imageSize: "2K",
    },
    prompt: "Arka planı gün batımı yap, kişiyi değiştirme",
    sourceImages: [{ base64Data: "YWJjZA==", mimeType: "image/png" }],
  });

  assert.deepEqual(request.body.input, [
    {
      type: "text",
      text: "Arka planı gün batımı yap, kişiyi değiştirme\n\nRequested image size: 2K.",
    },
    { type: "image", data: "YWJjZA==", mime_type: "image/png" },
  ]);
  assert.equal("response_format" in request.body, false);
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
