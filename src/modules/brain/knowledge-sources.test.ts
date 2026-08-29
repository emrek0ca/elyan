import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";
import { resetKnowledgeCacheForTests } from "./knowledge-cache.js";
import { probeTypedKnowledgeSources } from "./knowledge-sources.js";
import { resetFactSelectionForTests } from "../facts/select.js";

beforeEach(() => {
  resetKnowledgeCacheForTests();
  resetFactSelectionForTests();
});

/**
 * Yoklama, hiçbir tipli kaynak eşleşmediğinde de TURU DÜŞÜRMEZ: boş kısa
 * liste geçerli bir cevaptır ve yönlendirici oradan korpusa/web'e devam eder.
 * `app` verilmediğinde Redis katmanı yoktur; süreç-içi katman tek başına
 * çalışmalıdır (işçi ve test yolları böyle koşuyor).
 */
test("a probe with no typed match returns an empty shortlist without failing", async () => {
  const probe = await probeTypedKnowledgeSources(null, {
    query: "Elyan masaüstü ne işe yarar?",
    probeCorpus: true,
  });
  assert.deepEqual(probe.providerShortlist, []);
  assert.equal(probe.cacheState, "miss");
});

/**
 * SIK SORULAN SORUNUN BEDELİ BİR KEZ ÖDENİR. İkinci tur ne gömme ne de
 * seçim çalıştırır; karar önbellekten gelir. Önbelleğe giren şey KARARDIR
 * (sağlayıcı kimlikleri, korpus alanları) — sağlayıcının döndürdüğü değişken
 * veri değil; onun tazelik penceresi `facts/cache.ts` içindedir.
 */
test("a completed probe caches its decision for the repeat question", async () => {
  const first = await probeTypedKnowledgeSources(null, {
    query: "Bugün dolar kaç TL?",
    probeCorpus: false,
  });
  const second = await probeTypedKnowledgeSources(null, {
    query: "  bugun   DOLAR kac tl? ",
    probeCorpus: false,
  });
  assert.equal(first.cacheState, "miss");
  assert.equal(second.cacheState, "hit");
  assert.deepEqual(
    second.providerShortlist.map((entry) => entry.provider.id),
    first.providerShortlist.map((entry) => entry.provider.id),
  );
  // Önbellek isabetinde bu turda gömme YAPILMAZ; aşağı akış `undefined`
  // görür ve gerçekten ihtiyaç duyarsa kendi vektörünü hesaplar.
  assert.equal(second.queryVector, undefined);
});

test("concurrent identical probes share one selection pass", async () => {
  const [a, b] = await Promise.all([
    probeTypedKnowledgeSources(null, { query: "Euro kaç TL?", probeCorpus: false }),
    probeTypedKnowledgeSources(null, { query: "Euro kaç TL?", probeCorpus: false }),
  ]);
  assert.deepEqual(a.providerShortlist, b.providerShortlist);
});
