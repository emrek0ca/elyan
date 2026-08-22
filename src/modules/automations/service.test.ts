import assert from "node:assert/strict";
import test from "node:test";
import {
  canSettleAutomationTask,
  isAutomationCapabilitySafe,
  nextAutomationRunAt,
} from "./service.js";
import {
  automationIntervalMinutesValues,
  createAutomationBodySchema,
} from "./schemas.js";

test("otomasyon yalnız yan etkisiz ve kayıtlı okuma yeteneklerini kabul eder", () => {
  assert.equal(isAutomationCapabilitySafe("desktop_os.status"), true);
  assert.equal(isAutomationCapabilitySafe("system.capabilities"), true);
  assert.equal(isAutomationCapabilitySafe("web.search"), true);
  assert.equal(isAutomationCapabilitySafe("file_write"), false);
  assert.equal(isAutomationCapabilitySafe("browser.navigate"), false);
  assert.equal(isAutomationCapabilitySafe("mcp.remote_read"), false);
  assert.equal(isAutomationCapabilitySafe("  "), false);
});

test("kaçırılmış otomasyon tikleri tek sonraki gelecekteki çalışmaya ilerler", () => {
  const next = nextAutomationRunAt({
    scheduledAt: new Date("2026-08-23T08:00:00.000Z"),
    now: new Date("2026-08-23T10:31:00.000Z"),
    intervalMinutes: 60,
  });
  assert.equal(next.toISOString(), "2026-08-23T11:00:00.000Z");
});

test("çok hızlı child task dispatch satırından önce settle olursa kaybolmaz", () => {
  assert.equal(
    canSettleAutomationTask({ lastTaskId: null, taskId: "child-1" }),
    true,
  );
  assert.equal(
    canSettleAutomationTask({ lastTaskId: "child-1", taskId: "child-1" }),
    true,
  );
  assert.equal(
    canSettleAutomationTask({ lastTaskId: "child-2", taskId: "child-1" }),
    false,
  );
});

test("otomasyon sözleşmesi yalnız desteklenen aralıkları ve güvenli başlangıcı parse eder", () => {
  const parsed = createAutomationBodySchema.parse({
    sourceTaskId: "11111111-1111-4111-8111-111111111111",
    intervalMinutes: 60,
  });
  assert.equal(parsed.timezone, "Europe/Istanbul");
  assert.deepEqual(automationIntervalMinutesValues, [15, 60, 360, 720, 1440, 10080]);
  assert.throws(() =>
    createAutomationBodySchema.parse({
      sourceTaskId: "11111111-1111-4111-8111-111111111111",
      intervalMinutes: 10,
    }),
  );
});
