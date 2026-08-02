import { createHash } from "node:crypto";

import type { UserUnderstandingContext } from "../../core/understanding/types.js";

/**
 * Grounded fast replies for social turns.
 *
 * WHY THIS EXISTS
 * ---------------
 * The fast chat route answered social turns from a fixed table of sentences.
 * Five of its eight branches contained the word "buradayım", so anyone who
 * opened more than a handful of conversations heard the same word every time
 * and the assistant read as dead.
 *
 * The instinct is to add more canned variants. That is the wrong fix and this
 * repo already paid for it once (NEREDE-KALDIK §1: adding patterns is a
 * bottomless pit). Rotating five greetings does not create life — it only
 * delays the moment you notice its absence.
 *
 * THE ACTUAL PROBLEM: warmth vocabulary is infinitely repeatable, therefore
 * dead. "Buradayım" could be said by anyone, at any moment, about anything.
 * "Dün bıraktığımız rapor hâlâ yarım" could only be said by *this* assistant
 * to *this* user *right now*. Liveness is not a tone — it is verifiable truth.
 *
 * THE CONTRACT
 * ------------
 *  1. **Zero extra latency.** No model call. This runs on the fast route and
 *     must stay as cheap as the table it replaces — it composes from context
 *     the request already carries.
 *  2. **No fabrication.** A cue is emitted only when a real signal backs it.
 *     No signal → plain opener. Inventing "how was your day?" familiarity is
 *     worse than saying little (§4.6).
 *  3. **One cue, never two.** Stacking facts turns a greeting into a status
 *     report. The greeting stays a greeting.
 *  4. **Never the same opener twice in a row.** Repetition is what killed the
 *     old table. This is enforced structurally (see {@link rememberReply}),
 *     not by writing more sentences.
 */

export type SocialTurnKind =
  | "greeting"
  | "morning"
  | "night"
  | "how_are_you"
  | "presence"
  | "what_doing"
  | "thanks"
  | "farewell"
  | "bored"
  | "affection"
  | "ack";

/** Live signals the desktop/runtime layer knows and the greeting can use. */
export type LiveSocialSignals = {
  /** A task is executing right now, with the step label if known. */
  activeTaskLabel?: string | null;
  /** Steps completed / total for the running task. */
  activeTaskProgress?: { completed: number; total: number } | null;
  /** Most recent artifact this assistant produced for the user. */
  recentOutputName?: string | null;
  /** Minutes since that artifact was produced. */
  recentOutputMinutesAgo?: number | null;
  /** Next calendar event title and minutes until it starts. */
  upcomingEventTitle?: string | null;
  upcomingEventMinutes?: number | null;
};

const MAX_CUE_CHARS = 90;
const PERSONAL_ANCHOR_MIN_CONFIDENCE = 0.72;
const PERSONAL_ANCHOR_MAX_AGE_DAYS = 180;

/**
 * How many recent openers to remember per user.
 *
 * Three is deliberate: it kills the "same sentence every single time" feel
 * without forcing the assistant to reach for an unnatural phrasing on the
 * fourth turn. In-process only — a restart resets it, which is fine: this is
 * a politeness heuristic, not state worth persisting.
 */
const RECENT_REPLY_MEMORY = 3;
const RECENT_USER_LIMIT = 512;
const SENSITIVE_ANCHOR_VALUE_RE =
  /(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:password|parola|şifre|sifre|token|secret|api[_ -]?key|credential|kimlik|adres|address|phone|telefon|iban|card|kart)\b|\b\d[\d\s().+-]{7,}\d\b)/iu;

const recentReplies = new Map<string, string[]>();

/**
 * KULLANICILAR ARASI SIZINTI YOK.
 *
 * This cache lives in a multi-tenant process, so two rules are absolute:
 *
 *  1. **No shared bucket.** An unidentified caller gets *no* memory at all
 *     rather than a common "anonymous" slot. A shared slot would mix one
 *     person's openers with another's — and those openers carry names.
 *  2. **No plaintext.** Only a salted hash of the opener is stored, never the
 *     sentence itself. Even a heap dump cannot read "Merhaba Ayşe" back out.
 *
 * What is remembered is deliberately worthless on its own: an opaque digest
 * used to answer one question — "did I just say this to *this* person?"
 */
