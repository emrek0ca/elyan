import assert from "node:assert/strict";
import test from "node:test";
import { detectGoalChatCommand } from "./chat-goal-commands.js";

test("goal chat: Türkçe hedef oluşturma komutları algılanır", () => {
  const cases: Array<[string, string]> = [
    ["30 günde İngilizce öğrenme hedefi oluştur", "30 günde İngilizce öğrenme"],
    ["hedef oluştur: her gün 5km koşu", "her gün 5km koşu"],
    ["bana kitap okuma için bir hedef koy", "kitap okuma"],
    ["yeni hedef ekle haftada 3 spor", "haftada 3 spor"],
  ];
  for (const [message, expectedFragment] of cases) {
    const command = detectGoalChatCommand(message);
    assert.ok(command, `algılanamadı: ${message}`);
    assert.equal(command.kind, "create");
    assert.ok(
      command.kind === "create" && command.title.includes(expectedFragment.split(" ")[0]),
      `başlık beklenen parçayı içermiyor: "${command.kind === "create" ? command.title : ""}"`,
    );
  }
});

test("goal chat: adım sayısı çıkarılır", () => {
  const command = detectGoalChatCommand("10 adımlık Python öğrenme hedefi oluştur");
  assert.ok(command && command.kind === "create");
  assert.equal(command.maxSteps, 10);
  assert.ok(command.title.includes("Python"));
});

test("goal chat: İngilizce create/set goal algılanır", () => {
  for (const message of ["create a goal to run daily", "set a new goal: read 12 books"]) {
    const command = detectGoalChatCommand(message);
    assert.ok(command, `algılanamadı: ${message}`);
    assert.equal(command.kind, "create");
  }
});

test("goal chat: tamamlama komutları algılanır", () => {
  for (const message of [
    "hedefi tamamla",
    "hedefimi bitir artık",
    "complete the goal",
  ]) {
    const command = detectGoalChatCommand(message);
    assert.ok(command, `algılanamadı: ${message}`);
    assert.equal(command.kind, "complete");
  }
});

test("goal chat: false positive yok — isim tamlamaları ve normal sohbet", () => {
  for (const message of [
    "hedef kitle belirle bu ürün için", // pazarlama, komut değil
    "hedef fiyat ne olmalı",
    "bu projenin hedefi ne?",
    "hedefim yok şu an",
    "React'te useEffect döngüsü nasıl kırılır?",
    "selam nasılsın",
    "golün hedefe gitmesi lazım",
  ]) {
    assert.equal(detectGoalChatCommand(message), null, `false positive: ${message}`);
  }
});

test("goal chat: boş/aşırı uzun mesaj güvenli", () => {
  assert.equal(detectGoalChatCommand(""), null);
  assert.equal(detectGoalChatCommand("hedef oluştur ".repeat(400)), null);
});
