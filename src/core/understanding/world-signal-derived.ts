import type { ContextPacket, LearningSignal } from "./types.js";

type FreshWorldSignal = {
  signalId?: string;
  kind: string;
  summary: string;
  confidence: number;
  facts: Record<string, unknown> | null;
  privacy?: Record<string, unknown> | null;
  createdAt: Date;
};

type DerivedHintBucket = {
  situationalHints: string[];
  behavioralHints: string[];
  environmentHints: string[];
};

const DERIVED_SIGNAL_ALLOWLIST = new Set([
  "energy_rhythm",
  "planning_style",
  "schedule_pressure_pattern",
  "mobility_context",
  "local_preference_context",
  "notification_attention_pattern",
  "preferred_working_window",
  "common_city",
  "preferred_planning_granularity",
]);

const LOCATION_RELEVANCE_PATTERN =
  /\b(nerede|konum|location|şehir|sehir|ilçe|ilce|yakın|yakin|çevre|cevre|mekan|restoran|yemek|hava|weather|rota|ulaşım|ulasim|öner|oner|gez|seyahat)\b/i;
const SCHEDULE_RELEVANCE_PATTERN =
  /\b(takvim|calendar|program|plan|planla|saat|bugün|bugun|yarın|yarin|toplantı|toplanti|müsait|musait|boş|bos|deadline|son tarih|odak|focus|yoğun|yogun|rutin|ajanda|zaman)\b/i;
const HEALTH_RELEVANCE_PATTERN =
  /\b(sağlık|saglik|health|uyku|sleep|enerji|energy|yorgun|dinlen|adım|adim|steps?|spor|egzersiz|workout|fitness|stres|stress|odak|focus|tempo)\b/i;
const NOTIFICATION_RELEVANCE_PATTERN =
  /\b(bildirim|notification|dikkat|attention|rahatsız|rahatsiz|odak|focus|sessiz|silent|acil|urgent|öncelik|oncelik)\b/i;
const GREETING_PATTERN =
  /^(selam|selamlar|merhaba|mrb|hey|hi|hello|günaydın|gunaydin|iyi akşamlar|iyi aksamlar|iyi geceler|naber|nasılsın|nasilsin)[\s!.?]*$/i;
const ADAPTIVE_WORK_PATTERN =
  /\b(plan|planla|planning|program|schedule|bugün|bugun|yarın|yarin|task|görev|gorev|workflow|routine|rutin|araştır|arastir|research|debug|kod|code|odak|focus|hazırla|hazirla|çıkar|cikar|optimize|iyileştir|iyilestir|prepare)\b/i;

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
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

function normalizeKey(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
}

function isPlaintextAllowed(signal: FreshWorldSignal): boolean {
  return signal.privacy?.backendPlaintextAllowed === true;
}

function signalAgeHours(signal: FreshWorldSignal, now = new Date()): number {
  return Math.max(0, (now.getTime() - signal.createdAt.getTime()) / 3_600_000);
}

function sanitizeDerivedValue(value: string, maxLength = 120): string | null {
  const compact = compactText(value).slice(0, maxLength);
  if (!compact) {
    return null;
  }
  if (/(https?:\/\/|file:\/\/|\/Users\/|[A-Za-z]:\\|@|token|secret|attendee|meeting link|message body|notification body)/i.test(compact)) {
    return null;
  }
  return compact;
}

function buildSignal(
  key: string,
  value: string,
  input: {
    confidence?: number;
    ttlDays: number;
    signalId?: string;
    sourceKey?: string;
    sourceKind?: string;
    sourceCategory: "situational" | "behavioral" | "environmental";
  },
): LearningSignal | null {
  if (!DERIVED_SIGNAL_ALLOWLIST.has(key)) {
    return null;
  }
  const cleaned = sanitizeDerivedValue(value);
  if (!cleaned) {
    return null;
  }
  return {
    type: "workflow",
    key,
    value: cleaned,
    confidence: Math.max(0.68, Math.min(0.99, input.confidence ?? 0.82)),
    scope: "user",
    source: "system",
    ttlDays: input.ttlDays,
    metadata: {
      sourceCategory: "world_signal_derived",
      derivedTraitCategory: input.sourceCategory,
      signalId: input.signalId ?? null,
      sourceKind: input.sourceKind ?? null,
      sourceKey: input.sourceKey ?? null,
    },
  };
}

function maybePush(target: string[], value: string | null) {
  if (!value) {
    return;
  }
  const compact = compactText(value);
  if (!compact || target.includes(compact)) {
    return;
  }
  target.push(compact);
}

