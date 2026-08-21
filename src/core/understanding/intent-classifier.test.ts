import assert from "node:assert/strict";
import test from "node:test";
import { classifyIntent } from "./intent-classifier.js";

test("classifyIntent detects coding and local runtime hints deterministically", () => {
  const result = classifyIntent({
    userId: "user_1",
    message: "Fix this Flutter build error on my local desktop and run tests",
  });

  assert.equal(result.primaryIntent, "debugging");
  assert.equal(result.requiresLocalRuntime, true);
  assert.equal(result.routingHints.mode, "local_private");
  assert.equal(result.routingHints.avoidCloud, true);
});

test("classifyIntent carries a secondary computer surface into local routing", () => {
  const result = classifyIntent({
    userId: "user_1",
    message: "Masaüstümde kedi resmi çiz",
  });

  assert.equal(result.secondaryIntents.includes("computer"), true);
  assert.equal(result.requiresLocalRuntime, true);
});

test("classifyIntent marks research requests as retrieval and citation work", () => {
  const result = classifyIntent({
    userId: "user_1",
    message: "Research the latest Fastify auth pattern and cite sources",
  });

  assert.equal(result.primaryIntent, "research");
  assert.equal(result.requiresRetrieval, true);
  assert.equal(result.requiresCitation, true);
  assert.equal(result.routingHints.mode, "research");
});

test("classifyIntent treats self-referential identity questions as current-user memory retrieval", () => {
  for (const message of ["Ben kimim?", "Who am I?"]) {
    const result = classifyIntent({ userId: "user_1", message });

    assert.equal(result.primaryIntent, "chat");
    assert.equal(result.requiresRetrieval, true);
    assert.equal(result.requiresCitation, false);
    assert.equal(result.taskFrame.shouldClarify, false);
    assert.equal(result.reason, "user_identity_query");
  }
});

test("classifyIntent keeps explicit mobile context questions on server chat", () => {
  for (const message of [
    "Şu an neredeyim?",
    "Sağlık verilerim nedir?",
    "Takvimimde bugün ne var?",
  ]) {
    const result = classifyIntent({ userId: "user-1", message });
    assert.equal(result.primaryIntent, "chat", message);
    assert.equal(result.requiresLocalRuntime, false, message);
    assert.equal(result.taskFrame.shouldClarify, false, message);
    assert.match(result.reason, /^mobile_context_/u, message);
  }
});

test("classifyIntent recognizes Turkish document-reading prompts", () => {
  const result = classifyIntent({
    userId: "user_1",
    message: "Bu PDF'te ne yazıyor, profesyonelce özetle ve düzenli Türkçe ile yaz.",
  });

  assert.equal(result.primaryIntent, "document");
  assert.equal(result.requiresToolUse, true);
  assert.equal(result.routingHints.mode, "task");
  assert.equal(result.taskFrame.likelyAnswerShape, "read, transform, or export the document");
});

test("classifyIntent recognizes multilingual proofreading and grammar requests as writing work", () => {
  const turkish = classifyIntent({
    userId: "user_1",
    message: "Bu metnin imla, yazım ve noktalama hatalarını düzelt; anlamı değiştirme.",
  });
  const english = classifyIntent({
    userId: "user_1",
    message: "Proofread this paragraph, fix spelling and punctuation, and keep the original meaning.",
  });

  assert.equal(turkish.primaryIntent, "writing");
  assert.equal(turkish.taskFrame.likelyAnswerShape, "polished text with the requested tone");
  assert.equal(turkish.requiresLocalRuntime, false);
  assert.equal(english.primaryIntent, "writing");
  assert.equal(english.taskFrame.likelyAnswerShape, "polished text with the requested tone");
  assert.equal(english.requiresLocalRuntime, false);
});

