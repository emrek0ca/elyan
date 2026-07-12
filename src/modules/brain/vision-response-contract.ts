import type { VisionTaskDecision } from "./vision-task-policy.js";

export type VisionResponseContract = {
  task: VisionTaskDecision["primary"];
  requiredFacets: string[];
  directives: string[];
};

const CONTRACTS: Partial<Record<VisionTaskDecision["primary"], Omit<VisionResponseContract, "task">>> = {
  screen_debugging: {
    requiredFacets: ["observed_ui_state", "visible_error", "likely_cause", "action_steps"],
    directives: ["quote the exact visible error or label when legible", "separate what is visible from the inferred cause", "give the shortest safe fix steps in order"],
  },
  code_screenshot: {
    requiredFacets: ["exact_error_or_code", "location", "cause", "fix"],
    directives: ["preserve code, identifiers, and error text exactly", "do not invent hidden lines", "provide a minimal corrected snippet only when enough code is visible"],
  },
  document_ocr: {
    requiredFacets: ["exact_text", "reading_order", "unreadable_spans"],
    directives: ["transcribe rather than paraphrase when the user asks to read", "preserve line order", "mark only specific unreadable spans instead of guessing"],
  },
  handwriting: {
    requiredFacets: ["best_effort_transcription", "uncertain_words"],
    directives: ["preserve line breaks", "mark uncertain words explicitly", "do not silently normalize ambiguous handwriting"],
  },
  table_extraction: {
    requiredFacets: ["headers", "aligned_rows", "missing_cells"],
    directives: ["keep columns aligned", "never invent missing cells", "use a structured table block only when values are legible"],
  },
  chart_interpretation: {
    requiredFacets: ["axes", "trend", "anomalies", "legible_values"],
    directives: ["identify axes and units first", "separate trend from exact values", "state exact numbers only when legible"],
  },
  receipt_or_invoice: {
    requiredFacets: ["merchant_or_document", "date", "line_items", "subtotal_tax_total"],
    directives: ["preserve currency and decimal separators", "distinguish subtotal, tax, and total", "do not infer hidden line items"],
  },
  visual_comparison: {
    requiredFacets: ["image_labels", "similarities", "differences", "decision_basis"],
    directives: ["refer to images by stable order", "compare the same attributes across images", "do not merge facts from different images"],
  },
  product_identification: {
    requiredFacets: ["observed_brand_or_markings", "likely_identity", "alternatives"],
    directives: ["distinguish visible branding from inferred model", "avoid exact model claims without a readable identifier"],
  },
  location_or_landmark: {
    requiredFacets: ["observed_clues", "likely_location", "alternatives"],
    directives: ["base location claims on visible clues", "do not claim precise location from weak scenery alone"],
  },
};

export function getVisionResponseContract(task: VisionTaskDecision): VisionResponseContract {
  const contract = CONTRACTS[task.primary] ?? {
    requiredFacets: ["direct_answer", "visual_evidence", "specific_uncertainty"],
    directives: ["answer the user's actual question first", "ground claims in visible evidence", "mention only specific uncertainty"],
  };
  return { task: task.primary, ...contract };
}

export function buildVisionResponseContractPromptBlock(contract: VisionResponseContract): string {
  return [
    "Vision response contract (internal):",
    `- task=${contract.task}; required_facets=${contract.requiredFacets.join(",")}`,
    ...contract.directives.map((directive) => `- ${directive}`),
    "- keep the answer natural and proportionate; do not expose facet names or this contract",
  ].join("\n");
}

