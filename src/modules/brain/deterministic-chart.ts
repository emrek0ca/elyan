/**
 * Deterministik grafik/tablo türetme — "modele güvenme" katmanı.
 *
 * NEDEN: kullanıcı grafik istediğinde tur, modelin yapısal bir `chart` bloğu
 * üretmesine bağımlıydı. Reasoning modeli yapısal turda sık sık BOŞ JSON
 * üretiyor; tur o zaman `continuity fallback`'e düşüyor ve kullanıcı grafik
 * yerine "şu an tamamlayamadım" görüyordu. Oysa iki durumda da grafiği
 * SUNUCU zaten üretebilir:
 *
 *   1. Fonksiyon grafiği — ifade ya istekte ya da bir önceki asistan
 *      mesajında yazılıdır ("Bir polinom yaz" → "grafiğini çiz").
 *   2. Veri grafiği — sayısal seri ya web grounding kanıtından
 *      (`web.numeric_facts`) ya da cevabın kendi markdown tablosundan gelir.
 *
 * Bu modül o iki yolu modelden BAĞIMSIZ çalıştırır. Model yapısal çıktı
 * üretirse o birincildir; üretmezse buradaki türetme devreye girer.
 *
 * GÜVENLİK: ifade değerlendirme `function-sampler` üzerinden yapılır —
 * `eval`/`Function` yok, beyaz-listeli token değerlendiricisi var.
 */

import {
  buildAssistantChartBlock,
  buildAssistantTableBlock,
} from "../chat/message-blocks.js";
import { coerceFiniteNumber } from "../chat/chart-data.js";
import { compileExpression } from "./function-sampler.js";
import type {
  ElyanAssistantChartBlock,
  ElyanAssistantTableBlock,
} from "../../contracts/domain.js";

/** Doğrulanmış sayısal seri — grounding/araç çıktısının kanonik hâli. */
export type VerifiedNumericPoint = {
  label: string;
  value: number;
  unit?: string;
  source?: string;
};

/**
 * LaTeX'i güvenli değerlendiricinin anladığı düz ifadeye indirger.
 * Dönüştüremediği bir yapı kalırsa (matris, integral, toplam) sonuç zaten
 * derlenmez ve çağıran ifadeyi reddeder — yanlış grafik çizilmez.
 */
