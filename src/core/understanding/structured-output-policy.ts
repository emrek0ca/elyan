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
  /\b(grafik|grafiği|grafigi|chart|graph|plot|çiz|ciz|çizim|cizim|visualize|visualise|görselleştir|gorsellestir)\b/i,
  /\b(fonksiyon grafiği|fonksiyon grafigi|function graph|function plot|scatter|line chart|bar chart|pie chart)\b/i,
  /\b(3d|3 boyutlu|üç boyutlu|uc boyutlu|surface|mesh|yüzey grafiği|yuzey grafigi)\b/i,
];

const EXPLICIT_MATH_LATEX_REQUEST_PATTERNS = [
  /\b(matematik|math|denklem|equation|integral|türev|turev|limit|ispat|proof|çöz|coz|solve)\b/i,
  /\b(latex|tex|ka?tex|formula|formül|formul)\b/i,
];

const EXPLICIT_SVG_REQUEST_PATTERNS = [
  /\b(svg|vektör|vektor|vector|diagram|geometrik çizim|geometrik cizim)\b/i,
];

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
