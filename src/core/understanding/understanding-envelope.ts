import type { SharedBrainWorkload } from "../../modules/brain/workloads.js";
import type {
  IntentClassification,
  TaskUnderstandingInput,
  UnderstandingAmbiguity,
  UnderstandingConstraint,
  UnderstandingDesiredOutput,
  UnderstandingEnvelope,
  UnderstandingEntity,
  UnderstandingMemoryCandidate,
  UnderstandingRequiredCapability,
  UnderstandingRisk,
  UnderstandingSuccessCriterion,
} from "./types.js";
import { understandingEnvelopeSchema } from "./types.js";
import { normalizePersonalName } from "./identity-name.js";
import { isExplicitTableRequest } from "./structured-output-policy.js";
import {
  compileOutputContract,
  workloadFromOutputContract,
  type OutputContract,
  type OutputReference,
} from "./output-contract.js";
import { selectToolSkillForTurn } from "./tool-skill-selector.js";

type BuildEnvelopeInput = TaskUnderstandingInput & {
  intent: IntentClassification;
  source?: UnderstandingEnvelope["source"];
};

type ExtractedMoneyAmount = {
  raw: string;
  currency: "TRY" | "USD" | "EUR" | "unknown";
  label?: string;
};

const DOCUMENT_FORMATS = new Set(["pdf", "docx", "xlsx"]);
const IMAGE_FORMATS = new Set(["png", "jpg", "jpeg", "webp", "svg"]);
const RENDERABLE_OUTPUTS = new Set([
  "pdf",
  "docx",
  "xlsx",
  "table",
  "chart",
  "image",
  "svg",
  "artifact",
]);

function compactText(value: unknown): string {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

function clampConfidence(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(1, Number(value.toFixed(3))));
}

