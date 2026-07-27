import type {
  FeedbackReasonTag,
  FeedbackType,
  LearningSignal,
  TaskUnderstandingInput,
  UnderstandingIntent,
} from "./types.js";
import { filterLearningSignals } from "./personalization-policy.js";
import { extractProjectHints } from "./project-context.js";
import { detectTurkicLanguagePreference } from "./turkic-language.js";
import { unicodeWordPattern } from "../../lib/tr-word-boundary.js";

const stackKeywords = [
  "typescript",
  "javascript",
  "node",
  "fastify",
  "drizzle",
  "postgres",
  "pgvector",
  "flutter",
  "swift",
  "python",
  "react",
  "next.js",
  "docker",
  "linux",
  "macos",
  "windows",
];

const IDENTITY_EXTRACTOR_VERSION = "identity_v1";
const STYLE_CORRECTION_EXTRACTOR_VERSION = "style_correction_v1";
const explicitConciseCorrectionPattern = unicodeWordPattern(
  String.raw`\b(daha\s+k[ıi]sa|k[ıi]sa\s+(?:yaz|cevap\s+ver|tut|kes|ge[çc]|anlat)|gereksiz\s+uzatma|uzatma|(?:cevap|yan[ıi]t|yazd[ıi][ğg][ıi]n|bu)\s+(?:çok|cok|fazla)\s+uzun|(?:çok|cok|fazla)\s+uzun\s+(?:oldu|geldi|yazd[ıi]n)|shorter|more\s+concise|be\s+concise|keep\s+it\s+short)\b`,
  "i",
);
const warmTeachingStyleWordPattern = unicodeWordPattern(
  String.raw`\b(doğal|dogal|samimi|sıcakkanlı|sicakkanli|yakın|yakin|olgun|açıklayıcı|aciklayici|öğretici|ogretici|natural|warm|warmer|personable|close|closer|mature|explanatory|teaching|teacherly)\b`,
  "i",
);
const warmTeachingScopeWordPattern = unicodeWordPattern(
  String.raw`\b(cevap|yanıt|yanit|konuş|konus|üslup|uslup|ton|kişilik|kisilik|karakter|tarz|style|tone|personality|reply|response|answer|every language|all languages|her dil|elyan)\b`,
  "i",
);
const warmTeachingDirectiveWordPattern = unicodeWordPattern(
  String.raw`\b(daha|biraz daha|olmasını|olmasini|sağla|sagla|geliştir|gelistir|istiyorum|tercih|should be|make it|be more|become|improve)\b`,
  "i",
);
const nameRememberPattern = unicodeWordPattern(
  String.raw`\b(?:benim adım|adım)\s+([A-Za-zÇĞİÖŞÜçğıöşü-]+(?:\s+[A-Za-zÇĞİÖŞÜçğıöşü-]+){0,2}?)(?:['’](?:ı|i|u|ü|yı|yi|yu|yü))?\s+(?:hat[ıi]rla|unutma|akl[ıi]nda tut)\b`,
  "i",
);
const nameStatementPattern = unicodeWordPattern(
  String.raw`\b(?:benim adım|adım)\s+([A-Za-zÇĞİÖŞÜçğıöşü'-]+(?:\s+[A-Za-zÇĞİÖŞÜçğıöşü'-]+){0,2})`,
  "i",
);
const englishNameStatementPattern = unicodeWordPattern(String.raw`\bmy name is\s+([A-Za-z][A-Za-z' -]{1,60})`, "i");
const preferredNameCallPattern = unicodeWordPattern(
  String.raw`\b(?:bana|beni)\s+([A-Za-zÇĞİÖŞÜçğıöşü'-]+)\s+(?:diye\s+)?(?:çağır|cagir)\b`,
  "i",
);
const preferredNameAddressPattern = unicodeWordPattern(
  String.raw`\b(?:bundan\s+sonra\s+)?(?:bana|beni)\s+([A-Za-zÇĞİÖŞÜçğıöşü'-]+)\s+(?:diye\s+)?(?:de|seslen|hitap\s+et)\b`,
  "i",
);
const englishPreferredNamePattern = unicodeWordPattern(String.raw`\bcall me\s+([A-Za-z][A-Za-z' -]{1,60})`, "i");
const jobSelfStatementPattern = unicodeWordPattern(
  String.raw`\b(?:ben|i[' ]?m|i am)\s+(?:bir\s+|an?\s+)?([^.,\n]{2,60})\s+(?:olarak\s+)?çalışıyorum\b`,
  "i",
);
const jobRoleStatementPattern = unicodeWordPattern(String.raw`\b([^.,\n]{2,60})\s+olarak\s+çalışıyorum\b`, "i");
const englishWorkAsPattern = unicodeWordPattern(String.raw`\bi work as\s+([^.,\n]{2,60})`, "i");
const englishJobStatementPattern = unicodeWordPattern(String.raw`\bi[' ]?m\s+an?\s+([^.,\n]{2,60})`, "i");
const companyWorkplacePattern = unicodeWordPattern(
  String.raw`\b([^.,\n]{2,80})\s+(?:şirketinde|firmasında)\s+çalışıyorum\b`,
  "i",
);
const englishWorkAtPattern = unicodeWordPattern(String.raw`\bi work at\s+([^.,\n]{2,80})`, "i");
const locationLivingPattern = unicodeWordPattern(String.raw`\b([^.,\n]{2,60})['’]?(?:da|de|ta|te)\s+yaşıyorum\b`, "i");
const englishLiveInPattern = unicodeWordPattern(String.raw`\bi live in\s+([^.,\n]{2,60})`, "i");
const locationStatementPattern = unicodeWordPattern(String.raw`\bkonumum\s+([^.,\n]{2,60})`, "i");
const timezoneStatementPattern = unicodeWordPattern(
  String.raw`\b(?:saat dilimim|time ?zone(?: is)?|timezone(?: is)?)\s+([A-Za-z0-9_+\-:/]{2,40})`,
  "i",
);
const explicitLanguageStatementPattern = unicodeWordPattern(
  String.raw`\b(?:tercih ettiğim dil|tercih ettigim dil|preferred language(?: is)?)\s+([^.,\n]{2,32})`,
  "i",
);
const conciseKeywordPattern = unicodeWordPattern(String.raw`\b(concise|short|brief|kisa|kısa|terse)\b`, "i");
const detailedKeywordPattern = unicodeWordPattern(
  String.raw`\b(detailed|thorough|detayli|detaylı|ayrintili|ayrıntılı)\b`,
  "i",
);
const feedbackStyleKeywordPattern = unicodeWordPattern(
  String.raw`\b(shorter|longer|concise|detailed|turkish|english|warm|warmer|natural|personable|mature|teaching|explanatory|kısa|detaylı|türkçe|ingilizce|samimi|sıcakkanlı|sicakkanli|doğal|dogal|olgun|öğretici|ogretici|açıklayıcı|aciklayici)\b`,
  "i",
);
const preferredAnswerPattern = unicodeWordPattern(
  String.raw`\b(format|style|tone|concise|detailed|bullet|türkçe|turkish)\b`,
  "i",
);
const implementationBoundaryPattern = unicodeWordPattern(
  String.raw`\b(do not|don't|never|asla|yapma|dokunma|bozma|redesign|replace)\b`,
  "i",
);
const PREFERRED_NAME_STOP_WORDS = new Set([
  "cevap",
  "yanıt",
  "yanit",
  "yardım",
  "yardim",
  "bilgi",
  "destek",
  "kısa",
  "kisa",
  "uzun",
  "detaylı",
  "detayli",
  "şunu",
  "sunu",
  "bunu",
]);

