import assert from "node:assert/strict";
import test from "node:test";
import {
  buildNormalizedComposerContext,
  normalizeComposerContext,
  parseComposerContext,
} from "./composer-context.js";

test("composer normalization keeps only server-shaped quote fields", () => {
  const normalized = buildNormalizedComposerContext({
    quote: {
      messageId: "message-1",
      sessionId: "session-1",
      role: "assistant",
      taskId: null,
      text: "private full message text",
      preview: "private preview",
    },
  });

  assert.deepEqual(normalized, {
    quote: {
      messageId: "message-1",
      role: "assistant",
      text: "private preview",
    },
  });
});

test("composer normalization does not retain raw media refs in chat metadata", async () => {
  const result = await normalizeComposerContext({
    app: { db: {} } as never,
    userId: "user-1",
    sessionId: "session-1",
    metadata: {
      mediaInputRefs: [{ inputRef: "secret-ref" }],
      mediaInputPrivacy: { localSensitivity: "personal" },
      composerContext: {},
    },
  });

  assert.equal(result.metadata.mediaInputRefs, undefined);
  assert.equal(result.metadata.mediaInputPrivacy, undefined);
  assert.ok(result.droppedFields.includes("metadata.mediaInputRefs"));
});

test("composer parser accepts only canonical quick-action IDs", () => {
  const parsed = parseComposerContext({
    composerContext: {
      quickAction: {
        id: "not-a-canonical-action",
        source: "semantic",
        context: { sessionId: "session-1" },
      },
    },
  });

  assert.deepEqual(parsed.context, {});
  assert.deepEqual(parsed.invalidFields, ["quickAction"]);
});
