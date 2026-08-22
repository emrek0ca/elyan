import assert from "node:assert/strict";
import test from "node:test";
import {
  TOOL_SUCCESS_MIN_OBSERVATIONS,
  estimateToolSuccess,
} from "./tool-success-model.js";

// ---------------------------------------------------------------------------
// P(success | task, tool, context) — deneyimden araç başarısı.
//
// İlk hâli sinir ağı DEĞİL, sayım. Sebep: bugün elde 60 görev var. Az veriyle
// model eğitmek, veriyi ezberleyip kendinden emin yanlışlar üretmektir — bu
// projede "tahmin sert sözleşmeye dönüşüyor" hata sınıfı defalarca tekrarlandı.
//
// BELİRSİZLİK GİZLENMEZ: eşik altındaysa `null`. "Veri yok" ile "%50 ihtimal"
// asla aynı şey değildir.
// ---------------------------------------------------------------------------

function fakeApp(rows: Array<{ total: number; scoreSum: number }>) {
  let call = 0;
  return {
    log: { warn: () => {} },
    db: {
      select: () => ({
        from: () => ({
          where: () => Promise.resolve([rows[Math.min(call++, rows.length - 1)]]),
        }),
      }),
    },
  } as never;
}

test("gözlem eşiğin altındaysa tahmin YOK", async () => {
  const estimate = await estimateToolSuccess(fakeApp([{ total: 2, scoreSum: 200 }]), {
    userId: "u",
    tool: "document_write",
  });
  assert.equal(estimate, null);
});

test("yeterli gözlemde olasılık üretilir", async () => {
  const estimate = await estimateToolSuccess(
    fakeApp([{ total: 10, scoreSum: 1000 }]),
    { userId: "u", tool: "document_write" },
  );
  assert.ok(estimate);
  assert.equal(estimate?.observations, 10);
  // 10 gözlemin hepsi tam puan → olasılık yüksek ama 1.0 DEĞİL (Laplace).
  assert.ok((estimate?.probability ?? 0) > 0.9);
  assert.ok((estimate?.probability ?? 1) < 1);
});

test("tek başarısızlık aracı sıfırlamaz", async () => {
  // 10 çağrının 9'u tam, 1'i sıfır.
  const estimate = await estimateToolSuccess(
    fakeApp([{ total: 10, scoreSum: 900 }]),
    { userId: "u", tool: "open_app" },
  );
  assert.ok((estimate?.probability ?? 0) > 0.7);
});

test("hep başarısız araç düşük olasılık alır", async () => {
  const estimate = await estimateToolSuccess(fakeApp([{ total: 8, scoreSum: 0 }]), {
    userId: "u",
    tool: "shell_run",
  });
  assert.ok(estimate);
  assert.ok((estimate?.probability ?? 1) < 0.2);
});

test("bağlam kademeli gevşer ve temeli bildirilir", async () => {
  // tam bağlam yetersiz → araç+niyet yetersiz → yalnız araç yeterli
  const estimate = await estimateToolSuccess(
    fakeApp([
      { total: 1, scoreSum: 100 },
      { total: 3, scoreSum: 300 },
      { total: 12, scoreSum: 900 },
    ]),
    { userId: "u", tool: "document_write", intentKind: "document_task", device: "desktop" },
  );
  assert.equal(estimate?.basis, "tool");
  assert.equal(estimate?.observations, 12);
});

test("eşik makul", () => {
  assert.ok(TOOL_SUCCESS_MIN_OBSERVATIONS >= 5);
});