function baseSignal(signal: Omit<LearningSignal, "metadata"> & { metadata?: Record<string, unknown> }): LearningSignal {
  return {
    metadata: {},
    ...signal,
  };
}

function readMetadataString(input: TaskUnderstandingInput, key: string): string | null {
  const metadata = input.metadata;
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return null;
  }
  const value = metadata[key];
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

function readMetadataRecord(input: TaskUnderstandingInput, key: string): Record<string, unknown> | null {
  const metadata = input.metadata;
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return null;
  }
  const value = metadata[key];
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readMetadataRouteValue(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim().length > 0 ? value.trim().slice(0, 80) : null;
}

function normalizeFeedbackReasonTags(input: string[] | undefined): FeedbackReasonTag[] {
  const normalized = new Set<FeedbackReasonTag>();
  for (const raw of input ?? []) {
    const value = raw.trim().toLowerCase();
    switch (value) {
      case "too_general":
      case "too_long":
      case "misunderstood":
      case "not_warm_enough":
      case "too_playful":
      case "too_formal":
      case "too_casual":
      case "incorrect":
      case "irrelevant":
        normalized.add(value);
        break;
    }
  }
  return [...normalized];
}

function toTitleCaseWords(value: string): string {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

function cleanIdentityValue(value: string, maxLength = 80): string | null {
  const compact = value.replace(/\s+/g, " ").trim().replace(/[.,;:!?]+$/g, "");
  if (!compact || compact.length > maxLength) {
    return null;
  }
  return compact;
}

function isPlausiblePreferredName(value: string): boolean {
  const compact = cleanIdentityValue(value, 40);
  if (!compact) {
    return false;
  }
  const normalized = compact.toLocaleLowerCase("tr");
  const parts = normalized.split(/\s+/).filter(Boolean);
  if (parts.length === 0 || parts.length > 3 || parts.some((part) => PREFERRED_NAME_STOP_WORDS.has(part))) {
    return false;
  }
  return /^[A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü'-]*(?:\s+[A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü'-]*){0,2}$/.test(compact);
}

