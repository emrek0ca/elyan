import assert from "node:assert/strict";
import test from "node:test";
import { chatMessages, chatSessions, proactiveTriggers, userProactivePrefs } from "../../db/schema.js";
import {
  applyTurnProactiveOps,
  buildProactiveOpeningCompose,
  evaluateProactivePolicy,
  claimNextDueProactiveTrigger,
  publishProactiveAssistantMessage,
  recordTurnFollowUps,
  resolveFollowUpDue,
} from "./proactive-engine.js";

test("typed proactive ops persist user mute and quiet-hour preferences", async () => {
  const writes: Array<{ table: unknown; values: Record<string, unknown> }> = [];
  const app = {
    db: {
      select() {
        return { from() { return this; }, where() { return this; }, limit() { return Promise.resolve([]); } };
      },
      insert(table: unknown) {
        return {
          values(values: Record<string, unknown>) {
            writes.push({ table, values });
            return { onConflictDoUpdate() { return Promise.resolve(); } };
          },
        };
      },
    },
  };
  const count = await applyTurnProactiveOps(app as never, {
    userId: "11111111-1111-4111-8111-111111111111",
    envelope: {
      ...envelope([]),
      proactive_ops: [
        { op: "mute", kind: "follow_up" },
        { op: "set_quiet_hours", quiet_start_hour: 21, quiet_end_hour: 9, timezone: "Europe/Istanbul" },
      ],
    },
  });
  assert.equal(count, 2);
  assert.equal(writes[0]?.table, userProactivePrefs);
  assert.deepEqual(writes[0]?.values.mutedKinds, ["follow_up"]);
  assert.equal(writes[0]?.values.quietStartHour, 21);
});

test("proactive policy enforces mute, daily cap and overnight quiet hours", () => {
  assert.deepEqual(evaluateProactivePolicy({
    policy: { mutedKinds: ["follow_up"] }, kind: "follow_up", firedToday: 0,
    now: new Date("2026-07-04T09:00:00Z"),
  }), { allowed: false, reason: "muted_kind" });
  assert.deepEqual(evaluateProactivePolicy({
    policy: { maxDaily: 3 }, kind: "reminder", firedToday: 3,
    now: new Date("2026-07-04T09:00:00Z"),
  }), { allowed: false, reason: "daily_limit" });
  assert.deepEqual(evaluateProactivePolicy({
    policy: { timezone: "UTC", quietStartHour: 22, quietEndHour: 8 },
    kind: "reminder", firedToday: 0, now: new Date("2026-07-04T23:00:00Z"),
  }), { allowed: false, reason: "quiet_hours" });
});
import type { TurnEnvelope } from "./turn-envelope.js";

function envelope(followUps: TurnEnvelope["follow_ups"]): TurnEnvelope {
  return {
    reply: { text: "", lang: "tr", tone: "neutral" },
    blocks: [],
    memory_ops: [],
    goal_ops: [],
    follow_ups: followUps,
    tool_requests: [],
    affect: { user_mood_guess: "unknown", energy: "mid", register: "neutral" },
  };
}

function createFakeApp() {
  const inserted: Array<{ table: unknown; values: Record<string, unknown> }> = [];
  const app = {
    db: {
      insert(table: unknown) {
        return {
          values(values: Record<string, unknown>) {
            inserted.push({ table, values });
            return Promise.resolve([]);
          },
        };
      },
    },
  };
  return { app: app as never, inserted };
}

function createFakePublishApp(input: { sessions?: Array<Record<string, unknown>> }) {
  const inserted: Array<{ table: unknown; values: Record<string, unknown> }> = [];
  const updates: Array<{ table: unknown; values: Record<string, unknown> }> = [];
  const events: Array<Record<string, unknown>> = [];
  const app = {
    db: {
      select() {
        return {
          from(table: unknown) {
            return {
              where() {
                return this;
              },
              limit() {
                if (table === chatSessions) return Promise.resolve(input.sessions ?? []);
                return Promise.resolve([]);
              },
            };
          },
        };
      },
      insert(table: unknown) {
        return {
          values(values: Record<string, unknown>) {
            inserted.push({ table, values });
            return {
              returning() {
                return Promise.resolve([
                  {
                    id: values.id,
                    createdAt: values.createdAt,
                    updatedAt: values.updatedAt,
                  },
                ]);
              },
            };
          },
        };
      },
      update(table: unknown) {
        return {
          set(values: Record<string, unknown>) {
            updates.push({ table, values });
            return {
              where() {
                return Promise.resolve([]);
              },
            };
          },
        };
      },
    },
    services: {
      eventBus: {
        publish(event: Record<string, unknown>) {
          events.push(event);
          return Promise.resolve(event);
        },
        publishVolatile(event: Record<string, unknown>) {
          events.push(event);
          return Promise.resolve(event);
        },
      },
    },
  };
  return { app: app as never, inserted, updates, events };
}

