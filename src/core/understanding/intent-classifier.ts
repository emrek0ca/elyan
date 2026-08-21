import type { IntentClassification, RoutingHints, TaskUnderstandingInput, UnderstandingIntent } from "./types.js";
import { hasTurkicLanguageSignals } from "./turkic-language.js";
import {
  classifyIntentSemantic,
  classifyIntentTransformer,
} from "./intent-semantic.js";
import { explicitMobileContextKindsForPrompt } from "./context-packets.js";
import { trStemPattern } from "../../lib/tr-word-boundary.js";
import { isPlanOrStepRequest } from "./structured-output-policy.js";

const intentRules: Array<{ intent: UnderstandingIntent; patterns: RegExp[] }> = [
  {
    intent: "debugging",
    // Turkish letters break JS `\b` (ç/ı/ş/ü… are not ASCII word chars), which
    // makes `\bbug\b` falsely match "bug" inside "bugün". Unicode-letter
    // lookarounds keep the token boundaries correct across Turkish text.
    patterns: [
      /(?<!\p{L})(error|exception|stack trace|crash|fails?|failing|bug|broken|debug|fix|regression)(?!\p{L})/iu,
      /(?<!\p{L})(hata|bug|bozuk|patliyor|patlıyor|duzelt|düzelt|calismiyor|çalışmıyor)(?!\p{L})/iu,
    ],
  },
  {
    intent: "coding",
    patterns: [
      /\b(code|implement|refactor|typescript|javascript|python|swift|flutter|sql|api|backend|frontend|test)\b/i,
      /\b(kod|uygula|implement|refaktor|backend|frontend|test|repo|dosya)\b/i,
      // C/C++ ve sistem programlama: `\b` "+" karakterinde çalışmadığı için
      // c++ lookaround ile yakalanıyor. Tek başına "c" harfi çok geniş —
      // yalnızca dil/derleyici bağlamıyla eşleşir.
      /(?<!\p{L})(c\+\+|cpp|c\s*dili(?:yle|nde|ni)?|c\s+programlama|cmake|makefile|gcc|clang|msvc|gdb|valgrind|stl|raii|malloc|calloc|realloc|memcpy|sizeof|nullptr|unique_ptr|shared_ptr|constexpr|std::\w+)(?!\p{L})/iu,
      /(?<!\p{L})(pointer|i[şs]aret[çc]i|segfault|segmentation\s+fault|core\s+dump|memory\s+leak|bellek\s+s[ıi]z[ıi]nt[ıi]|undefined\s+behavior|tan[ıi]ms[ıi]z\s+davran[ıi][şs]|header\s+dosya|derleyici|compiler|linker|derleme\s+hata)(?!\p{L})/iu,
    ],
  },
  {
    intent: "research",
    patterns: [
      /\b(research|sources?|cite|citation|latest|compare|look up|verify|fact check|validate|investigate|analyze|analysis|evaluate|assessment|review|survey|overview)\b/i,
      /\b(araştır|kaynak|alıntı|güncel|karsilastir|karşılaştır|doğrula|dogrula|kanıtla|kanitla|incele|anket|genel bakış|genel bakis)\b/i,
      /\b(türk dünyası|turkic|oğuz|oguz|kıpçak|kipchak|karluk|qipchak|qarluq|azerbaijani|kazakh|kyrgyz|uzbek|turkmen|uyghur|tatar|bashkir|gagauz|karakalpak|sakha|chuvash)\b.*\b(araştır|arastir|incele|study|learn|öğren|ogren|compare|karşılaştır|karsilastir|gramer|grammar|lehçe|lehce|etimoloji|etymology|kaynak|source)\b/i,
      /\b(tarih|tarihsel|tarihçe|tarihce|historical|kronoloji|chronolog)\b/i,
      /\b(nüfus|nufus|population|gdp|gsyih|ekonomi|economy|istatistik|statistic|trend|büyüme|buyume|growth)\b/i,
      /(?<!\p{L})(analiz\s+et|değerlendir|degerlendir|karşılaştır|karsilastir|kıyasla|kiyasla)\p{L}*/iu,
      /(?<!\p{L})(etki\p{L}*|nas[ıi]l\s+etkil|sebep\p{L}*|neden\p{L}*)\s.{0,40}(ekonomi|toplum|dünya|sektör|piyasa|iş\s+dünya)/iu,
      /\b(yapay\s*zeka|artificial\s*intelligence|machine\s*learning|deep\s*learning|AI)\b.*\b(etki|analiz|gelecek|future|trend)\b/i,
    ],
  },
  {
    intent: "math",
    patterns: [
      /\b(math|solve|equation|integral|derivative|latex|proof|calculate|computation|formula)\b/i,
      /\b(matematik|denklem|integral|türev|ispat|hesapla|hesap|toplam|çarp|kaç tane|kaç kişi|kaç lira|kaçtır|sonuç|formül)\b/i,
      /(?<!\p{L})böl(?!\p{L}).{0,20}(?:\d|say[ıi]|kalan|pay|payda|bölüm|bölme)/iu,
      /(?<!\p{L})(koyun|inek|elma|araba|öğrenci|ogrenci|kişi|kisi)\p{L}*\s+\p{L}*\s*(?:var|kald[ıi]|eklen|satt[ıi]|ald[ıi]|toplam|ka[çc])\b/iu,
      /\b\d+\s*[\+\-\*\/\^]\s*\d+/,
      /\b\d+\s*[''](?:ın|in|un|ün|nın|nin|nun|nün)\b/i,
    ],
  },
  {
    intent: "document",
    patterns: [
      /\b(pdf|docx|xlsx|pptx|spreadsheet|presentation|document|export|ocr|scan)\b/i,
      /\b(belge|dokuman|döküman|sunum|tablo|dosya|ekli|sayfa|içerik|icerik|metin|word|tarat|tarama|ekran görüntüsü|ekran goruntusu|görüntü|goruntu)\b/i,
      /\b(ne yazıyor|ne yaziyo|içinde ne var|icinde ne var|okur musun|okurmusun|özetini çıkar|ozetini cikar|metni çıkar|metni cikar|belgeyi oku|dosyayı incele|dosyayi incele|görseli oku|gorseli oku|resimden oku|fotoğraftan oku|fotograftan oku|görselden metin çıkar|gorselden metin cikar)\b/i,
    ],
  },
  {
    intent: "writing",
    patterns: [
      /\b(write|rewrite|draft|polish|summarize|email|copy|tone|proofread|proof-read|copyedit|copy-edit|edit|grammar|spelling|orthography|punctuation|paraphrase|formalize|locali[sz]e)\b/i,
      /\b(yaz|duzenle|düzenle|ozetle|özetle|mail|metin|profesyonel(?:ce)?|imla|yazım|yazim|noktalama|redakte|redaksiyon|yeniden yaz|tekrar yaz|akıc[ıi]|düzgün Türkçe|dogru turkce|doğru türkçe|çeviri|ceviri|tercüme|tercume|translate|transliterate|gramer|grammar|dil bilgisi|dilbilgisi|üslup|uslup|parafraz|resmi(?:leştir|lestir)?|akademik|lehçe|lehce|language)\b/i,
    ],
  },
  {
    intent: "image",
    patterns: [
      /\b(image|photo|picture|ocr|vision|generate.*image|edit.*image|screenshot|scan|crop|extract text)\b/i,
      /\b(gorsel|görsel|resim|foto|ocr|tarama|tarat|ekran görüntüsü|ekran goruntusu|resimden|fotoğraftan|fotograftan|görselden|gorselden)\b/i,
    ],
  },
  {
    intent: "automation",
    patterns: [
      /\b(automate|automation|workflow|schedule|trigger|run task)\b/i,
      /\b(otomasyon|akış|akis|zamanla|tetikle)\b/i,
      /(?<!\p{L})(aç|kapat|indir|kaydet|yükle|yukle|çalıştır|calistir|kopyala|taşı|tasi|sil)(?!\p{L}).*(?<!\p{L})(dosya|uygulama|uygulama|safari|chrome|firefox|finder|klasör|klasor|terminal)(?!\p{L})/iu,
      /(?<!\p{L})(dosya|uygulama|safari|chrome|firefox|finder|klasör|klasor|terminal)(?!\p{L}).*(?<!\p{L})(aç|kapat|indir|kaydet|yükle|yukle|çalıştır|calistir|kopyala|taşı|tasi|sil)(?!\p{L})/iu,
    ],
  },
  {
    intent: "browser",
    patterns: [
      /\b(browser|website|web page|crawl|scrape|click|navigate)\b/i,
      /\b(tarayıcı|tarayici|site|web|gez|tikla|tıkla)\b/i,
      /(?<!\p{L})(safari|chrome|firefox|edge|arc)\b/iu,
      /(?<!\p{L})(aç|ac|git|gir|ziyaret et|araştır|arastir|bul)(?!\p{L}).*(?<!\p{L})(site|sayfa|web|link|url|http)(?!\p{L})/iu,
      /(?<!\p{L})(site|sayfa|web|link|url|http)(?!\p{L}).*(?<!\p{L})(aç|ac|git|gir|ziyaret et|araştır|arastir|bul)(?!\p{L})/iu,
    ],
  },
  {
    intent: "computer",
    patterns: [
      /\b(computer|desktop|screenshot|hotkey|keyboard|mouse|window)\b/i,
      // `\b` ile yazıldığında "masaüstümde" YANLIŞLIKLA eşleşiyordu (ASCII
      // `\b` için 'ü'→'m' geçişi sınır gibi görünür), "bilgisayarımda" ise
      // hiç eşleşmiyordu. `trStemPattern` ikisini de doğru yapar: kök +
      // sınırlı ek toleransı. "fare" kısa ve ek almadan kullanılıyor, yine de
      // toleransla güvenli ("farelerin" da fare demektir).
      trStemPattern([
        "bilgisayar",
        "masaustu",
        "masaüstü",
        "ekran görüntüsü",
        "ekran goruntusu",
        "klavye",
        "fare",
      ]),
      /(?<!\p{L})(ekran görüntüsü al|ekran goruntusu al|screenshot al|video kaydet|ses kaydet)(?!\p{L})/iu,
      /(?<!\p{L})(yerel|local)(?!\p{L}).*(?<!\p{L})(dosya|klasör|klasor|uygulama|program)(?!\p{L})/iu,
    ],
  },
  {
    intent: "planning",
    patterns: [
      /\b(plan|planla|planning|roadmap|strategy|steps|scope|architecture|ecosystem|system design|workflow)\b/i,
      /\b(plan|planla|yol haritasi|yol haritası|strateji|mimari|ekosistem|iş akışı|is akisi)\b/i,
      /(?<!\p{L})(?:\d+\s*)?(?:ad[ıi]ml[ıi]k|g[üu]nl[üu]k|haftal[ıi]k|a[şs]amal[ıi])[\s\S]{0,80}?(?:program|takvim|rutin|plan)[\s\S]{0,40}?(?:[çc][ıi]kar|haz[ıi]rla|olu[şs]tur|yaz|[öo]ner)(?!\p{L})/iu,
      /(?<!\p{L})(?:[çc]al[ıi][şs]ma|ders|haz[ıi]rl[ıi]k|[öo][ğg]renme|proje)[\s\S]{0,80}?(?:program|takvim|rutin|plan|yol haritas[ıi])[\s\S]{0,40}?(?:[çc][ıi]kar|haz[ıi]rla|olu[şs]tur|yaz|[öo]ner)(?!\p{L})/iu,
    ],
  },
];

