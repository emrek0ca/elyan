import assert from "node:assert/strict";
import test from "node:test";
import { PgDialect } from "drizzle-orm/pg-core";
import type { SQL } from "drizzle-orm";
import {
  getConnectorAccessToken,
  listConnectedCapabilityGrants,
  markConnectionAuthExpired,
} from "./service.js";
import { listMcpServers, updateMcpServer } from "../mcp/service.js";

/**
 * Kiracı izolasyonu regresyon kilidi: kullanıcıya bağlı her sorgunun WHERE
 * koşulunda user_id (veya güncellemede id+status) filtresi OLDUĞUNU, koşulu
 * gerçek SQL'e dökerek kanıtlar. Bugün doğru olan filtre yarınki bir
 * refactor'da sessizce düşerse bu testler kırılır — kullanıcı verileri asla
 * birbirine karışamaz.
 */

const dialect = new PgDialect();

function renderCondition(condition: unknown): { sql: string; params: unknown[] } {
  const query = dialect.sqlToQuery(condition as SQL);
  return { sql: query.sql, params: query.params };
}

type CapturedQuery = {
  kind: "select" | "update" | "delete";
  condition?: unknown;
  set?: Record<string, unknown>;
};

/** Sorgu zincirlerini kaydeden, sıraya konmuş sonuçları dönen sahte db. */
class RecordingDb {
  readonly captured: CapturedQuery[] = [];
  readonly inserted: Array<Record<string, unknown>> = [];

  constructor(private readonly selectResults: unknown[][]) {}

  select() {
    const entry: CapturedQuery = { kind: "select" };
    this.captured.push(entry);
    const rows = this.selectResults.shift() ?? [];
    const chain = {
      from: () => chain,
      where: (condition: unknown) => {
        entry.condition = condition;
        return chain;
      },
      orderBy: () => chain,
      limit: () => chain,
      then: <T>(resolve?: (value: unknown[]) => T) =>
        Promise.resolve(rows).then(resolve),
    };
    return chain;
  }

  update() {
    const entry: CapturedQuery = { kind: "update" };
    this.captured.push(entry);
    const chain = {
      set: (values: Record<string, unknown>) => {
        entry.set = values;
        return chain;
      },
      where: (condition: unknown) => {
        entry.condition = condition;
        return chain;
      },
      returning: () => Promise.resolve([]),
    };
    return chain;
  }

  insert() {
    const inserted = this.inserted;
    const chain = {
      values: (values: Record<string, unknown>) => {
        inserted.push(values);
        return chain;
      },
      returning: () => Promise.resolve([{ id: "row-1" }]),
      onConflictDoNothing: () => chain,
      then: <T>(resolve?: (value: unknown[]) => T) =>
        Promise.resolve([]).then(resolve),
    };
    return chain;
  }
}

function appWith(db: RecordingDb) {
  return {
    db,
    config: {},
    log: { warn() {}, debug() {}, info() {}, error() {} },
  } as never;
}

const USER_A = "11111111-1111-4111-8111-111111111111";

test("getConnectorAccessToken filters connections by the requesting user id", async () => {
  const db = new RecordingDb([[]]);
  await assert.rejects(
    getConnectorAccessToken(appWith(db), {
      userId: USER_A,
      capability: "gmail",
      requiredScopes: ["https://www.googleapis.com/auth/gmail.readonly"],
    }),
    /No connected integration grants capability/u,
  );
  const select = db.captured.find((entry) => entry.kind === "select");
  assert.ok(select?.condition, "sorgu WHERE koşulu taşımalı");
  const { sql, params } = renderCondition(select.condition);
  assert.match(sql, /"integration_connections"\."user_id" = /u);
  assert.match(sql, /"integration_connections"\."status" = /u);
  assert.ok(params.includes(USER_A), "WHERE parametreleri istek sahibinin id'sini içermeli");
  assert.ok(params.includes("connected"));
});

test("listConnectedCapabilityGrants scopes rows to the requesting user id", async () => {
  const db = new RecordingDb([[]]);
  const grants = await listConnectedCapabilityGrants(appWith(db), USER_A);
  assert.deepEqual(grants, []);
  const select = db.captured.find((entry) => entry.kind === "select");
  assert.ok(select?.condition);
  const { sql, params } = renderCondition(select.condition);
  assert.match(sql, /"integration_connections"\."user_id" = /u);
  assert.ok(params.includes(USER_A));
  assert.ok(params.includes("connected"));
});

test("listMcpServers scopes rows to the requesting user id", async () => {
  const db = new RecordingDb([[]]);
  await listMcpServers(appWith(db), USER_A);
  const select = db.captured.find((entry) => entry.kind === "select");
  assert.ok(select?.condition);
  const { sql, params } = renderCondition(select.condition);
  assert.match(sql, /"mcp_servers"\."user_id" = /u);
  assert.ok(params.includes(USER_A));
});

test("updateMcpServer requires both server id and owner user id (cross-user update = not found)", async () => {
  const db = new RecordingDb([[]]);
  await assert.rejects(
    updateMcpServer(appWith(db), {
      userId: USER_A,
      serverId: "22222222-2222-4222-8222-222222222222",
      name: "ele-gecirilen",
    }),
    /MCP server not found/u,
  );
  const update = db.captured.find((entry) => entry.kind === "update");
  assert.ok(update?.condition);
  const { sql, params } = renderCondition(update.condition);
  assert.match(sql, /"mcp_servers"\."id" = /u);
  assert.match(sql, /"mcp_servers"\."user_id" = /u);
  assert.ok(params.includes(USER_A));
});

test("markConnectionAuthExpired flips only the owner's connected row to error", async () => {
  const db = new RecordingDb([]);
  await markConnectionAuthExpired(
    appWith(db),
    "33333333-3333-4333-8333-333333333333",
    "google",
  );
  const update = db.captured.find((entry) => entry.kind === "update");
  assert.ok(update?.condition, "durum güncellemesi WHERE koşulu taşımalı");
  assert.equal(update.set?.status, "error");
  const { sql, params } = renderCondition(update.condition);
  assert.match(sql, /"integration_connections"\."id" = /u);
  assert.match(sql, /"integration_connections"\."status" = /u);
  assert.ok(params.includes("connected"));
  // returning [] (satır zaten connected değil) → audit yazılmaz.
  assert.equal(db.inserted.length, 0);
});