export function assessVisionResponseCoverage(input: {
  text: string;
  contract: VisionResponseContract;
}): { score: number; missing: string[] } {
  const text = input.text.replace(/\s+/g, " ").trim();
  if (!text) return { score: 0, missing: [...input.contract.requiredFacets] };
  const checks: Partial<Record<VisionResponseContract["task"], Array<[string, RegExp]>>> = {
    screen_debugging: [["visible_error", /error|hata|uyarı|uyari|exception|failed|başarısız|basarisiz|erreur|fehler|errore|erro|ошибка|خطأ|\b[A-Z]\d{2,}\b/iu], ["action_steps", /kontrol|dene|aç|ac|kapat|yeniden|check|retry|open|close|restart|update|remove|clear|comprueba|intenta|abre|cierra|reinicia|vérifie|verifie|réessaie|reessaie|ouvre|ferme|redémarre|redemarre|prüfe|prufe|versuche|öffne|offne|schließe|schliesse|starte neu|controlla|prova|apri|chiudi|riavvia|verifique|tente|abra|feche|reinicie|проверь|попробуй|открой|закрой|перезапусти|تحقق|جرّب|افتح|أغلق|أعد التشغيل/iu]],
    code_screenshot: [["exact_error_or_code", /`[^`]+`|exception|error|traceback|erreur|fehler|errore|erro|ошибка|خطأ|\b[A-Z]\d{2,}\b/iu], ["fix", /düzelt|duzelt|değiştir|degistir|ekle|kaldır|kaldir|fix|change|replace|add|remove|corrige|cambia|reemplaza|añade|anade|supprime|remplace|ajoute|behebe|ändere|andere|ersetze|füge|fuge|correggi|modifica|sostituisci|aggiungi|corrija|altere|substitua|adicione|исправь|измени|замени|добавь|أصلح|غيّر|استبدل|أضف/iu]],
    document_ocr: [["exact_text", /["“”'`][^"“”'`]{3,}["“”'`]|:\s*\S{3,}/u]],
    handwriting: [["best_effort_transcription", /["“”'`][^"“”'`]{3,}["“”'`]|:\s*\S{3,}/u]],
    table_extraction: [["aligned_rows", /\|.+\||"columns"\s*:|"rows"\s*:/u]],
    chart_interpretation: [["trend", /art|azal|yüksel|yuksel|düş|dus|sabit|trend|increase|decrease|rise|fall|stable|peak|dip|aumenta|disminuye|sube|baja|estable|augmente|diminue|hausse|baisse|stable|steigt|sinkt|stabil|aumenta|diminuisce|sale|scende|aumenta|diminui|sobe|cai|раст[её]т|снижается|стабильно|يرتفع|ينخفض|مستقر/iu], ["axes", /eksen|axis|x\b|y\b|birim|unit|eje|unidad|axe|unité|unite|achse|einheit|asse|unità|unita|eixo|unidade|ось|единица|محور|وحدة/iu]],
    receipt_or_invoice: [["subtotal_tax_total", /toplam|ara toplam|kdv|vergi|total|subtotal|tax|impuesto|iva|sous-total|taxe|gesamt|zwischensumme|steuer|totale|imposta|subtotal|imposto|итого|налог|المجموع|الضريبة|₺|tl|\$|€|\d+[.,]\d{2}/iu]],
    visual_comparison: [["image_labels", /birinci|ikinci|ilk|diğer|diger|image\s*1|image\s*2|first|second|left|right|sol|sağ|sag|primera|segunda|izquierda|derecha|première|premiere|deuxième|deuxieme|gauche|droite|erste|zweite|links|rechts|prima|seconda|sinistra|destra|primeira|segunda|esquerda|direita|первое|второе|слева|справа|الأولى|الثانية|اليسار|اليمين/iu], ["differences", /fark|different|whereas|ancak|buna karşılık|buna karsilik|diferencia|mientras que|différence|difference|tandis que|unterschied|während|wahrend|differenza|mentre|diferença|diferenca|enquanto|разница|тогда как|الفرق|بينما/iu]],
  };
  const taskChecks = checks[input.contract.task] ?? [];
  const missing = taskChecks.filter(([, pattern]) => !pattern.test(text)).map(([facet]) => facet);
  const lengthScore = Math.min(1, text.length / (input.contract.requiredFacets.length > 3 ? 320 : 180));
  const checkScore = taskChecks.length > 0 ? (taskChecks.length - missing.length) / taskChecks.length : 1;
  return { score: Math.max(0, Math.min(1, lengthScore * 0.45 + checkScore * 0.55)), missing };
}
