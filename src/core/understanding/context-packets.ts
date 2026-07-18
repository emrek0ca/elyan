import type {
  ContextFreshnessSummary,
  ContextPacket,
  ContextPacketFreshness,
  ContextPacketKind,
  ContextPacketMentionPolicy,
  UnderstandingIntent,
} from "./types.js";

const MAX_PACKETS = 10;
const MAX_PACKET_SUMMARY_CHARS = 360;
const MAX_FUTURE_CLOCK_SKEW_MS = 5 * 60_000;
const WORLD_SIGNAL_FUSION_WINDOW_MS = 5 * 60_000;
export const WORLD_SIGNAL_TTL_HOURS_BY_KIND = Object.freeze({
  health: 24,
  calendar: 18,
  device: 6,
  notification: 4,
  time: 8,
  location: 12,
  camera: 12,
  speech: 12,
  attachment: 12,
} as const);

export function getWorldSignalTtlHours(kind: string): number {
  return WORLD_SIGNAL_TTL_HOURS_BY_KIND[
    kind.trim().toLowerCase() as keyof typeof WORLD_SIGNAL_TTL_HOURS_BY_KIND
  ] ?? 12;
}

const HEALTH_CONTEXT_TTL_HOURS = getWorldSignalTtlHours("health");
const CALENDAR_CONTEXT_TTL_HOURS = getWorldSignalTtlHours("calendar");
const DEVICE_CONTEXT_TTL_HOURS = getWorldSignalTtlHours("device");
const NOTIFICATION_CONTEXT_TTL_HOURS = getWorldSignalTtlHours("notification");
const TIME_CONTEXT_TTL_HOURS = getWorldSignalTtlHours("time");
const WORLD_CONTEXT_TTL_HOURS = getWorldSignalTtlHours("location");

const SAFE_HEALTH_FACT_LABELS = new Map<string, string>([
  // Qualitative derived
  ["activitylevel", "activity"],
  ["activityband", "activity_band"],
  ["energy", "energy"],
  ["energylevel", "energy"],
  ["fatigue", "fatigue"],
  ["focus", "focus"],
  ["hydration", "hydration"],
  ["mood", "mood"],
  ["movementtrend", "movement_trend"],
  ["readiness", "readiness"],
  ["readinesslevel", "readiness"],
  ["recovery", "recovery"],
  ["sleepquality", "sleep_quality"],
  ["stress", "stress"],
  ["stresslevel", "stress"],
  ["timeframe", "timeframe"],
  ["trend", "trend"],
  ["wellbeing", "wellbeing"],
  // Step counts (mobile-derived)
  ["stepstoday", "steps_today"],
  ["stepsyesterday", "steps_yesterday"],
  ["stepsthisweek", "steps_week"],
  // Sleep hours (mobile-derived)
  ["sleephourstoday", "sleep_h_today"],
  ["sleephoursyesterday", "sleep_h_yesterday"],
  ["sleepremhours", "sleep_rem_h"],
  ["sleeprempercent", "sleep_rem_pct"],
  ["sleepdeephours", "sleep_deep_h"],
  ["sleepdeeppercent", "sleep_deep_pct"],
  // Energy & workouts
  ["activeenergykcal", "active_kcal"],
  ["workoutcount", "workouts"],
  ["workoutdurationminutes", "workout_min"],
  ["workouttype", "workout_type"],
]);

const RAW_HEALTH_TEXT_PATTERN =
  /\b(bpm|nabız|heart\s*rate|tansiyon|blood\s*pressure|glucose|kan şekeri|adım|steps?|kcal|kalori|calories?|kilometre|km|metre|meters?|raw|sample|teşhis|tani|tanı|diagnosis|ilaç|medication)\b/i;
const RAW_MEASUREMENT_PATTERN =
  /\b\d+(?:[.,]\d+)?\s*(?:bpm|adım|steps?|kcal|kalori|calories?|km|kilometre|metre|meters?|saat|hours?|dakika|minutes?)\b/gi;
