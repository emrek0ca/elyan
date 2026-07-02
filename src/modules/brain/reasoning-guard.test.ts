import assert from "node:assert/strict";
import test from "node:test";
import {
  classifyReasoningDump,
  extractFinalAnswerFromReasoningDump,
  looksLikeReasoningDumpOpening,
} from "./reasoning-guard.js";

/* Prod ekran görüntüsünden birebir dump ("Bana bi hayvan ismi söyle" vakası).
 * Satırların çoğu tek tek sanitizer'dan geçebiliyor — bütüncül sınıflandırma
 * şart. */
const PROD_DUMP = [
  "The user's preferred language is Turkish.",
  'The user\'s goal is explicitly "Bana bi hayvan ismi söyle".',
  'I should provide a single animal name in Turkish, or perhaps a few options if appropriate, but the request is simple: "tell me an animal name".',
  "I will provide one clear animal name, maybe with a brief, warm touch as per the persona (Elyan).",
  '"Kurt" (Wolf) or "Penguen" (Penguin) or "Kaplan" (Tiger).',
  'Let\'s go with "Penguen" (Penguin) or "Kurt" (Wolf).',
  'Actually, just giving one name is best. "Kurt" is simple. Or "Fok".',
  'Let\'s say "Kurt".',
  'Wait, the prompt says "Bana bi hayvan ismi söyle".',
  "I'll reply: \"Kurt.\" or \"Penguen.\"",
  'Let\'s add a tiny bit of warmth: "Kurt. Başka bir tür mü arıyorsun?" (Wolf. Are you looking for another type?)',
  'Or simply: "Kurt."',
  "The user's previous goal was the same.",
  'I will just say "Kurt." and maybe ask if they need more.',
  'Actually, "Penguen" is friendly.',
  'Let\'s stick to "Kurt".',
  'Response: "Kurt. Başka bir hayvan türü mü aklında var?"',
  "Keep it concise.",
  '"Kurt." is enough.',
  "Done.",
  "Checking constraints: concise, grounded, Turkish.",
].join("\n");

test("classifyReasoningDump flags the production reasoning dump", () => {
  const result = classifyReasoningDump(PROD_DUMP);
  assert.equal(result.isDump, true);
  assert.ok(result.score >= 0.5, `expected high meta score, got ${result.score}`);
});

test("classifyReasoningDump does not flag ordinary answers", () => {
  assert.equal(
    classifyReasoningDump("Kurt. Başka bir hayvan türü mü aklında var?").isDump,
    false,
  );
  assert.equal(
    classifyReasoningDump(
      [
        "Kuantum bilgisayarlar klasik bitler yerine kübitler kullanır.",
        "Kübitler süperpozisyon sayesinde aynı anda birden fazla durumda olabilir.",
        "Bu da belirli problemlerde üstel hız kazancı sağlar.",
      ].join("\n"),
    ).isDump,
    false,
  );
  // Markdown başlıklı, listeli normal cevap
  assert.equal(
    classifyReasoningDump(
      [
        "# Plan Karşılaştırma",
        "- Free: 5 saatlik pencere",
        "- Pro: sınırsız kullanım",
        "Detay istersen söyle.",
      ].join("\n"),
    ).isDump,
    false,
  );
});

test("looksLikeReasoningDumpOpening catches dump openings within the first window", () => {
  assert.equal(looksLikeReasoningDumpOpening("The user's preferred language is Turkish."), true);
  assert.equal(looksLikeReasoningDumpOpening("I should provide a single animal name"), true);
  assert.equal(looksLikeReasoningDumpOpening("Okay, the user wants an animal name."), true);
  assert.equal(looksLikeReasoningDumpOpening("Kullanıcının istediği basit bir hayvan ismi."), true);
  assert.equal(looksLikeReasoningDumpOpening("Wait, the prompt says something else."), true);
});

test("looksLikeReasoningDumpOpening leaves normal answer openings alone", () => {
  assert.equal(looksLikeReasoningDumpOpening("Kurt! Başka ister misin?"), false);
  assert.equal(looksLikeReasoningDumpOpening("Merhaba! Sana bir hayvan ismi söyleyeyim: Kurt."), false);
  assert.equal(looksLikeReasoningDumpOpening("# Rapor Özeti"), false);
  assert.equal(looksLikeReasoningDumpOpening("2024 verilerine göre enflasyon şöyle seyretti:"), false);
  assert.equal(looksLikeReasoningDumpOpening("Elbette, hemen açıklayayım."), false);
});

test("extractFinalAnswerFromReasoningDump recovers the intended answer from the prod dump", () => {
  const answer = extractFinalAnswerFromReasoningDump(PROD_DUMP);
  assert.equal(answer, "Kurt. Başka bir hayvan türü mü aklında var?");
});