function unique<T>(values: T[]): T[] {
  return [...new Set(values)];
}

// Yerel çalışma zamanı KANITI — ayrıntılı gerekçe `requiresLocalRuntime`
// tanımının başında.
//
// `LOCAL_OBJECT`: kullanıcının bilgisayarındaki somut nesneler.
// `LOCAL_ACTION`: o nesneye uygulanabilen eylem fiilleri.
// `TURKISH_SUFFIX`: eklemeli dil toleransı (`dosya` → `dosyayı`,
// `masaüstü` → `masaüstüne`). Türkçe ek zincirleri kısadır; 8 harf yeter.
const LOCAL_OBJECT =
  "masaüstü|masaustu|dosya|klasör|klasor|terminal|tarayıcı|tarayici|pencere|uygulama|safari|chrome|firefox|finder|ekran görüntüsü|ekran goruntusu|ekran kaydı|ekran kaydi" +
  // Belirsiz İngilizce konu isimleri: tek başına kanıt değil, eşleşme şart.
  "|desktop|folder|terminal|shell|browser";
const LOCAL_ACTION =
  "aç|ac|kapat|çalıştır|calistir|başlat|baslat|indir|kaydet|taşı|tasi|sil|kopyala|oluştur|olustur|yaz|ekle|yeniden adlandır|yeniden adlandir" +
  "|open|close|run|launch|download|save|move|delete|copy|create|rename";