const PRIVATE_DERIVED_TEXT_PATTERN =
  /(?:https?:\/\/|file:\/\/|\/Users\/|[A-Za-z]:\\|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:\+?\d[\d\s().-]{7,}\d)|\b(attendee|attendees|body|description|event\s*title|invitee|meeting\s*link|message\s*body|notification\s*body|raw|sample|secret|token)\b|\b(bildirim\s+gövdesi|bildirim\s+govdesi|mesaj\s+içeriği|mesaj\s+icerigi|özel\s+içerik|ozel\s+icerik)\b)/i;

const SAFE_CALENDAR_FACT_LABELS = new Map<string, string>([
  ["availability", "availability"],
  ["busyness", "busyness"],
  ["busylevel", "busy_level"],
  ["dayload", "day_load"],
  ["calendardensity", "calendar_density"],
  ["deadlineload", "deadline_load"],
  ["hasdeadlinelikeevent", "has_deadline"],
  ["eventcount", "events"],
  ["focuswindow", "focus_window"],
  ["freeminutestoday", "free_min_today"],
  ["longestfreeblockminutes", "longest_free_min"],
  ["freewindow", "free_window"],
  ["meetingload", "meeting_load"],
  ["nexteventminutes", "next_event_min"],
  ["nexteventdurationminutes", "next_event_duration_min"],
  ["nexteventwindow", "next_event_window"],
  ["nextwindow", "next_window"],
  ["schedulepressure", "schedule_pressure"],
  ["timeframe", "timeframe"],
]);

const SAFE_DEVICE_FACT_LABELS = new Map<string, string>([
  ["appversion", "app_version"],
  ["battery", "battery"],
  ["batterylevel", "battery"],
  ["charging", "charging"],
  ["connectivity", "connectivity"],
  ["devicestate", "device_state"],
  ["focusmode", "focus_mode"],
  ["lowpowermode", "low_power"],
  ["network", "network"],
  ["online", "online"],
  ["osversion", "os"],
  ["platform", "platform"],
  ["storage", "storage"],
]);

const SAFE_NOTIFICATION_FACT_LABELS = new Map<string, string>([
  ["authorization", "notif_permission"],
  ["attentionload", "attention_load"],
  ["countbucket", "notif_density"],
  ["digest", "notif_digest"],
  ["focusimpact", "focus_impact"],
  ["notificationload", "notif_load"],
  ["priority", "priority"],
  ["urgency", "urgency"],
]);

const SAFE_TIME_FACT_LABELS = new Map<string, string>([
  ["daypart", "daypart"],
  ["localeday", "local_day"],
  ["localtime", "local_time"],
  ["localtimeofday", "local_time"],
  ["timezone", "timezone"],
  ["weekday", "weekday"],
  ["workinghours", "working_hours"],
]);

const SAFE_LOCATION_FACT_LABELS = new Map<string, string>([
  ["city", "city"],
  ["district", "district"],
  ["country", "country"],
  ["countrycode", "country_code"],
  ["region", "region"],
  ["timezone", "timezone"],
  ["zone", "zone"],
  ["mobility", "mobility"],
  ["cityknown", "city_known"],
  ["precision", "precision"],
]);

const GREETING_PATTERN =
  /^(selam|selamlar|merhaba|mrb|hey|hi|hello|günaydın|gunaydin|iyi akşamlar|iyi aksamlar|iyi geceler|naber|nasılsın|nasilsin)[\s!.?]*$/i;
const DEVICE_RELEVANCE_PATTERN =
  /\b(cihaz|device|pil|battery|şarj|sarj|ağ|ag|network|wifi|internet|bağlantı|baglanti|online|offline|kopuyor|çevrim|performans|yavaş|yavas|hata|problem|sorun|çöktü|crash|timeout)\b/i;
const HEALTH_RELEVANCE_PATTERN =
  /\b(sağlık|saglik|health|uyku|sleep|enerji|energy|yorgun|dinlen|adım|adim|steps?|spor|egzersiz|workout|fitness|stres|stress|odak|focus|rutin|wellbeing|iyi oluş|iyi olus|tempo|kalori|calor|nabız|nabiz|heart|yürü|yuru|koş|kos|walk|run|form|kondisyon|performans|kilo|weight|diyet|diet|beslenme|nutrition|vitamin|protein|su içtim|su ictim|antrenman|hissediyorum|kendimi|nasılım|nasilim|vücud|vucut|body)\b/i;
