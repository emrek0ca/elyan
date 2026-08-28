import assert from "node:assert/strict";
import test from "node:test";
import {
  buildGeminiFreePublicOperationFrame,
  featureBudgetLimit,
} from "./gemini-free-tier-guard.js";

test("Gemini free public frame allows public Turkish news requests", () => {
  assert.equal(
    buildGeminiFreePublicOperationFrame("Türkiye'nin ekonomisi hakkındaki haberler"),
    "Türkiye'nin ekonomisi hakkındaki haberler",
  );
});

test("Gemini free public frame blocks private Turkish account requests", () => {
  assert.equal(buildGeminiFreePublicOperationFrame("Son 3 mailim nedir"), null);
  assert.equal(
    buildGeminiFreePublicOperationFrame("Bağlı hesabımdaki son mailleri göster"),
    null,
  );
});

test("the fabrication gate is not rationed like an optional feature", () => {
  // ÖLÇÜLEN ARIZA (2026-08-28): `execution_validate` günlük istek bütçesinin
  // %10'unu alıyordu — limit 200 iken GÜNDE 20 ÇAĞRI. Yirmi birinci eylem
  // iddiasından sonra uydurma kapısı günün geri kalanında kapalı kalıyor ve
  // kullanıcı masaüstü bağlı değilken "Hatırlatıcı eklendi" cevabı alıyordu.
  const total = 200;
  assert.equal(featureBudgetLimit(total, "execution_validate"), total);

  // Diğer özelliklerin payları korunuyor — bu bir muafiyet, tavanın
  // kaldırılması değil.
  assert.ok(featureBudgetLimit(total, "intent_route") < total);
  assert.ok(featureBudgetLimit(total, "brain_response") < total);
  assert.ok(featureBudgetLimit(total, "accessibility") < total);
});