function buildIdentitySignal(input: {
  key: "name" | "preferred_name" | "job_title" | "company" | "location" | "timezone" | "preferred_language";
  value: string;
  taskId?: string;
  confidence?: number;
}): LearningSignal | null {
  const cleaned = cleanIdentityValue(input.value, input.key === "job_title" || input.key === "company" ? 96 : 64);
  if (!cleaned) {
    return null;
  }

  return baseSignal({
    type: "identity",
    key: input.key,
    value: input.key === "name" || input.key === "preferred_name" ? toTitleCaseWords(cleaned) : cleaned,
    confidence: input.confidence ?? 0.92,
    scope: "user",
    source: "interaction",
    ttlDays: null,
    metadata: {
      explicit: true,
      extractorVersion: IDENTITY_EXTRACTOR_VERSION,
      ...(input.taskId ? { sourceTurnId: input.taskId } : {}),
    },
  });
}

function isExplicitConciseCorrection(text: string): boolean {
  return explicitConciseCorrectionPattern.test(text);
}

function isExplicitWarmTeachingStylePreference(text: string): boolean {
  const compact = text.replace(/\s+/g, " ").trim();
  if (!compact) {
    return false;
  }
  return (
    warmTeachingStyleWordPattern.test(compact) &&
    warmTeachingScopeWordPattern.test(compact) &&
    warmTeachingDirectiveWordPattern.test(compact)
  );
}

function buildWarmTeachingStyleSignals(input: {
  taskId?: string;
  source: "interaction" | "feedback";
  reason: string;
  confidence?: number;
}): LearningSignal[] {
  const metadata = {
    explicit: true,
    extractorVersion: STYLE_CORRECTION_EXTRACTOR_VERSION,
    reason: input.reason,
    ...(input.taskId ? { sourceTurnId: input.taskId } : {}),
  };
  return [
    baseSignal({
      type: "style",
      key: "response_style_preference",
      value: "warm_close_mature_teaching",
      confidence: input.confidence ?? 0.9,
      scope: "user",
      source: input.source,
      ttlDays: null,
      metadata,
    }),
    baseSignal({
      type: "style",
      key: "preferred_tone",
      value: "warm_close_mature",
      confidence: input.confidence ?? 0.88,
      scope: "user",
      source: input.source,
      ttlDays: null,
      metadata,
    }),
    baseSignal({
      type: "style",
      key: "explanation_style",
      value: "explanatory_teaching",
      confidence: input.confidence ?? 0.86,
      scope: "user",
      source: input.source,
      ttlDays: null,
      metadata,
    }),
  ];
}