const LOCATION_RELEVANCE_PATTERN =
  /\b(nerede|neredeyim|konum|location|şehir|sehir|ilçe|ilce|yakın|yakin|çevre|cevre|mekan|restoran|yemek|hava|weather|sıcaklık|sicaklik|gezi|seyahat|rota|ulaşım|ulasim|öner|oner|meşhur|meshur|kayseri|hatay|istanbul|ankara|izmir|cafe|kafe|otel|hotel|park|market|eczane|hastane|havalimanı|havalimani|otogar|istasyon|sokak|cadde|semt|mahalle|bölge|bolge)\b/i;
const SCHEDULE_RELEVANCE_PATTERN =
  /\b(takvim|calendar|program|plan|planla|saat|time|bugün|bugun|yarın|yarin|toplantı|toplanti|müsait|musait|boş|bos|deadline|son tarih|odak|focus|yoğun|yogun|rutin|ajanda|zaman|gün|gun|hafta|ay|randevu|etkinlik|event|görev|gorev|task|iş|is|çalışma|calisma|ödev|odev|ders|sınav|sinav|sunum|presentation)\b/i;
const EXPLICIT_HEALTH_DATA_REQUEST_PATTERN =
  /(?:sağlık|saglik)\s+(?:verilerim|bilgilerim|özetim|durumum)|(?:adımlarım|adimlarim|uykum|uyku\s+verim|nabzım|nabzim|kalorim|egzersizim|antrenmanım|antrenmanim)|(?:benim|bana\s+ait).{0,32}(?:sağlık|saglik|adım|adim|uyku|nabız|nabiz|kalori|egzersiz|antrenman)|my\s+(?:health|steps?|sleep|heart\s*rate|calories|workouts?|fitness)(?:\s+data)?|how\s+many\s+steps\s+(?:did|have)\s+i/iu;
const EXPLICIT_LOCATION_DATA_REQUEST_PATTERN =
  /neredeyim|konumum|bulunduğum\s+yer|bulundugum\s+yer|where\s+am\s+i|my\s+(?:current\s+)?location/iu;
const EXPLICIT_CALENDAR_DATA_REQUEST_PATTERN =
  /takvimim|ajandam|programım|programim|randevularım|randevularim|toplantılarım|toplantilarim|etkinliklerim|my\s+(?:calendar|schedule|appointments?|meetings?|events?)/iu;
const NOTIFICATION_RELEVANCE_PATTERN =
  /\b(bildirim|notification|dikkat|attention|rahatsız|rahatsiz|odak|focus|sessiz|silent|acil|urgent|öncelik|oncelik)\b/i;
const ADAPTIVE_WORK_PATTERN =
  /\b(plan|planla|planning|program|schedule|bugün|bugun|yarın|yarin|task|görev|gorev|workflow|routine|rutin|araştır|arastir|research|debug|kod|code|odak|focus|hazırla|hazirla|çıkar|cikar|optimize|iyileştir|iyilestir|prepare)\b/i;
const EDUCATIONAL_HELP_PATTERN =
  /\b(açıkla|acikla|anlat|öğret|ogret|explain|teach|öğren|ogren|learn|ders|lesson|adım adım|step by step|rehber|guide)\b/i;
const CASUAL_OR_CREATIVE_ONLY_PATTERN =
  /\b(sohbet|chat|şaka|saka|joke|şiir|siir|poem|tweet|caption|başlık|baslik|isim söyle|name one|yaratıcı|creative|garip|weird|hayvan|animal)\b/i;
function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export type ExplicitMobileContextKind = "health" | "location" | "calendar";

export function explicitMobileContextKindsForPrompt(
  requestText: string | undefined,
): ExplicitMobileContextKind[] {
  const message = normalizeText(requestText ?? "");
  if (!message) return [];
  const kinds: ExplicitMobileContextKind[] = [];
  if (EXPLICIT_HEALTH_DATA_REQUEST_PATTERN.test(message)) kinds.push("health");
  if (EXPLICIT_LOCATION_DATA_REQUEST_PATTERN.test(message)) kinds.push("location");
  if (EXPLICIT_CALENDAR_DATA_REQUEST_PATTERN.test(message)) kinds.push("calendar");
  return kinds;
}

