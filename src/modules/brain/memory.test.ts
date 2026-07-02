import assert from "node:assert/strict";
import test from "node:test";
import {
  listBrainMemory,
  processMemoryImportanceDecay,
  resolveDecayedMemoryImportance,
  resolveMemoryImportanceBaseline,
  scoreMemoryRecallCandidate,
  searchBrainMemory,
  softDeleteBrainMemory,
  updateBrainMemory,
} from "./memory.js";

class FakeMemoryDb {
  public readonly updates: Array<{ values: Record<string, unknown> }> = [];

  constructor(private readonly executeResults: unknown[]) {}

  execute() {
    return Promise.resolve(this.executeResults.shift() ?? { rows: [] });
  }

  insert() {
    const builder = {
      values() {
        return Promise.resolve([]);
      },
    };
    return builder;
  }

  update() {
    const updates = this.updates;
    const builder = {
      set(values: Record<string, unknown>) {
        updates.push({ values });
        return builder;
      },
      where() {
        return Promise.resolve([]);
      },
    };
    return builder;
  }
}

test("scoreMemoryRecallCandidate favors pinned semantic facts over fresher episodic memory", () => {
  const pinnedSemantic = scoreMemoryRecallCandidate({
    memorySource: "semantic_memory",
    memoryType: "semantic",
    confidence: 88,
    staleness: "fresh",
    importanceScore: 92,
    isPinned: true,
    conflictStatus: "active",
    updatedAt: new Date().toISOString(),
    lexicalScore: 6,
    semanticScore: 0.78,
    metadata: {
      projectCritical: true,
    },
  });
  const episodic = scoreMemoryRecallCandidate({
    memorySource: "episodic_memory",
    memoryType: "session_recovered",
    confidence: 91,
    staleness: "fresh",
    importanceScore: 70,
    isPinned: false,
    conflictStatus: "active",
    updatedAt: new Date().toISOString(),
    lexicalScore: 7,
    semanticScore: 0.74,
    metadata: {},
  });

  assert.equal(pinnedSemantic > episodic, true);
});

test("scoreMemoryRecallCandidate penalizes stale and contested memory aggressively", () => {
  const active = scoreMemoryRecallCandidate({
    memorySource: "semantic_memory",
    memoryType: "semantic",
    confidence: 82,
    staleness: "fresh",
    importanceScore: 80,
    isPinned: false,
    conflictStatus: "active",
    updatedAt: new Date().toISOString(),
    lexicalScore: 5,
    semanticScore: 0.72,
    metadata: {},
  });
  const stale = scoreMemoryRecallCandidate({
    memorySource: "semantic_memory",
    memoryType: "semantic",
    confidence: 82,
    staleness: "stale",
    importanceScore: 80,
    isPinned: false,
    conflictStatus: "active",
    updatedAt: new Date(Date.now() - 120 * 86_400_000).toISOString(),
    lexicalScore: 5,
    semanticScore: 0.72,
    metadata: {},
  });
  const contested = scoreMemoryRecallCandidate({
    memorySource: "semantic_memory",
    memoryType: "semantic",
    confidence: 82,
    staleness: "contested",
    importanceScore: 80,
    isPinned: false,
    conflictStatus: "contested",
    updatedAt: new Date().toISOString(),
    lexicalScore: 5,
    semanticScore: 0.72,
    metadata: {},
  });

  assert.equal(active > stale, true);
  assert.equal(stale > contested, true);
});