const TURKISH_SUFFIX = String.raw`\p{L}{0,8}`;

/**
 * Yerel bir nesne + eylem fiili eşleşmesi. İKİ YÖNLÜ: Türkçe fiil-sonda
 * olduğu için asıl sıra `İSİM … FİİL`, ama emir kipi `FİİL … İSİM` de gelir.
 * Araya en fazla bir cümlecik girebilir; cümle sonu işaretleri sınırdır ki
 * "dosya nedir? sonra safariyi aç" gibi iki ayrı cümle birleşmesin.
 */
const LOCAL_ACTION_TARGET_PATTERN = new RegExp(
  `(?<!\\p{L})(?:${LOCAL_OBJECT})${TURKISH_SUFFIX}(?!\\p{L})[^.!?]{0,40}?(?<!\\p{L})(?:${LOCAL_ACTION})${TURKISH_SUFFIX}(?!\\p{L})` +
    `|(?<!\\p{L})(?:${LOCAL_ACTION})${TURKISH_SUFFIX}(?!\\p{L})[^.!?]{0,40}?(?<!\\p{L})(?:${LOCAL_OBJECT})${TURKISH_SUFFIX}(?!\\p{L})`,
  "iu",
);

/**
 * Yalnız cihazda bulunabilen şeyler. Bunlar konu olarak geçse bile yerel
 * çalışma zamanı ister; bulutta karşılığı YOKTUR.
 */
