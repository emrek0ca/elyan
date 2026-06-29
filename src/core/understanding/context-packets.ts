import type {
  ContextFreshnessSummary,
  ContextPacket,
  ContextPacketFreshness,
  ContextPacketKind,
  ContextPacketMentionPolicy,
  UnderstandingIntent,
} from "./types.js";

const MAX_PACKETS = 8;
const MAX_PACKET_SUMMARY_CHARS = 280;
const HEALTH_CONTEXT_TTL_HOURS = 24;
const CALENDAR_CONTEXT_TTL_HOURS = 18;
const DEVICE_CONTEXT_TTL_HOURS = 6;
const NOTIFICATION_CONTEXT_TTL_HOURS = 4;
const TIME_CONTEXT_TTL_HOURS = 8;
const WORLD_CONTEXT_TTL_HOURS = 12;

const SAFE_HEALTH_FACT_LABELS = new Map<string, string>([
  // Qualitative derived
  ["activitylevel", "aktivite seviyesi"],
  ["activityband", "aktivite bandı"],
  ["energy", "enerji"],
  ["energylevel", "enerji durumu"],
  ["fatigue", "yorgunluk"],
  ["focus", "odak"],
  ["hydration", "hidrasyon"],
  ["mood", "ruh hali"],
  ["movementtrend", "hareket eğilimi"],
  ["readiness", "hazırlık"],
  ["readinesslevel", "hazırlık"],
  ["recovery", "toparlanma"],
  ["sleepquality", "uyku kalitesi"],
  ["stress", "stres"],
  ["stresslevel", "stres"],
  ["timeframe", "zaman aralığı"],
  ["trend", "eğilim"],
  ["wellbeing", "iyi oluş"],
  // Step counts (mobile-derived)
  ["stepstoday", "adım (bugün)"],
  ["stepsyesterday", "adım (dün)"],
  ["stepsthisweek", "adım (bu hafta)"],
  // Sleep hours (mobile-derived)
  ["sleephourstoday", "uyku (bu gece, saat)"],
  ["sleephoursyesterday", "uyku (önceki gece, saat)"],
  ["sleepremhours", "REM uykusu (saat)"],
  ["sleeprempercent", "REM uykusu (%)"],
  ["sleepdeephours", "derin uyku (saat)"],
  ["sleepdeeppercent", "derin uyku (%)"],
  // Energy & workouts
  ["activeenergykcal", "aktif enerji (kcal)"],
  ["workoutcount", "egzersiz sayısı"],
  ["workoutdurationminutes", "egzersiz süresi (dk)"],
  ["workouttype", "egzersiz türü"],
]);

const RAW_HEALTH_TEXT_PATTERN =
  /\b(bpm|nabız|heart\s*rate|tansiyon|blood\s*pressure|glucose|kan şekeri|adım|steps?|kcal|kalori|calories?|kilometre|km|metre|meters?|raw|sample|teşhis|tani|tanı|diagnosis|ilaç|medication)\b/i;
const RAW_MEASUREMENT_PATTERN =
  /\b\d+(?:[.,]\d+)?\s*(?:bpm|adım|steps?|kcal|kalori|calories?|km|kilometre|metre|meters?|saat|hours?|dakika|minutes?)\b/gi;
const PRIVATE_DERIVED_TEXT_PATTERN =
  /(?:https?:\/\/|file:\/\/|\/Users\/|[A-Za-z]:\\|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:\+?\d[\d\s().-]{7,}\d)|\b(attendee|attendees|body|description|event\s*title|invitee|meeting\s*link|message\s*body|notification\s*body|raw|sample|secret|token)\b|\b(bildirim\s+gövdesi|bildirim\s+govdesi|mesaj\s+içeriği|mesaj\s+icerigi|özel\s+içerik|ozel\s+icerik)\b)/i;

