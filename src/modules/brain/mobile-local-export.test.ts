import assert from "node:assert/strict";
import test from "node:test";
import {
  buildMobileLocalExportShortcutReply,
  getMostRecentAssistantMessage,
  isLikelyPureDocumentExportPrompt,
  isMobileLocalExportMode,
} from "./mobile-local-export.js";

test("isMobileLocalExportMode accepts boolean flags and normalized modes", () => {
  assert.equal(isMobileLocalExportMode({ mobileLocalExport: true }), true);
  assert.equal(isMobileLocalExportMode({ documentExportMode: "mobile local" }), true);
  assert.equal(isMobileLocalExportMode({ outputMode: "on-device-export" }), true);
  assert.equal(isMobileLocalExportMode({ outputMode: "server" }), false);
  assert.equal(isMobileLocalExportMode(undefined), false);
});

test("isLikelyPureDocumentExportPrompt detects document export intents", () => {
  assert.equal(isLikelyPureDocumentExportPrompt("Bunu PDF olarak hazırla"), true);
  assert.equal(isLikelyPureDocumentExportPrompt("Word raporu oluştur"), true);
  assert.equal(isLikelyPureDocumentExportPrompt("Bu konuyu kısaca açıkla"), false);
});

test("getMostRecentAssistantMessage skips stored transient acknowledgements", () => {
  assert.equal(
    getMostRecentAssistantMessage([
      { role: "assistant", content: "Önceki gerçek cevap" },
      { role: "user", content: "PDF yap" },
      { role: "assistant", content: "Belge hazırlanıyor, birkaç saniye..." },
    ]),
    "Önceki gerçek cevap",
  );
});

test("buildMobileLocalExportShortcutReply reuses prior assistant content for local export", () => {
  assert.equal(
    buildMobileLocalExportShortcutReply({
      prompt: "Bunu SVG olarak ver",
      requestMetadata: { documentExportMode: "mobile_local" },
      conversation: [
        { role: "user", content: "Bir logo tasarla" },
        { role: "assistant", content: "Logo açıklaması burada." },
      ],
    }),
    "Logo açıklaması burada.",
  );
});

test("buildMobileLocalExportShortcutReply avoids desktop handoff messages", () => {
  assert.equal(
    buildMobileLocalExportShortcutReply({
      prompt: "Bunu PDF olarak ver",
      requestMetadata: { mobileDocumentExport: true },
      conversation: [
        { role: "assistant", content: "Masaüstü runtime ile eşleştirmen gerekiyor." },
      ],
    }),
    null,
  );
});