const LOCAL_DEVICE_ONLY_PATTERN =
  /(?<!\p{L})(tuş kısayolu|tus kisayolu|ses kayıt|ses kayit|kamera|mikrofon|bildirim gönder|bildirim gonder)\p{L}{0,8}(?!\p{L})/iu;

function localActionOnLocalObject(text: string): boolean {
  return LOCAL_ACTION_TARGET_PATTERN.test(text);
}

function calculateRoutingHints(intent: UnderstandingIntent, requiresLocalRuntime: boolean, requiresCitation: boolean): RoutingHints {
  if (requiresLocalRuntime) {
    return {
      mode: "local_private",
      preferredCapabilities: unique([intent, "tool_use", "local_runtime"].filter((value) => value !== "unknown")),
      avoidCloud: true,
      requiresLocalRuntime: true,
    };
  }

  if (requiresCitation || intent === "research") {
    return {
      mode: "research",
      preferredCapabilities: ["retrieval", "citation"],
      avoidCloud: false,
      requiresLocalRuntime: false,
    };
  }

  if (["coding", "debugging", "math", "document", "automation"].includes(intent)) {
    return {
      mode: "task",
      preferredCapabilities: unique([intent === "debugging" ? "code" : intent, "reasoning", "tool_use"]),
      avoidCloud: false,
      requiresLocalRuntime: false,
    };
  }

  return {
    mode: "fast",
    preferredCapabilities: intent === "chat" || intent === "unknown" ? [] : [intent],
    avoidCloud: false,
    requiresLocalRuntime: false,
  };
}

function isProofreadingRequest(text: string): boolean {
  return /\b(imla|yazım|yazim|noktalama|dil bilgisi|dilbilgisi|gramer|grammar|spelling|orthography|punctuation|proofread|proof-read|copyedit|copy-edit|redaksiyon)\b/i.test(
    text,
  );
}

function isExplicitBriefProseRequest(text: string): boolean {
  return /\b(kısaca|kisaca|özetle|ozetle|özet halinde|ozet halinde|paragraf halinde|paragraf olarak|tek c[üu]mle\p{L}*|düz yazı|duz yazi)\b/iu.test(
    text,
  );
}

function isExplicitPlanningRequest(text: string): boolean {
  return /(?<!\p{L})(planla|plan|program|takvim|roadmap|yol haritas[ıi]|strateji|strategy|ad[ıi]mlara b[öo]l|ad[ıi]m ad[ıi]m|[çc][ıi]kar|haz[ıi]rla|olu[şs]tur)(?!\p{L})/iu.test(
    text,
  );
}

export function isCurrentUserIdentityQuery(text: string): boolean {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return false;
  }
  return [
    /^(?:peki\s+)?ben kimim[?!.]*$/iu,
    /^(?:peki\s+)?beni (?:ne kadar\s+)?tan[ıi]yor musun[?!.]*$/iu,
    /^(?:benim hakk[ıi]mda|hakk[ıi]mda) ne biliyorsun[?!.]*$/iu,
    /^kim oldu[ğg]umu biliyor musun[?!.]*$/iu,
    /^(?:so,?\s+)?who am i[?!.]*$/iu,
    /^(?:what|how much) do you know about me[?!.]*$/iu,
    /^do you know (?:who i am|me)[?!.]*$/iu,
    /^describe me[?!.]*$/iu,
  ].some((pattern) => pattern.test(normalized));
}