function buildExplicitConciseStyleSignals(input: {
  taskId?: string;
  source: "interaction" | "feedback";
  reason: string;
  confidence?: number;
}): LearningSignal[] {
  const metadata = {
    explicit: true,
    extractorVersion: STYLE_CORRECTION_EXTRACTOR_VERSION,
    reason: input.reason,
    ...(input.taskId ? { sourceTurnId: input.taskId } : {}),
  };
  return [
    baseSignal({
      type: "style",
      key: "answer_length",
      value: "concise",
      confidence: input.confidence ?? 0.9,
      scope: "user",
      source: input.source,
      ttlDays: null,
      metadata,
    }),
    baseSignal({
      type: "style",
      key: "brevity_preference",
      value: "short",
      confidence: input.confidence ?? 0.9,
      scope: "user",
      source: input.source,
      ttlDays: null,
      metadata,
    }),
  ];
}

function extractIdentitySignals(input: TaskUnderstandingInput): LearningSignal[] {
  const text = `${input.title ?? ""}\n${input.message ?? ""}`;
  const signals: LearningSignal[] = [];
  const push = (signal: LearningSignal | null) => {
    if (signal) {
      signals.push(signal);
    }
  };

  const nameMatch =
    text.match(nameRememberPattern) ??
    text.match(nameStatementPattern) ??
    text.match(englishNameStatementPattern);
  if (nameMatch?.[1]) {
    push(buildIdentitySignal({ key: "name", value: nameMatch[1], taskId: input.taskId, confidence: 0.97 }));
  }

  const preferredNameMatch =
    text.match(preferredNameCallPattern) ??
    text.match(preferredNameAddressPattern) ??
    text.match(englishPreferredNamePattern);
  if (preferredNameMatch?.[1] && isPlausiblePreferredName(preferredNameMatch[1])) {
    push(buildIdentitySignal({ key: "preferred_name", value: preferredNameMatch[1], taskId: input.taskId, confidence: 0.96 }));
  }

  const jobMatch =
    text.match(jobSelfStatementPattern) ??
    text.match(jobRoleStatementPattern) ??
    text.match(englishWorkAsPattern) ??
    text.match(englishJobStatementPattern);
  if (jobMatch?.[1]) {
    push(buildIdentitySignal({ key: "job_title", value: jobMatch[1], taskId: input.taskId, confidence: 0.93 }));
  }

  const companyMatch =
    text.match(/(?:şirketim|firmam)\s+([^.,\n]{2,80})/iu) ??
    text.match(companyWorkplacePattern) ??
    text.match(englishWorkAtPattern);
  if (companyMatch?.[1]) {
    push(buildIdentitySignal({ key: "company", value: companyMatch[1], taskId: input.taskId, confidence: 0.9 }));
  }

  const locationMatch =
    text.match(locationLivingPattern) ??
    text.match(englishLiveInPattern) ??
    text.match(locationStatementPattern);
  if (locationMatch?.[1]) {
    push(buildIdentitySignal({ key: "location", value: locationMatch[1], taskId: input.taskId, confidence: 0.88 }));
  }

  const timezoneMatch =
    text.match(timezoneStatementPattern);
  if (timezoneMatch?.[1]) {
    push(buildIdentitySignal({ key: "timezone", value: timezoneMatch[1], taskId: input.taskId, confidence: 0.9 }));
  }

  const explicitLanguageMatch =
    text.match(explicitLanguageStatementPattern);
  if (explicitLanguageMatch?.[1]) {
    push(buildIdentitySignal({ key: "preferred_language", value: explicitLanguageMatch[1], taskId: input.taskId, confidence: 0.9 }));
  }

  return signals;
}

