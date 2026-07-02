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

const NEGATED_TABLE_REQUEST_PATTERNS = [
  /\b(tablo|table|matris|matrix|csv|xlsx|excel|spreadsheet)\b.{0,48}\b(istemiyorum|isteme|olmas[ıi]n|kullanma|ekleme|yapma|kurma|çıkarma|cikarma|no|without)\b/iu,
  /\b(istemiyorum|isteme|olmas[ıi]n|kullanma|ekleme|yapma|kurma|çıkarma|cikarma|no|without)\b.{0,48}\b(tablo|table|matris|matrix|csv|xlsx|excel|spreadsheet)\b/iu,
];

const NON_TABLE_PREFERENCE_PATTERNS = [
  /\b(liste|list|madde madde|bullet|paragraf|paragraflar|düz yazı|duz yazi|özet|ozet|açıkla|acikla|anlat|kısa bilgi|kisa bilgi)\b/i,
];

const PLAN_OR_STEP_REQUEST_PATTERNS = [
  /\b(plan|planı|plani|planını|planini|planla|roadmap|yol haritası|yol haritasi|program|takvim|schedule|routine|rutin)\b/i,
  /\b(çalışma|calisma|ders|hazırlık|hazirlik|teknofest|proje|öğrenme|ogrenme)\b.{0,60}\b(plan|program|takvim|rutini|rutini|roadmap|yol haritası|yol haritasi)\b/i,
  /\b(\d+\s*(adım|adim|günlük|gunluk|haftalık|haftalik|aşamalı|asamali)|adım adım|adim adim)\b.{0,80}\b(plan|program|çıkar|cikar|hazırla|hazirla|oluştur|olustur)\b/i,
];

const EXPLICIT_CHART_REQUEST_PATTERNS = [
  /(?<!\p{L})(grafik|grafiği|grafiğini|grafigi|grafigini|chart|graph|plot|çiz|ciz|çizim|cizim|visualize|visualise|görselleştir|gorsellestir)(?!\p{L})/iu,
  /(?<!\p{L})(fonksiyon grafiği|fonksiyon grafigi|function graph|function plot|scatter|line chart|bar chart|pie chart)(?!\p{L})/iu,
  /(?<!\p{L})(3d|3 boyutlu|üç boyutlu|uc boyutlu|surface|mesh|yüzey grafiği|yuzey grafigi)(?!\p{L})/iu,
];

const NEGATED_CHART_REQUEST_PATTERNS = [
  /\b(grafik|chart|graph|plot|diagram|diyagram)\b.{0,40}\b(istemiyorum|isteme|olmas[ıi]n|kullanma|ekleme|no|without)\b/iu,
  /\b(istemiyorum|isteme|olmas[ıi]n|kullanma|ekleme|no|without)\b.{0,40}\b(grafik|chart|graph|plot|diagram|diyagram)\b/iu,
];

const EXPLICIT_MATH_SURFACE_3D_REQUEST_PATTERNS = [
  /\b(3d|3 boyutlu|üç boyutlu|uc boyutlu)\b.{0,80}\b(yüzey grafiği|yuzey grafigi|surface plot|surface|mesh|grafiğini çiz|grafigini ciz|grafik|plot)\b/i,
  /\b(4d|4 boyutlu|dört boyutlu|dort boyutlu)\b.{0,80}\b(grafik|plot|surface|yüzey|yuzey)\b/i,
  /\bz\s*=\s*f\s*\(\s*x\s*,\s*y\s*\)\b.{0,80}\b(çiz|ciz|grafik|plot|surface)\b/i,
  /\bz\s*=\s*[^,\n]+?\b.{0,80}\b(3d|3 boyutlu|üç boyutlu|uc boyutlu|4d|4 boyutlu|surface plot|yüzey grafiği|yuzey grafigi)\b/i,
  /\b(surface plot|math surface|3d surface|4d surface)\b/i,
];

const EXPLICIT_MATH_LATEX_REQUEST_PATTERNS = [
  /(?<!\p{L})(matematik|math|denklem|equation|integral|türev|turev|limit|ispat|proof|çöz|coz|solve)(?!\p{L})/iu,
  /(?<!\p{L})(latex|tex|ka?tex|formula|formül|formul)(?!\p{L})/iu,
  // Objects whose canonical answer *is* a math expression. Real prod hit:
  // "Bana bir polinom yaz" got its math block dropped by
  // `filterAssistantBlocksByIntent` because none of these nouns were treated
  // as math intent, and the user only saw "İşte örnek bir polinom:" with an
  // empty tail. Same reasoning for fonksiyon / matris / seri / dizi …
  /(?<!\p{L})(polinom|polynomial|fonksiyon|function|matris|matrix|vekt[öo]r(?:\s+alan[ıi])?|dizi|series?|serisi|seri|kesir|fraction|kompleks\s+say[ıi]|karma[şs][ıi]k\s+say[ıi]|complex\s+number|kalk[üu]l[üu]s|calculus|cebir|algebra|geometri|geometry|trigonometri|trigonometry|logaritma|logarithm)(?!\p{L})/iu,
];

