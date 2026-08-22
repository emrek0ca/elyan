import assert from "node:assert/strict";
import test from "node:test";
import { needsLiveResearch } from "./knowledge-recency.js";

// ---------------------------------------------------------------------------
// ŞÜPHEDE HIZLI YOL.
//
// Kullanıcının önceliği açıkça şuydu: "en hızlı ve en doğru yolu kullanmalıyız".
// Araştırma pahalı ve kırılgan; modelin bildiği bir konuda gereksiz araştırma
// yalnız bekletir. Karar verilemediğinde model bilgisiyle devam edilir.
//
// Ters yön (canlı veri gerekirken model bilgisi) UYDURMA riskidir ve ölçüm
// kapısında ayrı sayılır: `npm run eval:knowledge-recency`
// (korpus 100% → tutulan 94.4%, uydurma riski 0).
// ---------------------------------------------------------------------------

test("karar yoksa canlı araştırma tetiklenmez", () => {
  assert.equal(needsLiveResearch(null), false);
  assert.equal(needsLiveResearch(undefined), false);
});

test("yalnız current_facts canlı araştırma açar", () => {
  assert.equal(
    needsLiveResearch({ recency: "current_facts", score: 0.9, margin: 0.1 }),
    true,
  );
  assert.equal(
    needsLiveResearch({ recency: "stable_knowledge", score: 0.9, margin: 0.1 }),
    false,
  );
});