export function isExclusiveMobileContextRequest(
  requestText: string | undefined,
  kinds = explicitMobileContextKindsForPrompt(requestText),
): boolean {
  if (kinds.length === 0) return false;
  const tokens = normalizeText(requestText ?? "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .split(/\s+/u)
    .filter(Boolean);
  if (tokens.length === 0 || tokens.length > 28) return false;

  const common = /^(?:benim|bana|ait|bugün\p{L}*|bugun\p{L}*|dün\p{L}*|dun\p{L}*|şu|su|anda|an|mevcut|güncel|guncel|kaç\p{L}*|kac\p{L}*|ne|nedir|neler|var|nasıl|nasil|göster\p{L}*|goster\p{L}*|söyle\p{L}*|soyle\p{L}*|özet\p{L}*|ozet\p{L}*|veri\p{L}*|bilgi\p{L}*|durum\p{L}*|current|today|yesterday|what|which|where|how|many|show|tell|give|take|me|do|did|have|has|is|are|am|i|my|the|any|on|for|this|turn|and|ve)$/iu;
  const allowedByKind: Record<ExplicitMobileContextKind, RegExp> = {
    health:
      /^(?:sağlık\p{L}*|saglik\p{L}*|adım\p{L}*|adim\p{L}*|uyku\p{L}*|nabız\p{L}*|nabiz\p{L}*|kalori\p{L}*|egzersiz\p{L}*|antrenman\p{L}*|health|steps?|sleep|heart|rate|calories|workouts?|fitness|exercises?)$/iu,
    location:
      /^(?:nerede\p{L}*|konum\p{L}*|bulun\p{L}*|yer\p{L}*|location|located)$/iu,
    calendar:
      /^(?:takvim\p{L}*|ajanda\p{L}*|program\p{L}*|randevu\p{L}*|toplantı\p{L}*|toplanti\p{L}*|etkinlik\p{L}*|calendar|schedule|appointments?|meetings?|events?)$/iu,
  };
  return tokens.every(
    (token) =>
      common.test(token) || kinds.some((kind) => allowedByKind[kind].test(token)),
  );
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
  const isCasualOrCreativeOnly =
    (intent === "chat" || intent === "writing" || intent === "image") &&
    CASUAL_OR_CREATIVE_ONLY_PATTERN.test(message) &&
    !ADAPTIVE_WORK_PATTERN.test(message) &&
    !SCHEDULE_RELEVANCE_PATTERN.test(message) &&
    !LOCATION_RELEVANCE_PATTERN.test(message);
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

  if (isCasualOrCreativeOnly) {
    return {
      mentionPolicy: "silent",
      relevanceReason: "casual_or_creative_request_no_live_context_needed",
      allowedUse: ["do not mention this context"],
    };
  }

  if (input.packetKind === "health_context") {
    const explicit = HEALTH_RELEVANCE_PATTERN.test(message);
    const implicit = intent === "planning" || (ADAPTIVE_WORK_PATTERN.test(message) && !EDUCATIONAL_HELP_PATTERN.test(message));
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

  if (input.packetKind === "calendar_context") {
    const explicit = SCHEDULE_RELEVANCE_PATTERN.test(message) || intent === "planning";
    const implicit =
      !explicit &&
      (intent === "coding" ||
        intent === "debugging" ||
        intent === "document" ||
        intent === "research" ||
        intent === "automation" ||
        ADAPTIVE_WORK_PATTERN.test(message));
    return {
      mentionPolicy: explicit ? "explicit_when_relevant" : implicit ? "implicit" : "silent",
      relevanceReason: explicit
        ? "schedule_or_planning_request"
        : implicit
          ? "calendar_context_for_work_pacing_only"
          : "calendar_context_not_requested",
      allowedUse: explicit
        ? ["schedule-aware planning", "timing suggestions", "do not expose private event details"]
        : implicit
          ? ["adjust brevity and timing without naming the context"]
          : ["do not mention calendar context"],
    };
  }

  if (input.packetKind === "time_context") {
    const explicit =
      SCHEDULE_RELEVANCE_PATTERN.test(message) ||
      intent === "planning";
    const implicit =
      !explicit &&
      (intent === "coding" ||
        intent === "debugging" ||
        intent === "document" ||
        intent === "research" ||
        intent === "automation" ||
        intent === "math" ||
        ADAPTIVE_WORK_PATTERN.test(message));
    return {
      mentionPolicy: explicit ? "explicit_when_relevant" : implicit ? "implicit" : "silent",
      relevanceReason: explicit
        ? "time_aware_work_or_schedule_request"
        : implicit
          ? "time_context_for_work_pacing_only"
          : "time_context_not_requested",
      allowedUse: explicit
        ? [
            "time-aware framing",
            "schedule-aware planning",
            "suggest shorter path during late or busy windows",
          ]
        : implicit
          ? ["adjust brevity and timing without naming the context"]
          : ["do not mention time context"],
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

function mentionPriority(packet: ContextPacket): number {
  switch (packet.mentionPolicy) {
    case "explicit_when_relevant":
      return 0;
    case "implicit":
      return 1;
    default:
      return 2;
  }
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

function worldSignalConfidence(record: Record<string, unknown>): number {
  const direct = readNumber(record, "confidence");
  const bps = readNumber(record, "confidenceBps");
  return normalizeConfidence(direct ?? (bps == null ? null : bps / 1000));
}

function stableEvidenceValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableEvidenceValue);
  const record = readRecord(value);
  if (!record) return value;
  return Object.fromEntries(
    Object.entries(record)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, nested]) => [key, stableEvidenceValue(nested)]),
  );
}

function worldSignalEvidenceKey(record: Record<string, unknown>): string {
  return JSON.stringify({
    summary: normalizeText(readString(record, "summary") ?? ""),
    facts: stableEvidenceValue(record.facts),
  });
}

/**
 * Keeps one current record per signal kind. Within the newest five-minute
 * cohort confidence wins and recency breaks ties. Exact corroborating records
 * increase evidence; differing alternatives are suppressed instead of being
 * copied into the prompt as contradictory packets.
 */
export function fuseWorldSignalRecordsByKind<T extends object>(
  values: T[],
  options: { now?: Date } = {},
): Array<T & { fusionEvidenceCount: number; conflictSuppressedCount: number }> {
  const now = options.now ?? new Date();
  const grouped = new Map<string, Array<{ value: T; record: Record<string, unknown> }>>();
  for (const value of values) {
    const record = readRecord(value);
    const kind = (readString(record, "kind") ?? "").toLowerCase();
    if (!record || !kind) continue;
    const observedAt = parseDate(record.createdAt);
    if (
      !observedAt ||
      observedAt.getTime() - now.getTime() > MAX_FUTURE_CLOCK_SKEW_MS
    ) {
      continue;
    }
    const bucket = grouped.get(kind) ?? [];
    bucket.push({ value, record });
    grouped.set(kind, bucket);
  }

  return [...grouped.values()]
    .map((bucket) => {
      const latestObservedAt = Math.max(
        ...bucket.map(({ record }) => parseDate(record.createdAt)?.getTime() ?? 0),
      );
      const contenders = bucket.filter(({ record }) => {
        const observedAt = parseDate(record.createdAt)?.getTime() ?? 0;
        return latestObservedAt - observedAt <= WORLD_SIGNAL_FUSION_WINDOW_MS;
      });
      const winner = [...contenders].sort((left, right) => {
        const confidenceDelta =
          worldSignalConfidence(right.record) - worldSignalConfidence(left.record);
        if (confidenceDelta !== 0) return confidenceDelta;
        return (
          (parseDate(right.record.createdAt)?.getTime() ?? 0) -
          (parseDate(left.record.createdAt)?.getTime() ?? 0)
        );
      })[0] ?? bucket[0]!;
      const evidenceKey = worldSignalEvidenceKey(winner.record);
      const fusionEvidenceCount = contenders.filter(
        ({ record }) => worldSignalEvidenceKey(record) === evidenceKey,
      ).length;
      return {
        ...winner.value,
        fusionEvidenceCount: Math.max(1, fusionEvidenceCount),
        conflictSuppressedCount: Math.max(
          0,
          contenders.length - fusionEvidenceCount,
        ),
      };
    })
    .sort(
      (left, right) =>
        (parseDate(readRecord(right)?.createdAt)?.getTime() ?? 0) -
          (parseDate(readRecord(left)?.createdAt)?.getTime() ?? 0) ||
        worldSignalConfidence(readRecord(right) ?? {}) -
          worldSignalConfidence(readRecord(left) ?? {}),
    );
}

function classifyFreshness(createdAt: Date | null, now: Date, ttlHours: number): ContextPacketFreshness {
  if (!createdAt) {
    return "unknown";
  }
  if (createdAt.getTime() - now.getTime() > MAX_FUTURE_CLOCK_SKEW_MS) {
    return "stale";
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
    return "high";
  }
  if (normalized >= 0.42) {
    return "medium";
  }
  return "low";
}

function safeFactValue(value: unknown, options: { allowPlaintext?: boolean } = {}): string | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return qualitativeScore(value);
  }
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
  }
  if (typeof value !== "string") {
    return null;
  }
  const compact = clipCompactText(value, 64);
  if (!compact) {
    return null;
  }
  if (RAW_HEALTH_TEXT_PATTERN.test(compact)) {
    return null;
  }
  return compact.replace(RAW_MEASUREMENT_PATTERN, "ölçüm");
}

