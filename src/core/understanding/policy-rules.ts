import type { SharedBrainWorkload } from "../../modules/brain/workloads.js";

export type PolicyRuleSignals = {
  anyTokens?: string[];
  allTokens?: string[];
  patterns?: RegExp[];
  allPatterns?: RegExp[];
  nonePatterns?: RegExp[];
};

export type PolicyRuleAction = {
  workload?: SharedBrainWorkload;
  widget?: "table" | "chart" | "document" | "math";
  grounding?: "web" | "memory" | "none";
};

export type PolicyRule = {
  id: string;
  phase: "pre_planning" | "post_planning";
  signals: PolicyRuleSignals;
  action: PolicyRuleAction;
  priority: number;
  examples: string[];
};

export type PolicyRuleMatch = {
  rule: PolicyRule;
  action: PolicyRuleAction;
};

const DOC_NOUN = String.raw`(?:rapor\p{L}{0,8}|makale\p{L}{0,8}|belge\p{L}{0,8}|d[öo]k[üu]man\p{L}{0,8}|deneme\p{L}{0,8}|kompozisyon\p{L}{0,8}|dilek[çc]e\p{L}{0,8}|mektup\p{L}{0,8}|essay|article|report|bülten|bulten|kılavuz|kilavuz|sunum metni|köşe yaz[ıi]s[ıi]|kose yaz[ıi]s[ıi]|blog yaz[ıi]s[ıi]|blog post|taslak)`;
const DOC_VERB = String.raw`(?:yaz|haz[ıi]rla|olu[şs]tur|[üu]ret|d[üu]zenle|d[öo]n[üu][şs]t[üu]r|[çc]evir|kaleme al|derle|haz[ıi]rlay)`;

const TABLE_NOUN_PATTERN = /(?<!\p{L})(tablo|table|matris|matrix|csv|xlsx|excel|spreadsheet)(?!\p{L})/iu;
const TABLE_ACTION_PATTERN = /(?<!\p{L})(ver|göster|goster|sun|hazırla|hazirla|oluştur|olustur|üret|uret|çıkar|cikar|dışa aktar|disa aktar|export|düzenle|duzenle|çevir|cevir|karşılaştır|karsilastir|compare|listele|list|sırala|sirala|özetle|ozetle)(?!\p{L})/iu;
const NEGATED_TABLE_REQUEST_PATTERNS = [
  /\b(tablo|table|matris|matrix|csv|xlsx|excel|spreadsheet)\b.{0,48}\b(istemiyorum|isteme|olmas[ıi]n|kullanma|ekleme|yapma|kurma|çıkarma|cikarma|no|without)\b/iu,
  /\b(istemiyorum|isteme|olmas[ıi]n|kullanma|ekleme|yapma|kurma|çıkarma|cikarma|no|without)\b.{0,48}\b(tablo|table|matris|matrix|csv|xlsx|excel|spreadsheet)\b/iu,
];

