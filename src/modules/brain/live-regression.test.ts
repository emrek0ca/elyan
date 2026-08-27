import assert from "node:assert/strict";
import test from "node:test";
import { buildTemporalFactsPromptBlock } from "./inference.js";
import { routeSkill } from "../skills/router.js";
import {
  isReferentlessVisualEdit,
  resolveCompletionAssistantBlocks,
} from "../tasks/service.js";
import type { SkillSummary } from "../skills/types.js";

/**
 * CANLI ARIZALARDAN REGRESYON SETİ.
 *
 * Buradaki her vaka, yerelde çalışan sunucuya gerçek istek göndererek
 * bulundu — birim testleri yeşilken ürün bozuktu. Sebep şuydu: hepsi
 * sağlayıcı çağrısı gerektiriyor sanılıyordu, oysa her birinin kararı
 * sağlayıcıya çıkmadan verilebilir. Bu dosya o kararları tek tek çiviler.
 *
 * Kural: bir arıza canlıda görüldüyse, önce buraya bir vaka yazılır.
 */

function skill(overrides: Partial<SkillSummary> & { id: string }): SkillSummary {
  return {
    id: overrides.id,
    version: overrides.version ?? "1.0.0",
    summary: overrides.summary ?? overrides.id,
    requiresAttachment: overrides.requiresAttachment ?? false,
    manualSelectable: overrides.manualSelectable ?? true,
    triggers: overrides.triggers ?? { payloadTypes: [] },
    produces: overrides.produces ?? {
      desiredOutputKinds: [],
      artifactTypes: [],
      blockTypes: [],
    },
  } as SkillSummary;
}

test("the prompt carries today's date, so a date question is answerable", () => {
  // 2026-08-27: "Bugün ayın kaçı ve haftanın hangi günü?" turu tamamen
  // düştü. Model tarihi bilmiyordu, reddeden bir cümle üretti, boş-cevap
  // koruması onu cevapsızlık sayıp turu öldürdü.
  const block = buildTemporalFactsPromptBlock({
    now: new Date("2026-08-27T14:09:00.000Z"),
  });

  assert.match(block, /2026/);
  assert.match(block, /ISO: 2026-08-27T14:09:00\.000Z/);
  // Modelin "tarihi bilemem" demesini açıkça yasaklayan direktif kalmalı.
  assert.match(block, /never substitute your training cutoff/i);
});

test("an unknown user timezone never throws and never fabricates a zone", () => {
  // Hafızadan gelen saat dilimi bayat veya bozuk olabilir; `Intl` geçersiz
  // adla fırlatır ve turu düşürürdü.
  const block = buildTemporalFactsPromptBlock({
    now: new Date("2026-08-27T14:09:00.000Z"),
    context: {
      userModel: { locale: { timezone: "Mars/Olympus" } },
    } as never,
  });
  assert.match(block, /Saat: /);
});

test("desktop availability is stated only when it is actually known", () => {
  const now = new Date("2026-08-27T14:09:00.000Z");
  assert.match(
    buildTemporalFactsPromptBlock({ now, desktopAvailable: true }),
    /masaüstü uygulaması ŞU AN bağlı/,
  );
  assert.match(
    buildTemporalFactsPromptBlock({ now, desktopAvailable: false }),
    /bağlı DEĞİL/,
  );
  // Bilinmiyorsa hiçbir iddia yazılmaz.
  const unknown = buildTemporalFactsPromptBlock({ now });
  assert.equal(/masaüstü uygulaması/.test(unknown), false);
});

test("a chat-only turn does not pay for the skill classifier", async () => {
  // ÖLÇÜM: tek attachment gerektirmeyen beceri yalnız pdf/docx üretiyor ama
  // aday listesinde kalıyordu; her sıradan sohbet turu "beceri gerekiyor mu"
  // demek için ortalama 1481 ms harcıyordu — cevabın kendisi kadar.
  let classifierCalls = 0;
  const decision = await routeSkill({
    prompt: "1350 TL'nin %18 KDV dahil hali kaç TL?",
    skills: [
      skill({
        id: "research_document",
        produces: {
          desiredOutputKinds: ["pdf", "docx", "artifact"],
          artifactTypes: ["document"],
          blockTypes: ["document_block"],
        },
      }),
    ],
    desiredOutputKinds: ["chat_reply"],
    classify: async () => {
      classifierCalls += 1;
      return null;
    },
  });

  assert.equal(classifierCalls, 0);
  assert.equal(decision.needsSkill, false);
});

