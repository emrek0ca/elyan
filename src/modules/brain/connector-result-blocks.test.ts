import { strict as assert } from "node:assert";
import { test } from "node:test";
import { buildConnectorResultBlocks } from "./connector-result-blocks.js";
import type { AgentToolResult } from "./tool-registry.js";

function ok(tool: string, output: Record<string, unknown>): AgentToolResult {
  return { tool, ok: true, permission: "read", durationMs: 1, output, error: null };
}

test("gmail.search results become a table block with sender/subject/date", () => {
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
  const block = blocks[0] as { type: string; columns: string[]; rows: string[][] };
  assert.equal(block.type, "table");
  assert.deepEqual(block.columns, ["Kimden", "Konu", "Tarih"]);
  assert.equal(block.rows[0][0], "Ali Veli");
  assert.equal(block.rows[0][1], "Toplantı");
});

test("calendar and drive list results each become a table block", () => {
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
  assert.equal((blocks[0] as { type: string }).type, "table");
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
