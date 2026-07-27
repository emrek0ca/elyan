import assert from "node:assert/strict";
import test from "node:test";
import {
  buildLearningProvenance,
  resolveInteractionContext,
} from "./interaction-context.js";

test("interaction context unifies channel data under the authenticated canonical profile", () => {
  const context = resolveInteractionContext({
    source: "mobile",
    metadata: {
      channelContext: {
        channel: "whatsapp",
        identityRef: "wa_user_ref_42",
        conversationId: "thread_7",
        messageId: "message_9",
      },
    },
  });

  assert.equal(context.schemaVersion, "interaction_context.v1");
  assert.equal(context.channel, "whatsapp");
  assert.equal(context.profileScope, "canonical_user");
  assert.match(context.identityRef ?? "", /^ref_[a-f0-9]{24}$/);
  assert.match(context.conversationRef ?? "", /^ref_[a-f0-9]{24}$/);
  assert.match(context.messageRef ?? "", /^ref_[a-f0-9]{24}$/);
  assert.notEqual(context.identityRef, "wa_user_ref_42");
});

test("interaction context rejects raw or malformed identity metadata", () => {
  const context = resolveInteractionContext({
    source: "email",
    metadata: {
      channelContext: {
        identityRef: "person@example.com",
        conversationRef: "../../private",
      },
    },
  });

  assert.equal(context.channel, "email");
  assert.equal(context.identityRef, null);
  assert.equal(context.conversationRef, null);
});

test("learning provenance is compact, versioned, and channel attributed", () => {
  const provenance = buildLearningProvenance({
    interaction: resolveInteractionContext({
      source: "desktop",
      metadata: {},
    }),
    evidenceBasis: "explicit_user",
    observedAt: new Date("2026-07-27T10:00:00.000Z"),
  });

  assert.deepEqual(provenance, {
    schemaVersion: "learning_provenance.v2",
    profileScope: "canonical_user",
    channel: "desktop",
    evidenceBasis: "explicit_user",
    observedAt: "2026-07-27T10:00:00.000Z",
  });
});
