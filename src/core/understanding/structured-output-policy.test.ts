import assert from "node:assert/strict";
import test from "node:test";
import {
  decideStructuredResponseDecision,
  isExplicitTableRequest,
  isPlanOrStepRequest,
  requestsChartOutput,
  requestsTableOutput,
} from "./structured-output-policy.js";

test("decideStructuredResponseDecision defaults ordinary explanation prompts to prose", () => {
  const decision = decideStructuredResponseDecision({
    prompt: "Turk matematikcileri kisaca anlat",
  });

  assert.equal(isExplicitTableRequest("Turk matematikcileri kisaca anlat"), false);
  assert.equal(decision.primaryShape, "prose");
  assert.equal(decision.primaryBlockType, "text");
  assert.equal(decision.tablePolicy, "forbidden");
});

test("decideStructuredResponseDecision selects the requested widget shape only when explicit", () => {
  assert.equal(
    decideStructuredResponseDecision({ prompt: "Gelir gider verisini tablo olarak ver" }).primaryBlockType,
    "table",
  );
  assert.equal(
    decideStructuredResponseDecision({ prompt: "2020-2025 gelir gider cizgi grafik olustur" }).primaryBlockType,
    "chart",
  );
  assert.equal(
    decideStructuredResponseDecision({ prompt: "Ucgen icin sade SVG geometrik cizim olustur" }).primaryBlockType,
    "svg",
  );
  assert.equal(
    decideStructuredResponseDecision({ prompt: "x^2 fonksiyonunun turevini LaTeX ile ver" }).primaryBlockType,
    "math",
  );
});

test("decideStructuredResponseDecision allows proactive visuals on an ordinary non-explicit prompt", () => {
  // No explicit widget word and no plain-prose preference → the model may
  // proactively emit ONE widget when the answer content warrants it.
  const decision = decideStructuredResponseDecision({
    prompt: "Dunyanin en yuksek bes dagini ve yuksekliklerini soyle",
  });

  assert.equal(decision.primaryBlockType, "text");
  assert.equal(decision.widgetPolicy, "proactive_optional");
  assert.equal(decision.reasons.includes("proactive_visuals_allowed"), true);
});

test("decideStructuredResponseDecision stays prose-only when the user asks for plain text", () => {
  const decision = decideStructuredResponseDecision({
    prompt: "Bunu sadece duz yazi olarak anlat, tablo kullanma",
  });

  assert.equal(isExplicitTableRequest("Bunu sadece duz yazi olarak anlat, tablo kullanma"), false);
  assert.equal(decision.primaryBlockType, "text");
  assert.equal(decision.widgetPolicy, "none");
  assert.equal(decision.reasons.includes("explicit_prose_preference"), true);
});

test("decideStructuredResponseDecision respects explicit no-table comparison requests", () => {
  const prompt = "ios ve android geliştirmeyi karşılaştır ama tablo yapma";
  const decision = decideStructuredResponseDecision({ prompt });

  assert.equal(isExplicitTableRequest(prompt), false);
  assert.equal(decision.primaryShape, "prose");
  assert.equal(decision.primaryBlockType, "text");
  assert.equal(decision.tablePolicy, "forbidden");
  assert.equal(decision.widgetPolicy, "none");
});

test("decideStructuredResponseDecision keeps a brief-explanation prompt as prose-only", () => {
  // "kisaca anlat" signals the user wants a short prose answer, not a widget.
  const decision = decideStructuredResponseDecision({
    prompt: "Turk matematikcileri kisaca anlat",
  });

  assert.equal(decision.widgetPolicy, "none");
});

test("decideStructuredResponseDecision keeps summary prompts prose-only", () => {
  const decision = decideStructuredResponseDecision({
    prompt: "Bu metni kısa bir özet halinde yaz",
  });

  assert.equal(decision.primaryShape, "prose");
  assert.equal(decision.primaryBlockType, "text");
  assert.equal(decision.tablePolicy, "forbidden");
  assert.equal(decision.widgetPolicy, "none");
});