test("resolveDecayedMemoryImportance applies baselines, weekly decay, and verified boost", () => {
  const now = new Date("2030-02-01T00:00:00.000Z");
  assert.equal(
    resolveMemoryImportanceBaseline({
      factType: "semantic",
      key: "safety_boundary",
      isPinned: false,
    }),
    90,
  );
  assert.equal(
    resolveMemoryImportanceBaseline({
      factType: "self_model",
      key: "self_model_recent_topics",
      isPinned: false,
    }),
    80,
  );
  assert.equal(
    resolveMemoryImportanceBaseline({
      factType: "semantic",
      key: "response_style_preference",
      isPinned: false,
    }),
    60,
  );
  assert.equal(
    resolveMemoryImportanceBaseline({
      factType: "semantic",
      key: "project_context",
      isPinned: false,
    }),
    50,
  );
  assert.equal(resolveMemoryImportanceBaseline({ isPinned: true }), 100);

  assert.equal(
    resolveDecayedMemoryImportance({
      factType: "semantic",
      key: "ordinary_fact",
      importanceScore: 80,
      confidence: 70,
      isPinned: false,
      updatedAt: "2030-01-04T00:00:00.000Z",
      lastVerifiedAt: null,
      now,
    }).importanceScore,
    78,
  );
  assert.equal(
    resolveDecayedMemoryImportance({
      factType: "semantic",
      key: "ordinary_fact",
      importanceScore: 70,
      confidence: 90,
      isPinned: false,
      updatedAt: "2030-01-18T00:00:00.000Z",
      lastVerifiedAt: "2030-01-30T00:00:00.000Z",
      now,
    }).importanceScore,
    72,
  );
  assert.equal(
    resolveDecayedMemoryImportance({
      factType: "semantic",
      key: "ordinary_fact",
      importanceScore: 25,
      confidence: 70,
      isPinned: false,
      updatedAt: "2029-01-01T00:00:00.000Z",
      lastVerifiedAt: null,
      now,
    }).importanceScore,
    30,
  );
});

test("processMemoryImportanceDecay updates a bounded batch with decay metadata", async () => {
  const db = new FakeMemoryDb([
    {
      rows: [
        {
          id: "fact-1",
          factType: "semantic",
          key: "ordinary_fact",
          canonicalKey: "ordinary_fact",
          confidence: 70,
          importanceScore: 80,
          isPinned: false,
          updatedAt: "2030-01-04T00:00:00.000Z",
          lastVerifiedAt: null,
          metadata: { source: "test" },
        },
        {
          id: "fact-2",
          factType: "semantic",
          key: "response_style_preference",
          canonicalKey: "response_style_preference",
          confidence: 95,
          importanceScore: 62,
          isPinned: false,
          updatedAt: "2030-01-18T00:00:00.000Z",
          lastVerifiedAt: "2030-01-30T00:00:00.000Z",
          metadata: {},
        },
      ],
    },
  ]);
  const result = await processMemoryImportanceDecay(
    { db, log: { debug() {}, info() {}, warn() {} } } as never,
    { now: new Date("2030-02-01T00:00:00.000Z") },
  );

  assert.equal(result.status, "completed");
  assert.equal(result.processedCount, 2);
  assert.equal(result.updatedCount, 2);
  assert.equal(db.updates[0]?.values["importanceScore"], 78);
  assert.equal(db.updates[1]?.values["importanceScore"], 64);
  assert.equal(
    (db.updates[0]?.values["metadata"] as Record<string, unknown>)["lastImportanceDecayedAt"],
    "2030-02-01T00:00:00.000Z",
  );
});

test("processMemoryImportanceDecay skips when the DB budget expires", async () => {
  const slowApp = {
    db: {
      execute() {
        return new Promise((resolve) => {
          const t = setTimeout(() => resolve({ rows: [] }), 5_000);
          (t as unknown as { unref?: () => void }).unref?.();
        });
      },
      update() {
        throw new Error("update should not run after budget expiry");
      },
    },
    log: { warn() {}, debug() {}, info() {} },
  } as unknown as Parameters<typeof processMemoryImportanceDecay>[0];
  const startedAt = Date.now();
  const result = await processMemoryImportanceDecay(slowApp, {
    now: new Date("2030-02-01T00:00:00.000Z"),
  });

  assert.equal(result.status, "skipped");
  assert.equal(result.reason, "memory_decay_budget_expired");
  assert.ok(Date.now() - startedAt < 2_000);
});

