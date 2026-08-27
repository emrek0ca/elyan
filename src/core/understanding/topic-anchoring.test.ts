import assert from "node:assert/strict";
import test from "node:test";
import { buildTypedUnderstandingEnvelope } from "./understanding-envelope.js";
import { classifyIntent } from "./intent-classifier.js";

// ---------------------------------------------------------------------------
// KONU ŞU ANKİ SÖZDÜR — başlık yalnız yedektir.
//
// Canlı arıza (2026-08-21 23:36): sohbetin ilk turu "Terminali kapat" idi ve
// oturum başlığı öyle kaldı. İkinci turda kullanıcı "Gökhan türkmen den şarkı
// çal" yazdı; görev başlığı oturumdan miras alındı, zarfın konusu başlıktan
// türetildi, `semanticGoal.objective` "Terminali kapat" oldu ve sunucu planı
// `close_app{Terminal}` + `play_media` üretti. Masaüstü Terminal'i GERÇEKTEN
// yeniden kapattı; iki tur cevapta da birbirine karıştı.
// ---------------------------------------------------------------------------

function envelopeFor(message: string, title?: string) {
  const intent = classifyIntent({
    userId: "u1",
    accountId: "u1",
    message,
    routeContext: "topic_anchoring_test",
  });
  return buildTypedUnderstandingEnvelope({
    userId: "u1",
    message,
    ...(title ? { title } : {}),
    intent,
  } as never);
}

test("a stale session title never overrides the current request as the topic", () => {
  const envelope = envelopeFor(
    "Gökhan türkmen den şarkı çal",
    "Masaüstü cowork görevi — Terminali kapat — Bağlam: filesystem",
  );
  assert.equal(envelope.intent.topic, "Gökhan türkmen den şarkı çal");
  assert.equal(envelope.intent.topic?.includes("Terminal"), false);
});

test("the title still supplies the topic when there is no message", () => {
  const envelope = envelopeFor("", "Haftalık raporu hazırla");
  assert.equal(envelope.intent.topic, "Haftalık raporu hazırla");
});

test("topic is the plain current message when no title is given", () => {
  const envelope = envelopeFor("Terminali kapat");
  assert.equal(envelope.intent.topic, "Terminali kapat");
});

test("the planning goal is the current message, not the inherited title", () => {
  const envelope = envelopeFor(
    "Gökhan türkmen den şarkı çal",
    "Masaüstü cowork görevi — Terminali kapat — Bağlam: filesystem",
  );
  const goal = envelope.conversation_state?.currentGoal ?? "";
  assert.equal(goal, "Gökhan türkmen den şarkı çal");
  assert.equal(goal.includes("Terminal"), false);
});

test("canonical topic removes document commands and local delivery instructions", () => {
  for (const [message, expected] of [
    [
      "Atatürk'ün ilkeleri hakkında makale yaz 1 sayfalık. Masaüstüne kaydet",
      "Atatürk'ün ilkeleri",
    ],
    [
      "Karadeniz'in iklimi hakkında rapor hazırla 2 sayfalık. Masaüstüne kaydet",
      "Karadeniz'in iklimi",
    ],
    [
      "Kuantum hata düzeltme konusunda kaynaklı özet oluştur. Masaüstüne kaydet",
      "Kuantum hata düzeltme",
    ],
  ] as const) {
    const envelope = envelopeFor(message);
    assert.equal(envelope.intent.topic, expected);
    assert.equal(envelope.intent.subject, expected);
    assert.equal(envelope.entities.find((entity) => entity.type === "topic")?.value, expected);
    for (const command of ["makale yaz", "rapor hazırla", "1 sayfalık", "2 sayfalık", "masaüstüne kaydet"]) {
      assert.equal(envelope.intent.topic?.toLocaleLowerCase("tr-TR").includes(command), false);
    }
  }
});

test("canonical topic remains semantic for an unseen subject without a word list", () => {
  const envelope = envelopeFor(
    "Biyobozunur ambalajların deniz ekosistemine etkisi hakkında analiz hazırla. Masaüstüne kaydet",
  );

  assert.equal(
    envelope.intent.subject,
    "Biyobozunur ambalajların deniz ekosistemine etkisi",
  );
  assert.equal(
    envelope.intent.subject?.includes("analiz hazırla"),
    false,
  );
});