const EXPLICIT_SVG_REQUEST_PATTERNS = [
  /(?<!\p{L})(svg|vektör|vektor|vector|diagram|geometrik çizim|geometrik cizim)(?!\p{L})/iu,
];

export type StructuredResponseDecision = {
  primaryShape: "prose" | "list" | "table" | "chart" | "math_surface_3d" | "math" | "svg" | "document";
  primaryBlockType: "text" | "table" | "chart" | "math_surface_3d" | "math" | "svg" | "document_block";
  tablePolicy: "forbidden" | "explicit_only";
  // "single_primary_widget" → explicit request, force exactly one widget.
  // "proactive_optional"    → no explicit request, but the model MAY emit one
  //                           widget when the answer content genuinely warrants
  //                           it (balanced proactive). "none" → stay prose
  //                           (user explicitly asked for prose/list).
  widgetPolicy: "none" | "single_primary_widget" | "proactive_optional";
  reasons: string[];
};

// Strong signals that the user explicitly wants plain prose / a bullet list, so
// we should NOT proactively reach for a widget even if the topic looks visual.
const EXPLICIT_PROSE_PREFERENCE_PATTERNS = [
  /\b(düz yazı|duz yazi|paragraf olarak|paragraf halinde|madde madde|bullet|kısaca|kisaca|kısa(ca)? (anlat|açıkla|özetle)|kısa (bir )?özet|kisa (bir )?ozet|özet halinde|ozet halinde|tek c[uü]mle\p{L}*|sadece (yaz|anlat|söyle|soyle))\b/iu,
  /(?<!\p{L})(d[üu]z yaz[ıi]|plain text)(?:\s+olarak)?(?!\p{L})/iu,
  /\b(in plain text|as prose|in a paragraph|just explain|in words only|no (table|chart|diagram|graph))\b/i,
];

export function prefersPlainProseExplicitly(prompt: string): boolean {
  const normalized = compactText(prompt);
  if (!normalized) {
    return false;
  }
  if (NEGATED_TABLE_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized))) {
    return true;
  }
  return EXPLICIT_PROSE_PREFERENCE_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function isExplicitTableRequest(prompt: string): boolean {
  const normalized = compactText(prompt);
  if (!normalized) {
    return false;
  }
  if (NEGATED_TABLE_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized))) {
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

export function isPlanOrStepRequest(prompt: string): boolean {
  const normalized = compactText(prompt);
  if (!normalized || isExplicitTableRequest(normalized)) {
    return false;
  }
  return PLAN_OR_STEP_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized));
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
  if (NEGATED_CHART_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized))) {
    return false;
  }
  return EXPLICIT_CHART_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function isExplicitMathSurface3DRequest(prompt: string): boolean {
  const normalized = compactText(prompt);
  if (!normalized) {
    return false;
  }
  return EXPLICIT_MATH_SURFACE_3D_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized));
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

  if (isExplicitMathSurface3DRequest(prompt)) {
    reasons.push("explicit_math_surface_3d_request");
    return {
      primaryShape: "math_surface_3d",
      primaryBlockType: "math_surface_3d",
      tablePolicy: "forbidden",
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

  // No explicit widget request. Balanced-proactive default: let the model emit
  // ONE widget when the actual answer content is genuinely visual (a dataset, a
  // numeric series/trend, an equation, a process diagram) — the model sees the
  // content a keyword classifier cannot. Unless the user explicitly asked for
  // plain prose / a bullet list, in which case we stay text-only.
  const wantsPlainProse = prefersPlainProseExplicitly(prompt);
  if (wantsPlainProse) {
    reasons.push("explicit_prose_preference");
    return {
      primaryShape: "prose",
      primaryBlockType: "text",
      tablePolicy: "forbidden",
      widgetPolicy: "none",
      reasons,
    };
  }

  if (isPlanOrStepRequest(prompt) || selectedWorkload === "planning") {
    reasons.push(isPlanOrStepRequest(prompt) ? "plan_request_prefers_list" : "planning_workload_prefers_list");
    return {
      primaryShape: "list",
      primaryBlockType: "text",
      tablePolicy: "forbidden",
      widgetPolicy: "none",
      reasons,
    };
  }

  reasons.push("proactive_visuals_allowed");
  return {
    primaryShape: "prose",
    primaryBlockType: "text",
    // Tables stay opt-in even when proactive: charts/math/diagrams are the
    // proactive surfaces; tables remain the most over-used so they require a
    // genuine multi-row dataset (enforced in the prompt), not a forbidden state.
    tablePolicy: "explicit_only",
    widgetPolicy: "proactive_optional",
    reasons,
  };
}