test("listBrainMemory hides soft-deleted records for user-safe views by default", async () => {
  const app = {
    db: new FakeMemoryDb([
      {
        rows: [
          {
            id: "fact-active",
            memoryType: "semantic",
            title: "preferred_tone",
            content: "warm",
            confidence: 92,
            importanceScore: 88,
            isPinned: false,
            scope: "user",
            conflictStatus: "active",
            lifecycleStatus: "active",
            lastVerifiedAt: "2030-01-01T00:00:00.000Z",
            deletedAt: null,
            deletedReason: null,
            staleAt: null,
            metadata: {},
            createdAt: "2030-01-01T00:00:00.000Z",
            updatedAt: "2030-01-01T00:00:00.000Z",
          },
          {
            id: "fact-deleted",
            memoryType: "semantic",
            title: "project_constraint",
            content: "deprecated",
            confidence: 60,
            importanceScore: 55,
            isPinned: false,
            scope: "user",
            conflictStatus: "active",
            lifecycleStatus: "soft_deleted",
            lastVerifiedAt: "2030-01-01T00:00:00.000Z",
            deletedAt: "2030-01-02T00:00:00.000Z",
            deletedReason: "cleanup",
            staleAt: null,
            metadata: {},
            createdAt: "2030-01-01T00:00:00.000Z",
            updatedAt: "2030-01-02T00:00:00.000Z",
          },
        ],
      },
      { rows: [] },
    ]),
  };

  const result = await listBrainMemory(app as never, {
    userId: "user-1",
    limit: 10,
    includeSoftDeleted: false,
    surface: "all",
    lifecycle: [],
    isAdmin: false,
  });

  assert.equal(result.items.length, 1);
  assert.equal(result.items[0]?.id, "fact-active");
  assert.equal(result.summary.softDeleted, 1);
});

test("listBrainMemory presents synthesized continuity memories with clean labels", async () => {
  const app = {
    db: new FakeMemoryDb([
      {
        rows: [
          {
            id: "fact-continuity",
            memoryType: "self_model",
            title: "self_model_recent_topics",
            content: "Recent recurring topics: backend, auth, planning",
            confidence: 90,
            importanceScore: 82,
            isPinned: false,
            scope: "user",
            conflictStatus: "active",
            lifecycleStatus: "active",
            lastVerifiedAt: "2030-01-01T00:00:00.000Z",
            deletedAt: null,
            deletedReason: null,
            staleAt: null,
            metadata: {},
            createdAt: "2030-01-01T00:00:00.000Z",
            updatedAt: "2030-01-01T00:00:00.000Z",
          },
        ],
      },
      { rows: [] },
    ]),
  };

  const result = await listBrainMemory(app as never, {
    userId: "user-1",
    limit: 10,
    includeSoftDeleted: false,
    surface: "all",
    lifecycle: [],
    isAdmin: false,
  });

  assert.equal(result.items[0]?.title, "Recent Topics");
  assert.equal(result.items[0]?.content, "backend, auth, planning");
  assert.equal(
    ((result.items[0]?.metadata?.presentation as Record<string, unknown> | undefined)?.editable),
    true,
  );
});

test("softDeleteBrainMemory marks a memory as soft_deleted and keeps audit-safe metadata", async () => {
  const app = {
    db: new FakeMemoryDb([
      {
        rows: [
          {
            id: "fact-1",
            memoryType: "semantic",
            title: "preferred_tone",
            content: "warm",
            confidence: 92,
            importanceScore: 88,
            isPinned: true,
            scope: "user",
            conflictStatus: "active",
            lifecycleStatus: "active",
            lastVerifiedAt: "2030-01-01T00:00:00.000Z",
            deletedAt: null,
            deletedReason: null,
            staleAt: null,
            metadata: {},
            createdAt: "2030-01-01T00:00:00.000Z",
            updatedAt: "2030-01-01T00:00:00.000Z",
          },
        ],
      },
      { rows: [] },
      {
        rows: [
          {
            id: "fact-1",
            memoryType: "semantic",
            title: "preferred_tone",
            content: "warm",
            confidence: 92,
            importanceScore: 88,
            isPinned: true,
            scope: "user",
            conflictStatus: "active",
            lifecycleStatus: "soft_deleted",
            lastVerifiedAt: "2030-01-01T00:00:00.000Z",
            deletedAt: "2030-01-03T00:00:00.000Z",
            deletedReason: "cleanup",
            staleAt: null,
            metadata: {},
            createdAt: "2030-01-01T00:00:00.000Z",
            updatedAt: "2030-01-03T00:00:00.000Z",
          },
        ],
      },
      { rows: [] },
    ]),
  };

  const result = await softDeleteBrainMemory(app as never, {
    userId: "user-1",
    memoryId: "fact-1",
    reason: "cleanup",
    actorUserId: "user-1",
  });

  assert.equal(result.lifecycleStatus, "soft_deleted");
  assert.equal((app.db as FakeMemoryDb).updates[0]?.values["lifecycleStatus"], "soft_deleted");
});