function deriveFromHealth(signal: FreshWorldSignal): LearningSignal[] {
  const facts = signal.facts;
  const readiness = readNumber(facts, "readiness");
  // Mobile sends qualitative bands (energyLevel/activityBand/trend) rather than
  // a numeric readiness score, so reason from those when readiness is absent.
  const energy = readString(facts, "energy") ?? readString(facts, "energyLevel");
  const fatigue = readString(facts, "fatigue");
  const focus = readString(facts, "focus");
  const activityBand = readString(facts, "activityBand") ?? readString(facts, "activityLevel");
  const sleepQuality = readString(facts, "sleepQuality");
  const trend = readString(facts, "trend");
  const stepsToday = readNumber(facts, "stepsToday");
  const stepsYesterday = readNumber(facts, "stepsYesterday");
  const energyLow = readiness != null ? readiness < 0.45 : energy === "low" || sleepQuality === "low";
  const energyHigh = readiness != null ? readiness >= 0.72 : energy === "high" || (sleepQuality === "good" && activityBand === "high");
  // DİL-NÖTR TOKEN DEĞERLERİ: türetilmiş değerler İngilizce nesir yerine
  // makine-okur key=value token'ları taşır. Nesir hâli (örn. "low energy
  // window; prefer shorter, lower-friction steps") Türkçe sohbetlere İngilizce
  // parça sızdırıyordu ve model bunu policy cümlesi gibi aynalıyordu.
  // Token'lar (`energy=low pace=light`) modelde veri alanı muamelesi görür —
  // model kavramı KENDİ cevap dilinde, kendi samimi ifadesiyle söyler.
  const rhythm = energyLow
    ? "energy=low pace=light"
    : energyHigh
      ? "energy=high focus=deep"
      : energy
        ? `energy=${energy} pace=adaptive`
        : null;
  const signals: LearningSignal[] = [];
  const energySignal = rhythm
    ? buildSignal("energy_rhythm", rhythm, {
        confidence: signal.confidence,
        ttlDays: 2,
        signalId: signal.signalId,
        sourceKind: signal.kind,
        sourceCategory: "situational",
      })
    : null;
  if (energySignal) {
    signals.push(energySignal);
  }
  // Movement momentum: a clear day-over-day rise or fall in activity is a
  // useful situational nudge even without a clinical reading.
  const stepsTrend =
    trend === "better" || (stepsToday != null && stepsYesterday != null && stepsToday - stepsYesterday > 2000)
      ? "activity_trend=up momentum=build"
      : trend === "worse" || (stepsToday != null && stepsYesterday != null && stepsYesterday - stepsToday > 2000)
        ? "activity_trend=down pace=gentle"
        : null;
  const trendSignal = stepsTrend
    ? buildSignal("energy_rhythm", stepsTrend, {
        confidence: Math.max(0.7, signal.confidence - 0.06),
        ttlDays: 1,
        signalId: signal.signalId,
        sourceKind: signal.kind,
        sourceCategory: "situational",
      })
    : null;
  if (trendSignal) {
    signals.push(trendSignal);
  }
  const planningStyle = (energyHigh && (focus || activityBand === "high"))
    ? "focus_blocks=large depth=deep"
    : (fatigue || energyLow)
      ? "steps=small wins=fast"
      : null;
  const planningSignal = planningStyle
    ? buildSignal("planning_style", planningStyle, {
        confidence: signal.confidence,
        ttlDays: 3,
        signalId: signal.signalId,
        sourceKind: signal.kind,
        sourceCategory: "behavioral",
      })
    : null;
  if (planningSignal) {
    signals.push(planningSignal);
  }
  return signals;
}

function deriveFromCalendar(signal: FreshWorldSignal): LearningSignal[] {
  const facts = signal.facts;
  const freeMinutes = readNumber(facts, "freeMinutesToday");
  const longestBlock = readNumber(facts, "longestFreeBlockMinutes");
  const busyness = readString(facts, "busyness") ?? readString(facts, "busyLevel");
  const schedulePressure = busyness
    ? `schedule=${busyness}`
    : longestBlock != null && longestBlock >= 90
      ? `focus_window_min=${Math.round(longestBlock)}`
      : freeMinutes != null && freeMinutes < 45
        ? `free_min=${Math.round(freeMinutes)} plan=compact`
        : null;
  const planningGranularity = longestBlock != null && longestBlock >= 90
    ? "blocks=large uninterrupted=preferred"
    : freeMinutes != null && freeMinutes < 45
      ? "steps=timeboxed density=compact"
      : null;
  return [
    buildSignal("schedule_pressure_pattern", schedulePressure ?? "", {
      confidence: signal.confidence,
      ttlDays: 2,
      signalId: signal.signalId,
      sourceKind: signal.kind,
      sourceCategory: "situational",
    }),
    buildSignal("preferred_working_window", schedulePressure ?? "", {
      confidence: Math.max(0.7, signal.confidence - 0.08),
      ttlDays: 7,
      signalId: signal.signalId,
      sourceKind: signal.kind,
      sourceCategory: "behavioral",
    }),
    buildSignal("preferred_planning_granularity", planningGranularity ?? "", {
      confidence: Math.max(0.72, signal.confidence - 0.04),
      ttlDays: 14,
      signalId: signal.signalId,
      sourceKind: signal.kind,
      sourceCategory: "behavioral",
    }),
  ].filter((item): item is LearningSignal => item != null);
}

