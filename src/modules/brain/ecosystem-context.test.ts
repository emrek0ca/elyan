import assert from "node:assert/strict";
import test from "node:test";
import {
  buildEcosystemContextBlock,
  summarizeCapabilityFamilies,
} from "./ecosystem-context.js";

test("ecosystem block is derived from the manifest, not a hand list", () => {
  const families = summarizeCapabilityFamilies([
    { name: "shell_session_run" },
    { name: "document_write" },
    { name: "get_calendar_events" },
  ] as never);
  assert.ok(families.get("terminal")?.includes("shell_session_run"));
  assert.ok(families.get("belge ve görsel üretimi")?.includes("document_write"));
  assert.ok(families.get("takvim ve hatırlatıcı")?.includes("get_calendar_events"));
});

test("every family is represented, not just the first ones", () => {
  const block = buildEcosystemContextBlock({ desktopPaired: true });
  // Terminal en sonda gelen ailelerden biri; bütçe sırayla tüketilseydi düşerdi.
  assert.ok(block.includes("shell_session"), "terminal ailesi eksik");
  assert.ok(block.includes("desktop_operator"), "ekran kontrolü eksik");
  assert.ok(block.includes("document_write"), "belge üretimi eksik");
});

test("desktop pairing is never claimed when unknown", () => {
  const unknown = buildEcosystemContextBlock({ desktopPaired: null });
  assert.ok(!unknown.includes("BAĞLI"), "bilinmezken bağlantı iddia edildi");

  const paired = buildEcosystemContextBlock({ desktopPaired: true });
  assert.ok(paired.includes("BAĞLI:"));

  const unpaired = buildEcosystemContextBlock({ desktopPaired: false });
  assert.ok(unpaired.includes("BAĞLI DEĞİL"));
  // Bağlı değilken bile yeteneklerini bilmeli; sadece "yaptım" diyememeli.
  assert.ok(unpaired.includes("YAPTIĞINI"));
});

test("block does not prime self-description", () => {
  const block = buildEcosystemContextBlock({ desktopPaired: true });
  // İlk sürüm "SEN KİMSİN — ELYAN:" ile başlıyordu ve model belirsiz sorulara
  // kendini tanıtarak cevap vermeye başladı. Başlık kimlik değil ortam olmalı.
  assert.ok(!block.includes("SEN KİMSİN"), "kimlik başlığı geri gelmiş");
  assert.ok(block.includes("ÇALIŞMA ORTAMIN"));
  assert.ok(block.includes("KENDİNİ ANLATMA"));
});

test("block instructs behaviour, not performed warmth", () => {
  const block = buildEcosystemContextBlock({ desktopPaired: true });
  assert.ok(block.includes("Kısa konuş"));
  assert.ok(block.includes("YAPMADIĞIN bir şeyi yaptım deme"));
  // "samimi/sıcak ol" gibi talimatlar yapmacıklığı artırdığı için olmamalı.
  assert.ok(!/samimi|sıcak ol|arkadaş canlısı/i.test(block));
});

test("block stays bounded so it cannot eat the prompt budget", () => {
  assert.ok(buildEcosystemContextBlock({ desktopPaired: true }).length < 3000);
});
