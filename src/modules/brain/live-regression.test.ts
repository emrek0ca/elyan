import assert from "node:assert/strict";
import test from "node:test";
import {
  buildTemporalFactsPromptBlock,
  isWholeReplyJson,
} from "./inference.js";
import { routeSkill } from "../skills/router.js";
import {
  isReferentlessVisualEdit,
  resolveCompletionAssistantBlocks,
} from "../tasks/service.js";
import { buildAgentToolCatalogForTurn } from "./tool-registry.js";
import { isHostedImageEditIntent } from "./image-generation.js";
import { isGeminiFallbackQueueConfigured } from "./chat-generation-queue.js";
import { isSocialChatPrompt } from "./chat-heuristics.js";
import {
  ASSISTANT_TURN_FAILURE_FALLBACK_TR,
  assistantTurnFailureMessage,
  isGenericAssistantFallbackReply,
} from "./response-policy.js";
import { getSharedBrainFallbackMessage } from "../tasks/service-helpers.js";
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

const CONNECTOR_READ_TOOLS = [
  "gmail.search",
  "gmail.read",
  "calendar.list_events",
  "drive.search",
  "notion.search",
  "github.search",
  "slack.search",
];

test("a connected account stays reachable when the semantic selector cannot run", () => {
  // Bağlı hesap araçlarının TEK seçim yolu canlı semantik ipucuydu ve o ipucu
  // bir işçi modeline bağlı. İşçi düştüğünde ipucu `null` oluyor, bu da
  // "bu tur bağlı hesaba gitmiyor" ile aynı değere iniyordu: kullanıcının
  // bağladığı Gmail/Takvim/Drive/Notion/GitHub/Slack araçlarının hepsi
  // katalogdan siliniyordu ve Elyan "erişimim yok" diyordu.
  const catalog = buildAgentToolCatalogForTurn({
    prompt: "Bu haftaki toplantılarım neler?",
    intent: "chat",
    action: null,
    desiredOutputKinds: ["chat_reply"],
    requiredCapabilities: [],
    advertisedConnectorTools: CONNECTOR_READ_TOOLS,
    connectorReadHint: null,
    connectorWriteHint: null,
    connectorSemanticUnavailable: true,
    includeCoreTools: false,
  } as never);

  const names = catalog.map((tool) => tool.name);
  for (const tool of CONNECTOR_READ_TOOLS) {
    assert.equal(names.includes(tool), true, `${tool} katalogda olmalı`);
  }
});

test("a healthy selector that declines still keeps connected tools out", () => {
  // Bozulmuş mod yalnız ARIZA içindir. Seçici çalıştı ve "bu tur bağlı hesaba
  // gitmiyor" dediyse araçlar sunulmamalı; aksi halde her sohbet turu bağlı
  // hesap araçlarıyla dolar.
  const catalog = buildAgentToolCatalogForTurn({
    prompt: "Bugün hava çok güzel",
    intent: "chat",
    action: null,
    desiredOutputKinds: ["chat_reply"],
    requiredCapabilities: [],
    advertisedConnectorTools: CONNECTOR_READ_TOOLS,
    connectorReadHint: null,
    connectorWriteHint: null,
    connectorSemanticUnavailable: false,
    includeCoreTools: false,
  } as never);

  assert.deepEqual(catalog.map((tool) => tool.name), []);
});

test("a side-effect connector tool needs the turn to be a side effect first", () => {
  const base = {
    prompt: "Bu maili gönder",
    intent: "chat",
    action: null,
    desiredOutputKinds: ["chat_reply"],
    requiredCapabilities: [],
    advertisedConnectorTools: ["gmail.send"],
    connectorReadHint: null,
    connectorWriteHint: null,
    connectorSemanticUnavailable: true,
    includeCoreTools: false,
  };

  // Zarf turu yan etkili ilan etmediyse yazma aracı bozulmuş modda da gelmez.
  assert.deepEqual(
    buildAgentToolCatalogForTurn({ ...base, sideEffectRequested: false } as never)
      .map((tool) => tool.name),
    [],
  );
  // Yan etkili ilan edildiyse araç sunulur; yürütme yine onaya bağlıdır.
  assert.deepEqual(
    buildAgentToolCatalogForTurn({ ...base, sideEffectRequested: true } as never)
      .map((tool) => tool.name),
    ["gmail.send"],
  );
});