function signatureOf(reply: string): string {
  const normalized = reply
    .toLocaleLowerCase("tr-TR")
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
  return createHash("sha256")
    .update(`elyan.social-opener.v1:${normalized}`)
    .digest("base64url")
    .slice(0, 22);
}

function isIdentified(userId: string): boolean {
  const id = String(userId ?? "").trim();
  return id.length > 0 && id !== "anonymous";
}

/** Was this opener already used in the last few turns with this user? */
export function isRepeatReply(userId: string, reply: string): boolean {
  if (!isIdentified(userId)) return false;
  const seen = recentReplies.get(userId);
  return seen ? seen.includes(signatureOf(reply)) : false;
}

export function rememberReply(userId: string, reply: string): void {
  // Kimliksiz çağıran hiç hatırlanmaz — ortak kova AÇILMAZ.
  if (!isIdentified(userId)) return;
  const signature = signatureOf(reply);
  const seen = recentReplies.get(userId) ?? [];
  const next = [signature, ...seen.filter((item) => item !== signature)].slice(
    0,
    RECENT_REPLY_MEMORY,
  );
  recentReplies.set(userId, next);
  if (recentReplies.size > RECENT_USER_LIMIT) {
    const oldest = recentReplies.keys().next().value;
    if (oldest !== undefined) recentReplies.delete(oldest);
  }
}

/** Oturum kapanınca kullanıcının izini bırakma. */
export function forgetUser(userId: string): void {
  recentReplies.delete(userId);
}

/** Test seam — the cache is process-global by design. */
export function resetRecentReplies(): void {
  recentReplies.clear();
}

function compact(value: string | null | undefined): string | null {
  const text = String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
  if (!text) return null;
  return text.length > MAX_CUE_CHARS
    ? `${text.slice(0, MAX_CUE_CHARS - 1).trimEnd()}…`
    : text;
}

function safeAnchorValue(value: string | null | undefined): string | null {
  const text = compact(value);
  if (!text || SENSITIVE_ANCHOR_VALUE_RE.test(text)) return null;
  return text;
}

function safePersonalAnchorCue(
  context: UserUnderstandingContext | undefined,
): string | null {
  const facts = context?.memoryRecall?.facts ?? [];
  const safeFacts = facts
    .filter(
      (fact) =>
        fact.confidence >= PERSONAL_ANCHOR_MIN_CONFIDENCE &&
        fact.ageDays >= 0 &&
        fact.ageDays <= PERSONAL_ANCHOR_MAX_AGE_DAYS,
    )
    .map((fact) => ({
      key: fact.key.trim().toLocaleLowerCase("en-US"),
      value: safeAnchorValue(fact.value),
    }))
    .filter((fact): fact is { key: string; value: string } =>
      Boolean(fact.value),
    );
  const read = (...keys: string[]) =>
    safeFacts.find((fact) => keys.includes(fact.key))?.value ?? null;

  const project = read("active_project", "project", "primary_repo");
  if (project) return `${project} bağlamını aklımda tutuyorum.`;

  // `working_boundary` / `implementation_boundary` bilerek ATLANIYOR.
  // Bunlar Elyan'ın kendi çalışma kuralları — kullanıcı hakkında bir tercih
  // değil. Selamlaşmaya iliştirilince "Çalışma sınırını biliyorum: preserve
  // existing architecture and avoid unrelated rewrites." gibi, çoğu zaman
  // İngilizce ve kullanıcıya hiçbir şey ifade etmeyen bir cümle çıkıyordu.

  const length = read("answer_length", "brevity_preference");
  if (length && /short|concise|kısa|kisa|brief/i.test(length)) {
    return "Kısa ve net gitmeyi tercih ettiğini biliyorum.";
  }
  if (length && /detailed|long|detay|uzun/i.test(length)) {
    return "Gerektiğinde detaylı anlatımı tercih ettiğini biliyorum.";
  }

  const planning = read(
    "preferred_planning_granularity",
    "planning_granularity",
  );
  if (planning) return `Plan yoğunluğu tercihin aklımda: ${planning}.`;

  const tone = read("preferred_tone", "response_style_preference");
  if (tone && /professional|calm|precise|net|sakin|profesyonel/i.test(tone)) {
    return "Sakin ve net tonda kalacağım.";
  }

  return null;
}