function safeDerivedFactValue(value: unknown): string | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return qualitativeScore(value);
  }
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
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
  const compact = clipCompactText(value.replace(RAW_MEASUREMENT_PATTERN, "ölçüm"), 180);
  if (!compact) {
    return "";
  }
  if (RAW_HEALTH_TEXT_PATTERN.test(compact)) {
    return "health_signal=recent detail=high_level";
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
    parts.push(`${label}=${safeValue}`);
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
    parts.push(`${label}=${safeValue}`);
    if (parts.length >= 4) {
      break;
    }
  }
  return parts;
}

function extractWorldSignalRecords(
  metadata: Record<string, unknown> | undefined,
  now: Date,
): Record<string, unknown>[] {
  const root = readRecord(metadata);
  const compactContext = readRecord(root?.compactContext);
  const chatContext = readRecord(root?.chatContext);
  const memorySnapshot = readRecord(root?.memorySnapshot);
  const directDerived = readRecord(root?.derivedContextDigest);
  const compactDerived = readRecord(compactContext?.derivedContextDigest);
  const chatDerived = readRecord(chatContext?.lastDerivedContextDigest);
  const sources = [
    readArray(compactDerived?.worldSignals),
    readArray(chatDerived?.worldSignals),
    readArray(directDerived?.worldSignals),
    readArray(memorySnapshot?.recentSignals),
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
      // The same signal can arrive through compact, chat and snapshot metadata
      // with differently clipped summaries. Prefer its stable id so one source
      // produces one packet; fall back to content only for legacy id-less rows.
      const key = signalId
        ? `id:${signalId}`.toLowerCase()
        : `content:${kind}:${summary}`.toLowerCase();
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      records.push(record);
    }
  }

  return fuseWorldSignalRecordsByKind(records, { now });
}

