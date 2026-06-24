import type { IntentClassification, RoutingHints, TaskUnderstandingInput, UnderstandingIntent } from "./types.js";
import { hasTurkicLanguageSignals } from "./turkic-language.js";

const intentRules: Array<{ intent: UnderstandingIntent; patterns: RegExp[] }> = [
  {
    intent: "debugging",
    patterns: [
      /\b(error|exception|stack trace|crash|fails?|failing|bug|broken|debug|fix|regression)\b/i,
      /\b(hata|bug|bozuk|patliyor|patlıyor|duzelt|düzelt|calismiyor|çalışmıyor)\b/i,
    ],
  },
  {
    intent: "coding",
    patterns: [
      /\b(code|implement|refactor|typescript|javascript|python|swift|flutter|sql|api|backend|frontend|test)\b/i,
      /\b(kod|uygula|implement|refaktor|backend|frontend|test|repo|dosya)\b/i,
    ],
  },
  {
    intent: "research",
    patterns: [
      /\b(research|sources?|cite|citation|latest|compare|look up|verify|fact check|validate)\b/i,
      /\b(araştır|kaynak|alıntı|güncel|karsilastir|karşılaştır|doğrula|dogrula|kanıtla|kanitla)\b/i,
      /\b(türk dünyası|turkic|oğuz|oguz|kıpçak|kipchak|karluk|qipchak|qarluq|azerbaijani|kazakh|kyrgyz|uzbek|turkmen|uyghur|tatar|bashkir|gagauz|karakalpak|sakha|chuvash)\b.*\b(araştır|arastir|incele|study|learn|öğren|ogren|compare|karşılaştır|karsilastir|gramer|grammar|lehçe|lehce|etimoloji|etymology|kaynak|source)\b/i,
    ],
  },
  {
    intent: "math",
    patterns: [/\b(math|solve|equation|integral|derivative|latex|proof)\b/i, /\b(matematik|denklem|integral|türev|ispat)\b/i],
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
    patterns: [/\b(automate|automation|workflow|schedule|trigger|run task)\b/i, /\b(otomasyon|akış|akis|zamanla|tetikle)\b/i],
  },
  {
    intent: "browser",
    patterns: [/\b(browser|website|web page|crawl|scrape|click|navigate)\b/i, /\b(tarayıcı|site|web|gez|tikla|tıkla)\b/i],
  },
  {
    intent: "computer",
    patterns: [/\b(computer|desktop|screenshot|hotkey|keyboard|mouse|window)\b/i, /\b(bilgisayar|masaustu|masaüstü|ekran görüntüsü|klavye|fare)\b/i],
  },
  {
    intent: "planning",
    patterns: [
      /\b(plan|roadmap|strategy|steps|scope|architecture|ecosystem|system design|workflow)\b/i,
      /\b(plan|yol haritasi|yol haritası|strateji|mimari|ekosistem|iş akışı|is akisi)\b/i,
    ],
  },
];

function unique<T>(values: T[]): T[] {
  return [...new Set(values)];
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
  if (
    input.requiresLongRunningTask &&
    !["coding", "debugging", "document", "image", "automation", "browser", "computer"].includes(input.primaryIntent)
  ) {
    return "deep";
  }
  if (input.requiresToolUse || ["coding", "debugging", "document", "browser", "computer", "automation", "image"].includes(input.primaryIntent)) {
    return "balanced";
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

    if (architecturePrompt) {
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

    const primaryIntent = matched[0] ?? (text.trim().length > 0 ? "chat" : "unknown");
    const secondaryIntents = unique(matched.filter((intent) => intent !== primaryIntent));
    const requiresLocalRuntime =
      ["automation", "browser", "computer"].includes(primaryIntent) ||
      /\b(local|desktop|file system|screenshot|click|type|hotkey|browser|terminal|shell)\b/i.test(text) ||
      /\b(yerel|masaustu|masaüstü|dosya|terminal|tarayıcı|ekran)\b/i.test(text);
    const requiresRetrieval =
      primaryIntent === "research" || /\b(previous|past|memory|context|docs|retrieval|history)\b/i.test(text);
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
    const confidence = matched.length > 0 ? Math.min(0.95, 0.62 + matched.length * 0.1) : primaryIntent === "chat" ? 0.55 : 0.2;
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
      reason: matched.length > 0 ? `matched_${primaryIntent}_rules` : "no_rule_match",
      taskFrame: {
        goal:
          primaryIntent === "research"
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
        likelyAnswerShape,
        reasoningMode,
        shouldClarify: confidence < 0.5 || (primaryIntent === "chat" && matched.length === 0 && text.trim().length < 12),
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
