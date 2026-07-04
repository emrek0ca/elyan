import assert from "node:assert/strict";
import test from "node:test";
import {
  applyCanonicalDialogueStateToMetadata,
  buildDialogueStateFallbackFromMetadata,
  dialogueStateSchema,
  deriveConversationDynamics,
  mergeDialogueState,
  recordDialogueStateTurn,
  resolveDialogueStateSessionId,
} from "./dialogue-state.js";

test("conversation dynamics tracks reply cadence and bounded phrase signatures", () => {
  const first = deriveConversationDynamics(
    dialogueStateSchema.parse({}).conversationDynamics,
    "Tamam, bunu birlikte çözelim. Sonucu birazdan kontrol edeceğim.",
  );
  const second = deriveConversationDynamics(first, "İşlem tamamlandı. Sonuç doğru görünüyor.");
  assert.equal(second.turnCount, 2);
  assert.equal(second.averageReplyChars > 0, true);
  assert.equal(second.recentOpeners[0], "İşlem tamamlandı.");
  assert.equal(second.recentClosers.length, 2);
});

test("canonical dialogue state overrides client rolling summary but preserves hints", () => {
  const metadata = applyCanonicalDialogueStateToMetadata({
    metadata: {
      compactContext: {
        rollingSummary: { userGoal: "client goal", contextNotes: ["keep"] },
        wantsLongForm: true,
      },
    },
    snapshot: {
      sessionId: "11111111-1111-4111-8111-111111111111",
      userId: "22222222-2222-4222-8222-222222222222",
      revision: 4,
      state: dialogueStateSchema.parse({
        goal: "server goal",
        stage: "executing",
        openLoops: ["verify"],
        lastAssistantDigest: "server digest",
        userMemory: {
          preferredName: "Emre",
          preferredLanguage: "Türkçe",
        },
      }),
    },
  });
  const compact = metadata.compactContext as Record<string, unknown>;
  const rolling = compact.rollingSummary as Record<string, unknown>;
  assert.equal(rolling.userGoal, "server goal");
  assert.deepEqual(rolling.contextNotes, ["keep"]);
  assert.equal(compact.wantsLongForm, true);
  assert.deepEqual(compact.userMemory, {
    name: null,
    preferredName: "Emre",
    preferredLanguage: "Türkçe",
    preferredTone: null,
    responseStyle: null,
    timezone: null,
    updatedAt: null,
  });
  assert.equal(metadata.dialogueStateRevision, 4);
});

test("resolveDialogueStateSessionId reads direct and nested chat session ids", () => {
  assert.equal(
    resolveDialogueStateSessionId({
      sessionId: "11111111-1111-4111-8111-111111111111",
    }),
    "11111111-1111-4111-8111-111111111111",
  );
  assert.equal(
    resolveDialogueStateSessionId({
      chat: { sessionId: "22222222-2222-4222-8222-222222222222" },
    }),
    "22222222-2222-4222-8222-222222222222",
  );
  assert.equal(resolveDialogueStateSessionId({ chat: { sessionId: "bad" } }), null);
});

test("buildDialogueStateFallbackFromMetadata preserves sanitized compact context", () => {
  const state = buildDialogueStateFallbackFromMetadata({
    dialogueStateSource: "server_dialogue_state.v1",
    dialogueStateUserId: "user-1",
    dialogueStateSessionId: "11111111-1111-4111-8111-111111111111",
    compactContext: {
      source: "server_dialogue_state.v1",
      ownerUserId: "user-1",
      ownerSessionId: "11111111-1111-4111-8111-111111111111",
      rollingSummary: {
        userGoal: "F2'yi bitir",
        assistantState: "turn envelope eklendi",
        openLoops: ["benchmark tekrar kosulacak"],
      },
      lastAssistantBlocksDigest: "summary + text",
      userMemory: {
        preferredName: "Emre",
        preferredLanguage: "tr",
      },
    },
  }, {
    userId: "user-1",
    sessionId: "11111111-1111-4111-8111-111111111111",
  });

  assert.equal(state.goal, "F2'yi bitir");
  assert.equal(state.stage, "turn envelope eklendi");
  assert.deepEqual(state.openLoops, ["benchmark tekrar kosulacak"]);
  assert.equal(state.lastAssistantDigest, "summary + text");
  assert.equal(state.userMemory.preferredName, "Emre");
  assert.equal(state.userMemory.preferredLanguage, "tr");
});