const SAFE_CALENDAR_FACT_LABELS = new Map<string, string>([
  ["availability", "uygunluk"],
  ["busyness", "takvim yoğunluğu"],
  ["busylevel", "yoğunluk seviyesi"],
  ["dayload", "gün yoğunluğu"],
  ["calendardensity", "takvim dolulugu"],
  ["deadlineload", "son tarih baskısı"],
  ["hasdeadlinelikeevent", "deadline var mı"],
  ["eventcount", "etkinlik sayısı"],
  ["focuswindow", "odak penceresi"],
  ["freeminutestoday", "bugün boş süre (dk)"],
  ["longestfreeblockminutes", "en uzun boş blok (dk)"],
  ["freewindow", "boş zaman penceresi"],
  ["meetingload", "toplantı yükü"],
  ["nexteventminutes", "sonraki etkinliğe kalan (dk)"],
  ["nexteventdurationminutes", "sonraki etkinlik süresi (dk)"],
  ["nexteventwindow", "sonraki etkinlik penceresi"],
  ["nextwindow", "sonraki uygun aralık"],
  ["schedulepressure", "program baskısı"],
  ["timeframe", "zaman aralığı"],
]);

const SAFE_DEVICE_FACT_LABELS = new Map<string, string>([
  ["appversion", "uygulama sürümü"],
  ["battery", "pil"],
  ["batterylevel", "pil"],
  ["charging", "şarj"],
  ["connectivity", "bağlantı"],
  ["devicestate", "cihaz durumu"],
  ["focusmode", "odak modu"],
  ["lowpowermode", "düşük güç modu"],
  ["network", "ağ"],
  ["online", "çevrimiçi durum"],
  ["osversion", "işletim sistemi"],
  ["platform", "platform"],
  ["storage", "depolama"],
]);

const SAFE_NOTIFICATION_FACT_LABELS = new Map<string, string>([
  ["authorization", "bildirim izni"],
  ["attentionload", "dikkat yükü"],
  ["countbucket", "bildirim yoğunluğu"],
  ["digest", "bildirim özeti"],
  ["focusimpact", "odak etkisi"],
  ["notificationload", "bildirim yükü"],
  ["priority", "öncelik"],
  ["urgency", "aciliyet"],
]);

const SAFE_TIME_FACT_LABELS = new Map<string, string>([
  ["daypart", "günün bölümü"],
  ["localeday", "yerel gün"],
  ["localtime", "yerel saat"],
  ["localtimeofday", "yerel saat"],
  ["timezone", "saat dilimi"],
  ["weekday", "hafta günü"],
  ["workinghours", "çalışma saatleri"],
]);

const SAFE_LOCATION_FACT_LABELS = new Map<string, string>([
  ["city", "şehir"],
  ["district", "ilçe"],
  ["country", "ülke"],
  ["countrycode", "ülke kodu"],
  ["region", "bölge"],
  ["timezone", "saat dilimi"],
  ["zone", "bölge"],
  ["mobility", "hareket durumu"],
  ["cityknown", "şehir bilinuyor"],
  ["precision", "konum hassasiyeti"],
]);

const GREETING_PATTERN =
  /^(selam|selamlar|merhaba|mrb|hey|hi|hello|günaydın|gunaydin|iyi akşamlar|iyi aksamlar|iyi geceler|naber|nasılsın|nasilsin)[\s!.?]*$/i;
const DEVICE_RELEVANCE_PATTERN =
  /\b(cihaz|device|pil|battery|şarj|sarj|ağ|ag|network|wifi|internet|bağlantı|baglanti|online|offline|kopuyor|çevrim|performans|yavaş|yavas|hata|problem|sorun|çöktü|crash|timeout)\b/i;
const HEALTH_RELEVANCE_PATTERN =
  /\b(sağlık|saglik|health|uyku|sleep|enerji|energy|yorgun|dinlen|adım|adim|steps?|spor|egzersiz|workout|fitness|stres|stress|odak|focus|rutin|wellbeing|iyi oluş|iyi olus|tempo)\b/i;
const LOCATION_RELEVANCE_PATTERN =
  /\b(nerede|konum|location|şehir|sehir|ilçe|ilce|yakın|yakin|çevre|cevre|mekan|restoran|yemek|hava|weather|sıcaklık|sicaklik|gezi|seyahat|rota|ulaşım|ulasim|öner|oner|meşhur|meshur|kayseri|hatay|istanbul|ankara|izmir)\b/i;
