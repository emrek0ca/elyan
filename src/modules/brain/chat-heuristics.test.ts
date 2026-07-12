import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { buildSharedBrainAckText, isShortFollowUpPrompt, isSocialChatPrompt, selectHybridMobileChatWorkload } from "./chat-heuristics.js";
import type { SharedBrainWorkload } from "./workloads.js";

test("buildSharedBrainAckText returns empty string so frontend loading indicator handles pending state", () => {
  // All workloads must return empty — no "Bir saniye bakıyorum" injected into
  // the assistant message before the real answer arrives.
  assert.equal(buildSharedBrainAckText("mobile_chat_fast"), "");
  assert.equal(buildSharedBrainAckText("mobile_chat_balanced"), "");
  assert.equal(buildSharedBrainAckText("planning"), "");
});

test("selectHybridMobileChatWorkload keeps only greetings on fast and upgrades explanatory asks", () => {
  assert.equal(
    selectHybridMobileChatWorkload({
      message: "Selam",
      primaryIntent: "chat",
      brainProfile: null,
    }),
    "mobile_chat_fast",
  );
  assert.equal(
    selectHybridMobileChatWorkload({
      message: "Bunu neden böyle yaptığını kısa ama net şekilde açıkla.",
      primaryIntent: "chat",
      brainProfile: null,
    }),
    "mobile_chat_balanced",
  );
});

test("isSocialChatPrompt treats short slang call-outs as social turns", () => {
  assert.equal(isSocialChatPrompt("Lan"), true);
  assert.equal(isSocialChatPrompt("Kanka!"), true);
  assert.equal(isSocialChatPrompt("kanka JWT nasıl çalışır"), false);
});

/* ── Türkçe ek/çekim varyasyonları: intent regex kaçırma vakaları ───────── */

test("selectHybridMobileChatWorkload catches Turkish suffixed analysis verbs (test-önce vakalar)", () => {
  // "karşılaştır" kökü çekimli halde: -ma, -manı, -ır mısın
  assert.equal(
    selectHybridMobileChatWorkload({
      message: "Bu iki telefonu karşılaştırmanı istiyorum",
      primaryIntent: "chat",
      brainProfile: null,
    }),
    "mobile_chat_balanced",
  );
  assert.equal(
    selectHybridMobileChatWorkload({
      message: "Node.js ve Python farkını açıkla",
      primaryIntent: "chat",
      brainProfile: null,
    }),
    "mobile_chat_balanced",
  );
  // "özetle" kökü: "özetler misin" (\b sınırı r harfinde kaçırıyordu)
  assert.equal(
    selectHybridMobileChatWorkload({
      message: "Şu metni özetler misin",
      primaryIntent: "chat",
      brainProfile: null,
    }),
    "mobile_chat_balanced",
  );
  // "açıkla" kökü: "açıklar mısın"
  assert.equal(
    selectHybridMobileChatWorkload({
      message: "Bunu bana açıklar mısın",
      primaryIntent: "chat",
      brainProfile: null,
    }),
    "mobile_chat_balanced",
  );
  // "değerlendir" kökü: "değerlendirmeni istiyorum"
  assert.equal(
    selectHybridMobileChatWorkload({
      message: "Şu planı değerlendirmeni istiyorum",
      primaryIntent: "chat",
      brainProfile: null,
    }),
    "mobile_chat_balanced",
  );
  // "incele" kökü: "inceler misin"
  assert.equal(
    selectHybridMobileChatWorkload({
      message: "Şu kodu inceler misin",
      primaryIntent: "chat",
      brainProfile: null,
    }),
    "mobile_chat_fast",
  );
});

test("selectHybridMobileChatWorkload matches workload routing benchmark fixtures", () => {
  const path = `${process.cwd()}/benchmarks/workload-routing.jsonl`;
  const cases = readFileSync(path, "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line) as {
      id: string;
      message: string;
      primaryIntent: string;
      expectedWorkload: Extract<SharedBrainWorkload, "mobile_chat_fast" | "mobile_chat_balanced" | "planning">;
    });
  const mismatches: string[] = [];

  for (const fixture of cases) {
    const actual = selectHybridMobileChatWorkload({
      message: fixture.message,
      primaryIntent: fixture.primaryIntent,
      brainProfile: null,
    });
    if (actual !== fixture.expectedWorkload) {
      mismatches.push(`${fixture.id}: expected ${fixture.expectedWorkload}, got ${actual}`);
    }
  }

  const accuracy = (cases.length - mismatches.length) / cases.length;
  assert.ok(
    accuracy >= 0.9,
    `workload routing accuracy ${accuracy}; mismatches: ${mismatches.join(", ")}`,
  );
});

test("suffix handling does not break greetings or unrelated short chat", () => {
  assert.equal(
    selectHybridMobileChatWorkload({
      message: "Selam, naber?",
      primaryIntent: "chat",
      brainProfile: null,
    }),
    "mobile_chat_fast",
  );
  assert.equal(
    selectHybridMobileChatWorkload({
      message: "Bugün hava güzel",
      primaryIntent: "chat",
      brainProfile: null,
    }),
    "mobile_chat_fast",
  );
});

/* ── Kısa takip mesajı tespiti ──────────────────────────────────────────── */

test("isShortFollowUpPrompt detects short follow-up turns", () => {
  assert.equal(isShortFollowUpPrompt("anlamadım"), true);
  assert.equal(isShortFollowUpPrompt("Anlamadım?"), true);
  assert.equal(isShortFollowUpPrompt("devam et"), true);
  assert.equal(isShortFollowUpPrompt("devam"), true);
  assert.equal(isShortFollowUpPrompt("onu düzelt"), true);
  assert.equal(isShortFollowUpPrompt("bunu kısalt"), true);
  assert.equal(isShortFollowUpPrompt("tekrar dene"), true);
  assert.equal(isShortFollowUpPrompt("daha kısa yaz"), true);
  assert.equal(isShortFollowUpPrompt("olmadı"), true);
  assert.equal(isShortFollowUpPrompt("yanlış oldu"), true);
});

test("isShortFollowUpPrompt does not flag full standalone questions", () => {
  assert.equal(isShortFollowUpPrompt("Atatürk kimdir?"), false);
  assert.equal(isShortFollowUpPrompt("Bana kuantum bilgisayarları detaylıca anlatır mısın"), false);
  assert.equal(isShortFollowUpPrompt("Selam"), false);
  assert.equal(isShortFollowUpPrompt(""), false);
  assert.equal(
    isShortFollowUpPrompt("Bu raporu düzeltmeni istiyorum çünkü üçüncü bölümde hatalar var ve tablolar eksik kalmış durumda"),
    false,
  );
});