test("buildDialogueStateFallbackFromMetadata ignores untrusted client cached user memory", () => {
  const state = buildDialogueStateFallbackFromMetadata({
    compactContext: {
      rollingSummary: {
        userGoal: "Other account private goal",
        assistantState: "other account state",
        openLoops: ["other account loop"],
      },
      lastAssistantBlocksDigest: "other account digest",
      userMemory: {
        preferredName: "Emre",
        preferredLanguage: "tr",
      },
    },
  }, {
    userId: "different-user",
    sessionId: "22222222-2222-4222-8222-222222222222",
  });

  assert.equal(state.goal, null);
  assert.equal(state.stage, null);
  assert.deepEqual(state.openLoops, []);
  assert.equal(state.lastAssistantDigest, null);
  assert.equal(state.userMemory.preferredName, null);
  assert.equal(state.userMemory.preferredLanguage, null);
});

test("buildDialogueStateFallbackFromMetadata ignores server metadata owned by another user", () => {
  const state = buildDialogueStateFallbackFromMetadata({
    dialogueStateSource: "server_dialogue_state.v1",
    dialogueStateUserId: "user-a",
    dialogueStateSessionId: "11111111-1111-4111-8111-111111111111",
    compactContext: {
      source: "server_dialogue_state.v1",
      ownerUserId: "user-a",
      ownerSessionId: "11111111-1111-4111-8111-111111111111",
      rollingSummary: {
        userGoal: "User A goal",
      },
      userMemory: {
        preferredName: "Emre",
      },
    },
  }, {
    userId: "user-b",
    sessionId: "11111111-1111-4111-8111-111111111111",
  });

  assert.equal(state.goal, null);
  assert.equal(state.userMemory.preferredName, null);
});

test("mergeDialogueState folds TurnEnvelope ops into canonical typed state", () => {
  const state = mergeDialogueState({
    previous: {
      goal: "Elyan backend",
      stage: "F2",
      openLoops: ["eski takip"],
      factsTouched: ["preferred_language"],
      toolHistory: [],
      moodTrend: [],
    },
    userMessage: "Yarın deployu hatırlat",
    assistantText: "Tamam, yarın sabah hatırlatacağım.",
    assistantBlocks: [{ type: "text", markdown: "Tamam" }],
    workload: "mobile_chat_fast",
    now: new Date("2026-07-03T12:00:00.000Z"),
    envelope: {
      reply: { text: "Tamam, yarın sabah hatırlatacağım.", lang: "tr", tone: "warm" },
      blocks: [],
      memory_ops: [
        {
          op: "write",
          kind: "preference",
          key: "reminder_preference",
          value: "morning",
          confidence: 0.8,
        },
      ],
      goal_ops: [{ op: "advance", step: "reminder_captured" }],
      follow_ups: [
        {
          due: "tomorrow",
          topic: "deploy",
          nudge: "Deploy nasil gitti?",
        },
      ],
      tool_requests: [{ tool: "schedule.create", args: { due: "tomorrow" } }],
      affect: {
        user_mood_guess: "focused",
        energy: "mid",
        register: "technical",
      },
    },
    toolResults: [
      {
        tool: "schedule.create",
        ok: false,
        permission: "side_effect",
        durationMs: 8,
        output: null,
        error: {
          code: "tool_side_effect_requires_approval",
          message: "Approval required.",
        },
      },
    ],
  });

  assert.equal(state.goal, "Elyan backend");
  assert.equal(state.stage, "reminder_captured");
  assert.equal(state.openLoops[0], "tomorrow: deploy — Deploy nasil gitti?");
  assert.equal(state.openLoops.includes("eski takip"), true);
  assert.deepEqual(state.factsTouched.slice(0, 2), [
    "reminder_preference",
    "preferred_language",
  ]);
  assert.equal(state.toolHistory[0]?.tool, "schedule.create");
  assert.equal(state.toolHistory[0]?.status, "failed");
  assert.equal(state.toolHistory[0]?.durationMs, 8);
  assert.equal(state.toolHistory[0]?.errorCode, "tool_side_effect_requires_approval");
  assert.equal(state.toolHistory[1]?.status, "requested");
  assert.equal(state.moodTrend[0]?.mood, "focused");
  assert.equal(state.userRegister, "technical");
  assert.equal(state.lastAssistantDigest, "Tamam, yarın sabah hatırlatacağım.");
});