const SCHEDULE_RELEVANCE_PATTERN =
  /\b(takvim|calendar|program|plan|planla|saat|time|bugün|bugun|yarın|yarin|toplantı|toplanti|müsait|musait|boş|bos|deadline|son tarih|odak|focus|yoğun|yogun|rutin|ajanda|zaman)\b/i;
const NOTIFICATION_RELEVANCE_PATTERN =
  /\b(bildirim|notification|dikkat|attention|rahatsız|rahatsiz|odak|focus|sessiz|silent|acil|urgent|öncelik|oncelik)\b/i;
const ADAPTIVE_WORK_PATTERN =
  /\b(plan|planla|planning|program|schedule|bugün|bugun|yarın|yarin|task|görev|gorev|workflow|routine|rutin|araştır|arastir|research|debug|kod|code|odak|focus|hazırla|hazirla|çıkar|cikar|optimize|iyileştir|iyilestir|prepare)\b/i;

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function readString(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readNumber(record: Record<string, unknown> | null, key: string): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function compactText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function clipCompactText(value: string, maxChars: number): string {
  const compact = compactText(value);
  if (compact.length <= maxChars) {
    return compact;
  }
  return `${compact.slice(0, Math.max(0, maxChars - 1)).trim()}…`;
}

function normalizeKey(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
}

function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim().toLowerCase();
}

function resolveMentionPolicy(input: {
  packetKind: ContextPacketKind;
  message: string;
  intent?: UnderstandingIntent;
}): {
  mentionPolicy: ContextPacketMentionPolicy;
  relevanceReason: string;
  allowedUse: string[];
} {
  const message = normalizeText(input.message);
  const intent = input.intent ?? "unknown";
  const isGreeting = GREETING_PATTERN.test(message);
  if (!message || isGreeting) {
    return {
      mentionPolicy: "silent",
      relevanceReason: isGreeting ? "greeting_context_suppressed" : "no_request_relevance",
      allowedUse: ["keep context private unless the user asks"],
    };
  }

  if (input.packetKind === "device_context") {
    const explicit = DEVICE_RELEVANCE_PATTERN.test(message);
    return {
      mentionPolicy: explicit ? "explicit_when_relevant" : "silent",
      relevanceReason: explicit ? "device_or_connectivity_request" : "device_context_not_requested",
      allowedUse: explicit
        ? ["explain reliability or connectivity impact", "avoid exposing diagnostics unless useful"]
        : ["do not mention device state"],
    };
  }

  if (input.packetKind === "health_context") {
    const explicit = HEALTH_RELEVANCE_PATTERN.test(message);
    const implicit = intent === "planning" || intent === "writing";
    return {
      mentionPolicy: explicit ? "explicit_when_relevant" : implicit ? "implicit" : "silent",
      relevanceReason: explicit
        ? "wellbeing_or_readiness_request"
        : implicit
          ? "planning_pacing_context"
          : "health_context_not_requested",
      allowedUse: explicit
        ? [
            // The user explicitly asked about their own health metrics. The
            // figures here are user-derived (steps, sleep, energy) and were
            // already marked plaintext-safe, so answer with the actual numbers
            // when asked. Only clinical interpretation stays off-limits.
            "share the user's own metrics with exact figures when asked",
            "wellbeing nudge",
            "energy-aware pacing",
            "no medical diagnosis or clinical interpretation",
          ]
        : implicit
          ? ["adjust pacing without naming health data"]
          : ["do not mention health context"],
    };
  }

  if (input.packetKind === "calendar_context" || input.packetKind === "time_context") {
    const explicit = SCHEDULE_RELEVANCE_PATTERN.test(message) || intent === "planning";
    return {
      mentionPolicy: explicit ? "explicit_when_relevant" : "implicit",
      relevanceReason: explicit ? "schedule_or_planning_request" : "time_context_for_pacing_only",
      allowedUse: explicit
        ? ["schedule-aware planning", "timing suggestions", "do not expose private event details"]
        : ["adjust brevity and timing without naming the context"],
    };
  }

  if (input.packetKind === "world_context") {
    const explicit = LOCATION_RELEVANCE_PATTERN.test(message);
    const implicit = !explicit && (intent === "planning" || ADAPTIVE_WORK_PATTERN.test(message));
    return {
      mentionPolicy: explicit ? "explicit_when_relevant" : implicit ? "implicit" : "silent",
      relevanceReason: explicit
        ? "location_or_local_recommendation_request"
        : implicit
          ? "location_context_for_logistics_only"
          : "location_context_not_requested",
      allowedUse: explicit
        ? ["local recommendation", "logistics or place-aware suggestion", "do not invent live weather"]
        : implicit
          ? ["silently adjust timing or logistics", "do not mention location unless asked"]
          : ["do not mention location"],
    };
  }

  if (input.packetKind === "notification_context") {
    const explicit = NOTIFICATION_RELEVANCE_PATTERN.test(message);
    const implicit = !explicit && (intent === "planning" || ADAPTIVE_WORK_PATTERN.test(message));
    return {
      mentionPolicy: explicit ? "explicit_when_relevant" : implicit ? "implicit" : "silent",
      relevanceReason: explicit
        ? "attention_or_notification_request"
        : implicit
          ? "attention_context_for_pacing_only"
          : "notification_context_not_requested",
      allowedUse: explicit
        ? ["attention-aware prioritization", "do not quote notification contents"]
        : implicit
          ? ["silently reduce cognitive load", "do not mention notifications"]
          : ["do not mention notifications"],
    };
  }

  return {
    mentionPolicy: "silent",
    relevanceReason: "context_not_requested",
    allowedUse: ["do not mention this context"],
  };
}