/**
 * The single most relevant true thing to mention right now, or null.
 *
 * Order is by *how much the user is likely to care in this second*, not by how
 * impressive the signal is: something running beats something finished, and
 * something finished beats something scheduled.
 */
export function selectLivenessCue(
  context: UserUnderstandingContext | undefined,
  signals: LiveSocialSignals | undefined,
): string | null {
  if (signals?.activeTaskLabel) {
    const label = compact(signals.activeTaskLabel);
    const progress = signals.activeTaskProgress;
    if (label && progress && progress.total > 0) {
      return `Şu an ${label} üzerindeyim — ${progress.completed}/${progress.total} adım.`;
    }
    if (label) return `Şu an ${label} üzerindeyim.`;
  }

  const goal = context?.activeGoal;
  if (goal && (goal.status === "active" || goal.status === "paused")) {
    const next = compact(goal.progress?.nextAction ?? null);
    const title = compact(goal.title);
    if (title && next) return `${title} için sıradaki adım: ${next}`;
    if (title) return `${title} hâlâ açık.`;
  }

  const openLoop = compact(context?.continuitySummary?.openLoops?.[0] ?? null);
  if (openLoop) return `${openLoop} yarım kalmıştı.`;

  if (signals?.recentOutputName) {
    const name = compact(signals.recentOutputName);
    const minutes = signals.recentOutputMinutesAgo;
    if (name && typeof minutes === "number" && minutes >= 0 && minutes <= 720) {
      return minutes < 60
        ? `${name} az önce hazır oldu.`
        : `${name} bugün hazırdı.`;
    }
    if (name) return `${name} elimizde duruyor.`;
  }

  if (
    signals?.upcomingEventTitle &&
    typeof signals.upcomingEventMinutes === "number" &&
    signals.upcomingEventMinutes >= 0 &&
    signals.upcomingEventMinutes <= 90
  ) {
    const title = compact(signals.upcomingEventTitle);
    if (title) {
      return `${signals.upcomingEventMinutes} dakika sonra ${title} var.`;
    }
  }

  const personalAnchor = safePersonalAnchorCue(context);
  if (personalAnchor) return personalAnchor;

  return null;
}

/**
 * Openers for a user who is not in a neutral mood.
 *
 * Same warmth, different posture. Greeting a tired or frustrated person with
 * "Günaydın, hazırım!" is not friendliness — it is not listening. The affect
 * signal already exists on the understanding context (`currentAffect`); the
 * fast route simply never read it, so the assistant sounded identical whether
 * the user was delighted or exhausted.
 *
 * Only moods that should visibly change the posture are handled. Everything
 * else falls through to the neutral openers — inventing a reaction to a mood
 * we are not confident about is worse than staying plain.
 */
function moodOpenersFor(
  kind: SocialTurnKind,
  mood: string,
  name: string | null,
): string[] | null {
  const suffix = name ? ` ${name}` : "";
  if (mood === "frustrated") {
    switch (kind) {
      case "greeting":
      case "morning":
        return [`Buradayım${suffix}. Nerede takıldık?`];
      case "how_are_you":
        return ["Ben iyiyim. Asıl sen — neye takıldın?"];
      default:
        return null;
    }
  }
  if (mood === "tired") {
    switch (kind) {
      case "greeting":
      case "morning":
        return [`Merhaba${suffix}. Ağırdan alalım mı?`];
      case "how_are_you":
        return ["İyiyim. Sen yorgun görünüyorsun — küçük bir şeyle mi başlasak?"];
      default:
        return null;
    }
  }
  if (mood === "positive") {
    switch (kind) {
      case "greeting":
      case "morning":
        return [`Selam${suffix}! Enerjin yerinde, değerlendirelim.`];
      case "how_are_you":
        return ["Keyfim yerinde. Seninki de öyle görünüyor."];
      default:
        return null;
    }
  }
  return null;
}

