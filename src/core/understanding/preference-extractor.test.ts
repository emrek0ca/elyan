import assert from "node:assert/strict";
import test from "node:test";
import { extractFeedbackSignals, extractPreferenceSignals } from "./preference-extractor.js";

test("extractPreferenceSignals captures stable language, stack, and boundary preferences", () => {
  const result = extractPreferenceSignals({
    userId: "user_1",
    title: "Elyan backend",
    message: "Mevcut Fastify ve Postgres yapisini bozma, kisa ve teknik ilerle.",
    intent: "coding",
  });

  assert.ok(result.signals.some((signal) => signal.key === "preferred_language" && signal.value === "Turkish"));
  assert.ok(result.signals.some((signal) => signal.key === "stack" && signal.value === "fastify"));
  assert.ok(result.signals.some((signal) => signal.key === "implementation_boundary"));
});

test("extractPreferenceSignals still detects Turkish preference without diacritics", () => {
  const result = extractPreferenceSignals({
    userId: "user_1",
    message: "Merhaba Elyan, bunu daha profesyonel ve kisa yaz.",
    intent: "writing",
  });

  assert.ok(result.signals.some((signal) => signal.key === "preferred_language" && signal.value === "Turkish"));
});

test("extractPreferenceSignals captures Turkic family language preference", () => {
  const result = extractPreferenceSignals({
    userId: "user_1",
    message: "Oğuz, Kıpçak ve Karluk dillerini araştır ve Türk dünyası kaynaklarını karşılaştır.",
    intent: "research",
  });

  assert.ok(result.signals.some((signal) => signal.key === "preferred_language" && signal.value === "Turkic"));
});

test("extractPreferenceSignals does not persist private local paths", () => {
  const result = extractPreferenceSignals({
    userId: "user_1",
    message: "project: /Users/emre/Desktop/private keep this path",
  });

  assert.equal(result.signals.some((signal) => signal.value.includes("/Users/")), false);
});

test("extractFeedbackSignals converts bounded feedback into learning signals", () => {
  const result = extractFeedbackSignals({
    feedbackType: "user_correction",
    correction: "Answer shorter and in Turkish next time.",
  });

  assert.ok(result.signals.some((signal) => signal.key === "feedback_style"));
});

test("extractFeedbackSignals converts compact reason tags into safe quality signals", () => {
  const result = extractFeedbackSignals({
    feedbackType: "thumbs_down",
    taskId: "task_feedback_1",
    reasonTags: ["too_long", "not_warm_enough", "too_playful"],
  });

  assert.ok(result.signals.some((signal) => signal.key === "brevity_preference" && signal.value === "short"));
  assert.ok(
    result.signals.some(
      (signal) =>
        signal.key === "answer_length" &&
        signal.value === "concise" &&
        signal.metadata?.explicit === true &&
        signal.metadata?.sourceTurnId === "task_feedback_1",
    ),
  );
  assert.ok(result.signals.some((signal) => signal.key === "preferred_tone" && signal.value === "warm_professional"));
  assert.ok(result.signals.some((signal) => signal.key === "humor_level" && signal.value === "restrained"));
});

test("extractPreferenceSignals reads mobile response style metadata safely", () => {
  const result = extractPreferenceSignals({
    userId: "user_1",
    message: "Sunucudaki Elyan'i gelistir.",
    metadata: {
      responseStylePreference: "warm",
      humorMode: "light",
    },
  });

  assert.ok(result.signals.some((signal) => signal.key === "response_style_preference" && signal.value === "warm"));
  assert.ok(result.signals.some((signal) => signal.key === "humor_level" && signal.value === "light"));
});

test("extractPreferenceSignals captures explicit identity facts with provenance metadata", () => {
  const result = extractPreferenceSignals({
    userId: "user_1",
    taskId: "task_1",
    message: "Benim adım Ada Lovelace. Yazılım mühendisi olarak çalışıyorum. Şirketim Elyan Labs.",
  });

  assert.ok(result.signals.some((signal) => signal.key === "name" && signal.value === "Ada Lovelace"));
  assert.ok(result.signals.some((signal) => signal.key === "job_title" && signal.value.includes("Yazılım mühendisi")));
  assert.ok(result.signals.some((signal) => signal.key === "company" && signal.value === "Elyan Labs"));
  assert.ok(
    result.signals.every((signal) =>
      signal.key === "name" || signal.key === "job_title" || signal.key === "company"
        ? signal.metadata?.explicit === true && signal.metadata?.sourceTurnId === "task_1"
        : true,
    ),
  );
});

test("extractPreferenceSignals captures natural preferred-name corrections", () => {
  const result = extractPreferenceSignals({
    userId: "user_1",
    taskId: "task_2",
    message: "Bundan sonra bana Emre de, benim adım Emre.",
  });

  assert.ok(result.signals.some((signal) => signal.key === "preferred_name" && signal.value === "Emre"));
  assert.ok(result.signals.some((signal) => signal.key === "name" && signal.value === "Emre"));
  assert.ok(
    result.signals
      .filter((signal) => signal.key === "preferred_name" || signal.key === "name")
      .every((signal) => signal.metadata?.explicit === true && signal.metadata?.sourceTurnId === "task_2"),
  );
});

test("extractPreferenceSignals does not treat ordinary instructions as preferred names", () => {
  const result = extractPreferenceSignals({
    userId: "user_1",
    message: "Bana kısa cevap ver ve gereksiz uzatma.",
    taskId: "task_short_1",
  });

  assert.equal(result.signals.some((signal) => signal.key === "preferred_name"), false);
  assert.ok(
    result.signals.some(
      (signal) =>
        signal.key === "answer_length" &&
        signal.value === "concise" &&
        signal.metadata?.explicit === true &&
        signal.metadata?.sourceTurnId === "task_short_1",
    ),
  );
  assert.ok(
    result.signals.some(
      (signal) =>
        signal.key === "brevity_preference" &&
        signal.value === "short" &&
        signal.metadata?.explicit === true,
    ),
  );
});

test("extractPreferenceSignals does not infer identity from non-explicit wording", () => {
  const result = extractPreferenceSignals({
    userId: "user_1",
    message: "İstanbul'a taşınmayı düşünüyorum ve bu şirkete ilgim var.",
  });

  assert.equal(result.signals.some((signal) => ["name", "job_title", "company", "location"].includes(signal.key)), false);
});

test("extractPreferenceSignals does not treat long-form requests as brevity corrections", () => {
  const result = extractPreferenceSignals({
    userId: "user_1",
    message: "Bu konu için çok uzun ve detaylı bir rapor yaz.",
    intent: "writing",
  });

  assert.equal(
    result.signals.some(
      (signal) =>
        signal.key === "answer_length" &&
        signal.value === "concise" &&
        signal.metadata?.explicit === true,
    ),
    false,
  );
});
