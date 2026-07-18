import assert from "node:assert/strict";
import test from "node:test";
import { brainMemoryEpisodes } from "../../db/schema.js";
import {
  executeAgentTool,
  getAgentToolMetadata,
  listAgentTools,
  readCanonicalAgentToolArgs,
} from "./tool-registry.js";

function createFakeMemoryApp() {
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
  return { app: { db } as never, facts, episodes, updates };
}

function createFakeGoalsApp() {
  const rows: Array<Record<string, unknown>> = [
    {
      id: "11111111-1111-4111-8111-111111111111",
      userId: "user-1",
      sessionId: "22222222-2222-4222-8222-222222222222",
      taskId: null,
      title: "Backend agent loop",
      description: "",
      status: "active",
      currentStep: 0,
      maxSteps: 4,
      progress: {
        completedSteps: [],
        nextAction: null,
        blockers: [],
        engineState: "open",
      },
      scheduleHint: "on_next_message",
      dueAt: null,
      createdAt: new Date("2030-01-01T00:00:00.000Z"),
      updatedAt: new Date("2030-01-01T00:00:00.000Z"),
    },
  ];
  const db: any = {
    select() {
      return {
        from() {
          return this;
        },
        where() {
          return this;
        },
        orderBy() {
          return this;
        },
        limit() {
          return Promise.resolve(rows);
        },
      };
    },
    update() {
      return {
        set(values: Record<string, unknown>) {
          return {
            where() {
              rows[0] = {
                ...rows[0],
                ...values,
              };
              return {
                returning() {
                  return Promise.resolve([rows[0]]);
                },
              };
            },
          };
        },
      };
    },
  };
  return { app: { db, config: { ELYAN_GOAL_STATE_V2_ENABLED: false } } as never, rows };
}

test("listAgentTools exposes the first server brain tools with permissions", () => {
  const tools = listAgentTools();
  assert.equal(tools.some((tool) => tool.name === "web.search" && tool.permission === "read"), true);
  assert.equal(tools.some((tool) => tool.name === "web.fetch_url" && tool.permission === "read"), true);
  assert.equal(tools.some((tool) => tool.name === "memory.query" && tool.permission === "read"), true);
  assert.equal(tools.some((tool) => tool.name === "memory.write" && tool.permission === "write"), true);
  assert.equal(tools.some((tool) => tool.name === "goals.update" && tool.permission === "write"), true);
});

test("tool registry exposes timeout, idempotency and parallel safety", () => {
  assert.deepEqual(getAgentToolMetadata("web.search"), {
    name: "web.search",
    permission: "read",
    timeoutMs: 7_000,
    idempotency: "read_only",
    parallelSafe: true,
  });
  assert.deepEqual(getAgentToolMetadata("web.fetch_url"), {
    name: "web.fetch_url",
    permission: "read",
    timeoutMs: 8_000,
    idempotency: "read_only",
    parallelSafe: true,
  });
  assert.equal(getAgentToolMetadata("memory.write")?.parallelSafe, false);
  assert.equal(getAgentToolMetadata("memory.write")?.idempotency, "non_idempotent");
});