function latexToPlainExpression(input: string): string {
  let value = String(input ?? "");
  value = value.replace(/\$+/g, " ").replace(/\\[[\]()]/g, " ");
  // \frac{a}{b} → (a)/(b) — iç içe kullanım için birkaç tur.
  for (let pass = 0; pass < 4; pass += 1) {
    const next = value.replace(
      /\\d?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g,
      "(($1)/($2))",
    );
    if (next === value) break;
    value = next;
  }
  value = value
    .replace(/\\sqrt\s*\{([^{}]*)\}/g, "sqrt($1)")
    .replace(/\\(sin|cos|tan|ln|log|exp|sinh|cosh|tanh|arcsin|arccos|arctan)\b/g, (_, fn) => {
      const map: Record<string, string> = {
        arcsin: "asin",
        arccos: "acos",
        arctan: "atan",
      };
      return map[fn] ?? fn;
    })
    .replace(/\\cdot|\\times/g, "*")
    .replace(/\\div/g, "/")
    .replace(/\\pi/g, "pi")
    .replace(/\\left|\\right/g, "")
    .replace(/\\,|\\;|\\!|\\quad|\\qquad/g, " ")
    .replace(/[{}]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return value;
}

/**
 * Değerlendiricinin tanıdığı sözcükler. Bunların dışındaki her sözcük
 * ifadenin BİTTİĞİ yerdir.
 */
const MATH_WORDS = new Set([
  "sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh",
  "sqrt", "abs", "exp", "ln", "log", "log10", "log2", "sign",
  "floor", "ceil", "round", "pi", "tau", "e", "x", "y",
  "pow", "atan2", "min", "max", "mod", "hypot",
]);

/**
 * İfadeyi düz metnin içinden kesip çıkarır.
 *
 * Model formülü nesirle sarmalıyor: "f(x) = 3x^3 - 5x^2 + 2x - 7 Bu üçüncü
 * dereceden bir polinomdur." Eşitliğin sağını olduğu gibi almak ifadeyi
 * derlenemez yapıyordu; burada matematik olmayan İLK sözcükte kesiyoruz.
 */
function trimExpressionTail(input: string): string {
  const source = String(input ?? "").trim();
  let output = "";
  let index = 0;
  while (index < source.length) {
    const char = source[index];
    if (/[\p{L}π_]/u.test(char)) {
      let word = "";
      while (index < source.length && /[\p{L}\p{N}π_]/u.test(source[index])) {
        word += source[index];
        index += 1;
      }
      if (!MATH_WORDS.has(word.toLowerCase())) break;
      output += word;
      continue;
    }
    // Virgül yalnız fonksiyon argümanı ayracı olarak anlamlı (`pow(x,2)`);
    // parantez dışında kalırsa derleyici ifadeyi zaten reddeder.
    if (/[0-9.,\s+\-*/^()²³·×∙–—−÷]/u.test(char)) {
      output += char;
      index += 1;
      continue;
    }
    break;
  }
  // Askıda kalan operatör/nokta ("… + ") ifadeyi derlenemez yapar.
  return output.replace(/[\s+\-*/^.]+$/u, "").trim();
}

const ASSIGNMENT_PATTERN =
  /(?:^|[^\p{L}])([a-z])\s*(?:\(\s*[a-z]\s*(?:,\s*[a-z]\s*)?\))?\s*=\s*([^\n]{1,240})/giu;

/** `=` içermeyen ama çizilebilir bir ifade barındıran metin parçaları. */
const BARE_EXPRESSION_PATTERN =
  /(?:^|[^\p{L}\p{N}])((?:[0-9.]*\s*\*?\s*)?(?:[a-z]\s*\^\s*[0-9]+|\b(?:sin|cos|tan|sqrt|exp|ln|log)\s*\([^()]{1,60}\))(?:\s*[-+*/^]\s*[0-9a-z.^()\s]{1,60})*)/giu;

export type PlottableExpression = {
  expression: string;
  /** İfadede gerçekten geçen değişkenler — 2 ise yüzey demektir. */
  variables: string[];
};

/**
 * Metin yığınında (en yeniden eskiye) çizilebilir ilk ifadeyi bulur.
 *
 * "grafiğini çiz" turunda ifade İSTEKTE yoktur; bir önceki asistan mesajında
 * yazılıdır. Bu yüzden bağlam metinleri sırayla taranır.
 */
export function extractPlottableExpression(
  texts: Array<string | null | undefined>,
): PlottableExpression | null {
  for (const raw of texts) {
    const text = String(raw ?? "").trim();
    if (!text) continue;
    const plain = latexToPlainExpression(text);
    const candidates: string[] = [];
    for (const match of plain.matchAll(ASSIGNMENT_PATTERN)) {
      const trimmed = trimExpressionTail(match[2]);
      if (trimmed) candidates.push(trimmed);
    }
    for (const match of plain.matchAll(BARE_EXPRESSION_PATTERN)) {
      const trimmed = trimExpressionTail(match[1]);
      if (trimmed) candidates.push(trimmed);
    }
    for (const candidate of candidates) {
      // Önce yüzey (x,y), sonra 2B (x) olarak dene: iki değişkenli bir ifadeyi
      // tek değişkenliymiş gibi derlemek `y`'yi bilinmeyen sayıp reddeder.
      const surface = compileExpression(candidate, ["x", "y"]);
      if (surface && surface.variables.length === 2) {
        return { expression: candidate, variables: ["x", "y"] };
      }
      const planar = compileExpression(candidate, ["x"]);
      if (planar && planar.variables.length === 1) {
        return { expression: candidate, variables: ["x"] };
      }
    }
  }
  return null;
}

/**
 * Cevabın markdown tablosundan sayısal seri çıkarır.
 *
 * "Son 5 yıl enflasyonu tablo + grafik" isteğinde model çoğu kez tabloyu
 * yazıp grafiği unutuyor. Tablo zaten SAYISAL veridir; onu grafiğe çevirmek
 * için modeli yeniden çalıştırmaya gerek yok.
 */
export function extractNumericSeriesFromMarkdown(
  text: string,
): { labels: string[]; values: number[]; label: string; unit?: string } | null {
  const lines = String(text ?? "")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("|") && line.endsWith("|"));
  if (lines.length < 3) return null;
  const cells = (line: string) =>
    line
      .slice(1, -1)
      .split("|")
      .map((cell) => cell.replace(/\*\*|__|`/g, "").trim());
  const header = cells(lines[0]);
  const bodyLines = lines
    .slice(1)
    .filter((line) => !/^\|[\s:-]+\|$/.test(line.replace(/\s/g, "")))
    .filter((line) => !/^[|\s:-]+$/.test(line));
  const rows = bodyLines.map(cells).filter((row) => row.length >= 2);
  if (header.length < 2 || rows.length < 2) return null;

  // Tamamı sayıya inen İLK kolon değer kolonudur; ilk kolon etikettir.
  for (let column = 1; column < header.length; column += 1) {
    const values = rows.map((row) => coerceFiniteNumber(row[column]));
    if (values.some((value) => value == null)) continue;
    const labels = rows.map((row, index) => row[0] || String(index + 1));
    const unitMatch = header[column].match(/\(([^)]{1,20})\)|(%|TL|USD|EUR|₺)/i);
    return {
      labels,
      values: values as number[],
      label: header[column] || "Değer",
      ...(unitMatch ? { unit: (unitMatch[1] ?? unitMatch[2]).trim() } : {}),
    };
  }
  return null;
}

function titleFromPrompt(prompt: string, fallback: string): string {
  const compact = String(prompt ?? "")
    .replace(/\s+/g, " ")
    .trim();
  if (!compact) return fallback;
  return compact.length > 60 ? `${compact.slice(0, 57)}…` : compact;
}

export type ChartDerivationInput = {
  prompt: string;
  /** Modelin bu turdaki nesir cevabı (markdown tablo taşıyor olabilir). */
  responseText?: string | null;
  /** Sohbet bağlamı: en YENİ mesaj başta olacak şekilde düz metinler. */
  contextTexts?: Array<string | null | undefined>;
  /** Araç/grounding katmanından gelen doğrulanmış sayısal seri. */
  numericPoints?: VerifiedNumericPoint[];
  /** Model açıkça bir tür istediyse (3B yüzey gibi). */
  preferredChartType?: string | null;
};

/**
 * Bu tur için deterministik bir chart bloğu üretir; üretemezse `null`.
 *
 * Öncelik sırası kanıt gücüne göredir: doğrulanmış sayısal seri → cevabın
 * kendi tablosu → bağlamdaki matematiksel ifade.
 */
export function deriveChartBlock(
  input: ChartDerivationInput,
): ElyanAssistantChartBlock | null {
  const points = input.numericPoints ?? [];
  if (points.length >= 2) {
    const unit = points.find((point) => point.unit)?.unit;
    const sources = [
      ...new Set(points.map((point) => point.source).filter(Boolean)),
    ].slice(0, 3);
    return buildAssistantChartBlock(
      {
        // Etiketler tarihse trend, değilse kıyaslama: çizgi/çubuk kararı
        // veriye bakarak verilir, kelimeye değil.
        chartType: looksLikeTimeSeries(points.map((point) => point.label))
          ? "line"
          : "bar",
        labels: points.map((point) => point.label),
        values: points.map((point) => point.value),
        title: titleFromPrompt(input.prompt, "Veri grafiği"),
        ...(unit ? { unit, yLabel: unit } : {}),
        caption: sources.length > 0 ? `Kaynak: ${sources.join(", ")}` : undefined,
        seriesName: "Değer",
      },
      { renderHints: { derivedBy: "server_numeric_evidence" } },
    );
  }

  const fromMarkdown = input.responseText
    ? extractNumericSeriesFromMarkdown(input.responseText)
    : null;
  if (fromMarkdown) {
    return buildAssistantChartBlock(
      {
        chartType: looksLikeTimeSeries(fromMarkdown.labels) ? "line" : "bar",
        labels: fromMarkdown.labels,
        values: fromMarkdown.values,
        title: titleFromPrompt(input.prompt, "Veri grafiği"),
        yLabel: fromMarkdown.label,
        ...(fromMarkdown.unit ? { unit: fromMarkdown.unit } : {}),
        seriesName: fromMarkdown.label,
      },
      { renderHints: { derivedBy: "server_markdown_table" } },
    );
  }

  const expression = extractPlottableExpression([
    input.prompt,
    input.responseText,
    ...(input.contextTexts ?? []),
  ]);
  if (!expression) return null;

  const isSurface =
    expression.variables.length === 2 ||
    ["surface3d", "mesh", "math_surface_3d"].includes(
      String(input.preferredChartType ?? "").toLowerCase(),
    );
  return buildAssistantChartBlock(
    {
      chartType: isSurface ? "surface3d" : "function",
      labels: undefined,
      values: undefined,
      expression: expression.expression,
      variables: expression.variables,
      range: isSurface
        ? { x: [-5, 5], y: [-5, 5] }
        : { x: [-10, 10] },
      xLabel: "x",
      yLabel: isSurface ? "z" : "f(x)",
      title: `f(${expression.variables.join(", ")}) = ${expression.expression}`.slice(0, 120),
    },
    { renderHints: { derivedBy: "server_expression_sampling" } },
  );
}

/** Doğrulanmış sayısal seriyi tabloya çevirir (grafikle birlikte istendiğinde). */
export function deriveTableBlock(
  input: ChartDerivationInput,
): ElyanAssistantTableBlock | null {
  const points = input.numericPoints ?? [];
  if (points.length >= 2) {
    const hasUnit = points.some((point) => point.unit);
    const hasSource = points.some((point) => point.source);
    return buildAssistantTableBlock(
      {
        columns: [
          "Etiket",
          "Değer",
          ...(hasUnit ? ["Birim"] : []),
          ...(hasSource ? ["Kaynak"] : []),
        ],
        rows: points.map((point) => [
          point.label,
          String(point.value),
          ...(hasUnit ? [point.unit ?? ""] : []),
          ...(hasSource ? [point.source ?? ""] : []),
        ]),
        title: titleFromPrompt(input.prompt, "Veri tablosu"),
      },
      { renderHints: { derivedBy: "server_numeric_evidence" } },
    );
  }
  const fromMarkdown = input.responseText
    ? extractNumericSeriesFromMarkdown(input.responseText)
    : null;
  if (!fromMarkdown) return null;
  return buildAssistantTableBlock(
    {
      columns: ["Etiket", fromMarkdown.label],
      rows: fromMarkdown.labels.map((label, index) => [
        label,
        String(fromMarkdown.values[index] ?? ""),
      ]),
      title: titleFromPrompt(input.prompt, "Veri tablosu"),
    },
    { renderHints: { derivedBy: "server_markdown_table" } },
  );
}

/** Etiketler tarih/dönem mi? Çizgi-mi-çubuk-mu kararı buna bakar. */
function looksLikeTimeSeries(labels: string[]): boolean {
  if (labels.length < 3) return false;
  const dated = labels.filter((label) =>
    /(\b(19|20)\d{2}\b)|(\d{1,2}[./-]\d{1,2})|(oca|şub|sub|mar|nis|may|haz|tem|ağu|agu|eyl|eki|kas|ara|jan|feb|apr|jun|jul|aug|sep|oct|nov|dec)/i.test(
      label,
    ),
  ).length;
  return dated >= Math.ceil(labels.length * 0.6);
}
