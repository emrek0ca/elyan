export type VisualIntentKind = "image_generate" | "image_edit" | "image_continue";

export type VisualIntentContract = {
  intent: VisualIntentKind;
  subject: string[];
  count: number;
  add: string[];
  remove: string[];
  preserve: string[];
  style: string | null;
  spatialInstruction: string | null;
  sourceArtifactId: string | null;
  negativeConstraints: string[];
};

type VisualIntentInput = {
  prompt: string;
  metadata?: Record<string, unknown>;
  sourceImageCount?: number;
};

const CONTINUATION_PATTERNS = [
  /\b(buna|şuna|suna|ona|bunu|şunu|sunu|bunun|şunun|sunun|onun)\b/i,
  /\b(aynı|ayni)\s+(görsel|gorsel|resim|sahne|stil|tarz)\b/i,
  /\b(bu|son|önceki|onceki)\s+(görsel|gorsel|resim|fotoğraf|fotograf|sahne)\b/i,
  /\b(devam|devamında|devaminda|follow[-\s]?up|continue|continuation)\b/i,
  /\b(yanına|yanina|yaninda|yanına da|yanina da|next to|beside|alongside)\b/i,
  /\b(arkasına|arkasina|önüne|onune|üstüne|ustune|altına|altina)\b/i,
  /\b(bir tane daha|1 tane daha|bir de|ayrıca|ayrica|another|one more)\b/i,
];

const EDIT_PATTERNS = [
  /\b(düzenle|duzenle|değiştir|degistir|kaldır|kaldir|sil|ekle|düzelt|duzelt|iyileştir|iyilestir|netleştir|netlestir|kırp|kirp|büyüt|buyut|küçült|kucult)\b/i,
  /\b(edit|remove|replace|erase|add|enhance|upscale|crop|blur|retouch|change)\b/i,
  /\b(arka plan|rengini|stilini|ışığı|isigi|kontrastı|kontrasti)\b/i,
  /\b(make|turn|transform)\s+(this|it|the image|the photo)\b/i,
];

const GENERATION_PATTERNS = [
  /\b(görsel|gorsel|resim|resmi|resmini|image|afiş|afis|poster|banner|kapak|thumbnail|illüstrasyon|illustration|mockup|cover|logo|ikon|avatar|maskot|sticker|çizim|cizim)\b.*\b(üret|uret|oluştur|olustur|hazırla|hazirla|tasarla|çiz|ciz|draw|paint|sketch|design|generate|create)\b/i,
  /\b(üret|uret|oluştur|olustur|hazırla|hazirla|tasarla|çiz|ciz|draw|paint|sketch|design|generate|create)\b.*\b(görsel|gorsel|resim|resmi|resmini|image|afiş|afis|poster|banner|kapak|thumbnail|illüstrasyon|illustration|mockup|cover|logo|ikon|avatar|maskot|sticker|çizim|cizim)\b/i,
  /(?<!\p{L})(çiz|ciz)(er|ersen|sene|senize|ebilir|iver|in|iniz|elim|sin)?(?!\p{L})/iu,
  /\b(draw|sketch|paint|illustrate|generate|create)\b/i,
];