function createFakeClaimApp(input: { rows: Array<Record<string, unknown>> }) {
  const updates: Array<{ table: unknown; values: Record<string, unknown> }> = [];
  const app = {
    db: {
      select() {
        return {
          from() {
            return {
              where() {
                return this;
              },
              orderBy() {
                return this;
              },
              limit() {
                return Promise.resolve(input.rows);
              },
            };
          },
        };
      },
      update(table: unknown) {
        return {
          set(values: Record<string, unknown>) {
            updates.push({ table, values });
            return {
              where() {
                return {
                  returning() {
                    const row = input.rows[0];
                    return Promise.resolve(row ? [{ ...row, ...values }] : []);
                  },
                };
              },
            };
          },
        };
      },
    },
  };
  return { app: app as never, updates };
}

test("resolveFollowUpDue maps relative due hints into future timestamps", () => {
  const now = new Date("2026-07-03T10:00:00.000Z");
  assert.equal(resolveFollowUpDue("next_turn", now).toISOString(), "2026-07-03T10:10:00.000Z");
  assert.equal(resolveFollowUpDue("tomorrow", now).toISOString(), "2026-07-04T06:00:00.000Z");
  assert.equal(resolveFollowUpDue("2026-07-05", now).toISOString(), "2026-07-05T06:00:00.000Z");
  assert.equal(resolveFollowUpDue("2026-07-05T08:30:00.000Z", now).toISOString(), "2026-07-05T08:30:00.000Z");
});

test("recordTurnFollowUps writes pending proactive follow-up triggers", async () => {
  const fake = createFakeApp();
  const result = await recordTurnFollowUps(fake.app, {
    userId: "user-1",
    sessionId: "11111111-1111-4111-8111-111111111111",
    now: new Date("2026-07-03T10:00:00.000Z"),
    envelope: envelope([
      {
        due: "tomorrow",
        topic: "deploy",
        nudge: "Deploy nasil gitti?",
      },
    ]),
  });

  assert.deepEqual(result, { processed: 1, created: 1, skipped: 0 });
  assert.equal(fake.inserted[0]?.table, proactiveTriggers);
  assert.equal(fake.inserted[0]?.values.userId, "user-1");
  assert.equal(fake.inserted[0]?.values.sessionId, "11111111-1111-4111-8111-111111111111");
  assert.equal(fake.inserted[0]?.values.kind, "follow_up");
  assert.equal(fake.inserted[0]?.values.status, "pending");
  assert.deepEqual(fake.inserted[0]?.values.payload, {
    source: "turn_envelope",
    topic: "deploy",
    nudge: "Deploy nasil gitti?",
    dueHint: "tomorrow",
  });
});

test("buildProactiveOpeningCompose uses nudge from partial scheduler payloads", () => {
  const now = new Date("2026-07-03T10:00:00.000Z");
  const result = buildProactiveOpeningCompose({
    id: "44444444-4444-4444-8444-444444444444",
    userId: "22222222-2222-4222-8222-222222222222",
    sessionId: "11111111-1111-4111-8111-111111111111",
    kind: "follow_up",
    due: now,
    payload: {
      nudge: "Dun Ingilizce hedefinin 3. adimindaydin, bugun 15 dakikan var mi?",
    },
    status: "running",
    createdBy: "scheduler",
    dedupeKey: null,
    firedAt: null,
    canceledAt: null,
    createdAt: now,
    updatedAt: now,
  });

  assert.equal(
    result.text,
    "Dun Ingilizce hedefinin 3. adimindaydin, bugun 15 dakikan var mi?",
  );
});