function withUsageGuidance(
  packet: ContextPacket,
  options: { requestText?: string; intent?: UnderstandingIntent },
): ContextPacket {
  const guidance = resolveMentionPolicy({
    packetKind: packet.kind,
    message: options.requestText ?? "",
    intent: options.intent,
  });
  return {
    ...packet,
    ...guidance,
  };
}

function parseDate(value: unknown): Date | null {
  if (value instanceof Date && Number.isFinite(value.getTime())) {
    return value;
  }
  if (typeof value !== "string" || !value.trim()) {
    return null;
  }
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) ? parsed : null;
}

function classifyFreshness(createdAt: Date | null, now: Date, ttlHours: number): ContextPacketFreshness {
  if (!createdAt) {
    return "unknown";
  }
  const ageHours = Math.max(0, now.getTime() - createdAt.getTime()) / 3_600_000;
  if (ageHours > ttlHours) {
    return "stale";
  }
  return ageHours <= 2 ? "fresh" : "recent";
}

function expiresAt(createdAt: Date | null, ttlHours: number): string | null {
  return createdAt
    ? new Date(createdAt.getTime() + ttlHours * 3_600_000).toISOString()
    : null;
}

function normalizeConfidence(value: number | null): number {
  if (value == null) {
    return 0.5;
  }
  return Math.max(0, Math.min(1, Number(value.toFixed(3))));
}

function qualitativeScore(value: number): string {
  const normalized = value > 1 ? value / 100 : value;
  if (normalized >= 0.74) {
    return "yüksek";
  }
  if (normalized >= 0.42) {
    return "orta";
  }
  return "düşük";
}

function safeFactValue(value: unknown, options: { allowPlaintext?: boolean } = {}): string | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    // When plaintext is allowed, show the actual number for user-owned derived data.
    if (options.allowPlaintext) {
      return String(Number.isInteger(value) ? value : value.toFixed(1));
    }
    return qualitativeScore(value);
  }
  if (typeof value === "boolean") {
    return value ? "var" : "yok";
  }
  if (typeof value !== "string") {
    return null;
  }
  const compact = clipCompactText(value, 64);
  if (!compact) {
    return null;
  }
  if (!options.allowPlaintext && RAW_HEALTH_TEXT_PATTERN.test(compact)) {
    return null;
  }
  return options.allowPlaintext ? compact : compact.replace(RAW_MEASUREMENT_PATTERN, "ölçüm");
}

function safeDerivedFactValue(value: unknown): string | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return qualitativeScore(value);
  }
  if (typeof value === "boolean") {
    return value ? "var" : "yok";
  }
  if (typeof value !== "string") {
    return null;
  }
  const compact = clipCompactText(value, 64);
  if (!compact || PRIVATE_DERIVED_TEXT_PATTERN.test(compact)) {
    return null;
  }
  return compact;
}