export const policyRules: PolicyRule[] = [
  {
    id: "workload.table_generate",
    phase: "pre_planning",
    priority: 90,
    signals: {
      nonePatterns: NEGATED_TABLE_REQUEST_PATTERNS,
      patterns: [/\b(tablo olarak|table format|table olarak|tablo halinde|tablo biçiminde|tablo biciminde)\b/i],
      allPatterns: [TABLE_NOUN_PATTERN, TABLE_ACTION_PATTERN],
    },
    action: {
      workload: "table_generate",
      widget: "table",
    },
    examples: [
      "Ülkeleri nüfuslarıyla tablo olarak ver",
      "Bunu excel tablosu halinde hazirla",
      "Ürünleri csv olarak çıkar",
      "iPhone ve Pixel farklarını table format ver",
    ],
  },
  {
    id: "workload.document_generate",
    phase: "pre_planning",
    priority: 80,
    signals: {
      patterns: [
        new RegExp(`(?<!\\p{L})${DOC_NOUN}(?!\\p{L})[\\s\\S]{0,48}?(?<!\\p{L})${DOC_VERB}`, "iu"),
        new RegExp(`(?<!\\p{L})${DOC_VERB}(?!\\p{L})[\\s\\S]{0,48}?(?<!\\p{L})${DOC_NOUN}(?!\\p{L})`, "iu"),
        /\b(pdf|docx|word|belge|doküman|dokuman|rapor)\b.*\b(hazırla|hazirla|oluştur|olustur|üret|uret|tasarla|düzenle|duzenle|dönüştür|donustur|çevir|cevir|yap)\b/i,
        /\b(hazırla|hazirla|oluştur|olustur|üret|uret|tasarla|düzenle|duzenle|dönüştür|donustur|çevir|cevir|yap)\b.*\b(pdf|docx|word|belge|doküman|dokuman|rapor)\b/i,
        /\b(tasarım|tasarim|layout|şablon|sablon)\b.*\b(pdf|docx|word|belge|doküman|dokuman|rapor|sunum metni)\b/i,
        /\b(pdf olarak|word olarak|docx olarak)\b.*\b(ver|hazırla|hazirla|oluştur|olustur|üret|uret|tasarla|düzenle|duzenle)\b/i,
        /(?<!\p{L})pdf(?:['’]?[iy])?(?!\p{L})(?=[\s\S]{0,160}(?<!\p{L})(?:özetle|ozetle)(?!\p{L}))(?=[\s\S]{0,160}(?<!\p{L})(?:profesyonel\p{L}*|düzenli|duzenli|resmi)(?!\p{L}))[\s\S]{0,160}(?<!\p{L})(?:yaz|düzenle|duzenle)(?!\p{L})/iu,
      ],
    },
    action: {
      workload: "document_generate",
      widget: "document",
    },
    examples: [
      "Yapay zeka etiği hakkında kısa bir rapor hazırla",
      "Kuantum dolanıklığı için blog yazısı oluştur",
      "Bu konu için docx olarak düzenli bir belge hazırla",
      "Startup fikrim için yatırımcı raporu yaz",
    ],
  },
  {
    id: "workload.visual_or_math_balanced",
    phase: "post_planning",
    priority: 70,
    signals: {
      nonePatterns: [
        /\b(grafik|chart|graph|plot|diagram|diyagram)\b.{0,40}\b(istemiyorum|isteme|olmas[ıi]n|kullanma|ekleme|no|without)\b/iu,
        /\b(istemiyorum|isteme|olmas[ıi]n|kullanma|ekleme|no|without)\b.{0,40}\b(grafik|chart|graph|plot|diagram|diyagram)\b/iu,
      ],
      patterns: [
        /(?<!\p{L})(grafik|grafiği|grafiğini|grafigi|grafigini|chart|graph|plot|çiz|ciz|çizim|cizim|visualize|visualise|görselleştir|gorsellestir)(?!\p{L})/iu,
        /(?<!\p{L})(svg|vektör|vektor|vector|diagram|diyagram|geometrik çizim|geometrik cizim)(?!\p{L})/iu,
        /(?<!\p{L})(fonksiyon grafiği|fonksiyon grafigi|function graph|function plot|scatter|line chart|bar chart|pie chart)(?!\p{L})/iu,
        /(?<!\p{L})(3d|3 boyutlu|üç boyutlu|uc boyutlu|surface|mesh|yüzey grafiği|yuzey grafigi)(?!\p{L})/iu,
        /\b(3d|3 boyutlu|üç boyutlu|uc boyutlu)\b.{0,80}\b(yüzey grafiği|yuzey grafigi|surface plot|surface|mesh|grafiğini çiz|grafigini ciz|grafik|plot)\b/i,
        /\b(4d|4 boyutlu|dört boyutlu|dort boyutlu)\b.{0,80}\b(grafik|plot|surface|yüzey|yuzey)\b/i,
        /\bz\s*=\s*f\s*\(\s*x\s*,\s*y\s*\)\b.{0,80}\b(çiz|ciz|grafik|plot|surface)\b/i,
        /\bz\s*=\s*[^,\n]+?\b.{0,80}\b(3d|3 boyutlu|üç boyutlu|uc boyutlu|4d|4 boyutlu|surface plot|yüzey grafiği|yuzey grafigi)\b/i,
        /\b(surface plot|math surface|3d surface|4d surface)\b/i,
        /(?<!\p{L})(matematik|math|denklem|equation|integral|türev|turev|limit|ispat|proof|çöz|coz|solve)(?!\p{L})/iu,
        /(?<!\p{L})(latex|tex|ka?tex|formula|formül|formul)(?!\p{L})/iu,
        /(?<!\p{L})(polinom|polynomial|fonksiyon|function|matris|matrix|vekt[öo]r(?:\s+alan[ıi])?|dizi|series?|serisi|seri|kesir|fraction|kompleks\s+say[ıi]|karma[şs][ıi]k\s+say[ıi]|complex\s+number|kalk[üu]l[üu]s|calculus|cebir|algebra|geometri|geometry|trigonometri|trigonometry|logaritma|logarithm)(?!\p{L})/iu,
      ],
    },
    action: {
      workload: "mobile_chat_balanced",
      widget: "chart",
    },
    examples: [
      "f(x)=x^2 fonksiyonunun grafiğini çiz",
      "Bu denklemi LaTeX ile adım adım çöz",
      "z = x^3 + y^2 fonksiyonunun 3 boyutlu yüzey grafiğini çiz",
      "Bana bir polinom yaz",
    ],
  },
];

function normalizeText(value: string): string {
  return String(value ?? "")
    .trim()
    .toLocaleLowerCase("tr-TR")
    .replace(/\s+/g, " ");
}

function tokenizePolicyText(value: string): Set<string> {
  const normalized = normalizeText(value);
  const tokens = normalized.match(/[\p{L}\p{N}_+-]+/gu) ?? [];
  return new Set(tokens);
}

function ruleMatches(rule: PolicyRule, text: string): boolean {
  const normalized = normalizeText(text);
  const tokens = tokenizePolicyText(normalized);
  const { anyTokens, allTokens, patterns, allPatterns, nonePatterns } = rule.signals;

  if (nonePatterns?.some((pattern) => pattern.test(normalized))) {
    return false;
  }

  if (patterns?.some((pattern) => pattern.test(normalized))) {
    return true;
  }
  if (allPatterns?.length && allPatterns.every((pattern) => pattern.test(normalized))) {
    return true;
  }
  if (allTokens?.length && allTokens.every((token) => tokens.has(normalizeText(token)))) {
    return true;
  }
  if (anyTokens?.length && anyTokens.some((token) => tokens.has(normalizeText(token)))) {
    return true;
  }
  return false;
}

export function evaluatePolicyRules(
  text: string,
  rules: PolicyRule[] = policyRules,
  options: { phase?: PolicyRule["phase"] } = {},
): PolicyRuleMatch[] {
  return rules
    .filter((rule) => !options.phase || rule.phase === options.phase)
    .filter((rule) => ruleMatches(rule, text))
    .sort((a, b) => b.priority - a.priority || a.id.localeCompare(b.id))
    .map((rule) => ({
      rule,
      action: rule.action,
    }));
}

export function selectPolicyWorkload(
  text: string,
  options: { phase?: PolicyRule["phase"] } = {},
): SharedBrainWorkload | null {
  return evaluatePolicyRules(text, policyRules, options).find((match) => match.action.workload)?.action.workload ?? null;
}
