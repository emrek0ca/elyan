import type { DesktopWorkOrderStep } from "./desktop-work-order.js";

/**
 * EN HIZLI YOL — GEREKSİZ ARAŞTIRMA/ANALİZ ADIMINI DÜŞÜR.
 *
 * Kullanıcının açık isteği: "model kendi bildiği ve internet araştırması
 * yapabilen modellerle çalışabilmeli. en hızlı ve en doğru yolu kullanmalıyız."
 *
 * Prompt direktifi tek başına yetmiyor. Ölçüm (canlı Groq, gerçek planlama
 * promptu, "zürafalar hakkında rapor"):
 *   direktif yokken : 4/4 → web_research → text_analyze → document_write
 *   direktif varken : 2/4 tek adım, 2/4 hâlâ text_analyze ekliyor
 *
 * `text_analyze` MODEL ÇAĞIRMAZ — metni mekanik olarak dilimler
 * (`actions/text_analyze.py`). Zaten kalıcı bilgiyle yazılacak bir raporda
 * araya girmesi çıktıyı rapor olmaktan çıkarıp madde listesine çevirir.
 *
 * TEHLİKE VE KORUMA: kullanıcı KENDİ verisini işletiyorsa ("bu dosyayı özetle
 * ve belge yap") analiz adımı meşrudur ve düşürülemez. Bu yüzden budama yalnız
 * planda YEREL/KULLANICI verisi okuyan hiçbir adım yokken çalışır.
 */
const RESEARCH_CAPABILITIES = new Set(["web_research", "text_analyze"]);

/** Kullanıcının kendi verisine dokunan her şey — bunlar varsa budama YOK. */
const LOCAL_SOURCE_CAPABILITIES = new Set([
  "document_read",
  "file_read",
  "file_search",
  "directory_tree",
  "image_read",
  "ocr_read",
  "data_analyze",
  "analyze_screen",
  "desktop_operator.observe_screen",
  "observe_screen",
  "retrieve_context",
  "clipboard_read",
  "browser_session.extract",
  "get_calendar_events",
  "get_reminders",
  "math_solve",
]);

const STEP_REFERENCE_RE = /\{\{\s*steps\.([A-Za-z0-9_-]+)[^}]*\}\}/g;

function stripReferences(value: unknown, removedIds: Set<string>): unknown {
  if (typeof value === "string") {
    return value
      .replace(STEP_REFERENCE_RE, (match, id: string) =>
        removedIds.has(id) ? "" : match,
      )
      .replace(/\s{2,}/g, " ")
      .trim();
  }
  if (Array.isArray(value)) return value.map((item) => stripReferences(item, removedIds));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, inner]) => [
        key,
        stripReferences(inner, removedIds),
      ]),
    );
  }
  return value;
}

export function pruneUnneededResearchSteps(input: {
  steps: DesktopWorkOrderStep[];
  recency: "stable_knowledge" | "current_facts" | null;
}): { steps: DesktopWorkOrderStep[]; pruned: string[] } {
  const { steps, recency } = input;
  if (recency !== "stable_knowledge") return { steps, pruned: [] };
  if (steps.length < 2) return { steps, pruned: [] };
  // Kullanıcının kendi verisi işin içindeyse analiz meşrudur.
  if (steps.some((step) => LOCAL_SOURCE_CAPABILITIES.has(step.capability))) {
    return { steps, pruned: [] };
  }
  const removable = steps.filter((step) => RESEARCH_CAPABILITIES.has(step.capability));
  if (removable.length === 0) return { steps, pruned: [] };
  const survivors = steps.filter((step) => !RESEARCH_CAPABILITIES.has(step.capability));
  // Budamadan sonra iş yapan adım kalmıyorsa dokunma: eksik plan, yavaş plandan kötüdür.
  if (survivors.length === 0) return { steps, pruned: [] };

  const removedIds = new Set(removable.map((step) => step.id));
  const cleaned = survivors.map((step) => ({
    ...step,
    args: stripReferences(step.args, removedIds) as Record<string, unknown>,
    dependsOn: (step.dependsOn ?? []).filter((id) => !removedIds.has(id)),
  }));
  return { steps: cleaned, pruned: [...removedIds] };
}