test("updateBrainMemory edits fact content and clears deleted state", async () => {
  const app = {
    db: new FakeMemoryDb([
      {
        rows: [
          {
            id: "fact-1",
            memoryType: "self_model",
            title: "self_model_recent_topics",
            content: "Recent recurring topics: backend, auth",
            confidence: 92,
            importanceScore: 88,
            isPinned: false,
            scope: "user",
            conflictStatus: "active",
            lifecycleStatus: "active",
            lastVerifiedAt: "2030-01-01T00:00:00.000Z",
            deletedAt: null,
            deletedReason: null,
            staleAt: null,
            metadata: {},
            createdAt: "2030-01-01T00:00:00.000Z",
            updatedAt: "2030-01-01T00:00:00.000Z",
          },
        ],
      },
      { rows: [] },
      {
        rows: [
          {
            id: "fact-1",
            memoryType: "self_model",
            title: "self_model_recent_topics",
            content: "Backend ve auth yerine backend ve routing",
            confidence: 92,
            importanceScore: 88,
            isPinned: false,
            scope: "user",
            conflictStatus: "active",
            lifecycleStatus: "active",
            lastVerifiedAt: "2030-01-01T00:00:00.000Z",
            deletedAt: null,
            deletedReason: null,
            staleAt: null,
            metadata: {
              userEdited: true,
            },
            createdAt: "2030-01-01T00:00:00.000Z",
            updatedAt: "2030-01-02T00:00:00.000Z",
          },
        ],
      },
    ]),
    log: {
      info: () => undefined,
      warn: () => undefined,
      debug: () => undefined,
    },
  };

  const result = await updateBrainMemory(app as never, {
    userId: "user-1",
    memoryId: "fact-1",
    content: "Backend ve auth yerine backend ve routing",
    title: null,
    reason: "manual correction",
    actorUserId: "user-1",
  });

  assert.equal((app.db as FakeMemoryDb).updates[0]?.values["value"], "Backend ve auth yerine backend ve routing");
  assert.equal(result.content, "Backend ve auth yerine backend ve routing");
});

test("searchBrainMemory returns lexical_fallback when db.execute is unavailable", async () => {
  // Guard: without an execute() method (e.g. an in-memory fake missing that
  // API) retrieval must degrade silently — never throw and never block
  // inference. This is the fast fail-open path.
  const app = { db: {}, log: { warn() {} }, config: {} } as unknown as Parameters<typeof searchBrainMemory>[0];
  const result = await searchBrainMemory(app, {
    userId: "user-1",
    query: "test",
    limit: 5,
  });
  assert.equal(result.retrievalMode, "lexical_fallback");
  assert.equal(result.degradedReason, "memory_execute_unavailable");
  assert.deepEqual(result.results, []);
});

test("searchBrainMemory degrades to budget_expired on a slow db (never blocks the caller)", async () => {
  // Simulate a stuck Postgres: execute() takes far longer than the budget
  // to resolve. The retrieval must give up within the shared budget rather
  // than freezing the inference path. Using a settleable slow promise (not a
  // never-resolving one) keeps the test process cleanly exitable while still
  // exercising the timeout race.
  const slowApp = {
    db: {
      execute() {
        return new Promise((resolve) => {
          const t = setTimeout(() => resolve({ rows: [] }), 5_000);
          (t as unknown as { unref?: () => void }).unref?.();
        });
      },
    },
    log: { warn() {} },
    config: {},
  } as unknown as Parameters<typeof searchBrainMemory>[0];
  const startedAt = Date.now();
  const result = await searchBrainMemory(slowApp, {
    userId: "user-1",
    query: "test",
    limit: 5,
  });
  const elapsed = Date.now() - startedAt;
  assert.equal(result.retrievalMode, "lexical_fallback");
  assert.equal(result.degradedReason, "memory_search_budget_expired");
  // 800ms budget + generous slack for test scheduling.
  assert.ok(elapsed < 2_000, `retrieval hung for ${elapsed}ms`);
});
