import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
  buildConnectorResultBlocks,
  connectorResultFallbackText,
  mergeAuthoritativeConnectorResultBlocks,
} from "./connector-result-blocks.js";
import type { AgentToolResult } from "./tool-registry.js";

function ok(tool: string, output: Record<string, unknown>): AgentToolResult {
  return { tool, ok: true, permission: "read", durationMs: 1, output, error: null };
}

test("gmail.search results become a connector result block with sender/subject/date", () => {
  const blocks = buildConnectorResultBlocks([
    ok("gmail.search", {
      results: [
        {
          from: "Ali Veli <ali@example.com>",
          subject: "Toplantı",
          date: "2026-07-18T09:00:00Z",
        },
      ],
    }),
  ]);
  assert.equal(blocks.length, 1);
  const block = blocks[0] as { type: string; columns: string[]; rows: string[][]; items: Array<{ title: string; subtitle: string }> };
  assert.equal(block.type, "connector_result");
  assert.deepEqual(block.columns, ["Kimden", "Konu", "Tarih"]);
  assert.equal(block.rows[0][0], "Ali Veli");
  assert.equal(block.rows[0][1], "Toplantı");
  assert.equal(block.items[0]?.title, "Toplantı");
  assert.equal(block.items[0]?.subtitle, "Ali Veli");
});

test("gmail.search message-shaped output still becomes a connector result block", () => {
  const blocks = buildConnectorResultBlocks([
    ok("gmail.search", {
      messages: [
        {
          from: "Ayşe <ayse@example.com>",
          subject: "Fatura",
          date: "2026-07-18T12:00:00Z",
        },
      ],
    }),
  ]);
  assert.equal(blocks.length, 1);
  const block = blocks[0] as { type: string; rows: string[][]; provider: string };
  assert.equal(block.type, "connector_result");
  assert.equal(block.provider, "gmail");
  assert.equal(block.rows[0][0], "Ayşe");
  assert.equal(block.rows[0][1], "Fatura");
});

test("calendar and drive list results each become a connector result block", () => {
  const blocks = buildConnectorResultBlocks([
    ok("calendar.list_events", {
      results: [{ title: "Demo", start: "2026-07-18T10:00:00Z", end: "", location: "Ofis" }],
    }),
    ok("drive.search", {
      results: [
        {
          name: "Plan",
          mimeType: "application/vnd.google-apps.document",
          modifiedTime: "2026-07-17T08:00:00Z",
        },
      ],
    }),
  ]);
  assert.equal(blocks.length, 2);
  assert.equal((blocks[0] as { type: string; provider: string }).type, "connector_result");
  assert.equal((blocks[0] as { provider: string }).provider, "calendar");
  const drive = blocks[1] as { rows: string[][] };
  assert.equal(drive.rows[0][1], "Doküman");
});

test("empty results, single-message reads, and failures yield no block", () => {
  assert.equal(buildConnectorResultBlocks([ok("gmail.search", { results: [] })]).length, 0);
  assert.equal(
    buildConnectorResultBlocks([ok("gmail.read", { subject: "x", body: "y" })]).length,
    0,
  );
  assert.equal(
    buildConnectorResultBlocks([
      { tool: "gmail.search", ok: false, permission: "read", durationMs: 1, output: null, error: { code: "connector_auth_required", message: "no" } },
    ]).length,
    0,
  );
});

test("remote MCP list-shaped connector outputs get a generic connector result block", () => {
  const blocks = buildConnectorResultBlocks([
    ok("github.list_repositories", {
      items: [
        {
          name: "elyan-backend",
          type: "repository",
          updated_at: "2026-07-18T10:00:00Z",
        },
      ],
    }),
    ok("notion.search", {
      results: [
        {
          title: "Roadmap",
          kind: "page",
          last_edited_time: "2026-07-17T09:00:00Z",
        },
      ],
    }),
  ]);
  assert.equal(blocks.length, 2);
  assert.equal((blocks[0] as { title?: string }).title, "GitHub sonuçları");
  assert.equal((blocks[1] as { title?: string }).title, "Notion sonuçları");
  assert.equal((blocks[0] as { type?: string }).type, "connector_result");
});

test("successful connector blocks survive a failed optional refinement pass", () => {
  const connectorBlocks = buildConnectorResultBlocks([
    ok("gmail.search", {
      results: [
        { from: "Ali <ali@example.com>", subject: "Toplantı" },
        { from: "Ayşe <ayse@example.com>", subject: "Fatura" },
      ],
    }),
  ]);
  const merged = mergeAuthoritativeConnectorResultBlocks(
    [
      { type: "text", markdown: "Maillerini inceliyorum." },
      { type: "table", columns: ["Konu"], rows: [["eski tekrar"]] },
    ],
    connectorBlocks,
  ) as Array<Record<string, unknown>>;

  assert.deepEqual(merged.map((block) => block.type), ["text", "table", "connector_result"]);
  assert.equal(
    (merged[2]?.items as unknown[]).length,
    2,
    "tool verisi refinement sonucundan bağımsız kalmalı",
  );
  assert.equal(connectorResultFallbackText(connectorBlocks), "Gelen kutusu — 2 e-posta");
});

test("non-list and empty connector successes have deterministic fallbacks", () => {
  assert.equal(
    connectorResultFallbackText([], [
      ok("gmail.read", {
        from: "Ali <ali@example.com>",
        subject: "Toplantı",
        body: "Yarın saat 10:00 için uygunum.",
      }),
    ]),
    "Toplantı — Ali\n\nYarın saat 10:00 için uygunum.",
  );
  assert.equal(
    connectorResultFallbackText([], [ok("gmail.search", { resultCount: 0, results: [] })]),
    "Gelen kutusunda eşleşen e-posta bulunamadı.",
  );
});