test("extractFinalAnswerFromReasoningDump falls back to speech and quoted candidates", () => {
  assert.equal(
    extractFinalAnswerFromReasoningDump(
      'The user wants a greeting. I\'ll reply: "Merhaba! Nasıl yardımcı olabilirim?"',
    ),
    "Merhaba! Nasıl yardımcı olabilirim?",
  );
  // Etiket yok, konuşma kalıbı yok → son yarıdaki son tırnaklı aday
  assert.equal(
    extractFinalAnswerFromReasoningDump(
      [
        "The user asked for a color.",
        "Options are red or blue.",
        'Let me pick. Final choice below.',
        '"Mavi güzel bir seçim olur."',
      ].join("\n"),
    ),
    "Mavi güzel bir seçim olur.",
  );
});

test("extractFinalAnswerFromReasoningDump returns null when no answer candidate exists", () => {
  assert.equal(
    extractFinalAnswerFromReasoningDump("The user wants something. I should think about it."),
    null,
  );
  assert.equal(extractFinalAnswerFromReasoningDump(""), null);
});

/* Prod 08:33 ekran görüntüsünden birebir ikinci dump şekli ("İos ve android
 * geliştirmeyi karşılaştır ama tablo yapma" vakası): "Here's a thinking"
 * açılışı + numaralı/bullet'lı "Etiket: değer" protokol yansıması satırları.
 * İlk guard sürümü bunu kaçırdı — açılış deseni "here's a thinking"i
 * tanımıyordu ve `^` anchor'lu meta desenler "2.- Format: ..." satırlarında
 * liste önekine takılıyordu. */
const PROD_DUMP_PROTOCOL_MIRROR = [
  "Here's a thinking1.- User- Topic: iOS vs Android development- Constraint: No tables",
  "- Topic: iOS vs Android development comparison",
  "2.- Format: Prose/bullet list, explicitly NO tables- Tone: Warm, professional, concise- Constraint: No tables",
  "- Topic: iOS vs Android development comparison",
  "- Format: Prose/bullet list, explicitly NO tables",
  "- Tone: Warm, professional, concise, grounded",
  "- Identity: Elyan",
  "- No hallucination, stick to knownfacts about iOS/Android development- Use web grounding if helpful, but general knowledge is sufficient- Constraint: No tables",
  "- Topic: iOS vs Android development comparison",
  "2. **Check Constraints & Policies:**- Data source: PUBLIC WEB GROUNDING is available.",
  "- Use web grounding if helpful, but general knowledge is sufficient here.",
].join("\n");

test("looksLikeReasoningDumpOpening catches the Here's-a-thinking protocol mirror", () => {
  assert.equal(looksLikeReasoningDumpOpening(PROD_DUMP_PROTOCOL_MIRROR), true);
  assert.equal(looksLikeReasoningDumpOpening("Here's a thinking process:"), true);
  assert.equal(looksLikeReasoningDumpOpening("Here is my thought process on this:"), true);
  // Gerçek cevaplar "Here's ..." ile başlayabilir — dump saymamalı.
  assert.equal(looksLikeReasoningDumpOpening("Here's a quick comparison of iOS and Android development."), false);
  assert.equal(looksLikeReasoningDumpOpening("Here's the recipe you asked for."), false);
});

test("classifyReasoningDump flags the protocol-mirror dump despite list prefixes", () => {
  const result = classifyReasoningDump(PROD_DUMP_PROTOCOL_MIRROR);
  assert.equal(result.isDump, true);
  assert.ok(result.score >= 0.5, `expected high meta score, got ${result.score}`);
});

test("classifyReasoningDump keeps real label-styled answers when meta ratio is low", () => {
  // Gerçek bir cevapta tek tük "Dil: Swift" gibi satırlar olabilir; oran
  // düşük kaldığı sürece dump sayılmamalı.
  const realAnswer = [
    "iOS ve Android geliştirme arasındaki temel farklar şunlar:",
    "iOS tarafında Swift ve Xcode kullanırsın; Apple'ın kapalı ekosistemi",
    "daha öngörülebilir cihaz çeşitliliği sunar.",
    "Android tarafında Kotlin ve Android Studio standarttır; cihaz",
    "çeşitliliği fazladır, test yükü buna göre artar.",
    "Yayınlama süreçlerinde App Store incelemesi genelde daha katıdır.",
    "Hangi tarafa odaklanacağın hedef kitlene bağlı.",
  ].join("\n");
  assert.equal(classifyReasoningDump(realAnswer).isDump, false);
});