function calculateReasoningMode(input: {
  primaryIntent: UnderstandingIntent;
  requiresRetrieval: boolean;
  requiresToolUse: boolean;
  requiresLongRunningTask: boolean;
  confidence: number;
}): "fast" | "balanced" | "deep" {
  if (input.primaryIntent === "planning" || input.requiresRetrieval) {
    return "deep";
  }
  // Research intent always gets deep reasoning for thorough analysis
  if (input.primaryIntent === "research") {
    return "deep";
  }
  if (
    input.requiresLongRunningTask &&
    !["coding", "debugging", "document", "image", "automation", "browser", "computer"].includes(input.primaryIntent)
  ) {
    return "deep";
  }
  if (input.requiresToolUse || ["coding", "debugging", "document", "browser", "computer", "automation", "image"].includes(input.primaryIntent)) {
    return "balanced";
  }
  // Non-trivial math is a deep task: the fast model is useful for short prose,
  // but not for derivations, proofs, or multi-step calculations.
  if (input.primaryIntent === "math") {
    return "deep";
  }
  if (input.confidence < 0.45) {
    return "balanced";
  }
  return "fast";
}

function calculateLikelyAnswerShape(input: {
  primaryIntent: UnderstandingIntent;
  requiresRetrieval: boolean;
  requiresToolUse: boolean;
  requiresCitation: boolean;
  requiresLongRunningTask: boolean;
}): string {
  if (input.primaryIntent === "research" || input.requiresCitation || input.requiresRetrieval) {
    return "grounded answer with sources and caveats";
  }
  if (input.primaryIntent === "writing") {
    return "polished text with the requested tone";
  }
  if (input.primaryIntent === "math") {
    return "concise solution with the calculation";
  }
  if (input.primaryIntent === "document") {
    return "read, transform, or export the document";
  }
  if (input.primaryIntent === "planning" || input.requiresLongRunningTask) {
    return "clear breakdown with next steps and tradeoffs";
  }
  if (input.requiresToolUse) {
    return "operational answer with concrete actions and execution boundaries";
  }
  return "direct answer with the minimum needed context";
}

function extractEcosystemFocus(text: string, intent: UnderstandingIntent): string[] {
  const lowered = text.toLowerCase();
  const hints = new Set<string>();

  if (/\belyan\b/i.test(text)) {
    hints.add("elyan_ecosystem");
  }
  if (/\b(desktop|runtime|pairing|pair|local runtime|local_runtime)\b/i.test(text)) {
    hints.add("desktop_runtime");
  }
  if (/\b(mobile|flutter|ios|android)\b/i.test(text)) {
    hints.add("mobile_surface");
  }
  if (/\b(backend|server|api|control plane|control-plane|control_plane)\b/i.test(text)) {
    hints.add("backend_control_plane");
  }
  if (/\b(brain|memory|retrieval|rag|learning|understanding)\b/i.test(text)) {
    hints.add("brain_understanding");
  }
  if (/\b(quota|billing|auth|subscription|credit|usage)\b/i.test(text)) {
    hints.add("policy_and_quota");
  }
  if (hasTurkicLanguageSignals(text)) {
    hints.add("turkic_language_family");
  }
  if (intent === "planning" && /\b(architecture|mimari|ecosystem|ekosistem)\b/i.test(lowered)) {
    hints.add("system_architecture");
  }

  return [...hints].slice(0, 6);
}

