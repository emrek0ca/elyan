function compactText(value: string): string {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

const EXPLICIT_TABLE_REQUEST_PATTERNS = [
  // Only genuine "I want a table" nouns. Generic words like satır/sütun/row/
  // column were dropped — they appear constantly in non-table questions
  // ("kodun 3. satırı", "şu sütunu açıkla") and were forcing tables everywhere.
  /(?<!\p{L})(tablo|table|matris|matrix)(?!\p{L})/iu,
  /(?<!\p{L})(csv|xlsx|excel|spreadsheet)(?!\p{L})/iu,
  /\b(tablo olarak|table format|table olarak|tablo halinde|tablo biçiminde|tablo biciminde)\b/i,
];

const TABLE_ACTION_PATTERNS = [
  /(?<!\p{L})(ver|göster|goster|sun|hazırla|hazirla|oluştur|olustur|üret|uret|çıkar|cikar|dışa aktar|disa aktar|export|düzenle|duzenle|çevir|cevir)(?!\p{L})/iu,
  /(?<!\p{L})(karşılaştır|karsilastir|compare|listele|list|sırala|sirala|özetle|ozetle)(?!\p{L})/iu,
];

const NON_TABLE_PREFERENCE_PATTERNS = [
  /\b(liste|list|madde madde|bullet|paragraf|paragraflar|düz yazı|duz yazi|özet|ozet|açıkla|acikla|anlat|kısa bilgi|kisa bilgi)\b/i,
];

const EXPLICIT_CHART_REQUEST_PATTERNS = [
  /(?<!\p{L})(grafik|grafiği|grafiğini|grafigi|grafigini|chart|graph|plot|çiz|ciz|çizim|cizim|visualize|visualise|görselleştir|gorsellestir)(?!\p{L})/iu,
  /(?<!\p{L})(fonksiyon grafiği|fonksiyon grafigi|function graph|function plot|scatter|line chart|bar chart|pie chart)(?!\p{L})/iu,
  /(?<!\p{L})(3d|3 boyutlu|üç boyutlu|uc boyutlu|surface|mesh|yüzey grafiği|yuzey grafigi)(?!\p{L})/iu,
];

const EXPLICIT_MATH_LATEX_REQUEST_PATTERNS = [
  /(?<!\p{L})(matematik|math|denklem|equation|integral|türev|turev|limit|ispat|proof|çöz|coz|solve)(?!\p{L})/iu,
  /(?<!\p{L})(latex|tex|ka?tex|formula|formül|formul)(?!\p{L})/iu,
];

const EXPLICIT_SVG_REQUEST_PATTERNS = [
  /(?<!\p{L})(svg|vektör|vektor|vector|diagram|geometrik çizim|geometrik cizim)(?!\p{L})/iu,
];

export type StructuredResponseDecision = {
  primaryShape: "prose" | "list" | "table" | "chart" | "math" | "svg" | "document";
  primaryBlockType: "text" | "table" | "chart" | "math" | "svg" | "document_block";
  tablePolicy: "forbidden" | "explicit_only";
  widgetPolicy: "none" | "single_primary_widget";
  reasons: string[];
};

export function isExplicitTableRequest(prompt: string): boolean {
  const normalized = compactText(prompt);
  if (!normalized) {
    return false;
  }

  const hasTableNoun = EXPLICIT_TABLE_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized));
  if (!hasTableNoun) {
    return false;
  }

  if (/\b(tablo olarak|table format|table olarak|tablo halinde|tablo biçiminde|tablo biciminde)\b/i.test(normalized)) {
    return true;
  }

  return TABLE_ACTION_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function shouldPreferPlainListOrProse(prompt: string): boolean {
  const normalized = compactText(prompt);
  if (!normalized) {
    return true;
  }
  if (isExplicitTableRequest(normalized)) {
    return false;
  }
  return NON_TABLE_PREFERENCE_PATTERNS.some((pattern) => pattern.test(normalized)) || !isExplicitTableRequest(normalized);
}

export function shouldPromoteMarkdownTableToWidget(input: {
  prompt?: string | null;
  selectedWorkload?: string | null;
}): boolean {
  if (String(input.selectedWorkload ?? "").trim().toLowerCase() === "table_generate") {
    return true;
  }
  return isExplicitTableRequest(input.prompt ?? "");
}

export function isExplicitChartRequest(prompt: string): boolean {
  const normalized = compactText(prompt);
  if (!normalized) {
    return false;
  }
  return EXPLICIT_CHART_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function isExplicitMathOrLatexRequest(prompt: string): boolean {
  const normalized = compactText(prompt);
  if (!normalized) {
    return false;
  }
  return EXPLICIT_MATH_LATEX_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function isExplicitSvgRequest(prompt: string): boolean {
  const normalized = compactText(prompt);
  if (!normalized) {
    return false;
  }
  return EXPLICIT_SVG_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function decideStructuredResponseDecision(input: {
  prompt?: string | null;
  selectedWorkload?: string | null;
}): StructuredResponseDecision {
  const prompt = input.prompt ?? "";
  const selectedWorkload = String(input.selectedWorkload ?? "").trim().toLowerCase();
  const reasons: string[] = [];

  if (selectedWorkload === "document_generate") {
    reasons.push("document_generation_workload");
    return {
      primaryShape: "document",
      primaryBlockType: "document_block",
      tablePolicy: isExplicitTableRequest(prompt) ? "explicit_only" : "forbidden",
      widgetPolicy: "single_primary_widget",
      reasons,
    };
  }

  if (isExplicitSvgRequest(prompt)) {
    reasons.push("explicit_svg_request");
    return {
      primaryShape: "svg",
      primaryBlockType: "svg",
      tablePolicy: "forbidden",
      widgetPolicy: "single_primary_widget",
      reasons,
    };
  }

  if (isExplicitChartRequest(prompt)) {
    reasons.push("explicit_chart_request");
    return {
      primaryShape: "chart",
      primaryBlockType: "chart",
      tablePolicy: "forbidden",
      widgetPolicy: "single_primary_widget",
      reasons,
    };
  }

  if (isExplicitMathOrLatexRequest(prompt)) {
    reasons.push("explicit_math_latex_request");
    return {
      primaryShape: "math",
      primaryBlockType: "math",
      tablePolicy: "forbidden",
      widgetPolicy: "single_primary_widget",
      reasons,
    };
  }

  if (
    selectedWorkload === "table_generate" ||
    shouldPromoteMarkdownTableToWidget({ prompt, selectedWorkload })
  ) {
    reasons.push(selectedWorkload === "table_generate" ? "table_workload" : "explicit_table_request");
    return {
      primaryShape: "table",
      primaryBlockType: "table",
      tablePolicy: "explicit_only",
      widgetPolicy: "single_primary_widget",
      reasons,
    };
  }

  if (shouldPreferPlainListOrProse(prompt)) {
    reasons.push("plain_list_or_prose_preferred");
  }

  return {
    primaryShape: "prose",
    primaryBlockType: "text",
    tablePolicy: "forbidden",
    widgetPolicy: "none",
    reasons,
  };
}