function fusedPacketEvidenceCount(
  signal: Record<string, unknown>,
  baseEvidenceCount: number,
): number {
  return Math.max(
    baseEvidenceCount,
    Math.round(readNumber(signal, "fusionEvidenceCount") ?? 1),
  );
}

function mobileContextCapabilities(
  metadata: Record<string, unknown> | undefined,
): Record<string, unknown> | null {
  const root = readRecord(metadata);
  const compactContext = readRecord(root?.compactContext);
  const chatContext = readRecord(root?.chatContext);
  return (
    readRecord(compactContext?.mobileContextCapabilities) ??
    readRecord(chatContext?.mobileContextCapabilities) ??
    readRecord(root?.mobileContextCapabilities)
  );
}

function isSignalAllowedByMobileCapabilities(
  kind: string,
  capabilities: Record<string, unknown> | null,
  signal: Record<string, unknown>,
): boolean {
  // New clients send current boolean capability truth. For legacy clients,
  // accept only a signal that carried explicit capture-time permission for
  // derived plaintext; an explicit false/missing kind on a present capability
  // record still fails closed.
  const capturePermission =
    !capabilities &&
    readRecord(signal.privacy)?.backendPlaintextAllowed === true;
  if (kind === "health") {
    return capabilities ? capabilities.healthEnabled === true : capturePermission;
  }
  if (kind === "location") {
    return capabilities ? capabilities.locationEnabled === true : capturePermission;
  }
  if (kind === "calendar") {
    return capabilities ? capabilities.calendarEnabled === true : capturePermission;
  }
  return true;
}