test("decideStructuredResponseDecision respects explicit no-chart prose requests", () => {
  const decision = decideStructuredResponseDecision({
    prompt: "Bunu düz yazı olarak anlat, grafik istemiyorum",
  });

  assert.equal(decision.primaryShape, "prose");
  assert.equal(decision.primaryBlockType, "text");
  assert.equal(decision.widgetPolicy, "none");
});

test("decideStructuredResponseDecision keeps planning prompts out of table widgets", () => {
  const decision = decideStructuredResponseDecision({
    prompt: "Bana 5 adımlık Teknofest çalışma planı çıkar",
    selectedWorkload: "planning",
  });

  assert.equal(isExplicitTableRequest("Bana 5 adımlık Teknofest çalışma planı çıkar"), false);
  assert.equal(isPlanOrStepRequest("Bana 5 adımlık Teknofest çalışma planı çıkar"), true);
  assert.equal(decision.primaryShape, "list");
  assert.equal(decision.primaryBlockType, "text");
  assert.equal(decision.tablePolicy, "forbidden");
  assert.equal(decision.widgetPolicy, "none");
  assert.equal(decision.reasons.includes("plan_request_prefers_list"), true);
});

test("decideStructuredResponseDecision still allows explicit table plans", () => {
  const decision = decideStructuredResponseDecision({
    prompt: "5 adımlık Teknofest çalışma planını tablo olarak ver",
    selectedWorkload: "planning",
  });

  assert.equal(isExplicitTableRequest("5 adımlık Teknofest çalışma planını tablo olarak ver"), true);
  assert.equal(decision.primaryBlockType, "table");
  assert.equal(decision.widgetPolicy, "single_primary_widget");
});

// --- Tek karar noktası (requestsTableOutput / requestsChartOutput) ---
//
// Bu testler ölçülmüş davranışı sabitliyor. `understanding-envelope` ve
// `web-grounding` daha önce ham `isExplicit*` çağırdığı için aynı turda
// widget kararıyla çelişiyorlardı; sözleşme tek yere toplandı.
//
// NOT: e5 ısıtması olmadan semantik yol hash prototipine düşer. Buradaki
// parafrazlar bilinçli olarak hash'in YAKALADIĞI kümeden seçildi ki test
// model indirmesine bağlı olmasın.

test("requestsTableOutput kelime listesini ve parafrazı birlikte kapsar", () => {
  // Kelime listesi yolu
  assert.equal(requestsTableOutput("Gelir gider verisini tablo olarak ver"), true);
  // Parafraz: hiçbir tablo kelimesi yok
  assert.equal(isExplicitTableRequest("her birinin fiyatını ve özelliğini düzenli göster"), false);
  assert.equal(requestsTableOutput("her birinin fiyatını ve özelliğini düzenli göster"), true);
});

test("requestsTableOutput olumsuzlamada ve düz yazı tercihinde semantiğe sormaz", () => {
  assert.equal(requestsTableOutput("tablo istemiyorum düz yazı olsun"), false);
  assert.equal(requestsTableOutput("bunu bana kısaca açıkla"), false);
  assert.equal(requestsTableOutput(""), false);
});

test("requestsChartOutput kelime listesini ve parafrazı birlikte kapsar", () => {
  assert.equal(requestsChartOutput("grafiğini çiz"), true);
  // Parafraz: "grafik/chart/plot/çiz" kelimelerinin hiçbiri yok
  assert.equal(requestsChartOutput("nasıl bir eğri çıkıyor bunun"), true);
  assert.equal(requestsChartOutput("zamana göre nasıl değiştiğini göster"), true);
});

test("requestsChartOutput olumsuzlamada ve sıradan sohbette kapalı", () => {
  assert.equal(requestsChartOutput("grafik olmasın lütfen"), false);
  assert.equal(requestsChartOutput("nasılsın bugün"), false);
  assert.equal(requestsChartOutput(""), false);
});

test("requestsChartOutput 3B yüzey isteğini de grafik ailesinde sayar", () => {
  // Yüzey istekleri dışarıdan veri gerekliliği açısından grafikle aynı
  // sözleşmeye tabi; `web-grounding` bunu ayrı ele alırsa tur veri
  // aranmadan reddediliyordu.
  assert.equal(requestsChartOutput("z = f(x, y) yüzeyini 3 boyutlu çiz"), true);
});