export function classifyIntent(input: TaskUnderstandingInput): IntentClassification {
  try {
    const text = `${input.title ?? ""}\n${input.message ?? ""}`.slice(0, 24_000);
    const lower = text.toLowerCase();
    const matched: UnderstandingIntent[] = [];
    const architecturePrompt = /\b(architecture|system design|ecosystem|ekosistem|mimari|how.*fit together|nasıl.*birlikte|ekosystem)\b/i.test(text);
    const briefProseRequest = isExplicitBriefProseRequest(text);
    const currentUserIdentityQuery = isCurrentUserIdentityQuery(text);
    const explicitMobileContextKinds =
      explicitMobileContextKindsForPrompt(input.message);
    const explicitPlanRequest =
      explicitMobileContextKinds.length === 0 && isPlanOrStepRequest(text);

    if (architecturePrompt && (!briefProseRequest || isExplicitPlanningRequest(text))) {
      matched.push("planning");
    }
    if (isProofreadingRequest(text)) {
      matched.push("writing");
    }

    for (const rule of intentRules) {
      if (rule.patterns.some((pattern) => pattern.test(text))) {
        matched.push(rule.intent);
      }
    }
    if (briefProseRequest && !isExplicitPlanningRequest(text)) {
      for (let index = matched.length - 1; index >= 0; index -= 1) {
        if (matched[index] === "planning") {
          matched.splice(index, 1);
        }
      }
    }
    // Personal health/location/calendar questions are requests for already
    // permission-filtered mobile context, not desktop-computer operations.
    // Reuse the context-packet detector so routing and injection share one
    // semantic truth instead of teaching the classifier another phrase list.
    if (explicitMobileContextKinds.length > 0) {
      matched.splice(0, matched.length);
    }

    // Semantic fallback recovers paraphrases that would otherwise collapse to
    // chat, and lets a strong subject intent outrank a generic writing action.
    let semanticIntent: UnderstandingIntent | null = null;
    let semanticScore = 0;
    if (
      explicitMobileContextKinds.length === 0 &&
      (matched.length === 0 ||
        (matched.length === 1 && matched[0] === "writing")) &&
      text.trim().length > 0
    ) {
      const semantic = classifyIntentSemantic(text);
      if (semantic && (matched.length === 0 || semantic.intent !== "writing")) {
        semanticIntent = semantic.intent;
        semanticScore = semantic.score;
      }
    }

    const primaryIntent =
      explicitMobileContextKinds.length > 0
        ? "chat"
        : explicitPlanRequest
          ? "planning"
        : semanticIntent ?? matched[0] ?? (text.trim().length > 0 ? "chat" : "unknown");
    const secondaryIntents = unique(matched.filter((intent) => intent !== primaryIntent));
    // A compound request can be ordered by a generic intent first while the
    // semantic secondary intent carries the actual computer surface. Treat
    // that typed signal as local evidence instead of depending on one exact
    // spelling or suffix in the raw message.
    // YEREL ÇALIŞMA ZAMANI KANITI — konu değil, HEDEF.
    //
    // Eski sürüm iki katmerli hatayla TERS çalışıyordu (ölçüldü 2026-08-20):
    //
    //   "masaüstüne rapor kaydet"          → bulut   (YANLIŞ)
    //   "dosyayı sil" / "safariyi aç"       → bulut   (YANLIŞ)
    //   "pencere yalıtımı hakkında bilgi"   → yerel   (YANLIŞ)
    //   "ekran kartı fiyatları ne alemde"   → yerel   (YANLIŞ)
    //
    // Sebep 1 — SÖZ DİZİMİ: eylem-hedef deseni `FİİL … İSİM` sırası
    // bekliyordu. Türkçe fiil-sonda bir dildir; asıl sıra `İSİM … FİİL`.
    // Dolayısıyla desen en açık yerel komutların HİÇBİRİNE uymuyordu ve
    // pratikte ölüydü.
    //
    // Sebep 2 — EK TOLERANSI: `(?!\p{L})` sınırı eklemeli dilde çöküyor.
    // `dosyayı`, `masaüstüne`, `klasörü`, `safariyi` — hepsi kaçıyordu.
    //
    // Sonuç: tek çalışan sinyal ÇIPLAK KONU İSMİ listesiydi ("dosya", "ekran",
    // "pencere" cümlede geçsin yeter). O da konu ile hedefi ayırt edemediği
    // için sohbet sorularını yerel çalışma zamanına sürüyordu.
    //
    // Yeni kural: çıplak konu ismi TEK BAŞINA yerel kanıt DEĞİLDİR. Yerel
    // çalışma zamanı ancak bir yerel NESNE bir EYLEM FİİLİYLE eşleştiğinde
    // gerekir — iki yönlü (İSİM…FİİL ve FİİL…İSİM) ve ek toleranslı.
    // ⚠ SEMANTİK OTORİTE DENENDİ VE ÖLÇÜMLE GERİ ALINDI (2026-08-20).
    //
    // `intent-semantic.ts`'in prototip mekanizmasıyla bu soruya ayrı bir
    // semantik karar katmanı yazıldı ve TUTULAN KÜMEDE ölçüldü (15 cümle,
    // hiçbiri tohum listesinde yok):
    //
    //   eski desen     9/15   yanlış-YEREL: 0   kaçırılan-yerel: 6
    //   bu desen       9/15   yanlış-YEREL: 0   kaçırılan-yerel: 6
    //   hash-semantik  9/15   yanlış-YEREL: 3   kaçırılan-yerel: 3
    //
    // Skor aynı ama hata SINIFI daha kötü: hash katmanı "migren için ne
    // önerirsin" gibi düz sohbeti masaüstü çalışma zamanına yolluyordu.
    // Sebep: `buildHashedKnowledgeEmbedding` gerçek bir anlam modeli değil,
    // hash'lenmiş sözcük torbasıdır — tohumla kelime paylaşmayan cümlede
    // anlamı değil sözcük örtüşmesini ölçer. "Semantik" adını taşıyan bu
    // SENKRON katman bu kararı veremez.
    //
    // GERÇEK ÇÖZÜM (yapılmadı, ayrı iş): karar `classifyIntent`in senkron
    // yolundan çıkıp anlama zarfına (gerçek model ya da e5 transformer yolu)
    // taşınmalı; aşağıdaki desenler yalnız model erişilemezken devreye giren
    // bozuk-mod yedeği olmalı. Buradaki hâliyle o yedek en azından TERS
    // çalışmıyor — düzeltmeden önce çalışıyordu.
    const requiresLocalRuntime =
      ["automation", "browser", "computer"].includes(primaryIntent) ||
      secondaryIntents.includes("computer") ||
      // Cihazda var, bulutta yok — konu olarak geçse bile cihaz ister.
      LOCAL_DEVICE_ONLY_PATTERN.test(text) ||
      // Yerel NESNE + EYLEM eşleşmesi (iki yönlü, ek toleranslı).
      localActionOnLocalObject(text) ||
      // Tartışmasız İngilizce CİHAZ EYLEMLERİ. `terminal`, `browser`, `shell`,
      // `desktop`, `local` buradan ÇIKARILDI: onlar konu ismidir ("terminal
      // hızı nasıl ölçülür", "browser market share") ve tek başına kanıt
      // sayılınca Türkçe tarafla aynı yanlış-YEREL hatasını üretiyorlardı.
      // Artık yukarıdaki nesne+eylem eşleşmesinden geçiyorlar.
      /\b(file system|screenshot|hotkey|keyboard shortcut|window management|screen record|screen capture|open app|launch app|quit app|close app|finder|dock)\b/i.test(text);
    const requiresRetrieval =
      currentUserIdentityQuery ||
      primaryIntent === "research" ||
      /\b(previous|past|memory|context|docs|retrieval|history)\b/i.test(text);
    const requiresCitation = primaryIntent === "research" || /\b(cite|citation|source|kaynak)\b/i.test(text);
    const requiresToolUse =
      requiresLocalRuntime || ["coding", "debugging", "document", "image", "automation", "browser", "computer"].includes(primaryIntent);
    const requiresLongRunningTask =
      requiresToolUse || /\b(build|test|run|export|generate|crawl|analyze|migrate|deploy)\b/i.test(lower);
    const privacyRisk =
      requiresLocalRuntime || /\b(secret|token|password|private|credential|local file|downloads|desktop)\b/i.test(lower)
        ? "high"
        : requiresRetrieval || requiresToolUse
          ? "medium"
          : "low";
    const confidence =
      currentUserIdentityQuery
        ? 0.96
        : explicitMobileContextKinds.length > 0
          ? 0.95
        : semanticIntent
          ? Math.min(0.6, 0.4 + semanticScore)
        : matched.length > 0
          ? Math.min(0.95, 0.62 + matched.length * 0.1)
          : primaryIntent === "chat"
            ? 0.55
            : 0.2;
    const reasoningMode = calculateReasoningMode({
      primaryIntent,
      requiresRetrieval,
      requiresToolUse,
      requiresLongRunningTask,
      confidence,
    });
    const likelyAnswerShape = calculateLikelyAnswerShape({
      primaryIntent,
      requiresRetrieval,
      requiresToolUse,
      requiresCitation,
      requiresLongRunningTask,
    });

    return {
      primaryIntent,
      secondaryIntents,
      requiresLocalRuntime,
      requiresRetrieval,
      requiresToolUse,
      requiresCitation,
      requiresLongRunningTask,
      privacyRisk,
      confidence,
      reason:
        currentUserIdentityQuery
          ? "user_identity_query"
          : explicitMobileContextKinds.length > 0
            ? `mobile_context_${explicitMobileContextKinds.join("_")}`
          : matched.length > 0
          ? `matched_${primaryIntent}_rules`
          : semanticIntent
            ? `semantic_${primaryIntent}`
            : "no_rule_match",
      taskFrame: {
        goal:
          currentUserIdentityQuery
            ? "describe the current user from verified current-user memory"
            : explicitMobileContextKinds.length > 0
              ? "answer from current permission-filtered mobile context"
            : primaryIntent === "research"
            ? "understand or verify external facts"
            : primaryIntent === "planning"
              ? "break the request into a reliable plan"
              : primaryIntent === "debugging"
                ? "diagnose and fix the problem"
                : primaryIntent === "coding"
                  ? "design or change implementation safely"
                  : primaryIntent === "writing"
                    ? "compose or polish text"
                    : primaryIntent === "math"
                      ? "solve the problem exactly"
                      : primaryIntent === "document"
                        ? "read, transform, or export the document"
                        : primaryIntent === "image"
                          ? "inspect or edit the image"
                          : primaryIntent === "browser"
                            ? "navigate or inspect the web surface"
                            : primaryIntent === "computer"
                              ? "use the desktop surface safely"
                              : primaryIntent === "automation"
                                ? "execute a bounded workflow"
                                : "answer naturally and directly",
        likelyAnswerShape: currentUserIdentityQuery
          ? "grounded current-user profile summary or an honest empty-profile fallback"
          : likelyAnswerShape,
        reasoningMode,
        shouldClarify:
          !currentUserIdentityQuery &&
          explicitMobileContextKinds.length === 0 &&
          (confidence < 0.5 || (primaryIntent === "chat" && matched.length === 0 && text.trim().length < 12)),
      },
      ecosystemHints: extractEcosystemFocus(text, primaryIntent),
      routingHints: calculateRoutingHints(primaryIntent, requiresLocalRuntime, requiresCitation),
    };
  } catch {
    return {
      primaryIntent: "unknown",
      secondaryIntents: [],
      requiresLocalRuntime: false,
      requiresRetrieval: false,
      requiresToolUse: false,
      requiresCitation: false,
      requiresLongRunningTask: false,
      privacyRisk: "low",
      confidence: 0,
      reason: "classifier_failed",
      taskFrame: {
        goal: "answer or route safely",
        likelyAnswerShape: "direct answer with caution",
        reasoningMode: "fast",
        shouldClarify: true,
      },
      ecosystemHints: [],
      routingHints: calculateRoutingHints("unknown", false, false),
    };
  }
}