function openersFor(kind: SocialTurnKind, name: string | null): string[] {
  const withName = (base: string, named: string) => (name ? named : base);
  switch (kind) {
    case "greeting":
      return [
        withName("Merhaba.", `Merhaba ${name}.`),
        withName("Selam.", `Selam ${name}.`),
      ];
    case "morning":
      return [
        withName("Günaydın.", `Günaydın ${name}.`),
        withName("Günaydın, hazırım.", `Günaydın ${name}, hazırım.`),
      ];
    case "night":
      return [
        withName("İyi geceler.", `İyi geceler ${name}.`),
        "İyi geceler; kaldığımız yerden devam ederiz.",
      ];
    case "how_are_you":
      return ["İyiyim, sen nasılsın?", "İyiyim. Sende ne var ne yok?"];
    case "presence":
      return ["Buradayım.", "Evet, dinliyorum."];
    case "what_doing":
      return ["Seninleyim.", "Seni bekliyordum."];
    case "thanks":
      return [
        withName("Rica ederim.", `Rica ederim ${name}.`),
        "Ne demek, her zaman.",
      ];
    case "farewell":
      return [
        withName("Görüşürüz.", `Görüşürüz ${name}.`),
        "Görüşmek üzere.",
      ];
    case "bored":
      return [
        "Küçük bir şey seçelim mi: sohbet, bir fikir oyunu, ya da yarım kalan bir iş?",
        "Bir şeye el atalım o zaman. Ne çekiyor içinden?",
      ];
    case "affection":
      return ["Bu iyi geldi. 💚", "Bunu duymak güzel. 💚"];
    case "ack":
      return ["Tamam, devam edelim.", "Anlaşıldı."];
  }
}

/**
 * Compose the reply: an opener plus at most one true cue.
 *
 * The repetition ban applies to the *opener*, which is what the user actually
 * hears as "the same thing again". A cue makes every line unique anyway, but
 * cues are not always available and that is exactly when repetition shows.
 */
export function buildGroundedSocialReply(args: {
  kind: SocialTurnKind;
  userId: string;
  name: string | null;
  context?: UserUnderstandingContext;
  signals?: LiveSocialSignals;
}): string {
  const { kind, userId, name, context, signals } = args;
  // Duygusal duruş ÖNCE gelir: aynı kişiye her gün aynı tonda "merhaba"
  // demek, onu tanıdığını unutmuş gibi hissettirir. Yeterince güvenli bir
  // sinyal yoksa nötr açılışlara düşer (uydurma tepki yok).
  const affect = context?.currentAffect;
  const moodOpeners =
    affect && affect.confidence >= 0.5
      ? moodOpenersFor(kind, affect.mood, name)
      : null;
  const openers = [...(moodOpeners ?? []), ...openersFor(kind, name)];
  const opener =
    openers.find((candidate) => !isRepeatReply(userId, candidate)) ??
    openers[0];

  // A cue only helps when the turn is an opening. Saying "thanks — by the way
  // your report is ready" turns gratitude into an interruption.
  const cueAllowed =
    kind === "greeting" ||
    kind === "morning" ||
    kind === "how_are_you" ||
    kind === "presence" ||
    kind === "what_doing";
  const cue = cueAllowed ? selectLivenessCue(context, signals) : null;

  const reply = cue ? `${opener} ${cue}` : opener;
  rememberReply(userId, opener);
  return reply;
}