function buildRequestedContextAvailabilityPackets(
  metadata: Record<string, unknown> | undefined,
  requestText: string | undefined,
  existingPackets: ContextPacket[],
): ContextPacket[] {
  const message = normalizeText(requestText ?? "");
  if (!message) {
    return [];
  }
  const capabilities = mobileContextCapabilities(metadata);
  if (!capabilities) {
    return [];
  }
  const explicitlyRequestedKinds = new Set(
    explicitMobileContextKindsForPrompt(requestText),
  );

  const hasSignal = (kind: string): boolean =>
    existingPackets.some((packet) => packet.signalKinds.includes(kind));
  const packet = (input: {
    kind: ContextPacketKind;
    signalKind: string;
    title: string;
    summary: string;
    privacyClass: ContextPacket["privacyClass"];
    relevanceReason: string;
    allowedUse: string[];
  }): ContextPacket => ({
    kind: input.kind,
    source: "conversation",
    title: input.title,
    summary: input.summary,
    confidence: 1,
    freshness: "fresh",
    privacyClass: input.privacyClass,
    evidenceCount: 0,
    createdAt: null,
    expiresAt: null,
    renderHint: "context_signal",
    signalKinds: [input.signalKind],
    mentionPolicy: "explicit_when_relevant",
    relevanceReason: input.relevanceReason,
    allowedUse: input.allowedUse,
  });

  const packets: ContextPacket[] = [];
  if (explicitlyRequestedKinds.has("health") && !hasSignal("health")) {
    const enabled = capabilities.healthEnabled === true;
    packets.push(packet({
      kind: "health_context",
      signalKind: "health_availability",
      title: "Sağlık bağlamı erişim durumu",
      summary: enabled
        ? "Health context is enabled, but no current authorized health signal was available for this turn."
        : "Health context is disabled in Elyan app settings for this turn.",
      privacyClass: "health_ephemeral",
      relevanceReason: enabled ? "health_context_unavailable" : "health_context_disabled",
      allowedUse: [
        "state clearly that current authorized health data is unavailable",
        "do not substitute web results, e-Nabız, or generic health records for the user's data",
        "do not claim access to health data",
      ],
    }));
  }

  if (explicitlyRequestedKinds.has("location") && !hasSignal("location")) {
    const enabled = capabilities.locationEnabled === true;
    packets.push(packet({
      kind: "world_context",
      signalKind: "location_availability",
      title: "Konum bağlamı erişim durumu",
      summary: enabled
        ? "Location context is enabled, but no current authorized location signal was available for this turn."
        : "Location context is disabled in Elyan app settings for this turn.",
      privacyClass: "ephemeral",
      relevanceReason: enabled ? "location_context_unavailable" : "location_context_disabled",
      allowedUse: [
        "state clearly that the current authorized location is unavailable",
        "do not infer the user's location from web results or unrelated context",
        "do not claim access to location data",
      ],
    }));
  }

  if (explicitlyRequestedKinds.has("calendar") && !hasSignal("calendar")) {
    const enabled = capabilities.calendarEnabled === true;
    packets.push(packet({
      kind: "calendar_context",
      signalKind: "calendar_availability",
      title: "Takvim bağlamı erişim durumu",
      summary: enabled
        ? "Calendar context is enabled, but no current authorized calendar signal was available for this turn."
        : "Calendar context is disabled in Elyan app settings for this turn.",
      privacyClass: "ephemeral",
      relevanceReason: enabled ? "calendar_context_unavailable" : "calendar_context_disabled",
      allowedUse: [
        "state clearly that current authorized calendar context is unavailable",
        "do not invent events or availability",
        "do not claim access to calendar data",
      ],
    }));
  }

  return packets;
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
    evidenceCount: fusedPacketEvidenceCount(signal, 1 + factsSummary.length),
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
    evidenceCount: fusedPacketEvidenceCount(signal, 1 + factsSummary.length),
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
  const summary = clipCompactText(
    scrubDerivedSummary(readString(signal, "summary") ?? "", `${kind}_signal=recent`),
    MAX_PACKET_SUMMARY_CHARS,
  );
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
    evidenceCount: fusedPacketEvidenceCount(signal, 1),
    createdAt: createdAt?.toISOString() ?? null,
    expiresAt: expiresAt(createdAt, WORLD_CONTEXT_TTL_HOURS),
    renderHint: "context_signal",
    signalKinds: [kind],
  };
}