test("a failure tells the user what happened, and is still recognised as a failure", () => {
  // 2026-08-27: saat sorusu "Bu turda yanıt oluşturulamadı. Tekrar dene."
  // aldı. Gerçek sebep sağlayıcının boş akış döndürmesiydi; kullanıcının
  // gördüğü ise Elyan'ın saati bilmediğiydi.
  const empty = assistantTurnFailureMessage("provider_empty_output");
  const unavailable = assistantTurnFailureMessage("server_brain_unavailable");
  const busy = assistantTurnFailureMessage("rate_limited");

  assert.notEqual(empty, ASSISTANT_TURN_FAILURE_FALLBACK_TR);
  assert.notEqual(unavailable, empty, "farklı arızalar farklı şey söylemeli");
  assert.notEqual(busy, unavailable);

  // KRİTİK: her yeni cümle "bu bir cevap değil" korumasınca TANINMALI.
  // Tanınmayan bir çıkmaz cümlesi turu başarılı gösterip görevi `completed`
  // yazmıştı; koruma tek tek string karşılaştırdığı için yeni cümleler
  // sessizce kapının dışında kalırdı.
  for (const message of [empty, unavailable, busy, ASSISTANT_TURN_FAILURE_FALLBACK_TR]) {
    assert.equal(isGenericAssistantFallbackReply(message), true, message);
  }

  // Bilinmeyen sebep uydurmaz, genel cümleye düşer.
  assert.equal(
    assistantTurnFailureMessage("hiç_bilinmeyen_sebep"),
    ASSISTANT_TURN_FAILURE_FALLBACK_TR,
  );
  assert.equal(assistantTurnFailureMessage(null), ASSISTANT_TURN_FAILURE_FALLBACK_TR);

  // Gerçek bir cevap asla arıza sayılmaz.
  assert.equal(isGenericAssistantFallbackReply("Ankara."), false);
});

test("an async dispatch failure tells the user what went wrong", () => {
  // ÖLÇÜLEN (2026-08-28): sağlayıcı hız sınırı verdiğinde tur asenkron
  // düşüyor ve kullanıcı sebebi öğrenemiyordu. Sınıf zaten elimizdeydi.
  class FakeAppError extends Error {
    code: string;
    details: Record<string, unknown>;
    constructor(code: string, message: string, details: Record<string, unknown> = {}) {
      super(message);
      this.code = code;
      this.details = details;
    }
  }

  const rateLimited = getSharedBrainFallbackMessage(
    new FakeAppError("rate_limited", "429 Too Many Requests from upstream"),
  );
  assert.equal(rateLimited, assistantTurnFailureMessage("rate_limited"));
  assert.equal(
    rateLimited.includes("429"),
    false,
    "sağlayıcının teknik metni kullanıcıya sızmamalı",
  );

  // Sebep `failureClass` içinde taşınıyorsa da okunur.
  assert.equal(
    getSharedBrainFallbackMessage(
      new FakeAppError("", "boş", { failureClass: "provider_empty_output" }),
    ),
    assistantTurnFailureMessage("provider_empty_output"),
  );

  // Tanınmayan sebep: mevcut davranış korunur, uydurma yapılmaz.
  assert.equal(
    getSharedBrainFallbackMessage(new Error("Anlaşılır bir açıklama.")),
    "Anlaşılır bir açıklama.",
  );
  assert.equal(
    getSharedBrainFallbackMessage(null),
    ASSISTANT_TURN_FAILURE_FALLBACK_TR,
  );
});

test("a reply that is entirely JSON is not an answer", () => {
  // ÖLÇÜLEN ARIZA (2026-08-28): "Bana bir hatırlatıcı kur: yarın 09:00
  // toplantı" isteğine kullanıcı ham araç çağrısını gördü:
  //   {"action":"add_reminder","title":"Toplantı","time":"2026-08-29T09:00:00"}
  // Mevcut sızıntı koruması ANAHTAR arıyordu (`tool_requests`, `tool:`,
  // konektör adı) ve bu şemada hiçbiri yoktu.
  const leaked = [
    '{\n"action": "add_reminder",\n"title": "Toplantı",\n"time": "2026-08-29T09:00:00"\n}',
    '{"tool":"x"}',
    '[{"step":1}]',
    '  { "a": 1 }  ',
    // İkinci vaka: JSON kapısı konduktan SONRA aynı sızıntı fonksiyon çağrısı
    // biçiminde geri geldi. Anahtar listesi değil, ŞEKİL kapısı gerekiyordu.
    'add_reminder({"title":"Doktor randevusu","time":"2026-08-29T10:00:00"})',
    'web.search({"q":"hava"})',
    'do_thing()',
  ];
  for (const text of leaked) {
    assert.equal(isWholeReplyJson(text), true, text.slice(0, 40));
  }

  // Gerçek cevaplar etkilenmez — JSON İÇEREN metin, JSON OLAN metin değildir.
  const answers = [
    "Hatırlatıcıyı kurdum: yarın 09:00, Toplantı.",
    "Ankara.",
    'Şöyle bir JSON kullanabilirsin: {"a": 1} — bu örnek yeterli.',
    "```json\n{\"a\":1}\n```",
    "{ bu bir cümle, JSON değil }",
    "",
    // Cümlenin İÇİNDE çağrı geçmesi serbest; yasak olan cevabın kendisinin
    // bir çağrı olması.
    "Bunun için add_reminder({...}) çağrısını kullanırım.",
    "Hatırlatıcı kuruldu (add_reminder).",
  ];
  for (const text of answers) {
    assert.equal(isWholeReplyJson(text), false, text.slice(0, 40));
  }
});