function deriveFromLocation(signal: FreshWorldSignal): LearningSignal[] {
  const facts = signal.facts;
  const city = readString(facts, "city");
  const region = readString(facts, "region") ?? readString(facts, "district");
  const timezone = readString(facts, "timezone");
  const mobility = readString(facts, "mobility");
  const environment = [city, region].filter(Boolean).join(", ");
  return [
    buildSignal("mobility_context", mobility ? `mobility=${mobility}` : "", {
      confidence: signal.confidence,
      ttlDays: 3,
      signalId: signal.signalId,
      sourceKind: signal.kind,
      sourceCategory: "situational",
    }),
    buildSignal(
      "local_preference_context",
      environment ? `locale=${environment}` : timezone ? `timezone=${timezone}` : "",
      {
        confidence: signal.confidence,
        ttlDays: 14,
        signalId: signal.signalId,
        sourceKind: signal.kind,
        sourceCategory: "environmental",
      },
    ),
    buildSignal("common_city", city ?? "", {
      confidence: Math.max(0.72, signal.confidence - 0.05),
      ttlDays: 30,
      signalId: signal.signalId,
      sourceKind: signal.kind,
      sourceCategory: "environmental",
    }),
  ].filter((item): item is LearningSignal => item != null);
}

function deriveFromNotification(signal: FreshWorldSignal): LearningSignal[] {
  const facts = signal.facts;
  const attention = readString(facts, "attentionLoad") ?? readString(facts, "notificationLoad");
  const urgency = readString(facts, "urgency");
  const value = attention
    ? `attention=${attention}${urgency ? ` urgency=${urgency}` : ""}`
    : urgency
      ? `urgency=${urgency}`
      : "";
  return [
    buildSignal("notification_attention_pattern", value, {
      confidence: signal.confidence,
      ttlDays: 1,
      signalId: signal.signalId,
      sourceKind: signal.kind,
      sourceCategory: "situational",
    }),
  ].filter((item): item is LearningSignal => item != null);
}

export function deriveLearningSignalsFromWorldSignals(signals: FreshWorldSignal[]): LearningSignal[] {
  const derived: LearningSignal[] = [];
  for (const signal of signals) {
    if (!isPlaintextAllowed(signal) && signal.kind === "health") {
      // Health can still derive from safe facts, but not from raw summary text.
    }
    if (signal.kind === "health") {
      derived.push(...deriveFromHealth(signal));
    } else if (signal.kind === "calendar") {
      derived.push(...deriveFromCalendar(signal));
    } else if (signal.kind === "location") {
      derived.push(...deriveFromLocation(signal));
    } else if (signal.kind === "notification") {
      derived.push(...deriveFromNotification(signal));
    }
  }
  return derived;
}

