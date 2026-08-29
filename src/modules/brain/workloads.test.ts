import assert from "node:assert/strict";
import test from "node:test";
import {
  getSharedBrainWorkloadProfile,
  resolveAttachmentAwareSharedBrainWorkload,
} from "./workloads.js";

test("getSharedBrainWorkloadProfile exposes the document analysis profile", () => {
  const profile = getSharedBrainWorkloadProfile("document_analysis");

  assert.deepEqual(profile, {
    workload: "document_analysis",
    timeoutMs: 8_500,
    firstDeltaBudgetMs: 2_200,
    maxTokens: 640,
    streamingEnabled: true,
    cachePolicy: "off",
    fallbackWorkload: "mobile_chat_balanced",
  });
});

test("resolveAttachmentAwareSharedBrainWorkload upgrades server-brain document chats", () => {
  assert.equal(
    resolveAttachmentAwareSharedBrainWorkload({
      route: "server_brain",
      selectedWorkload: "mobile_chat_fast",
      attachmentContextUsed: true,
    }),
    "document_analysis",
  );
  assert.equal(
    resolveAttachmentAwareSharedBrainWorkload({
      route: "server_brain",
      selectedWorkload: "mobile_chat_balanced",
      attachmentContextUsed: true,
    }),
    "document_analysis",
  );
});

test("resolveAttachmentAwareSharedBrainWorkload keeps planning, non-server, and no-context routes unchanged", () => {
  assert.equal(
    resolveAttachmentAwareSharedBrainWorkload({
      route: "server_brain",
      selectedWorkload: "planning",
      attachmentContextUsed: true,
    }),
    "planning",
  );
  assert.equal(
    resolveAttachmentAwareSharedBrainWorkload({
      route: "desktop_runtime",
      selectedWorkload: "mobile_chat_balanced",
      attachmentContextUsed: true,
    }),
    "mobile_chat_balanced",
  );
  assert.equal(
    resolveAttachmentAwareSharedBrainWorkload({
      route: "server_brain",
      selectedWorkload: "mobile_chat_fast",
      attachmentContextUsed: false,
    }),
    "mobile_chat_fast",
  );
});

test("document generation reserves room for hidden reasoning and the JSON body", () => {
  // `planning` ile AYNI ARIZA: gizli düşünme turu `max_tokens`a sayılıyor ve
  // 1.600 token, çok bölümlü bir belgenin JSON gövdesine düşünmeyle
  // PAYLAŞILDIĞINDA yetmiyordu. Canlıda 13 sağlayıcı denemesinin tamamı
  // json_validate_failed / empty_stream_response ile düştü.
  const profile = getSharedBrainWorkloadProfile("document_generate");
  assert.ok(
    profile.maxTokens >= 3_000,
    `belge turu düşünme + gövde için yer bırakmalı, bulunan: ${profile.maxTokens}`,
  );
  // İlk GÖRÜNÜR token düşünme bitmeden akmaz; bütçe ona göre olmalı.
  assert.ok(
    (profile.firstDeltaBudgetMs ?? 0) >= 4_000,
    "ilk delta bütçesi düşünmeyi karşılamalı",
  );
  assert.ok(profile.timeoutMs >= 20_000, "tur zaman aşımı bütçeyle orantılı olmalı");
});
