import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  isDesktopPlanMachineJsonRoute,
  isPlainProseGenerationRoute,
} from "./inference.js";

// ---------------------------------------------------------------------------
// CANLI ARIZA (görev 907dbd2d, 2026-08-22 15:00 — "zürafalar hakkında rapor").
//
// Belge gövdesini üreten çağrı DÜZ METİN ister, ama `ELYAN_TURN_ENVELOPE_ENABLED`
// canlıda açık olduğu için `json_object` formatına zorlanıyordu:
//   groq/compound      → provider_error:400   (json_object desteklemiyor)
//   openai/gpt-oss-20b → json_validate_failed (model düzyazı yazdı)
//   openai/gpt-oss-20b → empty_response ×2
// Sonuç: "writer content generation failed" ve belgeye yine 46 kelimelik brief.
// ---------------------------------------------------------------------------

test("yazıcı içerik rotası düz metin sayılır", () => {
  assert.equal(isPlainProseGenerationRoute("desktop_writer_content"), true);
});

test("plan rotaları düz metin DEĞİLDİR", () => {
  for (const route of [
    "desktop_plan_materialize",
    "desktop_plan_transport_repair",
    "desktop_plan_critique",
  ]) {
    assert.equal(isPlainProseGenerationRoute(route), false, route);
    assert.equal(isDesktopPlanMachineJsonRoute(route), true, route);
  }
});

test("sohbet rotası düz metin rotası değildir", () => {
  assert.equal(isPlainProseGenerationRoute("shared_brain"), false);
  assert.equal(isPlainProseGenerationRoute(undefined), false);
});

test("zarf kapısı düz metin turunu dışlar", () => {
  // Kaynak-düzeyi kilit: kapı bir daha sessizce kaldırılmasın.
  const source = readFileSync(
    new URL("./inference.ts", import.meta.url).pathname.replace(/\/dist\//, "/src/"),
    "utf8",
  );
  const guard = source.indexOf("const turnEnvelopeEnabled =");
  assert.ok(guard > -1);
  const body = source.slice(guard, guard + 400);
  assert.ok(
    body.includes("!plainProseTurn"),
    "zarf kapısı düz metin turunu dışlamıyor",
  );
});