function scrubHealthSummary(value: string, options: { allowPlaintext?: boolean } = {}): string {
  if (!value.trim()) {
    return "";
  }
  if (options.allowPlaintext) {
    // User explicitly allowed plaintext: only clip, do not scrub measurements.
    return clipCompactText(value, 240);
  }
  const compact = clipCompactText(value.replace(RAW_MEASUREMENT_PATTERN, "ölçüm"), 180);
  if (!compact) {
    return "";
  }
  if (RAW_HEALTH_TEXT_PATTERN.test(compact)) {
    return "Yakın dönem sağlık sinyali yüksek seviyeli bağlam olarak mevcut.";
  }
  return compact;
}

function scrubDerivedSummary(value: string, fallback: string): string {
  const compact = clipCompactText(value, 180);
  if (!compact) {
    return "";
  }
  if (PRIVATE_DERIVED_TEXT_PATTERN.test(compact)) {
    return fallback;
  }
  return compact;
}

function buildHealthFactsSummary(facts: Record<string, unknown> | null, options: { allowPlaintext?: boolean } = {}): string[] {
  if (!facts) {
    return [];
  }
  const parts: string[] = [];
  // Priority: qualitative first (always present), then numeric derived facts.
  const qualitativeKeys = new Set(["sleepquality", "activityband", "activitylevel", "energylevel", "energy", "trend", "readiness", "stress", "stresslevel", "wellbeing"]);
  const numericKeys = new Set(["stepstoday", "stepsyesterday", "stepsthisweek", "sleephourstoday", "sleephoursyesterday", "activeenergykcal", "workoutcount", "workoutdurationminutes", "workouttype", "sleeprempercent", "sleepdeeppercent"]);
  const orderedEntries = [
    ...Object.entries(facts).filter(([k]) => qualitativeKeys.has(normalizeKey(k))),
    ...Object.entries(facts).filter(([k]) => numericKeys.has(normalizeKey(k))),
  ];
  for (const [key, value] of orderedEntries) {
    const label = SAFE_HEALTH_FACT_LABELS.get(normalizeKey(key));
    if (!label) {
      continue;
    }
    const safeValue = safeFactValue(value, { allowPlaintext: options.allowPlaintext });
    if (!safeValue) {
      continue;
    }
    parts.push(`${label}: ${safeValue}`);
    if (parts.length >= 8) {
      break;
    }
  }
  return parts;
}

function buildDerivedFactsSummary(
  facts: Record<string, unknown> | null,
  labels: Map<string, string>,
): string[] {
  if (!facts) {
    return [];
  }
  const parts: string[] = [];
  for (const [key, value] of Object.entries(facts)) {
    const label = labels.get(normalizeKey(key));
    if (!label) {
      continue;
    }
    const safeValue = safeDerivedFactValue(value);
    if (!safeValue) {
      continue;
    }
    parts.push(`${label}: ${safeValue}`);
    if (parts.length >= 4) {
      break;
    }
  }
  return parts;
}

function extractWorldSignalRecords(metadata: Record<string, unknown> | undefined): Record<string, unknown>[] {
  const root = readRecord(metadata);
  const compactContext = readRecord(root?.compactContext);
  const chatContext = readRecord(root?.chatContext);
  const directDerived = readRecord(root?.derivedContextDigest);
  const compactDerived = readRecord(compactContext?.derivedContextDigest);
  const chatDerived = readRecord(chatContext?.lastDerivedContextDigest);
  const sources = [
    readArray(compactDerived?.worldSignals),
    readArray(chatDerived?.worldSignals),
    readArray(directDerived?.worldSignals),
  ];
  const seen = new Set<string>();
  const records: Record<string, unknown>[] = [];

  for (const source of sources) {
    for (const item of source) {
      const record = readRecord(item);
      if (!record) {
        continue;
      }
      const kind = readString(record, "kind");
      const summary = readString(record, "summary");
      if (!kind || !summary) {
        continue;
      }
      const signalId = readString(record, "signalId");
      const key = `${signalId ?? ""}:${kind}:${summary}`.toLowerCase();
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      records.push(record);
    }
  }

  return records;
}