test("a document request still reaches the skill classifier", async () => {
  let classifierCalls = 0;
  await routeSkill({
    prompt: "Atatürk'ün ilkeleri hakkında bir rapor hazırla",
    skills: [
      skill({
        id: "research_document",
        produces: {
          desiredOutputKinds: ["pdf", "docx", "artifact"],
          artifactTypes: ["document"],
          blockTypes: ["document_block"],
        },
      }),
    ],
    desiredOutputKinds: ["docx"],
    classify: async () => {
      classifierCalls += 1;
      return null;
    },
  });

  assert.equal(classifierCalls, 1);
});

test("a chat-capable skill is still a candidate on a plain turn", async () => {
  let classifierCalls = 0;
  await routeSkill({
    prompt: "Bu belgede ne yazıyor?",
    skills: [
      skill({
        id: "document_qa",
        produces: {
          desiredOutputKinds: ["chat_reply"],
          artifactTypes: [],
          blockTypes: ["text"],
        },
      }),
    ],
    desiredOutputKinds: [],
    classify: async () => {
      classifierCalls += 1;
      return null;
    },
  });

  assert.equal(classifierCalls, 1);
});

test("an image edit with nothing to edit is a misclassification, not a missing file", () => {
  // 2026-08-27: "Şu an saat kaç? Bir de bu ayın son günü hangi güne denk
  // geliyor?" ve "Şunu halleder misin?" turları görsel şeridine düştü ve
  // kullanıcı "Düzenlenecek son görseli bu sohbet içinde bulamadım" cevabını
  // aldı.
  for (const prompt of [
    "Şu an saat kaç? Bir de bu ayın son günü hangi güne denk geliyor?",
    "Şunu halleder misin?",
  ]) {
    assert.equal(
      isReferentlessVisualEdit({
        prompt,
        visualIntentKind: "image_edit",
        sourceImageCount: 0,
        hasSessionVisualHistory: false,
      }),
      true,
      prompt,
    );
  }
});

test("a real edit keeps its lane whenever a referent exists", () => {
  // Turda görsel var.
  assert.equal(
    isReferentlessVisualEdit({
      prompt: "Şunu halleder misin?",
      visualIntentKind: "image_edit",
      sourceImageCount: 1,
      hasSessionVisualHistory: false,
    }),
    false,
  );
  // Oturumda görsel geçmişi var.
  assert.equal(
    isReferentlessVisualEdit({
      prompt: "Şunu halleder misin?",
      visualIntentKind: "image_edit",
      sourceImageCount: 0,
      hasSessionVisualHistory: true,
    }),
    false,
  );
  // Cümlenin kendisi görsel eylem iddia ediyor.
  assert.equal(
    isReferentlessVisualEdit({
      prompt: "Arka planı beyaz yap",
      visualIntentKind: "image_edit",
      sourceImageCount: 0,
      hasSessionVisualHistory: false,
    }),
    false,
  );
  // Düzenleme/devam dışı bir niyet bu kapıya hiç uğramaz.
  assert.equal(
    isReferentlessVisualEdit({
      prompt: "Bir kedi çiz",
      visualIntentKind: "image_generate",
      sourceImageCount: 0,
      hasSessionVisualHistory: false,
    }),
    false,
  );
});

test("a complete answer is never handed a canned clarification", () => {
  // 2026-08-27: "1350 TL'nin %18 KDV dahil hali kaç TL? Adım adım göster."
  // planning sayıldı, model doğru cevabı ÜÇTEN AZ adımda verdi ve cevabın
  // yanına "Önceliğin, süren veya mevcut durumun hangisini esas alalım?"
  // sorusu basıldı.
  const answered = resolveCompletionAssistantBlocks({
    prompt: "1350 TL'nin %18 KDV dahil hali kaç TL? Adım adım göster.",
    responseText: [
      "1. KDV oranı %18 → 1,18 çarpanı",
      "2. 1350 × 1,18 = 1593 TL",
      "**Sonuç:** 1593 TL.",
    ].join("\n"),
    assistantBlocks: [],
    selectedWorkload: "planning",
    planIntent: true,
  });
  assert.equal(
    (answered.blocks as Array<Record<string, unknown>>).some(
      (block) => block.type === "clarification",
    ),
    false,
  );

  // Buna karşılık, içeriksiz bir "yaptım" onayı hâlâ netleştirme alır.
  const acknowledgement = resolveCompletionAssistantBlocks({
    prompt: "Bu hedef için bir plan oluştur",
    responseText: "Doktorluk hedefi için yol haritası hazırlandı.",
    assistantBlocks: [],
    selectedWorkload: "planning",
    planIntent: true,
  });
  assert.equal(
    (acknowledgement.blocks as Array<Record<string, unknown>>).some(
      (block) => block.type === "clarification",
    ),
    true,
  );
});