export function buildDerivedHintBuckets(input: {
  memory: Array<{
    key: string;
    value: string;
    metadata?: Record<string, unknown>;
    staleness?: string;
  }>;
  requestText: string;
  contextPackets?: Array<
    Pick<ContextPacket, "signalKinds" | "mentionPolicy" | "relevanceReason">
  >;
}): DerivedHintBucket {
  const situationalHints: string[] = [];
  const behavioralHints: string[] = [];
  const environmentHints: string[] = [];
  const request = compactText(input.requestText).toLowerCase();
  const isGreeting = GREETING_PATTERN.test(request);
  const wantsSchedule = SCHEDULE_RELEVANCE_PATTERN.test(request);
  const wantsHealth = HEALTH_RELEVANCE_PATTERN.test(request);
  const wantsLocation = LOCATION_RELEVANCE_PATTERN.test(request);
  const wantsNotifications = NOTIFICATION_RELEVANCE_PATTERN.test(request);
  const wantsAdaptiveHelp = ADAPTIVE_WORK_PATTERN.test(request);
  const packetGuidanceBySignalKind = new Map(
    (input.contextPackets ?? []).flatMap((packet) =>
      packet.signalKinds.map((kind) => [kind.toLowerCase(), packet] as const),
    ),
  );
  const usePacketGuidance = input.contextPackets !== undefined;

  for (const item of input.memory) {
    if (item.staleness === "stale" || item.staleness === "contested") {
      continue;
    }
    const metadata = readRecord(item.metadata);
    if (readString(metadata, "sourceCategory") !== "world_signal_derived") {
      continue;
    }
    const category = readString(metadata, "derivedTraitCategory");
    const sourceKind = readString(metadata, "sourceKind")?.toLowerCase() ?? null;
    const guidedPacket = sourceKind
      ? packetGuidanceBySignalKind.get(sourceKind)
      : undefined;
    if (
      usePacketGuidance &&
      (!guidedPacket || guidedPacket.mentionPolicy === "silent")
    ) {
      continue;
    }
    const value = sanitizeDerivedValue(item.value, 160);
    if (!value) {
      continue;
    }

    if (usePacketGuidance) {
      if (category === "situational") {
        maybePush(situationalHints, value);
      } else if (category === "behavioral") {
        maybePush(behavioralHints, value);
      } else if (category === "environmental") {
        maybePush(environmentHints, value);
      }
      continue;
    }

    if (category === "situational") {
      if (isGreeting) {
        continue;
      }
      if (
        item.key === "energy_rhythm" && (wantsHealth || wantsSchedule || /plan|write|debug|araştır|research/.test(request))
      ) {
        maybePush(situationalHints, value);
      } else if (item.key === "schedule_pressure_pattern" && (wantsSchedule || /plan|deadline|task/.test(request))) {
        maybePush(situationalHints, value);
      } else if (item.key === "mobility_context" && wantsLocation) {
        maybePush(situationalHints, value);
      } else if (item.key === "notification_attention_pattern" && wantsNotifications) {
        maybePush(situationalHints, value);
      }
    }

    if (category === "behavioral") {
      if (!isGreeting && (wantsSchedule || wantsHealth || wantsNotifications || wantsAdaptiveHelp)) {
        maybePush(behavioralHints, value);
      }
    }

    if (category === "environmental") {
      if (
        !isGreeting &&
        ((item.key === "common_city" && wantsLocation) ||
          (item.key !== "common_city" && (wantsLocation || wantsSchedule)))
      ) {
        maybePush(environmentHints, value);
      }
    }
  }

  return {
    situationalHints: situationalHints.slice(0, 4),
    behavioralHints: behavioralHints.slice(0, 4),
    environmentHints: environmentHints.slice(0, 4),
  };
}

export function toDerivedSignalInput(raw: {
  signalId?: string;
  kind: string;
  summary: string;
  confidence: number;
  facts: unknown;
  privacy?: unknown;
  createdAt: Date;
}): FreshWorldSignal {
  return {
    signalId: raw.signalId,
    kind: raw.kind,
    summary: compactText(raw.summary),
    confidence: Math.max(0, Math.min(1, raw.confidence)),
    facts: readRecord(raw.facts),
    privacy: readRecord(raw.privacy),
    createdAt: raw.createdAt,
  };
}

export function buildDerivedContextSummary(signals: FreshWorldSignal[]): string[] {
  const hints: string[] = [];
  for (const signal of signals) {
    const ageHours = signalAgeHours(signal);
    if (ageHours > 24) {
      continue;
    }
    if (signal.kind === "health") {
      const readiness = readNumber(signal.facts, "readiness");
      const energyLevel = normalizeKey(readString(signal.facts, "energyLevel") ?? readString(signal.facts, "energy") ?? "");
      const sleepQuality = normalizeKey(readString(signal.facts, "sleepQuality") ?? "");
      const lowEnergy = (readiness != null && readiness < 0.45) || energyLevel === "low" || sleepQuality === "low";
      const highEnergy = (readiness != null && readiness >= 0.72) || energyLevel === "high";
      // Dil-nötr token'lar: model kavramı kendi cevap dilinde ifade eder;
      // İngilizce coaching cümleleri Türkçe cevaplara sızmaz.
      if (lowEnergy) {
        maybePush(hints, "energy=low reply_pace=light");
      } else if (highEnergy) {
        maybePush(hints, "energy=high ambition=welcome");
      }
    } else if (signal.kind === "calendar") {
      const freeMinutes = readNumber(signal.facts, "freeMinutesToday");
      if (freeMinutes != null && freeMinutes < 45) {
        maybePush(hints, `free_min=${Math.round(freeMinutes)} plan=tight`);
      }
    } else if (signal.kind === "notification") {
      const attention = normalizeKey(readString(signal.facts, "attentionLoad") ?? "");
      if (attention === "high") {
        maybePush(hints, "attention=fragmented suggestions=low_noise");
      }
    }
  }
  return hints.slice(0, 3);
}