const NEGATED_VISUAL_ACTION_PATTERNS = [
  /(?<!\p{L})(?:görsel|gorsel|resim|image)(?:i|ı|u|ü)?\s+(?:oluştur|olustur|üret|uret|çiz|ciz|generate|create)(?:ma|me)(?!\p{L})/iu,
  /(?<!\p{L})(?:görsel|gorsel|resim|image)(?:i|ı|u|ü)?\s+(?:düzenle|duzenle|değiştir|degistir|edit|modify)(?:ma|me)(?!\p{L})/iu,
  /(?<!\p{L})(?:oluştur|olustur|üret|uret|çiz|ciz|generate|create)(?:ma|me)(?!\p{L}).{0,40}(?<!\p{L})(?:görsel|gorsel|resim|image)(?!\p{L})/iu,
  /(?<!\p{L})(?:düzenle|duzenle|değiştir|degistir|edit|modify)(?:ma|me)(?!\p{L}).{0,40}(?<!\p{L})(?:görsel|gorsel|resim|image)(?!\p{L})/iu,
  /\b(?:do not|don't|without)\s+(?:generate|create|draw|edit|modify)\b.{0,40}\b(?:image|picture|visual)\b/i,
];

const SUBJECT_PATTERNS: Array<[RegExp, string]> = [
  [/\b(at|atlar|atı|atin|horse|horses)\b/iu, "horse"],
  [/\b(kedi|kediler|cat|cats)\b/iu, "cat"],
  [/\b(köpek|kopek|köpekler|kopekler|dog|dogs)\b/iu, "dog"],
  [/\b(çocuk|cocuk|çocuklar|cocuklar|child|children|kid|kids)\b/iu, "child"],
  [/\b(araba|otomobil|car|cars)\b/iu, "car"],
  [/\b(insan|kişi|kisi|person|people|human)\b/iu, "person"],
  [/\b(kadın|kadin|woman|women)\b/iu, "woman"],
  [/\b(erkek|adam|man|men)\b/iu, "man"],
  [/\b(logo|ikon|icon)\b/iu, "logo"],
  [/\b(avatar|maskot|mascot)\b/iu, "character"],
];

const NEGATIVE_SUBJECT_CLAUSE_PATTERNS = [
  /(?:çocuk|cocuk|çocuklar|cocuklar|child|children|kid|kids|insan|kişi|kisi|person|people|human|kadın|kadin|woman|women|erkek|adam|man|men)(?:\s*(?:veya|ya da|,|\/|or|and)\s*(?:çocuk|cocuk|çocuklar|cocuklar|child|children|kid|kids|insan|kişi|kisi|person|people|human|kadın|kadin|woman|women|erkek|adam|man|men))*\s+(?:olmasın|olmasin|ekleme|eklenmesin|koyma|bulunmasın|bulunmasin|görünmesin|gorunmesin)/giu,
  /(?:do not|don't|without|no|exclude|avoid)\s+(?:add\s+)?(?:a\s+|any\s+)?(?:child|children|kid|kids|person|people|human|woman|women|man|men)(?:\s*(?:,|\/|or|and)\s*(?:a\s+|any\s+)?(?:child|children|kid|kids|person|people|human|woman|women|man|men))*/giu,
];

const STYLE_PATTERNS: Array<[RegExp, string]> = [
  [/\b(anime)\b/i, "anime"],
  [/\b(çizgi film|cizgi film|cartoon)\b/i, "cartoon"],
  [/\b(sinematik|cinematic)\b/i, "cinematic"],
  [/\b(fotogerçekçi|fotogercekci|photorealistic|realistic)\b/i, "photorealistic"],
  [/\b(sulu boya|watercolor)\b/i, "watercolor"],
  [/\b(yağlı boya|yagli boya|oil painting)\b/i, "oil painting"],
  [/\b(minimal|minimalist)\b/i, "minimal"],
  [/\b(3d)\b/i, "3d"],
];

const COLOR_PATTERNS: Array<[RegExp, string]> = [
  [/\b(kırmızı|kirmizi|red)\b/iu, "red"],
  [/\b(mavi|blue)\b/iu, "blue"],
  [/\b(yeşil|yesil|green)\b/iu, "green"],
  [/\b(sarı|sari|yellow)\b/iu, "yellow"],
  [/\b(siyah|black)\b/iu, "black"],
  [/\b(beyaz|white)\b/iu, "white"],
  [/\b(mor|purple)\b/iu, "purple"],
  [/\b(pembe|pink)\b/iu, "pink"],
  [/\b(turuncu|orange)\b/iu, "orange"],
  [/\b(gri|gray|grey)\b/iu, "gray"],
  [/\b(kahverengi|brown)\b/iu, "brown"],
  [/\b(altın|altin|gold)\b/iu, "gold"],
  [/\b(gümüş|gumus|silver)\b/iu, "silver"],
];

const COUNT_WORDS: Array<[RegExp, number]> = [
  [/\b(bir|1|one)\b/iu, 1],
  [/\b(iki|2|two)\b/iu, 2],
  [/\b(üç|uc|3|three)\b/iu, 3],
  [/\b(dört|dort|4|four)\b/iu, 4],
  [/\b(beş|bes|5|five)\b/iu, 5],
];

function compactText(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function unique(values: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    const normalized = compactText(value).toLowerCase();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function latestVisualIntentFromArtifact(
  artifact: Record<string, unknown> | null,
): VisualIntentContract | null {
  const metadata = asRecord(artifact?.metadata);
  const payload = asRecord(artifact?.payload);
  const candidate =
    asRecord(artifact?.visualIntent) ??
    asRecord(metadata?.visualIntent) ??
    asRecord(payload?.visualIntent);
  if (!candidate) return null;
  const intent = candidate.intent;
  if (
    intent !== "image_generate" &&
    intent !== "image_edit" &&
    intent !== "image_continue"
  ) {
    return null;
  }
  return {
    intent,
    subject: Array.isArray(candidate.subject)
      ? unique(candidate.subject.map((item) => compactText(item)))
      : [],
    count: Number.isFinite(candidate.count) ? Math.max(1, Number(candidate.count)) : 1,
    add: Array.isArray(candidate.add)
      ? unique(candidate.add.map((item) => compactText(item)))
      : [],
    remove: Array.isArray(candidate.remove)
      ? unique(candidate.remove.map((item) => compactText(item)))
      : [],
    preserve: Array.isArray(candidate.preserve)
      ? unique(candidate.preserve.map((item) => compactText(item)))
      : [],
    style: typeof candidate.style === "string" && candidate.style.trim()
      ? candidate.style.trim()
      : null,
    spatialInstruction:
      typeof candidate.spatialInstruction === "string" && candidate.spatialInstruction.trim()
        ? candidate.spatialInstruction.trim()
        : null,
    sourceArtifactId:
      typeof candidate.sourceArtifactId === "string" && candidate.sourceArtifactId.trim()
        ? candidate.sourceArtifactId.trim()
        : null,
    negativeConstraints: Array.isArray(candidate.negativeConstraints)
      ? unique(candidate.negativeConstraints.map((item) => compactText(item)))
      : [],
  };
}

export function latestImageArtifactFromMetadata(
  metadata: Record<string, unknown> | undefined,
): Record<string, unknown> | null {
  const lastVisualArtifact = asRecord(metadata?.lastVisualArtifact);
  if (lastVisualArtifact) {
    const type = String(
      lastVisualArtifact.artifactType ?? lastVisualArtifact.type ?? "",
    ).toLowerCase();
    const family = String(lastVisualArtifact.contentFamily ?? "").toLowerCase();
    const contentType = String(lastVisualArtifact.contentType ?? "").toLowerCase();
    if (type === "image" || family === "image" || contentType.startsWith("image/")) {
      return lastVisualArtifact;
    }
  }
  const sessionArtifacts = Array.isArray(metadata?.sessionArtifacts)
    ? metadata.sessionArtifacts
    : [];
  for (const item of sessionArtifacts) {
    const artifact = asRecord(item);
    if (!artifact) continue;
    const type = String(artifact.artifactType ?? artifact.type ?? "").toLowerCase();
    const family = String(artifact.contentFamily ?? "").toLowerCase();
    if (type === "image" || family === "image") {
      return artifact;
    }
  }
  return null;
}

function extractSubjects(prompt: string): string[] {
  return unique(
    SUBJECT_PATTERNS
      .filter(([pattern]) => pattern.test(prompt))
      .map(([, subject]) => subject),
  );
}

function extractNegativeClauseSubjects(prompt: string): string[] {
  const patterns: Array<[RegExp, string]> = [
    [/(?<!\p{L})(?:çocuk|cocuk|çocuklar|cocuklar|child|children|kid|kids)(?!\p{L})/iu, "child"],
    [/(?<!\p{L})(?:insan|kişi|kisi|person|people|human)(?!\p{L})/iu, "person"],
    [/(?<!\p{L})(?:kadın|kadin|woman|women)(?!\p{L})/iu, "woman"],
    [/(?<!\p{L})(?:erkek|adam|man|men)(?!\p{L})/iu, "man"],
  ];
  return unique(
    patterns
      .filter(([pattern]) => pattern.test(prompt))
      .map(([, subject]) => subject),
  );
}

function stripNegativeSubjectClauses(prompt: string): string {
  return NEGATIVE_SUBJECT_CLAUSE_PATTERNS.reduce(
    (current, pattern) => current.replace(pattern, " "),
    prompt,
  );
}

function extractNegativeSubjects(prompt: string): string[] {
  const clauses = NEGATIVE_SUBJECT_CLAUSE_PATTERNS.flatMap((pattern) =>
    [...prompt.matchAll(pattern)].map((match) => match[0] ?? ""),
  );
  const preCueClauses = [
    ...prompt.matchAll(
      /(?:^|[.!?;])\s*([^.!?;]{0,120}?)\s+(?:olmasın|olmasin|ekleme|eklenmesin|koyma|bulunmasın|bulunmasin|görünmesin|gorunmesin)\b/giu,
    ),
  ].map((match) => {
    const clause = match[1] ?? "";
    const afterPositiveBoundary = clause.split(/\b(?:olsun|only)\b/iu).pop() ?? clause;
    return afterPositiveBoundary.split(",").pop() ?? afterPositiveBoundary;
  });
  return unique(
    [...clauses, ...preCueClauses].flatMap((clause) =>
      extractNegativeClauseSubjects(clause),
    ),
  );
}

function extractStyle(prompt: string): string | null {
  return STYLE_PATTERNS.find(([pattern]) => pattern.test(prompt))?.[1] ?? null;
}

function extractColor(prompt: string): string | null {
  return COLOR_PATTERNS.find(([pattern]) => pattern.test(prompt))?.[1] ?? null;
}

function extractCount(prompt: string): number {
  const numeric = prompt.match(/\b([1-9])\s*(?:tane|adet)?\b/i);
  if (numeric?.[1]) {
    return Math.max(1, Math.min(9, Number(numeric[1])));
  }
  return COUNT_WORDS.find(([pattern]) => pattern.test(prompt))?.[1] ?? 1;
}

function extractSpatialInstruction(prompt: string): string | null {
  if (/\b(yanına|yanina|yaninda|next to|beside|alongside)\b/i.test(prompt)) {
    return "beside existing subject";
  }
  if (/\b(arkasına|arkasina|behind)\b/i.test(prompt)) return "behind existing subject";
  if (/\b(önüne|onune|in front of)\b/i.test(prompt)) return "in front of existing subject";
  if (/\b(üstüne|ustune|above|on top of)\b/i.test(prompt)) return "above existing subject";
  if (/\b(altına|altina|below|under)\b/i.test(prompt)) return "below existing subject";
  return null;
}

function extractRemove(prompt: string, subjects: string[]): string[] {
  if (!/\b(kaldır|kaldir|sil|remove|erase|without|olmasın|olmasin)\b/i.test(prompt)) {
    return [];
  }
  return subjects.length > 0 ? subjects : ["requested element"];
}

function sourceArtifactIdFromLatest(latestImage: Record<string, unknown> | null): string | null {
  const id = compactText(
    latestImage?.artifactId ??
      latestImage?.id ??
      latestImage?.taskArtifactId ??
      latestImage?.artifact_id ??
      "",
  );
  return id || null;
}

export function isVisualContinuationIntent(prompt: string): boolean {
  const normalized = compactText(prompt);
  return CONTINUATION_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function isVisualEditIntent(prompt: string): boolean {
  const normalized = compactText(prompt);
  return EDIT_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function isVisualGenerationIntent(prompt: string): boolean {
  const normalized = compactText(prompt);
  if (isNegatedVisualActionRequest(normalized)) return false;
  return GENERATION_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function isNegatedVisualActionRequest(prompt: string): boolean {
  const normalized = compactText(prompt);
  return NEGATED_VISUAL_ACTION_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function buildVisualIntentContract(input: VisualIntentInput): VisualIntentContract {
  const prompt = compactText(input.prompt);
  const metadata = input.metadata;
  const latestImage = latestImageArtifactFromMetadata(metadata);
  const latestIntent = latestVisualIntentFromArtifact(latestImage);
  const negativeSubjects = extractNegativeSubjects(prompt);
  const promptSubjects = extractSubjects(stripNegativeSubjectClauses(prompt))
    .filter((subject) => !negativeSubjects.includes(subject));
  const inheritedSubjects = latestIntent?.subject ?? [];
  const subjects = promptSubjects.length > 0 ? promptSubjects : inheritedSubjects;
  const hasSourceImage = (input.sourceImageCount ?? 0) > 0;
  const hasLatestImage = Boolean(latestImage);
  const negatedVisualAction = isNegatedVisualActionRequest(prompt);
  const continuation = !negatedVisualAction && isVisualContinuationIntent(prompt);
  const edit = !negatedVisualAction && isVisualEditIntent(prompt);
  const intent: VisualIntentKind = continuation
    ? "image_continue"
    : edit || hasSourceImage
      ? "image_edit"
      : "image_generate";
  const count = /\b(bir tane daha|1 tane daha|another|one more)\b/i.test(prompt)
    ? 1
    : extractCount(prompt);
  const style = extractStyle(prompt) ?? latestIntent?.style ?? null;
  const color = extractColor(prompt);
  const spatialInstruction = extractSpatialInstruction(prompt);
  const sourceArtifactId =
    intent === "image_generate"
      ? null
      : hasLatestImage
        ? sourceArtifactIdFromLatest(latestImage) ?? "last_image"
        : null;
  const primarySubject = subjects[0] ?? "main subject";
  const add =
    intent === "image_continue"
      ? unique([
          /\b(bir tane daha|1 tane daha|another|one more)\b/i.test(prompt)
            ? `one more ${primarySubject}`
            : promptSubjects.length > 0
              ? promptSubjects.map((subject) => `requested ${subject}`).join(", ")
              : color
                ? `change color to ${color}`
                : "requested continuation element",
        ])
      : edit && /\b(ekle|add)\b/i.test(prompt)
        ? unique(promptSubjects.length > 0 ? promptSubjects.map((subject) => `requested ${subject}`) : ["requested element"])
        : edit && color
          ? [`change color to ${color}`]
        : [];
  const remove = extractRemove(stripNegativeSubjectClauses(prompt), promptSubjects);
  const preserve =
    intent === "image_continue" || intent === "image_edit"
      ? unique([
          `existing ${primarySubject}`,
          "same style",
          "same background",
          "same composition",
        ])
      : [];
  const negativeConstraints =
    intent === "image_continue" || intent === "image_edit"
      ? unique([
          `do not replace the existing ${primarySubject}`,
          "do not change the existing scene",
          "do not create an unrelated image",
          ...negativeSubjects.map((subject) => `do not add ${subject}`),
          subjects.includes("child")
            ? ""
            : "do not add a child unless explicitly requested",
        ])
      : unique(negativeSubjects.map((subject) => `do not add ${subject}`));
  return {
    intent,
    subject: subjects,
    count,
    add,
    remove,
    preserve,
    style,
    spatialInstruction,
    sourceArtifactId,
    negativeConstraints,
  };
}

export function isVisualImageRequested(contract: VisualIntentContract, prompt: string): boolean {
  if (isNegatedVisualActionRequest(prompt)) return false;
  if (contract.intent === "image_continue" || contract.intent === "image_edit") {
    return true;
  }
  return isVisualGenerationIntent(prompt);
}
