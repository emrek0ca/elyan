import type { SharedBrainWorkload } from "../../modules/brain/workloads.js";
import { hasExplicitLocalSaveIntent } from "../../modules/tasks/local-read-intent.js";
import { trStemPattern } from "../../lib/tr-word-boundary.js";
import {
  recordBoolean as readBoolean,
  recordString as readString,
} from "../../lib/record.js";

export type OutputOperation =
  | "answer"
  | "create"
  | "transform"
  | "export"
  | "edit"
  | "analyze_then_export";

export type OutputReference =
  | "none"
  | "current_prompt"
  | "previous_answer"
  | "latest_artifact"
  | "attachment";

export type OutputKind =
  | "chat_reply"
  | "document"
  | "table"
  | "chart"
  | "image"
  | "svg";

export type OutputFormat =
  | "pdf"
  | "docx"
  | "xlsx"
  | "table"
  | "chart"
  | "png"
  | "jpg"
  | "jpeg"
  | "webp"
  | "svg";

export type OutputContract = {
  operation: OutputOperation;
  sourceReference: OutputReference;
  outputKind: OutputKind;
  outputFormat: OutputFormat | null;
  pageCount: number | null;
  requiresArtifact: boolean;
  confidence: number;
  reasons: string[];
};

export type OutputContractInput = {
  message: string;
  title?: string | null;
  metadata?: Record<string, unknown> | null;
};

const DOCUMENT_FORMATS = new Set<OutputFormat>(["pdf", "docx"]);
const TABLE_FORMATS = new Set<OutputFormat>(["xlsx", "table"]);
const IMAGE_FORMATS = new Set<OutputFormat>([
  "png",
  "jpg",
  "jpeg",
  "webp",
]);

const RESEARCH_REQUEST_PATTERN = trStemPattern([
  "araştır",
  "arastir",
  "incele",
  "research",
]);
const SAVE_REQUEST_PATTERN = trStemPattern(
  ["kaydet", "kayded", "save", "indir", "download"],
  {
    exclude: [
      "indirim",
      "indirimi",
      "indirimli",
      "indirime",
      "indirgeme",
      "indirgemeli",
    ],
  },
);
const LOCAL_OUTPUT_TARGET_PATTERN = trStemPattern([
  "masaüstü",
  "masaustu",
  "desktop",
  "bilgisayar",
  "computer",
]);
const NEGATED_ARTIFACT_PATTERN = trStemPattern([
  "kaydetme",
  "yazma",
  "oluşturma",
  "olusturma",
  "üretme",
  "uretme",
  "silme",
  "değiştirme",
  "degistirme",
]);

/**
 * Shared destination decision for the understanding envelope and execution
 * contract. A local noun alone is not enough: the user must also explicitly
 * request a save/write and must not negate artifact creation.
 */
export function hasExplicitLocalArtifactTarget(value: string): boolean {
  const text = normalize(value);
  return (
    SAVE_REQUEST_PATTERN.test(text) &&
    LOCAL_OUTPUT_TARGET_PATTERN.test(text) &&
    !NEGATED_ARTIFACT_PATTERN.test(text)
  );
}

function normalize(value: unknown): string {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase("tr-TR");
}