test("executeAgentTool can fetch URL context as a read-only tool", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(
      "Title: Tool URL\nURL: https://example.com/tool\n\nTool URL content with enough readable text for the fetch URL tool output contract.",
      { status: 200 },
    )) as typeof fetch;

  try {
    const result = await executeAgentTool(
      { config: { JINA_READER_ENABLED: true } } as never,
      {
        userId: "user-1",
        workload: "mobile_chat_fast",
      },
      {
        tool: "web.fetch_url",
        args: { url: "https://example.com/tool" },
      },
    );

    assert.equal(result.ok, true);
    assert.equal(result.permission, "read");
    assert.equal(result.output?.source, "jina");
    assert.equal(result.output?.sourceAuthority, "standard");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("executeAgentTool blocks write tools unless state-write policy is enabled", async () => {
  const result = await executeAgentTool(
    {} as never,
    {
      userId: "user-1",
      workload: "mobile_chat_fast",
      allowSideEffects: false,
      allowStateWrites: false,
    },
    {
      tool: "memory.write",
      args: {
        kind: "preference",
        key: "preferred_tone",
        value: "short",
      },
    },
  );

  assert.equal(result.ok, false);
  assert.equal(result.permission, "write");
  assert.equal(result.error?.code, "tool_write_requires_state_policy");
});

test("executeAgentTool allows internal memory writes when state-write policy is enabled", async () => {
  const fake = createFakeMemoryApp();
  const result = await executeAgentTool(
    fake.app,
    {
      userId: "user-1",
      sessionId: "11111111-1111-4111-8111-111111111111",
      workload: "mobile_chat_fast",
      allowStateWrites: true,
      allowSideEffects: false,
    },
    {
      tool: "memory.write",
      args: {
        kind: "preference",
        key: "preferred_tone",
        value: "short",
        confidence: 0.9,
      },
    },
  );

  assert.equal(result.ok, true);
  assert.equal(result.permission, "write");
  assert.equal(result.output?.factsWritten, 1);
  assert.equal(fake.facts[0]?.canonicalKey, "preferred_tone");
});

test("executeAgentTool advances the active goal when goalId is omitted", async () => {
  const fake = createFakeGoalsApp();
  const result = await executeAgentTool(
    fake.app,
    {
      userId: "user-1",
      sessionId: "22222222-2222-4222-8222-222222222222",
      workload: "mobile_chat_fast",
      allowStateWrites: true,
      allowSideEffects: false,
    },
    {
      tool: "goals.update",
      args: {
        action: "advance",
        step: 1,
        ofSteps: 4,
        next: "Tool loop state writes enabled",
      },
    },
  );

  assert.equal(result.ok, true);
  assert.equal(result.output?.goal && typeof result.output.goal, "object");
  assert.equal(fake.rows[0]?.currentStep, 1);
  assert.deepEqual(fake.rows[0]?.progress, {
    completedSteps: ["Tool loop state writes enabled"],
    nextAction: "Tool loop state writes enabled",
    blockers: [],
    engineState: "executing",
  });
});

test("executeAgentTool returns typed errors for unknown tools", async () => {
  const result = await executeAgentTool(
    {} as never,
    {
      userId: "user-1",
      workload: "mobile_chat_fast",
    },
    { tool: "not.real", args: {} },
  );

  assert.equal(result.ok, false);
  assert.equal(result.error?.code, "unknown_tool");
});

test("executeAgentTool: JSON-string args deterministik onarılır", async () => {
  const fake = createFakeMemoryApp();
  const result = await executeAgentTool(
    fake.app,
    { userId: "user-1", sessionId: null, workload: "mobile_chat_balanced", allowStateWrites: true, allowSideEffects: false },
    { tool: "memory.query", args: '{"query":"kahve tercihi","limit":3}' as never },
  );
  assert.equal(result.ok, true);
});

test("executeAgentTool: {arguments:{...}} sarmalaması açılır", async () => {
  const fake = createFakeMemoryApp();
  const result = await executeAgentTool(
    fake.app,
    { userId: "user-1", sessionId: null, workload: "mobile_chat_balanced", allowStateWrites: true, allowSideEffects: false },
    { tool: "memory.query", args: { arguments: { query: "kahve", limit: 2 } } as never },
  );
  assert.equal(result.ok, true);
});

test("executeAgentTool: geçersiz argümanda alan yollu hata mesajı döner", async () => {
  const fake = createFakeMemoryApp();
  const result = await executeAgentTool(
    fake.app,
    { userId: "user-1", sessionId: null, workload: "mobile_chat_balanced", allowStateWrites: true, allowSideEffects: false },
    { tool: "memory.query", args: { limit: 3 } as never },
  );
  assert.equal(result.ok, false);
  assert.equal(result.error?.code, "invalid_tool_args");
  assert.match(result.error?.message ?? "", /query/);
});

// ── Connector read arg toleransı ─────────────────────────────────────
// Canlı vaka: "Mailleri oku" turunda model gmail.search'e boş/eksik query
// üretti → invalid_tool_args → kullanıcıya "araç kataloğu doğrulayamıyor".
// Read araçları model bozulmalarına deterministik onarımla dayanmalı.

test("gmail.search: boş args gelen kutusu listelemeye çözülür", () => {
  const args = readCanonicalAgentToolArgs("gmail.search", {});
  assert.deepEqual(args, { query: "in:inbox", limit: 5 });
});

test("gmail.search: boş string query default'a düşer", () => {
  const args = readCanonicalAgentToolArgs("gmail.search", { query: "  " });
  assert.equal(args?.query, "in:inbox");
});

test("gmail.search: q/max_results alias'ları kanonik anahtara taşınır", () => {
  const args = readCanonicalAgentToolArgs("gmail.search", {
    q: "from:ali is:unread",
    max_results: 3,
  });
  assert.equal(args?.query, "from:ali is:unread");
  assert.equal(args?.limit, 3);
});

test("gmail.search: null query silinir ve default devreye girer", () => {
  const args = readCanonicalAgentToolArgs("gmail.search", {
    query: null,
    count: 2,
  });
  assert.equal(args?.query, "in:inbox");
  assert.equal(args?.limit, 2);
});

test("calendar.list_events ve drive.search boş args kabul eder", () => {
  assert.deepEqual(readCanonicalAgentToolArgs("calendar.list_events", {}), {
    days: 7,
    limit: 10,
  });
  assert.deepEqual(readCanonicalAgentToolArgs("drive.search", {}), {
    query: "",
    limit: 10,
  });
});

test("gmail.read: id alias'ı çalışır ama boş args hâlâ reddedilir", () => {
  assert.deepEqual(readCanonicalAgentToolArgs("gmail.read", { id: "abc123" }), {
    messageId: "abc123",
  });
  assert.equal(readCanonicalAgentToolArgs("gmail.read", {}), null);
});

test("yazma araçları gevşemez: gmail.send boş args reddedilir", () => {
  assert.equal(readCanonicalAgentToolArgs("gmail.send", {}), null);
  assert.equal(
    readCanonicalAgentToolArgs("calendar.create_event", { title: "x" }),
    null,
  );
});

test("executeAgentTool: bozuk gmail.search args'ı invalid_tool_args üretmez", async () => {
  const fake = createFakeMemoryApp();
  const result = await executeAgentTool(
    fake.app,
    { userId: "user-1", sessionId: null, workload: "mobile_chat_fast", allowStateWrites: false, allowSideEffects: false },
    // query sayı: alias onarımı da kurtaramaz → salt-default fallback yolu.
    { tool: "gmail.search", args: { query: 42 } as never },
  );
  // Fallback {} parse'ı geçer, yürütme fake app'te başka sebeple düşebilir;
  // kritik olan sözleşme hatasının kullanıcıya sızmaması.
  assert.notEqual(result.error?.code, "invalid_tool_args");
});

test("notion.search ve github.search boş args ve alias'larla çözülür", () => {
  assert.deepEqual(readCanonicalAgentToolArgs("notion.search", {}), {
    query: "",
    limit: 10,
  });
  assert.deepEqual(
    readCanonicalAgentToolArgs("github.search", {
      q: "is:open author:@me",
      per_page: 5,
    }),
    { query: "is:open author:@me", limit: 5 },
  );
});
