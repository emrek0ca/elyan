import assert from "node:assert/strict";
import test from "node:test";
import { normalizeMaterializedSteps } from "./materialize-plan.js";

// ---------------------------------------------------------------------------
// CANLI ARIZA (görev abeb6d44, 2026-08-22 15:44).
//
// Model DOĞRU ve çok adımlı bir plan üretti, JSON da geçerliydi
// (jsonObjectFound: true) — ama zarfı `{"plan":[...]}` diye adlandırdı.
// Ayrıştırıcı yalnız `steps` anahtarına bakıyordu; parsedStepCount null oldu,
// onarım aynı duvara tosladı ve kullanıcı şunu gördü:
//   "Görevin güvenilir yürütme planı hazırlanamadı."
//
// Katı json_schema gpt-oss'ta çalışmıyor, yani zarf adı sağlayıcı düzeyinde
// garanti edilemiyor. Bir eş anlamlı yüzünden doğru planı çöpe atmak,
// kırılganlığı kullanıcıya fatura etmektir.
// ---------------------------------------------------------------------------

const ALLOWED = ["web_research", "document_write", "text_analyze"];

test("canlı arızadaki `plan` zarfı kabul edilir", () => {
  const steps = normalizeMaterializedSteps(
    {
      plan: [
        {
          id: "web_research_giraffe",
          capability: "web_research",
          args: { query: "zürafa biyolojisi" },
          output: "research_summary",
        },
        {
          id: "write",
          capability: "document_write",
          args: { prompt: "{{steps.web_research_giraffe.output}}" },
        },
      ],
    },
    ALLOWED,
  );
  assert.equal(steps?.length, 2);
  assert.equal(steps?.[0].capability, "web_research");
  assert.deepEqual(steps?.[1].dependsOn, ["web_research_giraffe"]);
});

test("steps/actions/tasks zarfları da kabul edilir", () => {
  for (const key of ["steps", "actions", "tasks", "planSteps"]) {
    const steps = normalizeMaterializedSteps(
      { [key]: [{ id: "s1", capability: "document_write", args: {} }] },
      ALLOWED,
    );
    assert.equal(steps?.length, 1, key);
  }
});

test("sarmalanmış zarf da bulunur", () => {
  const steps = normalizeMaterializedSteps(
    { result: { steps: [{ id: "s1", capability: "document_write", args: {} }] } },
    ALLOWED,
  );
  assert.equal(steps?.length, 1);
});

test("adım alan adları için eş anlamlılar", () => {
  const steps = normalizeMaterializedSteps(
    {
      steps: [
        {
          id: "s1",
          tool: "document_write",
          arguments: { title: "Rapor" },
          label: "Belgeyi yaz",
        },
      ],
    },
    ALLOWED,
  );
  assert.equal(steps?.[0].capability, "document_write");
  assert.deepEqual(steps?.[0].args, { title: "Rapor" });
  assert.equal(steps?.[0].description, "Belgeyi yaz");
});

test("tolerans YAPIYI gevşetmez", () => {
  // Katalog dışı yetenek hâlâ elenir; zarf toleransı güvenlik kapısı değildir.
  assert.equal(
    normalizeMaterializedSteps(
      { plan: [{ id: "s1", capability: "shell_run", args: {} }] },
      ALLOWED,
    ),
    null,
  );
  assert.equal(normalizeMaterializedSteps({ plan: [] }, ALLOWED), null);
  assert.equal(normalizeMaterializedSteps(null, ALLOWED), null);
});