function buildHealthPacket(signal: Record<string, unknown>, now: Date): ContextPacket | null {
  const createdAt = parseDate(signal.createdAt);
  const freshness = classifyFreshness(createdAt, now, HEALTH_CONTEXT_TTL_HOURS);
  if (freshness === "stale") {
    return null;
  }
  // Mobile sets backendPlaintextAllowed:true when derived data (not raw sensor) is safe for AI.
  const privacyRecord = readRecord(signal.privacy);
  const allowPlaintext = privacyRecord?.backendPlaintextAllowed === true;
  const summary = scrubHealthSummary(readString(signal, "summary") ?? "", { allowPlaintext });
  const factsSummary = buildHealthFactsSummary(readRecord(signal.facts), { allowPlaintext });
  const packetSummary = clipCompactText(
    [summary, ...factsSummary].filter(Boolean).join("; "),
    MAX_PACKET_SUMMARY_CHARS,
  );
  if (!packetSummary) {
    return null;
  }

  return {
    kind: "health_context",
    source: "world_signal",
    title: "Kısa ömürlü sağlık bağlamı",
    summary: packetSummary,
    confidence: normalizeConfidence(readNumber(signal, "confidence")),
    freshness,
    privacyClass: "health_ephemeral",
    evidenceCount: 1 + factsSummary.length,
    createdAt: createdAt?.toISOString() ?? null,
    expiresAt: expiresAt(createdAt, HEALTH_CONTEXT_TTL_HOURS),
    renderHint: "context_signal",
    signalKinds: ["health"],
  };
}

function buildDerivedWorldPacket(
  signal: Record<string, unknown>,
  now: Date,
  options: {
    packetKind: ContextPacket["kind"];
    title: string;
    ttlHours: number;
    privacyClass: ContextPacket["privacyClass"];
    factLabels: Map<string, string>;
    summaryFallback: string;
    signalKind: string;
  },
): ContextPacket | null {
  const createdAt = parseDate(signal.createdAt);
  const freshness = classifyFreshness(createdAt, now, options.ttlHours);
  if (freshness === "stale") {
    return null;
  }
  const privacyRecord = readRecord(signal.privacy);
  const allowPlaintext = privacyRecord?.backendPlaintextAllowed === true;
  const rawSummary = readString(signal, "summary") ?? "";
  const summary = allowPlaintext
    ? clipCompactText(rawSummary, 200)
    : scrubDerivedSummary(rawSummary, options.summaryFallback);
  const factsSummary = buildDerivedFactsSummary(readRecord(signal.facts), options.factLabels);
  const packetSummary = clipCompactText(
    [summary, ...factsSummary].filter(Boolean).join("; "),
    MAX_PACKET_SUMMARY_CHARS,
  );
  if (!packetSummary) {
    return null;
  }

  return {
    kind: options.packetKind,
    source: "world_signal",
    title: options.title,
    summary: packetSummary,
    confidence: normalizeConfidence(readNumber(signal, "confidence")),
    freshness,
    privacyClass: options.privacyClass,
    evidenceCount: 1 + factsSummary.length,
    createdAt: createdAt?.toISOString() ?? null,
    expiresAt: expiresAt(createdAt, options.ttlHours),
    renderHint: "context_signal",
    signalKinds: [options.signalKind],
  };
}

function buildWorldPacket(signal: Record<string, unknown>, now: Date): ContextPacket | null {
  const kind = readString(signal, "kind") ?? "world";
  const createdAt = parseDate(signal.createdAt);
  const freshness = classifyFreshness(createdAt, now, WORLD_CONTEXT_TTL_HOURS);
  if (freshness === "stale") {
    return null;
  }
  const summary = clipCompactText(readString(signal, "summary") ?? "", MAX_PACKET_SUMMARY_CHARS);
  if (!summary) {
    return null;
  }

  return {
    kind: "world_context",
    source: "world_signal",
    title: `${kind} bağlamı`,
    summary,
    confidence: normalizeConfidence(readNumber(signal, "confidence")),
    freshness,
    privacyClass: "ephemeral",
    evidenceCount: 1,
    createdAt: createdAt?.toISOString() ?? null,
    expiresAt: expiresAt(createdAt, WORLD_CONTEXT_TTL_HOURS),
    renderHint: "context_signal",
    signalKinds: [kind],
  };
}