/**
 * Optional transformer enhancement for the sync classifier above. When the
 * sync path lands on "chat"/"unknown" or matches only weakly, the e5-small
 * embedder gives a real-semantic second opinion. Async by necessity (the
 * model call is non-blocking but takes ~50ms warm). Callers in async contexts
 * can `await enhanceIntentWithTransformer(text, classification)` to upgrade
 * the classification when the transformer disagrees with high confidence.
 *
 * Idempotent: when the transformer isn't loaded yet, returns the original.
 */
export async function enhanceIntentWithTransformer(
  text: string,
  current: IntentClassification,
  options: { resolveConflicts?: boolean } = {},
): Promise<IntentClassification> {
  const normalizedText = text.replace(/\s+/g, " ").trim();
  if (
    normalizedText.length <= 96 &&
    current.primaryIntent === "chat" &&
    !options.resolveConflicts
  ) {
    return current;
  }
  // Only re-classify when the sync path was unsure: "chat", "unknown", or
  // confidence below 0.6. A typed compound turn is the exception: the
  // synchronous classifier has already told us that more than one intent is
  // present, so a semantic model must resolve the precedence instead of
  // letting the first lexical rule become the route authority.
  if (
    !options.resolveConflicts &&
    current.primaryIntent !== "chat" &&
    current.primaryIntent !== "unknown" &&
    current.confidence >= 0.6
  ) {
    return current;
  }
  const result = await classifyIntentTransformer(text).catch(() => null);
  if (!result) return current;
  if (result.intent === current.primaryIntent) return current;
  // The transformer must beat a strong margin — semantic intent classification
  // on short prompts can be noisy. 0.68 cosine on e5 is a meaningful signal.
  if (result.score < 0.68) return current;
  return {
    ...current,
    primaryIntent: result.intent,
    secondaryIntents: unique([
      current.primaryIntent,
      ...current.secondaryIntents,
    ]).filter((intent) => intent !== result.intent),
    confidence: Math.max(current.confidence, Math.min(0.85, result.score)),
    reason: `${current.reason}+transformer_${result.intent}`,
  };
}
