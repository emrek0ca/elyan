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
    {
      prompt: "Chrome'u kapat",
      capabilities: ["close_app"],
      similarity: 0.94,
      outcome: "succeeded",
    },
    {
      prompt: "masaüstüne rapor hazırla",
      capabilities: ["web_research", "document_write"],
      similarity: 0.88,
      outcome: "succeeded",
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

test("failed attempts are shown as warnings, clearly separated from successes", () => {
  // Yalnız başarıları göstermek öğrenmenin yarısı. Ama başarısızlık örneği
  // başarıyla aynı bölümde görünürse model onu taklit edilecek bir çözüm
  // sanabilir — ayrım metnin kendisinde net olmalı.
  const rendered = renderPlanExemplars([
    {
      prompt: "Chrome'u kapat",
      capabilities: ["close_app"],
      similarity: 0.94,
      outcome: "succeeded",
    },
    {
      prompt: "chrome sekmesini kapat",
      capabilities: ["browser_control"],
      similarity: 0.9,
      outcome: "failed",
      failureReason: "Geçersiz tarayıcı eylemi.",
    },
  ]);
  assert.match(rendered, /PREVIOUSLY SUCCESSFUL PLANS/u);
  assert.match(rendered, /PREVIOUSLY FAILED ATTEMPTS/u);
  assert.match(rendered, /These chains did NOT work/u);
  assert.match(rendered, /failed: Geçersiz tarayıcı eylemi\./u);
  // Başarı bölümü önce gelmeli: örnek önce ne YAPILACAĞINI öğretir.
  assert.ok(
    rendered.indexOf("PREVIOUSLY SUCCESSFUL") <
      rendered.indexOf("PREVIOUSLY FAILED"),
  );
});

test("a history of only failures still renders without a misleading success header", () => {
  const rendered = renderPlanExemplars([
    {
      prompt: "sekmeyi kapat",
      capabilities: ["browser_control"],
      similarity: 0.9,
      outcome: "failed",
    },
  ]);
  assert.doesNotMatch(rendered, /PREVIOUSLY SUCCESSFUL/u);
  assert.match(rendered, /PREVIOUSLY FAILED ATTEMPTS/u);
});
