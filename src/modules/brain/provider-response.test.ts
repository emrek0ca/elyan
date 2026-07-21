import assert from "node:assert/strict";
import test from "node:test";
import {
  extractResponseDelta,
  extractResponseFinishReason,
  extractResponseReasoning,
  extractResponseText,
  resolveStreamContinuationTokenBudget,
  shouldAttemptStreamContinuation,
  shouldStreamReasoning,
  stripRepeatedContinuationPrefix,
  supportsNativeStreamingAttempt,
} from "./provider-response.js";

test("extractResponseText reads Claude content arrays and chat choices", () => {
  assert.equal(
    extractResponseText("claude", {
      content: [{ type: "text", text: "  Claude answer  " }],
    }),
    "Claude answer",
  );
  assert.equal(
    extractResponseText("groq", {
      choices: [{ message: { content: "  Chat answer  " } }],
    }),
    "Chat answer",
  );
  assert.equal(
    extractResponseText("groq", {
      choices: [
        { message: { content: [{ type: "text", text: "  Array answer  " }] } },
      ],
    }),
    "Array answer",
  );
});

test("extractResponseText reads Ollama response and message content", () => {
  assert.equal(extractResponseText("ollama", { response: "  generate  " }), "generate");
  assert.equal(
    extractResponseText("ollama", { message: { content: "  chat  " } }),
    "chat",
  );
});

test("extractResponseText reads Gemini native candidates", () => {
  assert.equal(
    extractResponseText("gemini", {
      candidates: [
        {
          content: {
            parts: [{ text: "  Merhaba." }],
          },
        },
      ],
    }),
    "Merhaba.",
  );
});

test("extractResponseText never exposes thought or reasoning parts", () => {
  assert.equal(
    extractResponseText("gemini", {
      candidates: [{
        content: {
          parts: [
            { thought: true, text: "private chain of thought" },
            { text: "Visible answer" },
          ],
        },
      }],
    }),
    "Visible answer",
  );
  assert.equal(
    extractResponseText("groq", {
      choices: [{
        message: {
          content: [
            { type: "reasoning", text: "private reasoning" },
            { type: "output_text", text: "Public answer" },
          ],
        },
      }],
    }),
    "Public answer",
  );
});

test("extractResponseDelta supports generate, chat, and OpenAI-compatible chunks", () => {
  assert.equal(extractResponseDelta({ response: "a" }), "a");
  assert.equal(extractResponseDelta({ message: { content: "b" } }), "b");
  assert.equal(
    extractResponseDelta({ choices: [{ delta: { content: "c" } }] }),
    "c",
  );
});

test("extractResponseReasoning supports Ollama and Groq reasoning channels", () => {
  assert.equal(extractResponseReasoning({ message: { reasoning: "think-a" } }), "think-a");
  assert.equal(
    extractResponseReasoning({ choices: [{ delta: { reasoning_content: "think-b" } }] }),
    "think-b",
  );
  assert.equal(
    extractResponseReasoning({ choices: [{ delta: { reasoning: "think-c" } }] }),
    "think-c",
  );
});

test("extractResponseFinishReason normalizes provider finish reason variants", () => {
  assert.equal(extractResponseFinishReason({ finishReason: "MAX_TOKENS" }), "max_tokens");
  assert.equal(
    extractResponseFinishReason({ choices: [{ finish_reason: "Length" }] }),
    "length",
  );
  assert.equal(extractResponseFinishReason({}), null);
});

test("stream continuation only retries unfinished length-limited text", () => {
  assert.equal(
    shouldAttemptStreamContinuation({ finishReason: "length", text: "This continues" }),
    true,
  );
  assert.equal(
    shouldAttemptStreamContinuation({ finishReason: "max_tokens", text: "Done." }),
    false,
  );
  assert.equal(
    shouldAttemptStreamContinuation({ finishReason: "stop", text: "This continues" }),
    false,
  );
});

test("resolveStreamContinuationTokenBudget preserves minimum and remaining caps", () => {
  assert.equal(
    resolveStreamContinuationTokenBudget({ maxTokens: 1000, usedContinuationTokens: 0 }),
    500,
  );
  assert.equal(
    resolveStreamContinuationTokenBudget({ maxTokens: 500, usedContinuationTokens: 250 }),
    250,
  );
  assert.equal(
    resolveStreamContinuationTokenBudget({ maxTokens: 500, usedContinuationTokens: 350 }),
    0,
  );
});

test("stripRepeatedContinuationPrefix removes overlapping continuation text", () => {
  assert.equal(
    stripRepeatedContinuationPrefix(
      "The final section starts with a shared prefix",
      "shared prefix and then continues",
    ),
    " and then continues",
  );
  assert.equal(stripRepeatedContinuationPrefix("short", "different"), "different");
});

test("streaming support and reasoning visibility stay workload/provider aware", () => {
  assert.equal(supportsNativeStreamingAttempt("claude", "/messages"), false);
  assert.equal(supportsNativeStreamingAttempt("ollama", "/api/generate"), true);
  assert.equal(supportsNativeStreamingAttempt("ollama", "/chat/completions"), false);
  assert.equal(supportsNativeStreamingAttempt("groq", "/chat/completions"), true);
  assert.equal(supportsNativeStreamingAttempt("gemini", "/chat/completions"), false);
  assert.equal(shouldStreamReasoning("planning"), true);
  assert.equal(shouldStreamReasoning("mobile_chat_fast"), false);
});
