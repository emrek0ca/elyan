import assert from "node:assert/strict";
import test from "node:test";
import {
  getSharedBrainWorkloadProfile,
  resolveAttachmentAwareSharedBrainWorkload,
} from "./workloads.js";

test("getSharedBrainWorkloadProfile exposes the document analysis profile", () => {
  const profile = getSharedBrainWorkloadProfile("document_analysis");

  assert.deepEqual(profile, {
    workload: "document_analysis",
    timeoutMs: 8_500,
    firstDeltaBudgetMs: 2_200,
    maxTokens: 640,
    streamingEnabled: true,
    cachePolicy: "off",
    fallbackWorkload: "mobile_chat_balanced",
  });
});

test("resolveAttachmentAwareSharedBrainWorkload upgrades server-brain document chats", () => {
  assert.equal(
    resolveAttachmentAwareSharedBrainWorkload({
      route: "server_brain",
      selectedWorkload: "mobile_chat_fast",
      attachmentContextUsed: true,
    }),
    "document_analysis",
  );
  assert.equal(
    resolveAttachmentAwareSharedBrainWorkload({
      route: "server_brain",
      selectedWorkload: "mobile_chat_balanced",
      attachmentContextUsed: true,
    }),
    "document_analysis",
  );
});

test("resolveAttachmentAwareSharedBrainWorkload keeps planning, non-server, and no-context routes unchanged", () => {
  assert.equal(
    resolveAttachmentAwareSharedBrainWorkload({
      route: "server_brain",
      selectedWorkload: "planning",
      attachmentContextUsed: true,
    }),
    "planning",
  );
  assert.equal(
    resolveAttachmentAwareSharedBrainWorkload({
      route: "desktop_runtime",
      selectedWorkload: "mobile_chat_balanced",
      attachmentContextUsed: true,
    }),
    "mobile_chat_balanced",
  );
  assert.equal(
    resolveAttachmentAwareSharedBrainWorkload({
      route: "server_brain",
      selectedWorkload: "mobile_chat_fast",
      attachmentContextUsed: false,
    }),
    "mobile_chat_fast",
  );
});
