import { trStemPattern } from "../../lib/tr-word-boundary.js";

/**
 * SONUÇ BİLİNCİ — "tamamlandı" ile "istediğim oldu" aynı şey değil.
 *
 * NEDEN VAR
 * ---------
 * Görev doğrulaması bugün YALNIZ VARLIK kontrolü yapıyor:
 *   output:artifact ✓  output:file_update ✓  rule:artifact_reference ✓
 * Bu yüzden içi kullanıcının kendi cümlesi olan bir belge tüm kapıları geçti
 * ve görev "completed" oldu.
 *
 * Epizodik hafıza (Katman 1) kurulduğunda bu doğrudan zarar vermeye başladı:
 * ölçüm, aynı cümlenin hem `server_brain → completed` hem
 * `desktop_runtime → completed` olarak kayıtlı olduğunu gösterdi. Oysa
 * `server_brain → completed` turları çöp PDF üreten ve netleştirme sorusu
 * soran turlardı. Bu etiketle öğrenmek, YANLIŞ dersi kalıcılaştırmaktır.
 *
 * Bu modül taşıma başarısını (runtime bitti mi) kullanıcı başarısından
 * (istenen şey oldu mu) ayırır.
 *
 * NE YAPMAZ: modele sormaz. Bütün kontroller deterministik ve ucuzdur;
 * her görev sonunda çalışır.
 */

export type OutcomeVerdict = "fulfilled" | "degraded" | "unfulfilled";

export type OutcomeAssessment = {
  verdict: OutcomeVerdict;
  reasons: string[];
};

type ExpectedOutput = { kind?: unknown; required?: unknown };

const PDF_REQUEST = trStemPattern(["pdf"]);
const DOCX_REQUEST = trStemPattern(["docx", "word"]);

/**
 * Cevap metni, işin kendisi yerine kullanıcıya sorulmuş bir soru mu?
 *
 * Canlı arıza (görev 67649401): model "Netleştireyim: tam olarak neyi yapmamı
 * istiyorsun?" dedi ve bu SORU PDF gövdesi olarak basıldı; görev "PDF Belgesi
 * hazır." diye başarılı raporlandı.
 */
const CLARIFICATION_STEMS = trStemPattern([
  "netleştir",
  "netlestir",
  "hangisini",
  "tam olarak ne",
  "biraz daha detay",
  "clarify",
]);

export function looksLikeClarification(text: string): boolean {
  const normalized = String(text ?? "").trim();
  if (!normalized) return false;
  if (/\?\s*$/u.test(normalized)) return true;
  return CLARIFICATION_STEMS.test(normalized);
}

function readBlocks(result: unknown): Array<Record<string, unknown>> {
  const record = (result ?? {}) as Record<string, unknown>;
  return Array.isArray(record.blocks)
    ? (record.blocks as Array<Record<string, unknown>>)
    : [];
}

/**
 * Üretilen dosyanın adı, kullanıcının cümlesinden mi türemiş?
 *
 * Canlı çıktı: `masaustune-zurafalar-hakkinda-bir-pdf-hazirla-ve-kaydet.docx`
 * Bu bir belge adı değil, isteğin sluglanmış hâlidir — başlık üretilemediğinde
 * masaüstünün düştüğü yol.
 */
/**
 * Türkçe harfleri ASCII'ye katla.
 *
 * ŞART: masaüstü dosya adını sluglarken zaten ASCII'ye çeviriyor
 * ("masaüstüne" → "masaustune"). İki tarafı aynı alfabeye indirmeden
 * karşılaştırma sessizce başarısız oluyordu (ölçüm: örtüşme 0.20, oysa dosya
 * adı isteğin birebir kopyasıydı).
 */
function foldToAscii(value: string): string {
  return value
    .toLocaleLowerCase("tr")
    .replace(/ı/g, "i")
    .replace(/ü/g, "u")
    .replace(/ö/g, "o")
    .replace(/ş/g, "s")
    .replace(/ğ/g, "g")
    .replace(/ç/g, "c")
    .replace(/â/g, "a")
    .replace(/î/g, "i")
    .replace(/û/g, "u");
}

export function filenameEchoesRequest(fileName: string, request: string): boolean {
  const name = foldToAscii(String(fileName ?? ""))
    .replace(/\.[a-z0-9]+$/i, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
  if (!name) return false;
  const requestWords = foldToAscii(String(request ?? ""))
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .split(/\s+/)
    .filter((word) => word.length > 3);
  if (requestWords.length < 3) return false;
  const nameWords = new Set(name.split(/\s+/));
  const overlap = requestWords.filter((word) =>
    [...nameWords].some((candidate) => candidate.startsWith(word.slice(0, 5))),
  ).length;
  // İsteğin sözcüklerinin çoğu dosya adında geçiyorsa bu bir eko.
  return overlap / requestWords.length >= 0.6;
}

export function assessTaskOutcome(input: {
  status: string;
  request: string;
  expectedOutputs?: unknown;
  result?: unknown;
  assistantText?: string | null;
  error?: string | null;
}): OutcomeAssessment {
  const reasons: string[] = [];

  if (input.status !== "completed") {
    return {
      verdict: input.status === "canceled" ? "unfulfilled" : "unfulfilled",
      reasons: [`status:${input.status}`, ...(input.error ? [`error:${input.error.slice(0, 120)}`] : [])],
    };
  }

  const blocks = readBlocks(input.result);
  const expected = Array.isArray(input.expectedOutputs)
    ? (input.expectedOutputs as ExpectedOutput[])
    : [];
  const artifactRequired = expected.some(
    (output) => output?.kind === "artifact" && output?.required === true,
  );
  const artifactBlock = blocks.find((block) => block.type === "artifact");

  // 1) Zorunlu artefakt yoksa iş yapılmamıştır.
  if (artifactRequired && !artifactBlock) {
    reasons.push("required_artifact_missing");
  }

  // 2) Cevap, işin kendisi yerine soru ise iş yapılmamıştır.
  const assistantText = String(input.assistantText ?? "").trim();
  if (assistantText && looksLikeClarification(assistantText)) {
    reasons.push("answer_is_clarification");
  }

  const artifactName = String(artifactBlock?.artifactName ?? artifactBlock?.title ?? "");

  // 3) İstenen biçim ile üretilen biçim uyuşmalı.
  if (artifactName) {
    if (PDF_REQUEST.test(input.request) && /\.docx$/i.test(artifactName)) {
      reasons.push("format_mismatch:pdf_requested_docx_produced");
    }
    if (
      DOCX_REQUEST.test(input.request) &&
      !PDF_REQUEST.test(input.request) &&
      /\.pdf$/i.test(artifactName)
    ) {
      reasons.push("format_mismatch:docx_requested_pdf_produced");
    }
    // 4) Dosya adı isteğin ekosu ise başlık üretilememiş demektir.
    if (filenameEchoesRequest(artifactName, input.request)) {
      reasons.push("filename_echoes_request");
    }
  }

  if (reasons.some((reason) => reason === "required_artifact_missing" || reason === "answer_is_clarification")) {
    return { verdict: "unfulfilled", reasons };
  }
  if (reasons.length > 0) return { verdict: "degraded", reasons };
  return { verdict: "fulfilled", reasons: [] };
}
