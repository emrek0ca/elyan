import assert from "node:assert/strict";
import test from "node:test";

import {
  buildGroundedSocialReply,
  forgetUser,
  isRepeatReply,
  rememberReply,
  resetRecentReplies,
  selectLivenessCue,
} from "./grounded-social-reply.js";

test("does not repeat the same opener back to back", () => {
  resetRecentReplies();
  const first = buildGroundedSocialReply({
    kind: "greeting",
    userId: "user-1",
    name: "Emre",
  });
  const second = buildGroundedSocialReply({
    kind: "greeting",
    userId: "user-1",
    name: "Emre",
  });
  assert.notEqual(second, first);
});

test("prefers a verifiable cue over warmth vocabulary", () => {
  resetRecentReplies();
  const reply = buildGroundedSocialReply({
    kind: "greeting",
    userId: "user-1",
    name: "Emre",
    signals: {
      activeTaskLabel: "belge yazımı",
      activeTaskProgress: { completed: 2, total: 4 },
    },
  });
  assert.ok(reply.includes("belge yazımı"));
  assert.ok(reply.includes("2/4"));
});

test("stays plain when nothing real is known (no fabricated familiarity)", () => {
  resetRecentReplies();
  const reply = buildGroundedSocialReply({
    kind: "greeting",
    userId: "user-1",
    name: null,
  });
  assert.equal(reply, "Merhaba.");
});

test("never attaches a cue to gratitude", () => {
  resetRecentReplies();
  const reply = buildGroundedSocialReply({
    kind: "thanks",
    userId: "user-1",
    name: "Emre",
    signals: { recentOutputName: "rapor.docx", recentOutputMinutesAgo: 2 },
  });
  assert.ok(!reply.includes("rapor.docx"));
});

test("emits at most one cue", () => {
  const cue = selectLivenessCue(undefined, {
    activeTaskLabel: "araştırma",
    recentOutputName: "rapor.docx",
    recentOutputMinutesAgo: 5,
    upcomingEventTitle: "Toplantı",
    upcomingEventMinutes: 10,
  });
  assert.ok(cue?.includes("araştırma"));
  assert.ok(!cue?.includes("rapor.docx"));
  assert.ok(!cue?.includes("Toplantı"));
});

test("adapts posture to a confident mood signal", () => {
  resetRecentReplies();
  const reply = buildGroundedSocialReply({
    kind: "greeting",
    userId: "user-1",
    name: "Emre",
    context: {
      currentAffect: {
        mood: "frustrated",
        energy: "mid",
        confidence: 0.9,
        source: "typed_fallback",
        responseDirective: "",
      },
    } as never,
  });
  assert.ok(reply.includes("Nerede takıldık?"));
});

test("ignores a low-confidence mood instead of guessing", () => {
  resetRecentReplies();
  const reply = buildGroundedSocialReply({
    kind: "greeting",
    userId: "user-1",
    name: "Emre",
    context: {
      currentAffect: {
        mood: "frustrated",
        energy: "mid",
        confidence: 0.2,
        source: "typed_fallback",
        responseDirective: "",
      },
    } as never,
  });
  assert.ok(!reply.includes("Nerede takıldık?"));
});

// KULLANICILAR ARASI SIZINTI YOK ------------------------------------------

test("keeps one user's openers out of another user's memory", () => {
  resetRecentReplies();
  rememberReply("user-a", "Merhaba Ayşe.");
  assert.equal(isRepeatReply("user-b", "Merhaba Ayşe."), false);
});

test("opens no shared bucket for unidentified callers", () => {
  resetRecentReplies();
  rememberReply("anonymous", "Merhaba Ayşe.");
  rememberReply("", "Merhaba Ayşe.");
  assert.equal(isRepeatReply("anonymous", "Merhaba Ayşe."), false);
  assert.equal(isRepeatReply("", "Merhaba Ayşe."), false);
});

test("matches by opaque digest, so the sentence itself is never stored", () => {
  resetRecentReplies();
  rememberReply("user-a", "Merhaba Ayşe.");
  assert.equal(isRepeatReply("user-a", "Merhaba Ayşe."), true);
  assert.equal(isRepeatReply("user-a", "Merhaba Ali."), false);
});

test("forgets a user on request", () => {
  resetRecentReplies();
  rememberReply("user-a", "Merhaba.");
  forgetUser("user-a");
  assert.equal(isRepeatReply("user-a", "Merhaba."), false);
});