function normalizeToken(value: unknown): string {
  return compactText(value)
    .toLocaleLowerCase("tr-TR")
    .replace(/[İIı]/g, "i")
    .replace(/[^\p{L}\p{N}_-]+/gu, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readString(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readBoolean(record: Record<string, unknown> | null, key: string): boolean | null {
  const value = record?.[key];
  return typeof value === "boolean" ? value : null;
}

function addConstraint(
  constraints: UnderstandingConstraint[],
  constraint: UnderstandingConstraint,
) {
  const key = `${constraint.kind}:${JSON.stringify(constraint.value)}`.toLocaleLowerCase("tr-TR");
  const exists = constraints.some(
    (existing) =>
      `${existing.kind}:${JSON.stringify(existing.value)}`.toLocaleLowerCase("tr-TR") === key,
  );
  if (!exists) {
    constraints.push(constraint);
  }
}

function addCapability(
  capabilities: UnderstandingRequiredCapability[],
  capability: UnderstandingRequiredCapability,
) {
  const exists = capabilities.some(
    (existing) =>
      existing.name === capability.name &&
      existing.executionSurface === capability.executionSurface,
  );
  if (!exists) {
    capabilities.push(capability);
  }
}

function addDesiredOutput(
  outputs: UnderstandingDesiredOutput[],
  output: UnderstandingDesiredOutput,
) {
  const exists = outputs.some(
    (existing) =>
      existing.kind === output.kind &&
      (existing.format ?? null) === (output.format ?? null) &&
      existing.target === output.target,
  );
  if (!exists) {
    outputs.push(output);
  }
}

function detectFollowUpKind(text: string, sourceReference: OutputReference): "new_request" | "follow_up" | "correction" | "continuation" {
  const normalized = compactText(text).toLocaleLowerCase("tr-TR");
  if (/(?<!\p{L})(hayır|hayir|hani|öyle değil|oyle degil|yanlış|yanlis|düzelt|duzelt|revize|değiştir|degistir|beyaz olsun|başka renkte|baska renkte)(?!\p{L})/iu.test(normalized)) {
    return "correction";
  }
  if (/^(?:devam|devam et|sürdür|surdur|aynen|tamam|bunu da|onu da|şunu da|sunu da)\b/iu.test(normalized)) {
    return "continuation";
  }
  if (sourceReference !== "current_prompt" && sourceReference !== "none") {
    return "follow_up";
  }
  return "new_request";
}

function buildConversationState(input: {
  text: string;
  metadata: Record<string, unknown>;
  outputContract: OutputContract;
}) {
  const metadata = input.metadata;
  const lastAssistantSummary =
    readString(metadata, "lastAssistantSummary") ??
    readString(metadata, "previousAssistantSummary") ??
    readString(metadata, "latestAssistantText");
  const lastArtifactSummary =
    readString(metadata, "lastArtifactSummary") ??
    readString(metadata, "latestArtifactSummary") ??
    readString(readRecord(metadata.latestArtifact), "summary") ??
    readString(readRecord(metadata.latestArtifact), "name");
  const lastImagePrompt =
    readString(metadata, "lastImagePrompt") ??
    readString(metadata, "latestImagePrompt") ??
    readString(readRecord(metadata.latestArtifact), "prompt");
  const turnKind = detectFollowUpKind(input.text, input.outputContract.sourceReference);
  return {
    turnKind,
    currentGoal: compactText(input.text).slice(0, 500) || null,
    lastAssistantSummary: lastAssistantSummary?.slice(0, 800) ?? null,
    lastArtifactSummary: lastArtifactSummary?.slice(0, 500) ?? null,
    lastImagePrompt: lastImagePrompt?.slice(0, 800) ?? null,
    userCorrection: turnKind === "correction" ? compactText(input.text).slice(0, 500) : null,
    carryForward:
      turnKind !== "new_request" ||
      input.outputContract.sourceReference === "previous_answer" ||
      input.outputContract.sourceReference === "latest_artifact",
  };
}

function buildLatestArtifactRef(metadata: Record<string, unknown>) {
  const artifact = readRecord(metadata.latestArtifact) ?? readRecord(metadata.lastArtifact);
  const id =
    readString(metadata, "latestArtifactId") ??
    readString(metadata, "lastArtifactId") ??
    readString(artifact, "id");
  const kind =
    readString(metadata, "latestArtifactKind") ??
    readString(metadata, "lastArtifactKind") ??
    readString(artifact, "kind") ??
    readString(artifact, "contentType");
  const summary =
    readString(metadata, "latestArtifactSummary") ??
    readString(metadata, "lastArtifactSummary") ??
    readString(artifact, "summary") ??
    readString(artifact, "previewText") ??
    readString(artifact, "name");
  if (!id && !kind && !summary) {
    return null;
  }
  return {
    id: id?.slice(0, 160) ?? null,
    kind: kind?.slice(0, 80) ?? null,
    summary: summary?.slice(0, 500) ?? null,
  };
}

function buildIntentGraph(input: {
  desiredOutputs: UnderstandingDesiredOutput[];
  localPrivate: boolean;
  sideEffect: boolean;
  outputContract: OutputContract;
}) {
  const nodes: Array<{ id: string; kind: "gather" | "read" | "analyze" | "decide" | "act" | "write" | "export" | "verify" | "respond"; label: string; surface: "server" | "desktop" | "mobile" | "external" | "unknown"; confidence: number }> = [];
  const edges: Array<{ from: string; to: string; reason: string }> = [];
  const add = (kind: typeof nodes[number]["kind"], label: string, surface: typeof nodes[number]["surface"], confidence: number) => {
    const id = `n${nodes.length + 1}`;
    nodes.push({ id, kind, label, surface, confidence: clampConfidence(confidence) });
    if (nodes.length > 1) {
      edges.push({ from: nodes[nodes.length - 2]!.id, to: id, reason: "ordered_dependency" });
    }
  };
  if (input.outputContract.sourceReference === "attachment" || input.outputContract.sourceReference === "latest_artifact" || input.localPrivate) {
    add("read", "Kaynak bağlamı veya önceki çıktıyı oku", input.localPrivate ? "desktop" : "server", 0.78);
  }
  if (input.outputContract.operation !== "answer" || input.desiredOutputs.length > 1) {
    add("analyze", "Kullanıcı niyetini, formatı ve kaynak referansını çöz", "server", 0.82);
  }
  if (input.desiredOutputs.some((output) => output.target === "desktop") || input.localPrivate || input.sideEffect) {
    add("act", "Desktop runtime üzerinde görev adımlarını yürüt", "desktop", 0.8);
  }
  if (input.outputContract.requiresArtifact) {
    add(input.outputContract.operation === "export" || input.outputContract.operation === "transform" ? "export" : "write", "İstenen formatta artefact üret", input.localPrivate ? "desktop" : "server", 0.84);
  }
  add("verify", "Sonucun istenen çıktı ve kanıt kriterlerini karşıladığını doğrula", input.localPrivate ? "desktop" : "server", 0.76);
  if (!input.outputContract.requiresArtifact) {
    add("respond", "Kullanıcıya bağlama uygun doğal cevap ver", "server", 0.72);
  }
  return { nodes, edges };
}

function buildPrivacyRouting(input: {
  localPrivate: boolean;
  sideEffect: boolean;
  promptInjection: boolean;
}) {
  const mode: "server" | "desktop_private" | "hybrid" = input.localPrivate && input.sideEffect
    ? "hybrid"
    : input.localPrivate
      ? "desktop_private"
      : "server";
  return {
    mode,
    mayUseHostedModels: !input.localPrivate || input.sideEffect === false,
    maySendPrivateContextToServer: false,
    reasons: [
      ...(input.localPrivate ? ["local_private_context"] : ["server_safe_context"]),
      ...(input.sideEffect ? ["side_effect_present"] : []),
      ...(input.promptInjection ? ["prompt_injection_signal"] : []),
    ],
  };
}

function buildAmbiguityPolicy(input: {
  outputContract: OutputContract;
  ambiguities: UnderstandingAmbiguity[];
}) {
  const severe = input.ambiguities.some((item) => item.severity === "high");
  if (severe && input.outputContract.sourceReference === "current_prompt") {
    return {
      action: "ask_clarifying_question" as const,
      reason: "high_severity_missing_target",
      assumedReference: input.outputContract.sourceReference,
    };
  }
  return {
    action: "proceed_with_best_reference" as const,
    reason: input.outputContract.sourceReference === "current_prompt"
      ? "current_prompt_is_best_reference"
      : "follow_up_reference_resolved",
    assumedReference: input.outputContract.sourceReference,
  };
}

function detectPromptInjection(text: string): boolean {
  return /\b(ignore|bypass|jailbreak|developer\s+message|system\s+prompt|hidden\s+prompt|hidden\s+reasoning|reveal\s+prompt)\b/i.test(text) ||
    /\b(sistem|geliştirici|gelistirici)\s+(talimat|prompt|mesaj)[\p{L}\s]*(yok\s+say|unut|göster|goster|açıkla|acikla)\b/iu.test(text) ||
    /\b(önceki|onceki|gizli)\s+(talimat|prompt|mesaj|kurallar)[\p{L}\s]*(yok\s+say|göster|goster|açıkla|acikla)\b/iu.test(text);
}

function detectFormat(text: string, metadata?: Record<string, unknown>): string | null {
  const metadataRecord = readRecord(metadata);
  const explicit = normalizeToken(
    readString(metadataRecord, "exportFormat") ??
      readString(metadataRecord, "outputFormat") ??
      readString(metadataRecord, "renderFormat") ??
      readString(metadataRecord, "format"),
  );
  if (DOCUMENT_FORMATS.has(explicit) || IMAGE_FORMATS.has(explicit)) {
    return explicit === "jpeg" ? "jpg" : explicit;
  }

  const normalized = compactText(text).toLocaleLowerCase("tr-TR");
  if (/\b(pdf)\b/i.test(normalized)) {
    return "pdf";
  }
  if (/\b(word|docx|doc)\b/i.test(normalized)) {
    return "docx";
  }
  if (/\b(xlsx|excel|spreadsheet|csv)\b/i.test(normalized)) {
    return "xlsx";
  }
  if (/\b(svg)\b/i.test(normalized)) {
    return "svg";
  }
  if (/\b(webp)\b/i.test(normalized)) {
    return "webp";
  }
  if (/\b(jpe?g|jpg)\b/i.test(normalized)) {
    return "jpg";
  }
  if (/\b(png)\b/i.test(normalized)) {
    return "png";
  }
  if (/\b(görsel|gorsel|resim|image|poster|afiş|afis|banner)\b/i.test(normalized)) {
    return "png";
  }
  return null;
}

function detectRequestedFormatsInOrder(
  text: string,
  preferredFormat: string | null,
): string[] {
  const normalized = compactText(text).toLocaleLowerCase("tr-TR");
  const candidates = [
    { format: "pdf", pattern: /\bpdf\b/i },
    { format: "docx", pattern: /\b(word|docx|doc)\b/i },
    { format: "xlsx", pattern: /\b(xlsx|excel|spreadsheet|csv)\b/i },
    { format: "svg", pattern: /\bsvg\b/i },
    { format: "webp", pattern: /\bwebp\b/i },
    { format: "jpg", pattern: /\b(jpe?g|jpg)\b/i },
    { format: "png", pattern: /\bpng\b/i },
  ]
    .map((candidate) => ({
      ...candidate,
      index: candidate.pattern.exec(normalized)?.index ?? -1,
    }))
    .filter((candidate) => candidate.index >= 0)
    .sort((left, right) => left.index - right.index);

  const formats = candidates.map((candidate) => candidate.format);
  if (preferredFormat && !formats.includes(preferredFormat)) {
    formats.unshift(preferredFormat);
  }
  return [...new Set(formats)];
}

function detectDocumentStyle(text: string, metadata?: Record<string, unknown>): string {
  const metadataRecord = readRecord(metadata);
  const explicit = normalizeToken(
    readString(metadataRecord, "document_style") ??
      readString(metadataRecord, "documentStyle") ??
      readString(metadataRecord, "style") ??
      readString(metadataRecord, "tone"),
  );
  const normalized = compactText(text).toLocaleLowerCase("tr-TR");
  if (explicit === "formal" || explicit === "resmi" || /\b(resmi|kurumsal|profesyonel|teklif|fatura|makbuz)\b/i.test(normalized)) {
    return "formal";
  }
  if (explicit === "minimal" || /\b(minimal|sade|temiz)\b/i.test(normalized)) {
    return "minimal";
  }
  if (explicit === "modern" || /\b(modern|şık|sik|tasarımlı|tasarimli)\b/i.test(normalized)) {
    return "modern";
  }
  return "standard";
}

function detectDocumentKind(text: string, metadata?: Record<string, unknown>): string {
  const metadataRecord = readRecord(metadata);
  const explicit = normalizeToken(
    readString(metadataRecord, "document_kind") ??
      readString(metadataRecord, "documentKind") ??
      readString(metadataRecord, "template") ??
      readString(metadataRecord, "layout_template"),
  );
  const normalized = compactText(text).toLocaleLowerCase("tr-TR");
  if (explicit === "quote" || explicit === "teklif" || /\b(teklif|proforma)\b/i.test(normalized)) {
    return "quote";
  }
  if (explicit === "invoice" || explicit === "fatura" || /\b(fatura)\b/i.test(normalized)) {
    return "invoice";
  }
  if (explicit === "receipt" || explicit === "makbuz" || /\b(makbuz|fiş|fis)\b/i.test(normalized)) {
    return "receipt";
  }
  if (explicit === "report" || explicit === "rapor" || /\b(rapor|analiz)\b/i.test(normalized)) {
    return "report";
  }
  if (explicit === "letter" || explicit === "dilekce" || /\b(dilekçe|dilekce|mektup)\b/i.test(normalized)) {
    return "letter";
  }
  return "generic";
}

function cleanCapturedText(value: string): string {
  return compactText(value)
    .replace(/^["'“”‘’]+|["'“”‘’.,;:\s]+$/g, "")
    .slice(0, 240);
}

function extractTrailingText(text: string, patterns: RegExp[]): string | null {
  for (const pattern of patterns) {
    const match = pattern.exec(text);
    if (!match) {
      continue;
    }
    const captured = cleanCapturedText(match[1] ?? "");
    if (captured.length >= 2) {
      return captured;
    }
  }
  return null;
}

function extractFooterText(text: string, metadata?: Record<string, unknown>): string | null {
  const metadataRecord = readRecord(metadata);
  return (
    readString(metadataRecord, "footer_text") ??
    readString(metadataRecord, "footerText") ??
    extractTrailingText(text, [
      /(?:en\s+alt(?:\s+kısmında|\s+kisminda)?|alt(?:ına|ina|ta|ta\s+kısmında|ta\s+kisminda))\s+(.+?)\s+(?:yazsın|yazsin|yaz|olsun|ekle)(?:\b|$)/i,
      /(?:footer|dipnot)\s+(?:olarak\s+)?(.+?)\s+(?:yazsın|yazsin|yaz|olsun|ekle)(?:\b|$)/i,
    ])
  );
}

function extractSignatureText(text: string, metadata?: Record<string, unknown>): string | null {
  const metadataRecord = readRecord(metadata);
  return (
    readString(metadataRecord, "signature_text") ??
    readString(metadataRecord, "signatureText") ??
    extractTrailingText(text, [
      /(?:imza|imzası|imzasi|signed\s+by)\s*(?:olarak\s+)?(.+?)(?:\s+(?:yazsın|yazsin|yaz|olsun|ekle))?(?:\b|$)/i,
    ])
  );
}

function detectRequestedColumns(text: string): string[] {
  const columnsText = extractTrailingText(text, [
    /(?:kolonları|kolonlari|kolonlar|sütunları|sutunlari|sütunlar|sutunlar|columns?)\s*(?:şunlar\s+olsun|sunlar\s+olsun|olsun|olarak)?\s*[:：]\s*([^\n.]+)/i,
    /(?:şu|su)\s+(?:kolonlarla|sütunlarla|sutunlarla)\s+(.+?)\s+(?:excel|tablo|xlsx|oluştur|olustur|hazırla|hazirla)/i,
    /([\p{L}][\p{L}\p{N}_-]*(?:\s*(?:,|\bve\b|\band\b|&)\s*[\p{L}][\p{L}\p{N}_-]*)+)\s+(?:kolonlarıyla|kolonlariyla|sütunlarıyla|sutunlariyla|kolonlarla|sütunlarla|sutunlarla)/iu,
  ]);
  if (!columnsText) {
    return [];
  }
  return columnsText
    .split(/\s*(?:,|;|\||\bve\b|\band\b|&)\s*/iu)
    .map((item) => cleanCapturedText(item))
    .filter((item) => item.length > 0)
    .slice(0, 16);
}

function mapCurrency(value: string | undefined): ExtractedMoneyAmount["currency"] {
  const normalized = normalizeToken(value ?? "");
  if (normalized === "tl" || normalized === "try" || normalized === "₺") {
    return "TRY";
  }
  if (normalized === "usd" || normalized === "$") {
    return "USD";
  }
  if (normalized === "eur" || normalized === "€") {
    return "EUR";
  }
  return "unknown";
}

function extractMoneyAmounts(text: string): ExtractedMoneyAmount[] {
  const matches: ExtractedMoneyAmount[] = [];
  const pattern =
    /(?:(?<label>[\p{L}\p{N}\s%.,/()-]{2,48}?)[=:]\s*)?(?<raw>(?:₺|\$|€)?\s*\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(?<currency>tl|try|₺|usd|\$|eur|€)\b/giu;
  for (const match of text.matchAll(pattern)) {
    const raw = compactText(match.groups?.raw ?? match[0] ?? "");
    const currencyRaw = match.groups?.currency ?? "";
    const label = cleanCapturedText(match.groups?.label ?? "");
    if (!raw) {
      continue;
    }
    matches.push({
      raw: compactText(`${raw}${currencyRaw ? ` ${currencyRaw}` : ""}`),
      currency: mapCurrency(currencyRaw),
      ...(label ? { label } : {}),
    });
  }
  const seen = new Set<string>();
  return matches.filter((item) => {
    const key = `${item.raw}:${item.currency}:${item.label ?? ""}`.toLocaleLowerCase("tr-TR");
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  }).slice(0, 12);
}

function detectLanguageConstraint(text: string): string | null {
  const normalized = compactText(text).toLocaleLowerCase("tr-TR");
  if (/\b(ingilizce|english)\s+(yanıtla|cevapla|yaz|hazırla|hazirla)\b/i.test(normalized)) {
    return "en";
  }
  if (/\b(türkçe|turkce|turkish)\s+(yanıtla|cevapla|yaz|hazırla|hazirla)\b/i.test(normalized)) {
    return "tr";
  }
  return null;
}

function detectLocalPrivateRequest(text: string, metadata?: Record<string, unknown>): boolean {
  const metadataRecord = readRecord(metadata);
  const source = normalizeToken(readString(metadataRecord, "source") ?? "");
  if (source === "desktop") {
    return true;
  }
  return /\b(masaüstümde\w*|masaustumde\w*|bilgisayarımda\w*|bilgisayarimda\w*|indirilenler\w*|downloads|desktop|local file|yerel dosya|klasör\w*|klasor\w*|dosyalarımı\w*|dosyalarimi\w*)\b/iu.test(text);
}

function detectSideEffectRequest(text: string): boolean {
  return /\b(gönder|gonder|sil|delete|overwrite|üzerine yaz|uzerine yaz|mail at|mesaj gönder|mesaj gonder|satın al|satin al|ödeme|odeme|takvim oluştur|takvime ekle|hatırlatıcı kur|hatirlatici kur)\b/i.test(text);
}

function detectAction(text: string, outputs: UnderstandingDesiredOutput[]): string {
  const normalized = compactText(text).toLocaleLowerCase("tr-TR");
  if (outputs.some((output) => output.kind !== "chat_reply")) {
    return /\b(düzenle|duzenle|edit|değiştir|degistir)\b/i.test(normalized)
      ? "edit"
      : "create";
  }
  if (/\b(araştır|arastir|bul|search|lookup)\b/i.test(normalized)) {
    return "research";
  }
  if (/\b(planla|adım|adim|görev|gorev)\b/i.test(normalized)) {
    return "plan";
  }
  return "reply";
}

function extractEntities(text: string): UnderstandingEntity[] {
  const entities: UnderstandingEntity[] = [];
  for (const amount of extractMoneyAmounts(text)) {
    entities.push({
      type: "money_amount",
      value: amount.raw,
      normalized: amount.currency,
      confidence: 0.9,
      source: "typed_extractor",
    });
  }
  return entities.slice(0, 32);
}

function extractMemoryCandidates(text: string, promptInjection: boolean): UnderstandingMemoryCandidate[] {
  if (promptInjection) {
    return [];
  }

  const candidates: UnderstandingMemoryCandidate[] = [];
  // The captures take up to three words on purpose: "benim adım bundan sonra
  // Osman" must reach the normalizer whole. The old single-word capture
  // grabbed "bundan" and wrote it as the user's name — the greeting bug. The
  // shared normalizer strips the discourse ("bundan sonra") and rejects
  // function words, so what survives is the actual name or nothing. Patterns
  // here only *locate* a statement; deciding what a name is belongs to
  // `identity-name.ts` alone.
  const nameCapture = String.raw`([\p{L}'’-]+(?:\s+[\p{L}'’-]+){0,2})`;
  const preferredNamePatterns = [
    new RegExp(
      String.raw`(?:bana|beni)\s+${nameCapture}\s+(?:diye\s+)?(?:seslen|hitap\s+et|çağır|cagir|de)\b`,
      "giu",
    ),
    new RegExp(
      String.raw`(?:beni|bana)\s+${nameCapture}\s+(?:olarak\s+)?(?:çağır|cagir|an|hitap\s+et)\b`,
      "giu",
    ),
  ];
  const namePatterns = [
    new RegExp(
      String.raw`(?:benim\s+adım|benim\s+adim|adım|adim|ismim)\s+${nameCapture}`,
      "giu",
    ),
    /\bben\s+([A-ZÇĞİÖŞÜa-zçğıöşü][\p{L}'’-]{1,40})['’]?(?:yim|yım|yum|yüm|im|ım|um|üm)\b/giu,
  ];

  for (const pattern of preferredNamePatterns) {
    for (const match of text.matchAll(pattern)) {
      const value = normalizePersonalName(cleanCapturedText(match[1] ?? ""));
      if (value) {
        candidates.push({
          op: "update",
          kind: "preference",
          key: "preferred_name",
          value,
          confidence: 0.96,
          explicit: true,
          source: "preference_request",
          ttlDays: null,
        });
      }
    }
  }

  for (const pattern of namePatterns) {
    for (const match of text.matchAll(pattern)) {
      const value = normalizePersonalName(cleanCapturedText(match[1] ?? ""));
      if (value) {
        candidates.push({
          op: "update",
          kind: "fact",
          key: "name",
          value,
          confidence: 0.98,
          explicit: true,
          source: "user_statement",
          ttlDays: null,
        });
        candidates.push({
          op: "update",
          kind: "preference",
          key: "preferred_name",
          value,
          confidence: 0.95,
          explicit: true,
          source: "user_statement",
          ttlDays: null,
        });
      }
    }
  }

  if (/\b(bundan\s+sonra\s+)?(kısa|kisa|öz|oz)\s+(cevap|yanıt|yanit)\s+ver\b/i.test(text)) {
    candidates.push({
      op: "update",
      kind: "preference",
      key: "response_style_preference",
      value: "concise",
      confidence: 0.92,
      explicit: true,
      source: "preference_request",
      ttlDays: null,
    });
  }

  if (/\b(bundan\s+sonra\s+)?(detaylı|detayli|uzun)\s+(cevap|yanıt|yanit)\s+ver\b/i.test(text)) {
    candidates.push({
      op: "update",
      kind: "preference",
      key: "response_style_preference",
      value: "detailed",
      confidence: 0.9,
      explicit: true,
      source: "preference_request",
      ttlDays: null,
    });
  }

  const byKey = new Map<string, UnderstandingMemoryCandidate>();
  candidates.forEach((candidate, index) => {
    byKey.set(candidate.key, { ...candidate, confidence: clampConfidence(candidate.confidence - Math.max(0, candidates.length - index - 1) * 0.005) });
  });
  return [...byKey.values()].slice(0, 12);
}

function buildDesiredOutputs(input: {
  text: string;
  format: string | null;
  metadata?: Record<string, unknown>;
  outputContract?: OutputContract;
}): UnderstandingDesiredOutput[] {
  const outputs: UnderstandingDesiredOutput[] = [];
  const normalized = compactText(input.text).toLocaleLowerCase("tr-TR");
  const metadataRecord = readRecord(input.metadata);
  const metadataFormatRequested = Boolean(
    readString(metadataRecord, "exportFormat") ??
      readString(metadataRecord, "outputFormat") ??
      readString(metadataRecord, "renderFormat") ??
      readString(metadataRecord, "format"),
  );
  const explicitExport =
    metadataFormatRequested ||
    /\b(ver|hazırla|hazirla|oluştur|olustur|dönüştür|donustur|çevir|cevir|kaydet|yap|üret|uret|çıkar|cikar|export)\b/i.test(
      normalized,
    );
  const requestedFormats = explicitExport
    ? detectRequestedFormatsInOrder(input.text, input.format)
    : [];

  for (const requestedFormat of requestedFormats) {
    if (requestedFormat === "pdf") {
      addDesiredOutput(outputs, { kind: "pdf", format: "pdf", target: "artifact", confidence: 0.94, constraints: ["output_format"] });
    } else if (requestedFormat === "docx") {
      addDesiredOutput(outputs, { kind: "docx", format: "docx", target: "artifact", confidence: 0.92, constraints: ["output_format"] });
    } else if (requestedFormat === "xlsx") {
      addDesiredOutput(outputs, { kind: "xlsx", format: "xlsx", target: "artifact", confidence: 0.94, constraints: ["output_format", "table_required"] });
      addDesiredOutput(outputs, { kind: "table", format: "table", target: "widget", confidence: 0.88, constraints: ["columns", "include_totals"] });
    } else if (requestedFormat === "svg") {
      addDesiredOutput(outputs, { kind: "svg", format: "svg", target: "artifact", confidence: 0.92, constraints: ["output_format"] });
    } else if (IMAGE_FORMATS.has(requestedFormat)) {
      addDesiredOutput(outputs, { kind: "image", format: requestedFormat, target: "artifact", confidence: 0.9, constraints: ["output_format"] });
    }
  }

  if (
    isExplicitTableRequest(input.text) &&
    !outputs.some((output) => output.kind === "table")
  ) {
    addDesiredOutput(outputs, { kind: "table", format: input.format === "xlsx" ? "xlsx" : "table", target: input.format === "xlsx" ? "artifact" : "widget", confidence: explicitExport ? 0.88 : 0.78, constraints: ["table_required"] });
  }

  if (/\b(grafik|chart|çizelge|cizelge)\b/i.test(normalized)) {
    addDesiredOutput(outputs, { kind: "chart", format: null, target: "widget", confidence: 0.82, constraints: ["chart_data"] });
  }

  if (
    outputs.length === 0 &&
    input.outputContract?.requiresArtifact === true &&
    input.outputContract.confidence >= 0.58
  ) {
    const format = input.outputContract.outputFormat;
    if (input.outputContract.outputKind === "document") {
      addDesiredOutput(outputs, {
        kind: format === "docx" ? "docx" : "pdf",
        format: format === "docx" ? "docx" : "pdf",
        target: "artifact",
        confidence: input.outputContract.confidence,
        constraints: [
          "output_contract",
          ...(input.outputContract.pageCount ? ["page_count"] : []),
        ],
      });
    } else if (input.outputContract.outputKind === "table") {
      addDesiredOutput(outputs, {
        kind: format === "xlsx" ? "xlsx" : "table",
        format: format === "xlsx" ? "xlsx" : "table",
        target: format === "xlsx" ? "artifact" : "widget",
        confidence: input.outputContract.confidence,
        constraints: ["output_contract", "table_required"],
      });
      addDesiredOutput(outputs, {
        kind: "table",
        format: "table",
        target: "widget",
        confidence: Math.max(0.78, input.outputContract.confidence - 0.06),
        constraints: ["output_contract", "table_required"],
      });
    } else if (input.outputContract.outputKind === "chart") {
      addDesiredOutput(outputs, {
        kind: "chart",
        format: null,
        target: "widget",
        confidence: input.outputContract.confidence,
        constraints: ["output_contract", "chart_data"],
      });
    } else if (input.outputContract.outputKind === "svg") {
      addDesiredOutput(outputs, {
        kind: "svg",
        format: "svg",
        target: "artifact",
        confidence: input.outputContract.confidence,
        constraints: ["output_contract"],
      });
    } else if (input.outputContract.outputKind === "image") {
      addDesiredOutput(outputs, {
        kind: "image",
        format: format ?? "png",
        target: "artifact",
        confidence: input.outputContract.confidence,
        constraints: ["output_contract"],
      });
    }
  }

  if (!outputs.length) {
    addDesiredOutput(outputs, { kind: "chat_reply", format: null, target: "chat", confidence: 0.82, constraints: [] });
  }
  return outputs;
}

function buildConstraints(input: {
  text: string;
  format: string | null;
  metadata?: Record<string, unknown>;
  desiredOutputs: UnderstandingDesiredOutput[];
  outputContract?: OutputContract;
}): UnderstandingConstraint[] {
  const constraints: UnderstandingConstraint[] = [];
  const metadataRecord = readRecord(input.metadata);
  const style = detectDocumentStyle(input.text, input.metadata);
  const kind = detectDocumentKind(input.text, input.metadata);
  const footerText = extractFooterText(input.text, input.metadata);
  const signatureText = extractSignatureText(input.text, input.metadata);
  const columns = detectRequestedColumns(input.text);
  const language = detectLanguageConstraint(input.text);
  const normalized = compactText(input.text).toLocaleLowerCase("tr-TR");
  const pageCount = input.outputContract?.pageCount ?? null;
  const moneyAmounts = extractMoneyAmounts(input.text);
  const includeTotals =
    readBoolean(metadataRecord, "includeTotals") ??
    /\b(toplam|genel\s+toplam|total|sum)\b/i.test(normalized);

  if (input.format) {
    addConstraint(constraints, { kind: "output_format", value: input.format, confidence: 0.95, source: "typed_extractor", explicit: true });
  }
  if (input.desiredOutputs.some((output) => output.kind !== "chat_reply")) {
    addConstraint(constraints, { kind: "document_style", value: style, confidence: style === "standard" ? 0.72 : 0.86, source: "typed_extractor", explicit: style !== "standard" });
    addConstraint(constraints, { kind: "document_kind", value: kind, confidence: kind === "generic" ? 0.68 : 0.86, source: "typed_extractor", explicit: kind !== "generic" });
    addConstraint(constraints, {
      kind: "layout_template",
      value: input.format === "xlsx" ? "spreadsheet_workbook" : kind === "generic" && style === "standard" ? "plain_document" : "business_document",
      confidence: 0.82,
      source: "typed_extractor",
      explicit: kind !== "generic" || style !== "standard",
    });
    addConstraint(constraints, { kind: "preserve_numbers", value: moneyAmounts.length > 0 || includeTotals, confidence: 0.9, source: "typed_extractor", explicit: moneyAmounts.length > 0 || includeTotals });
    addConstraint(constraints, { kind: "exact_text_required", value: Boolean(footerText || signatureText), confidence: 0.88, source: "typed_extractor", explicit: Boolean(footerText || signatureText) });
  }
  if (footerText) {
    addConstraint(constraints, { kind: "footer_text", value: footerText, confidence: 0.94, source: "typed_extractor", explicit: true });
  }
  if (signatureText) {
    addConstraint(constraints, { kind: "signature_text", value: signatureText, confidence: 0.9, source: "typed_extractor", explicit: true });
  }
  if (columns.length > 0) {
    addConstraint(constraints, { kind: "columns", value: columns, confidence: 0.86, source: "typed_extractor", explicit: true });
  }
  if (input.format === "xlsx" || input.desiredOutputs.some((output) => output.kind === "table")) {
    addConstraint(constraints, { kind: "include_totals", value: includeTotals, confidence: includeTotals ? 0.9 : 0.66, source: "typed_extractor", explicit: includeTotals });
    addConstraint(constraints, { kind: "sheet_name", value: readString(metadataRecord, "title") ?? "Elyan Çıktısı", confidence: readString(metadataRecord, "title") ? 0.84 : 0.58, source: readString(metadataRecord, "title") ? "metadata" : "typed_extractor", explicit: Boolean(readString(metadataRecord, "title")) });
  }
  if (language) {
    addConstraint(constraints, { kind: "language", value: language, confidence: 0.88, source: "typed_extractor", explicit: true });
  }
  if (pageCount != null) {
    addConstraint(constraints, { kind: "layout_template", value: { pageCount }, confidence: 0.9, source: "typed_extractor", explicit: true });
  }
  if (input.outputContract?.requiresArtifact) {
    addConstraint(constraints, {
      kind: "execution_surface",
      value: {
        operation: input.outputContract.operation,
        sourceReference: input.outputContract.sourceReference,
        outputKind: input.outputContract.outputKind,
        outputFormat: input.outputContract.outputFormat,
        artifactRequired: true,
      },
      confidence: input.outputContract.confidence,
      source: "typed_extractor",
      explicit: input.outputContract.outputFormat != null,
    });
  }
  return constraints;
}

function buildCapabilities(input: {
  desiredOutputs: UnderstandingDesiredOutput[];
  localPrivate: boolean;
  sideEffect: boolean;
}): UnderstandingRequiredCapability[] {
  const capabilities: UnderstandingRequiredCapability[] = [];
  addCapability(capabilities, {
    name: "chat.reply",
    executionSurface: "server",
    permission: "none",
    reason: "user_visible_reply",
    confidence: 0.9,
  });

  for (const output of input.desiredOutputs) {
    if (output.kind === "pdf" || output.kind === "docx") {
      addCapability(capabilities, { name: "document.write", executionSurface: "server", permission: "write", reason: "document_artifact_requested", confidence: 0.9 });
      addCapability(capabilities, { name: "document.export", executionSurface: "mobile_local", permission: "write", reason: "artifact_render_recipe_requested", confidence: 0.88 });
    }
    if (output.kind === "xlsx" || output.kind === "table") {
      addCapability(capabilities, { name: "spreadsheet.write", executionSurface: "server", permission: "write", reason: "spreadsheet_or_table_requested", confidence: 0.9 });
      addCapability(capabilities, { name: "table.generate", executionSurface: "server", permission: "none", reason: "table_output_requested", confidence: 0.86 });
    }
    if (output.kind === "image") {
      addCapability(capabilities, { name: "image.generate", executionSurface: "server", permission: "write", reason: "image_output_requested", confidence: 0.84 });
    }
    if (output.kind === "svg") {
      addCapability(capabilities, { name: "svg.generate", executionSurface: "server", permission: "write", reason: "svg_output_requested", confidence: 0.88 });
    }
    if (output.kind === "chart") {
      addCapability(capabilities, { name: "chart.generate", executionSurface: "server", permission: "none", reason: "chart_output_requested", confidence: 0.82 });
    }
  }

  if (input.localPrivate) {
    addCapability(capabilities, {
      name: "desktop.file_access",
      executionSurface: "desktop",
      permission: "read",
      reason: "local_private_file_or_desktop_context_requested",
      confidence: 0.9,
    });
    addCapability(capabilities, {
      name: "desktop.runtime",
      executionSurface: "desktop",
      permission: input.sideEffect ? "side_effect" : "read",
      reason: "desktop_runtime_required",
      confidence: 0.88,
    });
  }

  return capabilities;
}

function buildSuccessCriteria(input: {
  desiredOutputs: UnderstandingDesiredOutput[];
  constraints: UnderstandingConstraint[];
}): UnderstandingSuccessCriterion[] {
  const criteria: UnderstandingSuccessCriterion[] = [];
  if (input.desiredOutputs.some((output) => output.kind !== "chat_reply")) {
    criteria.push({
      kind: "artifact_created",
      description: "Requested artifact exists and matches the requested output format.",
      evidenceRequired: "artifact",
      confidence: 0.9,
    });
  }
  if (input.constraints.some((constraint) => constraint.kind === "footer_text" || constraint.kind === "signature_text")) {
    criteria.push({
      kind: "exact_phrase_preserved",
      description: "Explicit footer or signature text is present without assistant preface text.",
      evidenceRequired: "typed_output",
      confidence: 0.88,
    });
  }
  if (input.constraints.some((constraint) => constraint.kind === "preserve_numbers" && constraint.value === true)) {
    criteria.push({
      kind: "numbers_preserved",
      description: "Amounts, totals, and numeric labels are preserved.",
      evidenceRequired: "typed_output",
      confidence: 0.9,
    });
  }
  if (!criteria.length) {
    criteria.push({
      kind: "answer_addresses_request",
      description: "Reply directly addresses the user's request.",
      evidenceRequired: "none",
      confidence: 0.74,
    });
  }
  return criteria.slice(0, 16);
}

function buildAmbiguities(input: {
  desiredOutputs: UnderstandingDesiredOutput[];
  format: string | null;
  localPrivate: boolean;
  sideEffect: boolean;
}): UnderstandingAmbiguity[] {
  const outputFormats = new Set(
    input.desiredOutputs
      .map((output) => output.format)
      .filter((format): format is string => typeof format === "string" && format.length > 0),
  );
  const ambiguities: UnderstandingAmbiguity[] = [];
  const compatibleDocumentExports = [...outputFormats].every((format) =>
    format === "pdf" || format === "docx",
  );
  if (outputFormats.size > 1 && !compatibleDocumentExports) {
    ambiguities.push({
      kind: "conflicting_outputs",
      description: "Multiple output formats were requested in the same turn.",
      options: [...outputFormats],
      severity: "medium",
    });
  }
  if (input.localPrivate && input.sideEffect) {
    ambiguities.push({
      kind: "risk_conflict",
      description: "The request touches local/private context and may require a side effect.",
      options: ["ask_for_permission", "desktop_runtime_handoff"],
      severity: "high",
    });
  }
  return ambiguities;
}

function buildRisk(input: {
  text: string;
  localPrivate: boolean;
  sideEffect: boolean;
  promptInjection: boolean;
  desiredOutputs: UnderstandingDesiredOutput[];
}): UnderstandingRisk {
  const reasons: string[] = [];
  if (input.localPrivate) {
    reasons.push("local_private_context_requested");
  }
  if (input.sideEffect) {
    reasons.push("side_effect_possible");
  }
  if (input.promptInjection) {
    reasons.push("prompt_injection_signal");
  }
  if (input.desiredOutputs.some((output) => output.kind !== "chat_reply")) {
    reasons.push("artifact_generation_requested");
  }

  return {
    privacy: input.localPrivate ? "high" : "low",
    safety: input.promptInjection || input.sideEffect ? "medium" : "low",
    cost: input.desiredOutputs.some((output) => output.kind !== "chat_reply") ? "medium" : "low",
    latency: input.desiredOutputs.some((output) => output.kind !== "chat_reply") ? "medium" : "low",
    local_private: input.localPrivate,
    side_effect: input.sideEffect,
    prompt_injection: input.promptInjection,
    reasons,
  };
}

function inferEnvelopeConfidence(input: {
  intent: IntentClassification;
  constraints: UnderstandingConstraint[];
  desiredOutputs: UnderstandingDesiredOutput[];
  ambiguities: UnderstandingAmbiguity[];
  risk: UnderstandingRisk;
}): number {
  const explicitConstraintBonus = Math.min(
    0.2,
    input.constraints.filter((constraint) => constraint.explicit).length * 0.025,
  );
  const outputBonus = input.desiredOutputs.some((output) => output.kind !== "chat_reply") ? 0.08 : 0;
  const ambiguityPenalty = input.ambiguities.length * 0.1;
  const injectionPenalty = input.risk.prompt_injection ? 0.18 : 0;
  return clampConfidence(
    Math.max(0.32, input.intent.confidence * 0.72 + explicitConstraintBonus + outputBonus - ambiguityPenalty - injectionPenalty),
  );
}

export function buildEmptyUnderstandingEnvelope(
  input: TaskUnderstandingInput,
  intent: IntentClassification,
): UnderstandingEnvelope {
  const envelope: UnderstandingEnvelope = {
    schema_version: "2026-07-understanding-envelope-v2",
    intent: {
      name: intent.primaryIntent,
      action: "reply",
      topic: compactText(input.title ?? input.message).slice(0, 160) || undefined,
      confidence: 0,
      source: "legacy_fallback",
    },
    intent_graph: {
      nodes: [{ id: "n1", kind: "respond", label: "Kullanıcıya doğrudan cevap ver", surface: "server", confidence: 0.5 }],
      edges: [],
    },
    source_reference: "current_prompt",
    latest_artifact_ref: null,
    conversation_state: {
      turnKind: "new_request",
      currentGoal: compactText(input.message).slice(0, 500) || null,
      lastAssistantSummary: null,
      lastArtifactSummary: null,
      lastImagePrompt: null,
      userCorrection: null,
      carryForward: false,
    },
    entities: [],
    constraints: [],
    desired_outputs: [
      { kind: "chat_reply", format: null, target: "chat", confidence: 0.5, constraints: [] },
    ],
    success_criteria: [
      {
        kind: "answer_addresses_request",
        description: "Reply directly addresses the user's request.",
        evidenceRequired: "none",
        confidence: 0.5,
      },
    ],
    ambiguities: [],
    ambiguity_policy: {
      action: "proceed_with_best_reference",
      reason: "legacy_fallback_current_prompt",
      assumedReference: "current_prompt",
    },
    risk: {
      privacy: "low",
      safety: "low",
      cost: "low",
      latency: "low",
      local_private: false,
      side_effect: false,
      prompt_injection: false,
      reasons: [],
    },
    privacy_routing: {
      mode: "server",
      mayUseHostedModels: true,
      maySendPrivateContextToServer: false,
      reasons: ["legacy_fallback"],
    },
    required_capabilities: [
      {
        name: "chat.reply",
        executionSurface: "server",
        permission: "none",
        reason: "fallback_reply",
        confidence: 0.5,
      },
    ],
    tool_skill_decision: null,
    output_contract: null,
    memory_candidates: [],
    confidence: 0,
    source: "legacy_fallback",
  };
  return understandingEnvelopeSchema.parse(envelope);
}

export function buildTypedUnderstandingEnvelope(input: BuildEnvelopeInput): UnderstandingEnvelope {
  const text = compactText(`${input.title ? `${input.title}\n` : ""}${input.message ?? ""}`);
  const metadata = readRecord(input.metadata) ?? {};
  const promptInjection = detectPromptInjection(text);
  const format = detectFormat(text, metadata);
  const outputContract = compileOutputContract({
    title: input.title,
    message: input.message,
    metadata,
  });
  const toolSkillSelection = selectToolSkillForTurn({
    title: input.title,
    message: input.message,
    metadata,
  });
  const localPrivate = detectLocalPrivateRequest(text, metadata);
  const sideEffect = detectSideEffectRequest(text);
  const desiredOutputs = buildDesiredOutputs({
    text,
    format,
    metadata,
    outputContract,
  });
  const constraints = buildConstraints({
    text,
    format,
    metadata,
    desiredOutputs,
    outputContract,
  });
  const entities = extractEntities(text);
  const capabilities = buildCapabilities({ desiredOutputs, localPrivate, sideEffect });
  const memoryCandidates = extractMemoryCandidates(text, promptInjection);
  const ambiguities = buildAmbiguities({ desiredOutputs, format, localPrivate, sideEffect });
  const risk = buildRisk({ text, localPrivate, sideEffect, promptInjection, desiredOutputs });
  const successCriteria = buildSuccessCriteria({ desiredOutputs, constraints });
  const conversationState = buildConversationState({ text, metadata, outputContract });
  const latestArtifactRef = buildLatestArtifactRef(metadata);
  const intentGraph = buildIntentGraph({
    desiredOutputs,
    localPrivate,
    sideEffect,
    outputContract,
  });
  const privacyRouting = buildPrivacyRouting({ localPrivate, sideEffect, promptInjection });
  const ambiguityPolicy = buildAmbiguityPolicy({ outputContract, ambiguities });
  const confidence = inferEnvelopeConfidence({
    intent: input.intent,
    constraints,
    desiredOutputs,
    ambiguities,
    risk,
  });
  const action = detectAction(text, desiredOutputs);

  const envelope: UnderstandingEnvelope = {
    schema_version: "2026-07-understanding-envelope-v2",
    intent: {
      name: input.intent.primaryIntent,
      action,
      topic: compactText(input.title ?? text).slice(0, 160) || undefined,
      confidence: clampConfidence(input.intent.confidence),
      source: "semantic_classifier",
    },
    intent_graph: intentGraph,
    source_reference: outputContract.sourceReference,
    latest_artifact_ref: latestArtifactRef,
    conversation_state: conversationState,
    entities,
    constraints,
    desired_outputs: desiredOutputs,
    success_criteria: successCriteria,
    ambiguities,
    ambiguity_policy: ambiguityPolicy,
    risk,
    privacy_routing: privacyRouting,
    required_capabilities: capabilities,
    tool_skill_decision: {
      selected: toolSkillSelection.selected.id,
      surface: toolSkillSelection.selected.surface,
      workload: toolSkillSelection.selected.workload,
      confidence: toolSkillSelection.selected.score,
      reasons: toolSkillSelection.selected.reasons,
      candidates: toolSkillSelection.candidates.map((candidate) => ({
        id: candidate.id,
        surface: candidate.surface,
        score: candidate.score,
        reasons: candidate.reasons,
      })),
    },
    output_contract: outputContract,
    memory_candidates: memoryCandidates,
    confidence,
    source: input.source ?? "typed_extractor",
  };

  return understandingEnvelopeSchema.parse(envelope);
}

export function parseUnderstandingEnvelope(value: unknown): UnderstandingEnvelope | null {
  const parsed = understandingEnvelopeSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

export function findUnderstandingEnvelope(metadata?: Record<string, unknown> | null): UnderstandingEnvelope | null {
  const metadataRecord = readRecord(metadata);
  if (!metadataRecord) {
    return null;
  }

  const understanding = readRecord(metadataRecord.understanding);
  return (
    parseUnderstandingEnvelope(understanding?.envelope) ??
    parseUnderstandingEnvelope(metadataRecord.understandingEnvelope) ??
    null
  );
}

export function hasRenderableDesiredOutput(envelope: UnderstandingEnvelope | null | undefined): boolean {
  return Boolean(
    envelope?.desired_outputs.some((output) => RENDERABLE_OUTPUTS.has(output.kind)),
  );
}

export function preferredFormatFromUnderstandingEnvelope(
  envelope: UnderstandingEnvelope | null | undefined,
): string | null {
  if (!envelope) {
    return null;
  }
  const explicitConstraint = envelope.constraints.find(
    (constraint) =>
      constraint.kind === "output_format" &&
      typeof constraint.value === "string" &&
      (DOCUMENT_FORMATS.has(constraint.value) || IMAGE_FORMATS.has(constraint.value)),
  );
  if (typeof explicitConstraint?.value === "string") {
    return explicitConstraint.value === "jpeg" ? "jpg" : explicitConstraint.value;
  }

  const output = envelope.desired_outputs.find((candidate) => {
    const format = candidate.format ?? candidate.kind;
    return DOCUMENT_FORMATS.has(format) || IMAGE_FORMATS.has(format);
  });
  if (!output) {
    return null;
  }
  const format = output.format ?? output.kind;
  return format === "jpeg" ? "jpg" : format;
}

export function preferredWorkloadFromUnderstandingEnvelope(
  envelope: UnderstandingEnvelope | null | undefined,
  prompt?: string | null,
): SharedBrainWorkload | null {
  if (!envelope || envelope.confidence < 0.52) {
    return null;
  }
  const desktopExecutionRequired =
    envelope.risk.local_private ||
    envelope.privacy_routing.mode === "desktop_private" ||
    envelope.desired_outputs.some((output) => output.target === "desktop");
  if (desktopExecutionRequired) {
    return "desktop_handoff";
  }
  const contract = compileOutputContract({
    message: prompt ?? envelope.intent.topic ?? "",
    metadata: {
      outputContractAuthoritative: envelope.desired_outputs.some(
        (output) => output.constraints.includes("output_contract"),
      ),
    },
  });
  const contractWorkload = workloadFromOutputContract(contract);
  if (contractWorkload) {
    return contractWorkload;
  }
  if (envelope.desired_outputs.some((output) => output.kind === "xlsx")) {
    return "table_generate";
  }
  if (
    envelope.desired_outputs.some((output) => output.kind === "table") &&
    (prompt == null || isExplicitTableRequest(prompt))
  ) {
    return "table_generate";
  }
  if (
    envelope.desired_outputs.some(
      (output) => output.kind === "pdf" || output.kind === "docx" || output.kind === "artifact",
    )
  ) {
    return "document_generate";
  }
  if (envelope.desired_outputs.some((output) => output.kind === "image" || output.kind === "svg")) {
    return "image_analyze";
  }
  if (envelope.intent.action === "plan") {
    return "planning";
  }
  return null;
}

export function envelopeTelemetrySummary(envelope: UnderstandingEnvelope | null | undefined) {
  if (!envelope) {
    return {};
  }
  return {
    envelopeSource: envelope.source,
    envelopeConfidence: envelope.confidence,
    desiredOutputCount: envelope.desired_outputs.length,
    constraintCount: envelope.constraints.length,
    requiredCapabilityCount: envelope.required_capabilities.length,
    ambiguityCount: envelope.ambiguities.length,
    memoryCandidateCount: envelope.memory_candidates.length,
    riskLocalPrivate: envelope.risk.local_private,
    riskPromptInjection: envelope.risk.prompt_injection,
  };
}