export function extractPreferenceSignals(input: TaskUnderstandingInput & { intent?: UnderstandingIntent }): {
  signals: LearningSignal[];
} {
  const text = `${input.title ?? ""}\n${input.message ?? ""}`.slice(0, 12_000);
  const lower = text.toLowerCase();
  const signals: LearningSignal[] = [...extractIdentitySignals(input)];

  const detectedLanguage = detectTurkicLanguagePreference(text);
  if (detectedLanguage) {
    signals.push(
      baseSignal({
        type: "preference",
        key: "preferred_language",
        value: detectedLanguage,
        confidence: 0.82,
        scope: "user",
        source: "interaction",
        ttlDays: null,
      }),
    );
  }

  const explicitConciseCorrection = isExplicitConciseCorrection(text);
  if (explicitConciseCorrection) {
    signals.push(
      ...buildExplicitConciseStyleSignals({
        taskId: input.taskId,
        source: "interaction",
        reason: "user_requested_shorter_replies",
        confidence: 0.92,
      }),
    );
  }

  if (isExplicitWarmTeachingStylePreference(text)) {
    signals.push(
      ...buildWarmTeachingStyleSignals({
        taskId: input.taskId,
        source: "interaction",
        reason: "user_requested_warm_close_mature_teaching_style",
        confidence: 0.92,
      }),
    );
  }

  if (!explicitConciseCorrection && conciseKeywordPattern.test(text)) {
    signals.push(
      baseSignal({
        type: "style",
        key: "answer_length",
        value: "concise",
        confidence: 0.72,
        scope: "user",
        source: "interaction",
        ttlDays: null,
      }),
    );
  }

  if (detailedKeywordPattern.test(text)) {
    signals.push(
      baseSignal({
        type: "style",
        key: "answer_length",
        value: "detailed when needed",
        confidence: 0.72,
        scope: "user",
        source: "interaction",
        ttlDays: null,
      }),
    );
  }

  if (implementationBoundaryPattern.test(text)) {
    signals.push(
      baseSignal({
        type: "correction",
        key: "implementation_boundary",
        value: "preserve existing architecture and avoid unrelated rewrites",
        confidence: 0.86,
        scope: "user",
        source: "interaction",
        ttlDays: null,
      }),
    );
  }

  const responseStylePreference = readMetadataString(input, "responseStylePreference");
  if (responseStylePreference == "formal" || responseStylePreference == "balanced" || responseStylePreference == "warm") {
    signals.push(
      baseSignal({
        type: "style",
        key: "response_style_preference",
        value: responseStylePreference,
        confidence: 0.84,
        scope: "user",
        source: "interaction",
        ttlDays: 45,
        metadata: {
          origin: "mobile_chat_settings",
        },
      }),
    );
  }

  const routeDecision = readMetadataRecord(input, "routeDecision") ?? readMetadataRecord(input, "routingDecision");
  if (routeDecision) {
    const route = readMetadataRouteValue(routeDecision, "route");
    const mode = readMetadataRouteValue(routeDecision, "mode");
    const selectedWorkload = readMetadataRouteValue(routeDecision, "selectedWorkload");
    const requiredRuntime = readMetadataRouteValue(routeDecision, "requiredRuntime");
    const surface = readMetadataString(input, "channel") ?? readMetadataString(input, "surface");

    if (route) {
      signals.push(
        baseSignal({
          type: "routing",
          key: "dispatch_route",
          value: route,
          confidence: 0.78,
          scope: "user",
          source: "interaction",
          ttlDays: 30,
          metadata: selectedWorkload ? { selectedWorkload } : {},
        }),
      );
    }

    if (mode) {
      signals.push(
        baseSignal({
          type: "routing",
          key: "dispatch_mode",
          value: mode,
          confidence: 0.76,
          scope: "user",
          source: "interaction",
          ttlDays: 30,
        }),
      );
    }

    if (selectedWorkload) {
      signals.push(
        baseSignal({
          type: "routing",
          key: "dispatch_workload",
          value: selectedWorkload,
          confidence: 0.74,
          scope: "user",
          source: "interaction",
          ttlDays: 30,
        }),
      );
    }

    if (requiredRuntime) {
      signals.push(
        baseSignal({
          type: "routing",
          key: "dispatch_runtime",
          value: requiredRuntime,
          confidence: 0.72,
          scope: "user",
          source: "interaction",
          ttlDays: 30,
        }),
      );
    }

    if (surface === "chat" || surface === "task") {
      signals.push(
        baseSignal({
          type: "routing",
          key: "dispatch_surface",
          value: surface,
          confidence: 0.8,
          scope: "user",
          source: "interaction",
          ttlDays: 30,
        }),
      );
    }
  }

  const humorMode = readMetadataString(input, "humorMode");
  if (humorMode == "light" || humorMode == "restrained") {
    signals.push(
      baseSignal({
        type: "style",
        key: "humor_level",
        value: humorMode,
        confidence: 0.76,
        scope: "user",
        source: "interaction",
        ttlDays: 45,
      }),
    );
  }

  for (const keyword of stackKeywords) {
    if (lower.includes(keyword)) {
      signals.push(
        baseSignal({
          type: "technical_stack",
          key: "stack",
          value: keyword,
          confidence: 0.74,
          scope: "user",
          source: "interaction",
          ttlDays: null,
        }),
      );
    }
  }

  for (const hint of extractProjectHints(input)) {
    signals.push(
      baseSignal({
        type: "project_context",
        key: "project",
        value: hint.replace(/^project:/, ""),
        confidence: 0.76,
        scope: "project",
        source: "interaction",
        ttlDays: null,
      }),
    );
  }

  if (input.intent && input.intent !== "unknown" && input.intent !== "chat") {
    signals.push(
      baseSignal({
        type: "workflow",
        key: "recent_intent",
        value: input.intent,
        confidence: 0.7,
        scope: "user",
        source: "interaction",
        ttlDays: 30,
      }),
    );
  }

  return {
    signals: filterLearningSignals(signals).slice(0, 10),
  };
}