test("a bare everyday verb does not make a turn an image edit", () => {
  // ÖLÇÜLEN ARIZA (2026-08-28): "Hatırlatıcı ekle: cuma 15:00 diş hekimi"
  // görsel düzenleme şeridine düşüyor ve kullanıcı "Düzenlenecek son görseli
  // bu sohbet içinde bulamadım" cevabını alıyordu. Desen genel fiillerin
  // (`ekle`, `sil`, `değiştir`, `add`, `remove`) düz listesiydi.
  const notVisual = [
    "Hatırlatıcı ekle: cuma 15:00 diş hekimi",
    "Takvime toplantı ekle",
    "Bu dosyayı sil",
    "Randevuyu değiştir",
    "Listeye süt ekle",
    "Notu düzenle",
  ];
  for (const prompt of notVisual) {
    assert.equal(isHostedImageEditIntent(prompt), false, prompt);
  }

  // Gerçek görsel istekleri etkilenmez — fiil bir GÖRSEL NESNEYE bağlı.
  const visual = [
    "Bu görseli düzenle",
    "Fotoğraftaki arka planı sil",
    "Arka planı beyaz yap",
    "Resmi kırp",
    "Bu fotoğrafı iyileştir",
    // Türkçe ekli biçim: nesne KÖK olarak eşleşmeli, tam kelime olarak değil.
    "Görseldeki yazıyı kaldır",
    "remove the background from the photo",
  ];
  for (const prompt of visual) {
    assert.equal(isHostedImageEditIntent(prompt), true, prompt);
  }
});

test("a provider that policy forbids is not a fallback", () => {
  // ÖLÇÜLEN (2026-08-28): her tur zincire Gemini ile başlayıp
  // `policy_blocked:paid:paid_fallback_disabled` alıyordu. Kontrol yalnız API
  // anahtarına bakıyordu; anahtar hep var, izin hiç yok.
  const withKeyOnly = {
    config: { GEMINI_API_KEY: "k" },
  } as never;
  assert.equal(isGeminiFallbackQueueConfigured(withKeyOnly), false);

  const enabledButNotAttested = {
    config: { GEMINI_API_KEY: "k", GEMINI_PAID_FALLBACK_ENABLED: true },
  } as never;
  assert.equal(isGeminiFallbackQueueConfigured(enabledButNotAttested), false);

  const usable = {
    config: {
      GEMINI_API_KEY: "k",
      GEMINI_PAID_FALLBACK_ENABLED: true,
      GEMINI_PAID_DATA_PROCESSING_ATTESTED: true,
    },
  } as never;
  assert.equal(isGeminiFallbackQueueConfigured(usable), true);

  // Serbest-katman modu ücretli kapıdan bağımsızdır ve meşru bir yoldur.
  assert.equal(
    isGeminiFallbackQueueConfigured({
      config: { GEMINI_API_KEY: "k", GEMINI_FREE_ONLY: true },
    } as never),
    true,
  );

  // Anahtar yoksa izin verilse bile yedek yoktur.
  const noKey = {
    config: {
      GEMINI_PAID_FALLBACK_ENABLED: true,
      GEMINI_PAID_DATA_PROCESSING_ATTESTED: true,
    },
  } as never;
  assert.equal(isGeminiFallbackQueueConfigured(noKey), false);
});

test("a greeting inside a request is content, not a greeting", () => {
  // ÖLÇÜLEN ARIZA (2026-08-28): "Bu cümleyi İngilizceye çevir: yarın
  // görüşürüz" ucuz sosyal yola düşüyor ve kullanıcı çeviri yerine
  // "Görüşürüz." alıyordu. Model doğru cevabı üretiyordu ("See you
  // tomorrow."); tur ona hiç ulaşmıyordu.
  const requests = [
    "Bu cümleyi İngilizceye çevir: yarın görüşürüz",
    "Şu cümleyi düzelt: merhaba nasilsin",
    '"iyi geceler" ne demek İngilizce?',
    "Günaydın kelimesinin kökeni nedir?",
    "Bana merhaba diyen bir şiir yaz",
  ];
  for (const prompt of requests) {
    assert.equal(isSocialChatPrompt(prompt), false, prompt);
  }

  // Gerçek sosyal turlar ucuz yolda kalır.
  for (const prompt of [
    "Selam",
    "Merhaba, nasılsın?",
    "selam nasılsın",
    "Teşekkürler",
    "iyi geceler",
    "naber",
  ]) {
    assert.equal(isSocialChatPrompt(prompt), true, prompt);
  }
});

test("a greeting carrying extra words costs a model call, not a wrong answer", () => {
  // "Selam Elyan, nasıl gidiyor?" ucuz yolu KAYBEDER, çünkü "nasıl gidiyor"
  // sosyal desenlerde yok ve geriye iki terim kalıyor. Bilinçli takas: bu
  // istem modele gider ve model onu zaten doğru cevaplar. Bir model çağrısı,
  // yanlış cevaptan ucuzdur. Eşiği gevşetmek "Şu cümleyi düzelt: merhaba
  // nasilsin" istemini (aynı iki terim) geri sokardı.
  assert.equal(isSocialChatPrompt("Selam Elyan, nasıl gidiyor?"), false);
});
