import assert from "node:assert/strict";
import test from "node:test";
import { buildContextPacketsFromMetadata } from "./context-packets.js";

// Canlı vaka: "pilim ne durumda?" taze device sinyali varken paket üretmiyordu.
// Kök neden: alaka kalıpları ham ASCII `\b` kullanıyordu — ş/ğ/ü kenarlı
// alternatifler (şarj, ağ, yavaş, çöktü) hiç eşleşmiyor, "pilim" gibi ekli
// biçimler `\bpil\b`den kaçıyordu. Bu testler kalıpların Türkçe ile ölçülmüş
// davranışını sabitler.

function metadataWithSignals(now: Date) {
  const createdAt = now.toISOString();
  return {
    compactContext: {
      derivedContextDigest: {
        worldSignals: [
          {
            signalId: "sig-device",
            kind: "device",
            summary: "pil %25 (şarjda), hücresel ağ.",
            confidence: 0.9,
            createdAt,
            facts: { battery: "25", charging: "true" },
            privacy: {},
          },
          {
            signalId: "sig-time",
            kind: "time",
            summary: "Cuma, yerel saat 18:47 (akşam).",
            confidence: 0.95,
            createdAt,
            facts: { daypart: "evening" },
            privacy: {},
          },
        ],
      },
    },
  } as Record<string, unknown>;
}

function packetKinds(prompt: string): string[] {
  const now = new Date();
  return buildContextPacketsFromMetadata(metadataWithSignals(now), {
    now,
    requestText: prompt,
    intent: "chat",
  }).map((packet) => `${packet.kind}:${packet.mentionPolicy}`);
}

test("Türkçe ekli cihaz soruları device paketini açık alaka ile üretir", () => {
  for (const prompt of [
    "pilim ne durumda?",
    "şarjım çok hızlı bitiyor, sorun ne olabilir?",
    "internetim sürekli kopuyor",
    "telefon çok yavaşladı",
    "uygulama çöktü, neden?",
  ]) {
    const kinds = packetKinds(prompt);
    assert.ok(
      kinds.includes("device_context:explicit_when_relevant"),
      `${prompt} → device paketi bekleniyordu, gelen: ${kinds.join(", ")}`,
    );
  }
});

test("cihazla ilgisiz istekler device paketi sızdırmaz", () => {
  for (const prompt of [
    "Kuantum dolanıklığını anlat",
    "Hatay'da ne yenir?",
    "bana bir şiir yaz",
    "selam",
  ]) {
    const kinds = packetKinds(prompt);
    assert.equal(
      kinds.some((kind) => kind.startsWith("device_context:explicit")),
      false,
      `${prompt} → device paketi SIZMAMALIYDI, gelen: ${kinds.join(", ")}`,
    );
  }
});

test("zaman-duyarlı Türkçe istekler time paketini üretmeye devam eder", () => {
  const kinds = packetKinds("bugün programım nasıl, yetişir miyim?");
  assert.ok(
    kinds.some((kind) => kind.startsWith("time_context:")),
    `time paketi bekleniyordu, gelen: ${kinds.join(", ")}`,
  );
});