export function summarizeContextFreshness(
  packets: ContextPacket[],
  now = new Date(),
): ContextFreshnessSummary {
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
      oldest
        ? Number(Math.max(0, (now.getTime() - oldest.getTime()) / 3_600_000).toFixed(2))
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
  const capabilities = mobileContextCapabilities(metadata);

  for (const signal of extractWorldSignalRecords(metadata, now)) {
    const kind = (readString(signal, "kind") ?? "").toLowerCase();
    if (!isSignalAllowedByMobileCapabilities(kind, capabilities, signal)) {
      continue;
    }
    const packet = kind === "health"
      ? buildHealthPacket(signal, now)
      : kind === "calendar"
        ? buildDerivedWorldPacket(signal, now, {
            packetKind: "calendar_context",
            title: "Takvim ve zaman bağlamı",
            ttlHours: CALENDAR_CONTEXT_TTL_HOURS,
            privacyClass: "ephemeral",
            factLabels: SAFE_CALENDAR_FACT_LABELS,
            summaryFallback: "calendar_signal=recent detail=safe_summary",
            signalKind: "calendar",
          })
        : kind === "device"
          ? buildDerivedWorldPacket(signal, now, {
              packetKind: "device_context",
              title: "Cihaz durumu bağlamı",
              ttlHours: DEVICE_CONTEXT_TTL_HOURS,
              privacyClass: "safe_derived",
              factLabels: SAFE_DEVICE_FACT_LABELS,
              summaryFallback: "device_signal=recent detail=safe_summary",
              signalKind: "device",
            })
          : kind === "notification"
            ? buildDerivedWorldPacket(signal, now, {
                packetKind: "notification_context",
                title: "Bildirim ve dikkat bağlamı",
                ttlHours: NOTIFICATION_CONTEXT_TTL_HOURS,
                privacyClass: "ephemeral",
                factLabels: SAFE_NOTIFICATION_FACT_LABELS,
                summaryFallback: "notification_signal=recent detail=safe_summary",
                signalKind: "notification",
              })
            : kind === "location"
              ? buildDerivedWorldPacket(signal, now, {
                  packetKind: "world_context",
                  title: "Konum bağlamı",
                  ttlHours: WORLD_CONTEXT_TTL_HOURS,
                  privacyClass: "ephemeral",
                  factLabels: SAFE_LOCATION_FACT_LABELS,
                  summaryFallback: "location_signal=recent detail=safe_summary",
                  signalKind: "location",
                })
              : kind === "time"
                ? buildDerivedWorldPacket(signal, now, {
                  packetKind: "time_context",
                  title: "Yerel zaman bağlamı",
                  ttlHours: TIME_CONTEXT_TTL_HOURS,
                  privacyClass: "safe_derived",
                  factLabels: SAFE_TIME_FACT_LABELS,
                  summaryFallback: "time_signal=recent detail=safe_summary",
                  signalKind: "time",
                })
                : buildWorldPacket(signal, now);
    if (packet) {
      const guided = withUsageGuidance(packet, options);
      if (!options.requestText?.trim() || guided.mentionPolicy !== "silent") {
        packets.push(guided);
      }
    }
  }

  packets.push(...buildRequestedContextAvailabilityPackets(metadata, options.requestText, packets));

  return packets
    .sort((left, right) => {
      const priorityDelta = mentionPriority(left) - mentionPriority(right);
      if (priorityDelta !== 0) {
        return priorityDelta;
      }
      const leftDate = parseDate(left.createdAt)?.getTime() ?? 0;
      const rightDate = parseDate(right.createdAt)?.getTime() ?? 0;
      return rightDate - leftDate || right.confidence - left.confidence;
    })
    .slice(0, MAX_PACKETS);
}
