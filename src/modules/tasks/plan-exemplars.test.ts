import test from "node:test";
import assert from "node:assert/strict";
import {
  renderPlanExemplars,
  selectPlanExemplars,
  type PlanExemplar,
} from "./plan-exemplars.js";

// Sahte db. Kullanıcı kapsamının gerçekten uygulandığı, aşağıdaki "kapsam
// olmadan sorgu yapılmaz" testiyle doğrulanıyor: orada select() çağrılırsa
// test kırılıyor.
function fakeApp(rows: unknown[]) {
  const chain = {
    from() {
      return chain;
    },
    where() {
      return chain;
    },
    orderBy() {
      return chain;
    },
    async limit() {
      return rows;
    },
  };
  return {
    db: {
      select() {
        return chain;
      },
    },
    log: { warn() {}, info() {}, debug() {} },
  } as never;
}

test("plan exemplars refuse to run without a user scope", async () => {
  // Gizlilik sözleşmesi: kullanıcı kimliği yoksa hiçbir geçmiş okunmaz.
  // Boş userId ile db'ye HİÇ gidilmemeli.
  let queried = false;
  const app = {
    db: {
      select() {
        queried = true;
        throw new Error("kullanıcı kapsamı olmadan sorgu yapılmamalı");
      },
    },
    log: { warn() {}, info() {}, debug() {} },
  } as never;

  assert.deepEqual(
    await selectPlanExemplars(app, { userId: "", query: "Chrome'u kapat" }),
    [],
  );
  assert.deepEqual(
    await selectPlanExemplars(app, { userId: "   ", query: "Chrome'u kapat" }),
    [],
  );
  assert.equal(queried, false);
});

test("plan exemplars ignore history rows without a usable prompt or plan", async () => {
  // Embedder testte yok; bu yüzden sonuç boş döner. Ölçtüğümüz şey, eksik
  // kayıtların sessizce elenmesi ve hiçbir koşulda patlamaması.
  const app = fakeApp([
    { payload: { prompt: "", planPreview: { steps: [] } } },
    { payload: { planPreview: { steps: [{ capability: "close_app" }] } } },
    { payload: { prompt: "Chrome'u kapat" } },
    { payload: null },
  ]);
  assert.deepEqual(
    await selectPlanExemplars(app, {
      userId: "user-1",
      query: "tarayıcıyı kapat",
    }),
    [],
  );
});

test("plan exemplars render as evidence, not as a template to copy", () => {
  const exemplars: PlanExemplar[] = [
    { prompt: "Chrome'u kapat", capabilities: ["close_app"], similarity: 0.94 },
    {
      prompt: "masaüstüne rapor hazırla",
      capabilities: ["web_research", "document_write"],
      similarity: 0.88,
    },
  ];
  const rendered = renderPlanExemplars(exemplars);
  assert.match(rendered, /THIS SAME USER/u);
  assert.match(rendered, /not as a template to copy blindly/u);
  assert.match(rendered, /"Chrome'u kapat" → close_app/u);
  assert.match(rendered, /web_research → document_write/u);
});

test("plan exemplars render to nothing when the user has no history", () => {
  // Boş metin, planlama istemini hiç değiştirmemeli.
  assert.equal(renderPlanExemplars([]), "");
});
