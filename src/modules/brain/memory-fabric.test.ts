import assert from "node:assert/strict";
import test from "node:test";
import { brainMemoryEpisodes } from "../../db/schema.js";
import { canonicalizeMemoryKey, recordTurnMemoryOps } from "./memory-fabric.js";
import type { TurnEnvelope } from "./turn-envelope.js";

function createFakeApp() {
  const facts: Array<Record<string, unknown>> = [];
  const episodes: Array<Record<string, unknown>> = [];
  const updates: Array<Record<string, unknown>> = [];
  let id = 0;

  const db: any = {
    transaction<T>(fn: (tx: typeof db) => Promise<T>) {
      return fn(db);
    },
    select() {
      return {
        from() {
          return this;
        },
        where() {
          return this;
        },
        limit() {
          return Promise.resolve(facts.filter((row) => row.userId === "user-1"));
        },
      };
    },
    update() {
      return {
        set(values: Record<string, unknown>) {
          updates.push(values);
          for (const row of facts) {
            Object.assign(row, values);
          }
          return {
            where() {
              return Promise.resolve([]);
            },
          };
        },
      };
    },
    insert(table: unknown) {
      return {
        values(value: Record<string, unknown>) {
          const row = { id: `mem-${++id}`, ...value };
          if (table === brainMemoryEpisodes) episodes.push(row);
          else facts.push(row);
          return {
            returning() {
              return Promise.resolve([{ id: row.id }]);
            },
            then(resolve: (value: unknown) => void) {
              resolve([]);
            },
          };
        },
      };
    },
  };

  return {
    app: { db } as never,
    facts,
    episodes,
    updates,
  };
}

function envelope(memoryOps: TurnEnvelope["memory_ops"]): TurnEnvelope {
  return {
    reply: { text: "", lang: "tr", tone: "neutral" },
    blocks: [],
    memory_ops: memoryOps,
    goal_ops: [],
    follow_ups: [],
    tool_requests: [],
    affect: { user_mood_guess: "unknown", energy: "mid", register: "neutral" },
  };
}

test("canonicalizeMemoryKey creates stable bounded keys", () => {
  assert.equal(canonicalizeMemoryKey(" Preferred Tone! "), "preferred_tone");
  assert.equal(canonicalizeMemoryKey("Bana kısa cevap ver"), "bana_kısa_cevap_ver");
  assert.equal(canonicalizeMemoryKey("Hitap Sekli"), "preferred_name");
});

test("recordTurnMemoryOps treats repeated preferred name writes as replacements", async () => {
  const fake = createFakeApp();
  await recordTurnMemoryOps(fake.app, {
    userId: "user-1",
    envelope: envelope([
      {
        op: "write",
        kind: "preference",
        key: "preferred_name",
        value: "Kaptan",
        confidence: 0.9,
      },
    ]),
  });
  await recordTurnMemoryOps(fake.app, {
    userId: "user-1",
    envelope: envelope([
      {
        op: "write",
        kind: "preference",
        key: "hitap_sekli",
        value: "Komutan",
        confidence: 0.9,
      },
    ]),
  });

  assert.equal(
    fake.updates.some(
      (row) => row.conflictStatus === "superseded" && row.lifecycleStatus === "superseded",
    ),
    true,
  );
});

test("recordTurnMemoryOps writes preference facts without prompt content", async () => {
  const fake = createFakeApp();
  const result = await recordTurnMemoryOps(fake.app, {
    userId: "user-1",
    sessionId: "11111111-1111-4111-8111-111111111111",
    now: new Date("2026-07-03T12:00:00.000Z"),
    envelope: envelope([
      {
        op: "write",
        kind: "preference",
        key: "preferred_tone",
        value: "short and technical",
        confidence: 0.82,
      },
    ]),
  });

  assert.deepEqual(result, {
    processed: 1,
    factsWritten: 1,
    episodesWritten: 0,
    contested: 0,
    forgotten: 0,
    skipped: 0,
  });
  assert.equal(fake.facts.length, 1);
  assert.equal(fake.facts[0]?.canonicalKey, "preferred_tone");
  assert.equal(fake.facts[0]?.factType, "semantic");
  assert.equal(fake.facts[0]?.confidence, 82);
  assert.equal(fake.facts[0]?.revision, 1);
  assert.equal(fake.facts[0]?.sourceKind, "turn_envelope");
  assert.ok(fake.facts[0]?.validFrom instanceof Date);
  assert.equal(typeof fake.facts[0]?.contentHash, "string");
  assert.equal(JSON.stringify(fake.facts[0]?.metadata).includes("Bana"), false);
});

test("recordTurnMemoryOps update supersedes prior same-key facts", async () => {
  const fake = createFakeApp();
  await recordTurnMemoryOps(fake.app, {
    userId: "user-1",
    envelope: envelope([
      {
        op: "update",
        kind: "preference",
        key: "preferred_tone",
        value: "concise",
        confidence: 0.9,
      },
    ]),
  });

  assert.equal(fake.facts.length, 1);
  assert.equal(fake.updates.some((row) => row.lifecycleStatus === "superseded"), true);
});

test("recordTurnMemoryOps writes episode ops to episodic memory", async () => {
  const fake = createFakeApp();
  const result = await recordTurnMemoryOps(fake.app, {
    userId: "user-1",
    sessionId: "22222222-2222-4222-8222-222222222222",
    envelope: envelope([
      {
        op: "write",
        kind: "episode",
        key: "deploy_followup",
        value: "User asked Elyan to remember tomorrow morning deploy follow-up.",
        confidence: 0.75,
        ttl_days: 2,
      },
    ]),
  });

  assert.equal(result.episodesWritten, 1);
  assert.equal(fake.episodes.length, 1);
  assert.equal(fake.episodes[0]?.episodeType, "deploy_followup");
  assert.equal(fake.episodes[0]?.sourceSessionId, "22222222-2222-4222-8222-222222222222");
  assert.ok(fake.episodes[0]?.staleAt instanceof Date);
  assert.ok(fake.episodes[0]?.expiresAt instanceof Date);
  assert.ok(
    (fake.episodes[0]?.expiresAt as Date).getTime() -
      (fake.episodes[0]?.observedAt as Date).getTime() <=
      90 * 86_400_000,
  );
});

test("recordTurnMemoryOps creates a tombstone for explicit forget operations", async () => {
  const fake = createFakeApp();
  const result = await recordTurnMemoryOps(fake.app, {
    userId: "user-1",
    now: new Date("2026-07-04T12:00:00.000Z"),
    envelope: envelope([
      {
        op: "forget",
        kind: "preference",
        key: "preferred_name",
        value: "",
        confidence: 1,
      },
    ]),
  });

  assert.equal(result.forgotten, 1);
  assert.equal(
    fake.facts.some(
      (row) =>
        row.lifecycleStatus === "soft_deleted" &&
        (row.metadata as Record<string, unknown> | undefined)?.forgetTombstone === true,
    ),
    true,
  );
});
