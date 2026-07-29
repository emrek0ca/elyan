import assert from "node:assert/strict";
import test from "node:test";
import { AppError } from "../../lib/errors.js";
import {
  groqSdkBaseUrl,
  transcribeSpeechWithGroq,
} from "./groq-speech-adapter.js";

test("Groq speech adapter sends bounded Turkish audio to the configured model", async () => {
  let request: Record<string, unknown> | undefined;
  const client = {
    audio: {
      transcriptions: {
        async create(input: Record<string, unknown>) {
          request = input;
          return { text: "  Yarin   raporu hazirla.  " };
        },
      },
    },
  };

  const result = await transcribeSpeechWithGroq(
    {
      GROQ_API_KEY: "",
      GROQ_BASE_URL: "https://api.groq.com/openai/v1",
      GROQ_TRANSCRIBE_MODEL: "whisper-large-v3-turbo",
    },
    {
      audio: Buffer.alloc(256, 1),
      contentType: "audio/mp4",
      language: "tr",
    },
    client as never,
  );

  assert.equal(request?.model, "whisper-large-v3-turbo");
  assert.equal(request?.language, "tr");
  assert.equal(request?.temperature, 0);
  assert.equal(result.text, "Yarin raporu hazirla.");
  assert.equal(result.language, "tr");
});

test("Groq speech adapter fails safely when provider configuration is missing", async () => {
  await assert.rejects(
    transcribeSpeechWithGroq(
      {
        GROQ_API_KEY: "",
        GROQ_BASE_URL: "https://api.groq.com/openai/v1",
      },
      { audio: Buffer.alloc(256), contentType: "audio/mp4" },
    ),
    (error: unknown) =>
      error instanceof AppError && error.code === "speech_provider_unavailable",
  );
});

test("Groq speech adapter maps empty speech without exposing content", async () => {
  const client = {
    audio: {
      transcriptions: {
        async create() {
          return { text: "   " };
        },
      },
    },
  };
  await assert.rejects(
    transcribeSpeechWithGroq(
      {
        GROQ_API_KEY: "",
        GROQ_BASE_URL: "https://api.groq.com/openai/v1",
      },
      { audio: Buffer.alloc(256), contentType: "audio/mp4" },
      client as never,
    ),
    (error: unknown) =>
      error instanceof AppError && error.code === "speech_not_detected",
  );
});

test("Groq speech adapter stops before provider upload when already aborted", async () => {
  let createCalled = false;
  const client = {
    audio: {
      transcriptions: {
        async create() {
          createCalled = true;
          return { text: "should not run" };
        },
      },
    },
  };
  const controller = new AbortController();
  controller.abort();

  await assert.rejects(
    transcribeSpeechWithGroq(
      {
        GROQ_API_KEY: "",
        GROQ_BASE_URL: "https://api.groq.com/openai/v1",
      },
      {
        audio: Buffer.alloc(256),
        contentType: "audio/mp4",
        signal: controller.signal,
      },
      client as never,
    ),
    (error: unknown) =>
      error instanceof AppError && error.code === "speech_transcription_failed",
  );
  assert.equal(createCalled, false);
});

test("Groq speech adapter maps provider timeout failures safely", async () => {
  const client = {
    audio: {
      transcriptions: {
        async create() {
          throw new Error("provider timeout with private transcript");
        },
      },
    },
  };
  await assert.rejects(
    transcribeSpeechWithGroq(
      {
        GROQ_API_KEY: "",
        GROQ_BASE_URL: "https://api.groq.com/openai/v1",
      },
      { audio: Buffer.alloc(256), contentType: "audio/mp4" },
      client as never,
    ),
    (error: unknown) =>
      error instanceof AppError &&
      error.code === "speech_transcription_failed" &&
      !error.message.includes("private transcript"),
  );
});

test("Groq SDK base URL does not duplicate the OpenAI-compatible prefix", () => {
  assert.equal(
    groqSdkBaseUrl("https://api.groq.com/openai/v1"),
    "https://api.groq.com",
  );
  assert.equal(groqSdkBaseUrl("https://groq-proxy.example/"), "https://groq-proxy.example");
});