test("claimNextDueProactiveTrigger atomically marks the oldest pending trigger running", async () => {
  const now = new Date("2026-07-03T10:00:00.000Z");
  const fake = createFakeClaimApp({
    rows: [
      {
        id: "44444444-4444-4444-8444-444444444444",
        userId: "22222222-2222-4222-8222-222222222222",
        sessionId: "11111111-1111-4111-8111-111111111111",
        kind: "follow_up",
        due: now,
        payload: {},
        status: "pending",
        createdBy: "model",
        dedupeKey: null,
        firedAt: null,
        canceledAt: null,
        createdAt: now,
        updatedAt: now,
      },
    ],
  });

  const claimed = await claimNextDueProactiveTrigger(fake.app, { now });

  assert.equal(claimed?.id, "44444444-4444-4444-8444-444444444444");
  assert.equal(claimed?.status, "running");
  assert.equal(fake.updates[0]?.table, proactiveTriggers);
  assert.equal(fake.updates[0]?.values.status, "running");
});

test("publishProactiveAssistantMessage writes assistant message and emits chat SSE events", async () => {
  const now = new Date("2026-07-03T10:00:00.000Z");
  const sessionId = "11111111-1111-4111-8111-111111111111";
  const userId = "22222222-2222-4222-8222-222222222222";
  const fake = createFakePublishApp({
    sessions: [
      {
        id: sessionId,
        userId,
        targetDeviceId: "33333333-3333-4333-8333-333333333333",
      },
    ],
  });

  const result = await publishProactiveAssistantMessage(fake.app, {
    now,
    trigger: {
      id: "44444444-4444-4444-8444-444444444444",
      userId,
      sessionId,
      kind: "follow_up",
      due: now,
      payload: {
        source: "turn_envelope",
        topic: "deploy",
        nudge: "Deploy nasil gitti?",
        dueHint: "tomorrow",
      },
      status: "running",
      createdBy: "model",
      dedupeKey: null,
      firedAt: null,
      canceledAt: null,
      createdAt: now,
      updatedAt: now,
    },
    compose: {
      text: "Dunku deploy nasil gitti? Bir sorun ciktiysa beraber toparlayalim.",
      blocks: [{ type: "text", text: "Dunku deploy nasil gitti?" }],
    },
  });

  assert.equal(result.status, "fired");
  assert.equal(fake.inserted[0]?.table, chatMessages);
  assert.equal(fake.inserted[0]?.values.sessionId, sessionId);
  assert.equal(fake.inserted[0]?.values.userId, userId);
  assert.equal(fake.inserted[0]?.values.role, "assistant");
  assert.equal(fake.inserted[0]?.values.status, "completed");
  assert.match(String(fake.inserted[0]?.values.content), /deploy/);
  assert.equal(fake.updates.some((entry) => entry.table === chatSessions), true);
  assert.equal(
    fake.updates.some((entry) => entry.table === proactiveTriggers && entry.values.status === "fired"),
    true,
  );
  assert.deepEqual(
    fake.events.map((event) => event.topic),
    ["chat.message.created", "message.created", "message.completed"],
  );
  assert.equal((fake.events[0]?.payload as { sessionId?: string }).sessionId, sessionId);
  assert.equal((fake.events[0]?.payload as { proactive?: { triggerId?: string } }).proactive?.triggerId, "44444444-4444-4444-8444-444444444444");
  assert.equal((fake.events[2]?.payload as { content?: string }).content?.includes("deploy"), true);
});

test("publishProactiveAssistantMessage expires triggers that cannot target a session", async () => {
  const now = new Date("2026-07-03T10:00:00.000Z");
  const userId = "22222222-2222-4222-8222-222222222222";
  const fake = createFakePublishApp({ sessions: [] });

  const result = await publishProactiveAssistantMessage(fake.app, {
    now,
    trigger: {
      id: "44444444-4444-4444-8444-444444444444",
      userId,
      sessionId: null,
      kind: "follow_up",
      due: now,
      payload: {},
      status: "running",
      createdBy: "model",
      dedupeKey: null,
      firedAt: null,
      canceledAt: null,
      createdAt: now,
      updatedAt: now,
    },
    compose: { text: "Takip mesaji" },
  });

  assert.deepEqual(result, {
    status: "expired",
    triggerId: "44444444-4444-4444-8444-444444444444",
    reason: "missing_session",
  });
  assert.equal(fake.inserted.length, 0);
  assert.equal(fake.events.length, 0);
  assert.equal(
    fake.updates.some((entry) => entry.table === proactiveTriggers && entry.values.status === "expired"),
    true,
  );
});