test("mergeDialogueState keeps canonical single-value user memory current", () => {
  const state = mergeDialogueState({
    previous: {
      userMemory: {
        preferredName: "Zeynep",
        preferredLanguage: "tr",
        updatedAt: "2026-07-03T12:00:00.000Z",
      },
      factsTouched: ["preferred_name"],
    },
    userMessage: "Bundan sonra bana Emre de",
    assistantText: "Tamam Emre.",
    now: new Date("2026-07-04T10:00:00.000Z"),
    envelope: {
      reply: { text: "Tamam Emre.", lang: "tr", tone: "warm" },
      blocks: [],
      memory_ops: [
        {
          op: "write",
          kind: "preference",
          key: "hitap şekli",
          value: "Emre",
          confidence: 0.96,
        },
        {
          op: "write",
          kind: "fact",
          key: "timezone",
          value: "Europe/Istanbul",
          confidence: 0.9,
        },
      ],
      goal_ops: [],
      follow_ups: [],
      tool_requests: [],
      affect: { user_mood_guess: "focused", energy: "mid", register: "warm" },
    },
  });

  assert.equal(state.userMemory.preferredName, "Emre");
  assert.equal(state.userMemory.preferredLanguage, "tr");
  assert.equal(state.userMemory.timezone, "Europe/Istanbul");
  assert.equal(state.userMemory.updatedAt, "2026-07-04T10:00:00.000Z");
  assert.equal(state.factsTouched[0], "hitap şekli");
});

test("mergeDialogueState forgets single-value user memory without erasing other profile fields", () => {
  const state = mergeDialogueState({
    previous: {
      userMemory: {
        preferredName: "Emre",
        preferredLanguage: "tr",
        timezone: "Europe/Istanbul",
        updatedAt: "2026-07-03T12:00:00.000Z",
      },
    },
    userMessage: "Bana nasıl hitap edeceğini unut",
    assistantText: "Tamam.",
    now: new Date("2026-07-04T11:00:00.000Z"),
    envelope: {
      reply: { text: "Tamam.", lang: "tr", tone: "neutral" },
      blocks: [],
      memory_ops: [
        {
          op: "forget",
          kind: "preference",
          key: "preferred_name",
          value: "",
          confidence: 0.99,
        },
      ],
      goal_ops: [],
      follow_ups: [],
      tool_requests: [],
      affect: { user_mood_guess: "neutral", energy: "mid", register: "neutral" },
    },
  });

  assert.equal(state.userMemory.preferredName, null);
  assert.equal(state.userMemory.preferredLanguage, "tr");
  assert.equal(state.userMemory.timezone, "Europe/Istanbul");
  assert.equal(state.userMemory.updatedAt, "2026-07-04T11:00:00.000Z");
});

test("recordDialogueStateTurn inserts then optimistically updates dialogue state", async () => {
  let row: Record<string, unknown> | null = null;
  const app = {
    db: {
      select() {
        return {
          from() {
            return this;
          },
          where() {
            return this;
          },
          limit() {
            return Promise.resolve(row ? [row] : []);
          },
        };
      },
      insert() {
        return {
          values(value: Record<string, unknown>) {
            row = {
              sessionId: value.sessionId,
              userId: value.userId,
              revision: value.revision,
              state: value.state,
            };
            return Promise.resolve();
          },
        };
      },
      update() {
        return {
          set(value: Record<string, unknown>) {
            return {
              where() {
                row = row
                  ? {
                      ...row,
                      revision: value.revision,
                      state: value.state,
                    }
                  : row;
                return {
                  returning() {
                    return Promise.resolve(row ? [{ revision: row.revision }] : []);
                  },
                };
              },
            };
          },
        };
      },
    },
  };

  const first = await recordDialogueStateTurn(app as never, {
    userId: "33333333-3333-4333-8333-333333333333",
    sessionId: "44444444-4444-4444-8444-444444444444",
    userMessage: "F3'e devam et",
    assistantText: "Dialogue state basladi.",
    workload: "planning",
  });
  assert.equal(first?.revision, 1);
  assert.equal(first?.state.stage, "planning");

  const second = await recordDialogueStateTurn(app as never, {
    userId: "33333333-3333-4333-8333-333333333333",
    sessionId: "44444444-4444-4444-8444-444444444444",
    userMessage: "Yarin kontrol et",
    assistantText: "Takip eklendi.",
    envelope: {
      reply: { text: "Takip eklendi.", lang: "tr", tone: "warm" },
      blocks: [],
      memory_ops: [],
      goal_ops: [{ op: "block", next: "kontrol" }],
      follow_ups: [],
      tool_requests: [],
      affect: { user_mood_guess: "focused", energy: "mid", register: "technical" },
    },
  });
  assert.equal(second?.revision, 2);
  assert.equal(second?.state.stage, "blocked");
  assert.equal(second?.state.openLoops[0], "kontrol");
});