function safeMetadata(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function metadataFormat(metadata: Record<string, unknown> | null): OutputFormat | null {
  const value = normalize(
    readString(metadata, "exportFormat") ??
      readString(metadata, "outputFormat") ??
      readString(metadata, "renderFormat") ??
      readString(metadata, "format"),
  );
  if (value === "word" || value === "doc") return "docx";
  if (value === "excel" || value === "spreadsheet" || value === "csv") {
    return "xlsx";
  }
  if (
    value === "pdf" ||
    value === "docx" ||
    value === "xlsx" ||
    value === "table" ||
    value === "chart" ||
    value === "png" ||
    value === "jpg" ||
    value === "jpeg" ||
    value === "webp" ||
    value === "svg"
  ) {
    return value;
  }
  return null;
}

function isOutputFormatMention(
  text: string,
  index: number,
  matchLength: number,
): boolean {
  const after = text.slice(index + matchLength, index + matchLength + 96);
  // A format mentioned as the source of a read request is not a requested
  // output.  Only accept the format when it is attached to an output relation
  // or an output verb: "PDF yap", "Word'e çevir", "PDF olarak ver".
  if (
    /^(?:\s+|['’]?)(?:e|a|ye|ya|olarak|formatında|formatinda|dosyasına|dosyasina|file|document)\b/iu.test(
      after,
    ) ||
    /^\s*(?:sonra|ardından|ardindan)\s+(?:pdf|docx|word|xlsx|excel)\b/iu.test(
      after,
    ) ||
    /^\s*(?:(?:tablo|table)\s+)?(?:yap|yaz|oluştur|olustur|hazırla|hazirla|üret|uret|dönüştür|donustur|çevir|cevir|export|kaydet|ver|çıkar|cikar|tasarla|create|write|generate|convert|save|make)\p{L}*/iu.test(
      after,
    )
  ) {
    return true;
  }
  return false;
}

function inferFormat(text: string, metadata: Record<string, unknown> | null): OutputFormat | null {
  const explicit = metadataFormat(metadata);
  if (explicit) return explicit;
  const explicitFormatMatches = [
    { format: "pdf" as const, match: /\bpdf(?:'e|e)?\b/iu.exec(text) },
    { format: "docx" as const, match: /\b(?:docx|word|doc)\b/iu.exec(text) },
    { format: "xlsx" as const, match: /\b(?:xlsx|excel\p{L}{0,6}|spreadsheet|csv)\b/iu.exec(text) },
    { format: "table" as const, match: /\b(?:tablo|table)\b/iu.exec(text) },
    { format: "chart" as const, match: /\b(?:grafik|chart|plot|çizelge|cizelge)\b/iu.exec(text) },
    { format: "svg" as const, match: /\bsvg\b/iu.exec(text) },
  ]
    .filter(
      (item) =>
        item.match &&
        isOutputFormatMention(text, item.match.index ?? 0, item.match[0].length),
    )
    .sort((left, right) => (left.match?.index ?? 0) - (right.match?.index ?? 0));
  // File formats outrank a later generic widget noun: "Excel tablo yap"
  // requests an XLSX artifact, while "tablo" only describes its shape.
  const fileFormat = explicitFormatMatches.find((item) =>
    ["pdf", "docx", "xlsx"].includes(item.format),
  );
  if (fileFormat) return fileFormat.format;
  if (explicitFormatMatches.at(-1)) return explicitFormatMatches.at(-1)!.format;
  if (/\b(?:png|jpg|jpeg|webp)\b/iu.test(text)) {
    const match = text.match(/\b(png|jpg|jpeg|webp)\b/iu);
    return normalize(match?.[1]) as OutputFormat;
  }
  if (/(?<!\p{L})(?:görsel\p{L}*|gorsel\p{L}*|resm\p{L}*|foto(?!sentez)\p{L}*|fotoğraf\p{L}*|fotograf\p{L}*|image|picture|poster|afiş\p{L}*|afis\p{L}*)(?!\p{L})/iu.test(text)) {
    return "png";
  }
  const hasDocumentNoun = /(?<!\p{L})(?:rapor\p{L}*|makale\p{L}*|belge\p{L}*|döküman\p{L}*|dokuman\p{L}*|dilekçe\p{L}*|dilekce\p{L}*|savunma\p{L}*|sözleşme\p{L}*|sozlesme\p{L}*)(?!\p{L})/iu.test(text);
  const explicitlyForbidsArtifact = NEGATED_ARTIFACT_PATTERN.test(text);
  const asksDocumentCreation = /(?<!\p{L})(?:hazırla\p{L}*|hazirla\p{L}*|oluştur\p{L}*|olustur\p{L}*|üret\p{L}*|uret\p{L}*|yaz\p{L}{0,8}|tasarla\p{L}*|çıkar\p{L}*|cikar\p{L}*|raporlaştır\p{L}*|raporlastır\p{L}*|raporlastir\p{L}*|kaydet\p{L}*|olarak ver|formatında|formatinda)(?!\p{L})/iu.test(text);
  if (hasDocumentNoun && asksDocumentCreation && !explicitlyForbidsArtifact) {
    return "docx";
  }
  // Kullanıcı biçim söylemeden bir konuyu araştırıp kendi bilgisayarına
  // kaydetmemizi isterse ürün sözleşmesi varsayılan olarak DOCX araştırma
  // raporudur. Hedef ekli Türkçe biçimlerde de gelebilir: "masaüstüne",
  // "bilgisayarıma". Bu karar yalnız açık kaydetme + yerel hedef birlikte
  // bulunduğunda verilir; "araştır ama kaydetme, burada anlat" chat kalır.
  if (
    RESEARCH_REQUEST_PATTERN.test(text) &&
    hasExplicitLocalArtifactTarget(text)
  ) {
    return "docx";
  }
  return null;
}

function inferPageCount(text: string, metadata: Record<string, unknown> | null): number | null {
  const metadataPageCount = metadata?.pageCount ?? metadata?.page_count;
  if (typeof metadataPageCount === "number" && Number.isFinite(metadataPageCount)) {
    return Math.max(1, Math.min(80, Math.floor(metadataPageCount)));
  }
  const match =
    text.match(/\b(\d{1,2})\s*(?:sayfa|sayfalık|sayfalik|pages?|page)\b/iu) ??
    text.match(/\b(?:sayfa|pages?)\s*(?:sayısı|sayisi|count)?\s*[:=]?\s*(\d{1,2})\b/iu);
  if (!match) return null;
  return Math.max(1, Math.min(80, Number(match[1])));
}

function inferReference(text: string, metadata: Record<string, unknown> | null): OutputReference {
  if (readBoolean(metadata, "hasAttachment") === true) return "attachment";
  if (readBoolean(metadata, "hasLatestArtifact") === true) return "latest_artifact";
  if (/^(?:devam|devam et|sürdür|surdur|aynen|tamam|hani|continue|go on|keep going)\b/iu.test(text)) {
    return "previous_answer";
  }
  if (/(?<!\p{L})(?:bu|şu|su)\s+(?:konuşma\p{L}*|konusma\p{L}*|sohbet\p{L}*|oturum\p{L}*)(?!\p{L})/iu.test(text)) {
    return "previous_answer";
  }
  if (/\b(?:ekli|attached|dosya|belge|pdf|görsel|gorsel|resim|image)\b.{0,40}\b(?:bunu|şunu|sunu|onu|bu)\b/iu.test(text)) {
    return "attachment";
  }
  if (/(?<!\p{L})(?:bu|şu|su|o)\s+(?:rapor\p{L}*|belge\p{L}*|doküman\p{L}*|dokuman\p{L}*|metn\p{L}*|cevab\p{L}*|tablo\p{L}*|grafi\p{L}*|görsel\p{L}*|gorsel\p{L}*|resm\p{L}*)/iu.test(text)) {
    return readBoolean(metadata, "hasLatestArtifact") === true ? "latest_artifact" : "previous_answer";
  }
  if (/(?<!\p{L})(?:bunu|şunu|sunu|onu|sonuncu|önceki|onceki|yukarıdaki|yukaridaki|son cevap|son görsel|son gorsel|son belge|son sonuç|son sonuc|son çözüm|son cozum)\p{L}*/iu.test(text)) {
    return "previous_answer";
  }
  return "current_prompt";
}

function inferOperation(text: string, format: OutputFormat | null, reference: OutputReference): OutputOperation {
  const asksConceptQuestion =
    /\b(?:nedir|ne demek|fark[ıi]|aras[ıi]ndaki|nasıl çalışır|nasil calisir|why|what is|difference)\b/iu.test(text) &&
    /[?？]?\s*$/u.test(text);
  const negatesArtifact =
    /\b(?:kullanma|istemiyorum|olmas[ıi]n|yapma|çıkarma|cikarma|without|no)\b.{0,40}\b(?:tablo|table|grafik|chart|pdf|docx|excel|xlsx)\b/iu.test(text) ||
    /\b(?:tablo|table|grafik|chart|pdf|docx|excel|xlsx)\b.{0,40}\b(?:kullanma|istemiyorum|olmas[ıi]n|yapma|çıkarma|cikarma|without|no)\b/iu.test(text);
  if (asksConceptQuestion || negatesArtifact) return "answer";
  const hasAnalysis = trStemPattern([
    "analiz",
    "incele",
    "yorumla",
    "özetle",
    "ozetle",
    "araştır",
    "arastir",
    "research",
    "analyze",
    "summarize",
  ]).test(text);
  const hasTransform = /\b(?:dönüştür|donustur|çevir|cevir|aktar|export|convert)\b/iu.test(text);
  const hasEdit = /\b(?:düzenle|duzenle|değiştir|degistir|revize|iyileştir|iyilestir)\b/iu.test(text);
  const hasCreate = /\b(?:hazırla|hazirla|oluştur|olustur|üret|uret|yap|yaz\p{L}{0,8}|tasarla|kur)\b/iu.test(text);
  const hasExport = /\b(?:olarak ver|formatında|formatinda|çıktı|cikti|dosya|indir|kaydet)\b/iu.test(text);

  if (hasAnalysis && format) return "analyze_then_export";
  if (hasEdit) return "edit";
  if (hasTransform || (reference !== "current_prompt" && format)) return "transform";
  if (hasExport && format) return "export";
  if (hasCreate && format) return "create";
  if (hasCreate && /\b(?:rapor|makale|belge|döküman|dokuman|tablo|grafik|görsel|gorsel)\b/iu.test(text)) {
    return "create";
  }
  return format && !asksConceptQuestion && !negatesArtifact ? "export" : "answer";
}

function outputKindFor(format: OutputFormat | null, text: string): OutputKind {
  if (format && DOCUMENT_FORMATS.has(format)) return "document";
  if (format && TABLE_FORMATS.has(format)) return "table";
  if (format === "chart") return "chart";
  if (format === "svg") return "svg";
  if (format && IMAGE_FORMATS.has(format)) return "image";
  if (/\b(?:rapor|makale|belge|döküman|dokuman|dilekçe|dilekce)\b/iu.test(text)) return "document";
  if (/(?<!\p{L})(?:görsel\p{L}*|gorsel\p{L}*|resm\p{L}*|foto(?!sentez)\p{L}*|fotoğraf\p{L}*|fotograf\p{L}*|image|picture|poster|afiş\p{L}*|afis\p{L}*)(?!\p{L})/iu.test(text)) return "image";
  if (/\b(?:tablo|spreadsheet|excel)\b/iu.test(text)) return "table";
  if (/\b(?:grafik|chart|plot)\b/iu.test(text)) return "chart";
  return "chat_reply";
}

export function compileOutputContract(input: OutputContractInput): OutputContract {
  const metadata = safeMetadata(input.metadata);
  const text = normalize(`${input.title ? `${input.title}\n` : ""}${input.message}`);
  const format = inferFormat(text, metadata);
  const sourceReference = inferReference(text, metadata);
  const operation = inferOperation(text, format, sourceReference);
  const outputKind = operation === "answer" ? "chat_reply" : outputKindFor(format, text);
  const pageCount = inferPageCount(text, metadata);
  // AÇIK YEREL KAYIT İSTEĞİ DOSYA DEMEKTİR.
  //
  // Canlı arıza (2026-08-26, görev 234fbf31): "ekran görüntüsünü alıp
  // masaüstüne kaydet" isteğinde `requiresArtifact` FALSE çıktı, hedef "chat"
  // oldu ve tur dosyasız tamamlandı sayıldı. Sonra doğrulayıcı artefakt aradı,
  // bulamadı ve görevi düşürdü — sistem kendi içinde çelişiyordu.
  //
  // Biçim çıkarımı ("pdf", "docx") her cümlede yakalanmıyor; ama kullanıcı
  // "masaüstüne kaydet" dediğinde ortada bir DOSYA beklentisi vardır ve bu
  // biçimden bağımsızdır.
  const explicitLocalSave = hasExplicitLocalSaveIntent(text);
  const requiresArtifact =
    explicitLocalSave ||
    (operation !== "answer" && (outputKind !== "chat_reply" || format != null));
  const reasons = [
    `operation:${operation}`,
    `reference:${sourceReference}`,
    ...(format ? [`format:${format}`] : []),
    ...(pageCount ? [`page_count:${pageCount}`] : []),
    ...(requiresArtifact ? ["artifact_required"] : []),
    ...(explicitLocalSave ? ["explicit_local_save"] : []),
  ];
  const confidence =
    readBoolean(metadata, "outputContractAuthoritative") === true
      ? 0.96
      : Math.min(
          0.96,
          0.52 +
            (format ? 0.2 : 0) +
            (outputKind !== "chat_reply" ? 0.12 : 0) +
            (operation !== "answer" ? 0.08 : 0) +
            (sourceReference !== "current_prompt" ? 0.04 : 0),
        );
  return {
    operation,
    sourceReference,
    outputKind,
    outputFormat: format,
    pageCount,
    requiresArtifact,
    confidence,
    reasons,
  };
}

export function workloadFromOutputContract(
  contract: OutputContract,
): SharedBrainWorkload | null {
  if (!contract.requiresArtifact || contract.confidence < 0.58) return null;
  if (contract.outputKind === "table") return "table_generate";
  if (contract.outputKind === "document") return "document_generate";
  if (contract.outputKind === "chart" || contract.outputKind === "svg") {
    return "mobile_chat_balanced";
  }
  if (contract.outputKind === "image") return "image_analyze";
  return null;
}