export function summarizeContextFreshness(packets: ContextPacket[]): ContextFreshnessSummary {
  const dates = packets
    .map((packet) => parseDate(packet.createdAt))
    .filter((date): date is Date => date != null)
    .sort((left, right) => left.getTime() - right.getTime());
  const newest = dates[dates.length - 1] ?? null;
  const oldest = dates[0] ?? null;
  return {
    newestContextAt: newest?.toISOString() ?? null,
    oldestContextAt: oldest?.toISOString() ?? null,
    maxAgeHours:
      newest && oldest
        ? Number(Math.max(0, (newest.getTime() - oldest.getTime()) / 3_600_000).toFixed(2))
        : null,
    stalePacketCount: packets.filter((packet) => packet.freshness === "stale").length,
  };
}

export function buildContextPacketsFromMetadata(
  metadata: Record<string, unknown> | undefined,
  options: { now?: Date; requestText?: string; intent?: UnderstandingIntent } = {},
): ContextPacket[] {
  const now = options.now ?? new Date();
  const packets: ContextPacket[] = [];

  for (const signal of extractWorldSignalRecords(metadata)) {
    const kind = (readString(signal, "kind") ?? "").toLowerCase();
    const packet = kind === "health"
      ? buildHealthPacket(signal, now)
      : kind === "calendar"
        ? buildDerivedWorldPacket(signal, now, {
            packetKind: "calendar_context",
            title: "Takvim ve zaman bağlamı",
            ttlHours: CALENDAR_CONTEXT_TTL_HOURS,
            privacyClass: "ephemeral",
            factLabels: SAFE_CALENDAR_FACT_LABELS,
            summaryFallback: "Yakın dönem takvim yoğunluğu güvenli özet olarak mevcut.",
            signalKind: "calendar",
          })
        : kind === "device"
          ? buildDerivedWorldPacket(signal, now, {
              packetKind: "device_context",
              title: "Cihaz durumu bağlamı",
              ttlHours: DEVICE_CONTEXT_TTL_HOURS,
              privacyClass: "safe_derived",
              factLabels: SAFE_DEVICE_FACT_LABELS,
              summaryFallback: "Cihaz durumu güvenli özet olarak mevcut.",
              signalKind: "device",
            })
          : kind === "notification"
            ? buildDerivedWorldPacket(signal, now, {
                packetKind: "notification_context",
                title: "Bildirim ve dikkat bağlamı",
                ttlHours: NOTIFICATION_CONTEXT_TTL_HOURS,
                privacyClass: "ephemeral",
                factLabels: SAFE_NOTIFICATION_FACT_LABELS,
                summaryFallback: "Bildirim yoğunluğu güvenli özet olarak mevcut.",
                signalKind: "notification",
              })
            : kind === "location"
              ? buildDerivedWorldPacket(signal, now, {
                  packetKind: "world_context",
                  title: "Konum bağlamı",
                  ttlHours: WORLD_CONTEXT_TTL_HOURS,
                  privacyClass: "ephemeral",
                  factLabels: SAFE_LOCATION_FACT_LABELS,
                  summaryFallback: "Konum bağlamı güvenli özet olarak mevcut.",
                  signalKind: "location",
                })
              : kind === "time"
                ? buildDerivedWorldPacket(signal, now, {
                  packetKind: "time_context",
                  title: "Yerel zaman bağlamı",
                  ttlHours: TIME_CONTEXT_TTL_HOURS,
                  privacyClass: "safe_derived",
                  factLabels: SAFE_TIME_FACT_LABELS,
                  summaryFallback: "Yerel zaman bağlamı güvenli özet olarak mevcut.",
                  signalKind: "time",
                })
                : buildWorldPacket(signal, now);
    if (packet) {
      packets.push(withUsageGuidance(packet, options));
    }
  }

  return packets
    .sort((left, right) => {
      const leftDate = parseDate(left.createdAt)?.getTime() ?? 0;
      const rightDate = parseDate(right.createdAt)?.getTime() ?? 0;
      return rightDate - leftDate;
    })
    .slice(0, MAX_PACKETS);
}