export function extractFeedbackSignals(input: {
  feedbackType: FeedbackType;
  taskId?: string;
  correction?: string;
  preferredAnswer?: string;
  reasonTags?: string[];
}): { signals: LearningSignal[] } {
  const signals: LearningSignal[] = [];
  const reasonTags = normalizeFeedbackReasonTags(input.reasonTags);

  if (input.feedbackType === "thumbs_up" || input.feedbackType === "task_completed") {
    signals.push(
      baseSignal({
        type: "preference",
        key: "positive_feedback",
        value: input.feedbackType,
        confidence: 0.7,
        scope: "user",
        source: "feedback",
        ttlDays: 60,
        metadata: reasonTags.length ? { reasonTags } : {},
      }),
    );
    signals.push(
      baseSignal({
        type: "style",
        key: "follow_up_quality",
        value: "helpful",
        confidence: 0.68,
        scope: "user",
        source: "feedback",
        ttlDays: 45,
      }),
    );
  }

  if (input.feedbackType === "thumbs_down" || input.feedbackType === "task_failed" || input.feedbackType === "regenerate") {
    signals.push(
      baseSignal({
        type: "correction",
        key: "negative_feedback",
        value: input.feedbackType,
        confidence: 0.72,
        scope: "user",
        source: "feedback",
        ttlDays: 60,
        metadata: reasonTags.length ? { reasonTags } : {},
      }),
    );
    signals.push(
      baseSignal({
        type: "style",
        key: "follow_up_quality",
        value: "needs_improvement",
        confidence: 0.72,
        scope: "user",
        source: "feedback",
        ttlDays: 45,
      }),
    );
  }

  for (const tag of reasonTags) {
    if (tag === "too_long") {
      signals.push(
        baseSignal({
          type: "style",
          key: "brevity_preference",
          value: "short",
          confidence: 0.86,
          scope: "user",
          source: "feedback",
          ttlDays: 90,
          metadata: {
            explicit: true,
            extractorVersion: STYLE_CORRECTION_EXTRACTOR_VERSION,
            reason: "feedback_too_long",
            ...(input.taskId ? { sourceTurnId: input.taskId } : {}),
          },
        }),
      );
      signals.push(
        ...buildExplicitConciseStyleSignals({
          taskId: input.taskId,
          source: "feedback",
          reason: "feedback_too_long",
          confidence: 0.9,
        }),
      );
    } else if (tag === "too_general") {
      signals.push(
        baseSignal({
          type: "style",
          key: "helpfulness_signal",
          value: "needs_more_specificity",
          confidence: 0.82,
          scope: "user",
          source: "feedback",
          ttlDays: 60,
        }),
      );
    } else if (tag === "misunderstood") {
      signals.push(
        baseSignal({
          type: "correction",
          key: "task_handoff_helpfulness",
          value: "needs_better_context_alignment",
          confidence: 0.82,
          scope: "user",
          source: "feedback",
          ttlDays: 45,
        }),
      );
    } else if (tag === "not_warm_enough") {
      signals.push(
        baseSignal({
          type: "style",
          key: "preferred_tone",
          value: "warm_professional",
          confidence: 0.84,
          scope: "user",
          source: "feedback",
          ttlDays: 90,
          metadata: {
            explicit: true,
            reason: "feedback_requested_warmer_tone",
            ...(input.taskId ? { sourceTurnId: input.taskId } : {}),
          },
        }),
      );
    } else if (tag === "too_playful") {
      signals.push(
        baseSignal({
          type: "style",
          key: "humor_level",
          value: "restrained",
          confidence: 0.88,
          scope: "user",
          source: "feedback",
          ttlDays: 90,
        }),
      );
      signals.push(
        baseSignal({
          type: "correction",
          key: "humor_feedback",
          value: "reject_excessive_humor",
          confidence: 0.84,
          scope: "user",
          source: "feedback",
          ttlDays: 90,
        }),
      );
    } else if (tag === "too_formal" || tag === "too_casual") {
      const preferredTone =
        tag === "too_formal" ? "warm_natural" : "calm_professional";
      signals.push(
        baseSignal({
          type: "style",
          key: "preferred_tone",
          value: preferredTone,
          confidence: 0.88,
          scope: "user",
          source: "feedback",
          ttlDays: 180,
          metadata: {
            explicit: true,
            reason: `feedback_${tag}`,
            ...(input.taskId ? { sourceTurnId: input.taskId } : {}),
          },
        }),
      );
    } else if (tag === "incorrect" || tag === "irrelevant") {
      signals.push(
        baseSignal({
          type: "correction",
          key: "answer_quality_correction",
          value:
            tag === "incorrect"
              ? "prioritize factual correctness and verification"
              : "stay directly relevant to the user request",
          confidence: 0.88,
          scope: "user",
          source: "feedback",
          ttlDays: 90,
          metadata: {
            explicit: true,
            reason: `feedback_${tag}`,
            ...(input.taskId ? { sourceTurnId: input.taskId } : {}),
          },
        }),
      );
    }
  }

  const correction = input.correction?.replace(/\s+/g, " ").trim();

  if (correction && feedbackStyleKeywordPattern.test(correction)) {
    signals.push(
      baseSignal({
        type: "style",
        key: "feedback_style",
        value: correction.slice(0, 160),
        confidence: 0.8,
        scope: "user",
        source: "feedback",
        ttlDays: null,
      }),
    );
  }
  if (correction && isExplicitConciseCorrection(correction)) {
    signals.push(
      ...buildExplicitConciseStyleSignals({
        taskId: input.taskId,
        source: "feedback",
        reason: "feedback_correction_requested_shorter_replies",
        confidence: 0.92,
      }),
    );
  }
  if (correction && isExplicitWarmTeachingStylePreference(correction)) {
    signals.push(
      ...buildWarmTeachingStyleSignals({
        taskId: input.taskId,
        source: "feedback",
        reason: "feedback_requested_warm_close_mature_teaching_style",
        confidence: 0.9,
      }),
    );
  }

  if (input.preferredAnswer && preferredAnswerPattern.test(input.preferredAnswer)) {
    signals.push(
      baseSignal({
        type: "style",
        key: "preferred_answer_pattern",
        value: input.preferredAnswer.replace(/\s+/g, " ").trim().slice(0, 160),
        confidence: 0.72,
        scope: "user",
        source: "feedback",
        ttlDays: null,
      }),
    );
  }

  return {
    signals: filterLearningSignals(signals).slice(0, 6),
  };
}