test("classifyIntent recognizes Elyan ecosystem architecture prompts as deep planning work", () => {
  const result = classifyIntent({
    userId: "user_1",
    message: "Explain the Elyan ecosystem architecture and how desktop, backend, and mobile fit together",
  });

  assert.equal(result.primaryIntent, "planning");
  assert.equal(result.taskFrame.reasoningMode, "deep");
  assert.equal(result.taskFrame.shouldClarify, false);
  assert.equal(result.ecosystemHints.includes("elyan_ecosystem"), true);
  assert.equal(result.ecosystemHints.includes("desktop_runtime"), true);
  assert.equal(result.ecosystemHints.includes("backend_control_plane"), true);
});

test("classifyIntent recognizes Turkic language research prompts", () => {
  const result = classifyIntent({
    userId: "user_1",
    message: "Oğuz, Kıpçak ve Karluk dillerini araştır, karşılaştır ve Türk dünyası kaynaklarını incele.",
  });

  assert.equal(result.primaryIntent, "research");
  assert.equal(result.requiresCitation, true);
  assert.equal(result.ecosystemHints.includes("turkic_language_family"), true);
  assert.equal(result.routingHints.mode, "research");
});

test("classifyIntent fails open for empty chat-like input", () => {
  const result = classifyIntent({
    userId: "user_1",
    message: "",
  });

  assert.equal(result.primaryIntent, "unknown");
  assert.equal(result.requiresToolUse, false);
});

test("classifyIntent does not misclassify Turkish 'bugün' as debugging", () => {
  const result = classifyIntent({ userId: "user_1", message: "nasılsın bugün" });
  assert.equal(result.primaryIntent, "chat");
});

test("classifyIntent recognizes Turkish step program requests as planning", () => {
  const result = classifyIntent({
    userId: "user_1",
    message: "5 adımlık Teknofest hazırlık programı çıkar",
  });
  assert.equal(result.primaryIntent, "planning");
});

test("classifyIntent gives a compound roadmap request a planning primary intent", () => {
  const result = classifyIntent({
    userId: "user_1",
    message: "Bu hedef için bir plan oluştur, doktor olmak istiyorum ama matematik bölümündeyim",
  });

  assert.equal(result.primaryIntent, "planning");
  assert.equal(result.secondaryIntents.includes("math"), true);
  assert.equal(result.requiresToolUse, false);
});

test("classifyIntent keeps a direct math solve out of planning", () => {
  const result = classifyIntent({
    userId: "user_1",
    message: "Bu matematik sorusunu çöz",
  });

  assert.equal(result.primaryIntent, "math");
  assert.equal(result.secondaryIntents.includes("planning"), false);
});

test("classifyIntent recognizes a subject-specific weekly plan", () => {
  const result = classifyIntent({
    userId: "user_1",
    message: "Matematik çalışmak için haftalık plan çıkar",
  });

  assert.equal(result.primaryIntent, "planning");
  assert.equal(result.secondaryIntents.includes("math"), true);
});

test("classifyIntent keeps brief architecture explanations out of local planning", () => {
  const result = classifyIntent({
    userId: "user_1",
    message: "Kısaca özetle: local-first mimari neden önemli?",
  });
  assert.notEqual(result.primaryIntent, "planning");
  assert.equal(result.requiresLocalRuntime, false);
});

test("classifyIntent recovers intent semantically when no regex rule matches", () => {
  // Lexically overlaps the planning seed phrases without hitting a planning regex.
  const result = classifyIntent({
    userId: "user_1",
    message: "bunu adımlara böl ve bir yol planı çıkar",
  });
  assert.equal(result.primaryIntent, "planning");
  assert.match(result.reason, /^(matched_planning_rules|semantic_planning)$/);
});

test("classifyIntent uses semantic subject intent for debugging and advanced math prompts", () => {
  const debugging = classifyIntent({
    userId: "user_1",
    message: "Bu fonksiyon neden yanlış sonuç veriyor: `return total / items.length`",
  });
  const math = classifyIntent({
    userId: "user_1",
    message: "Bana ileri analiz dersinden örnek soru yaz",
  });

  assert.equal(debugging.primaryIntent, "debugging");
  assert.equal(math.primaryIntent, "math");
  assert.equal(math.secondaryIntents.includes("writing"), true);
});
