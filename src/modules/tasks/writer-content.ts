import type { FastifyInstance } from "fastify";
import { generateGovernedSharedBrainReply } from "../brain/inference.js";
import {
  classifyKnowledgeRecency,
  needsLiveResearch,
} from "../../core/understanding/knowledge-recency.js";
import type { DesktopWorkOrder, DesktopWorkOrderStep } from "./desktop-work-order.js";

/**
 * YAZICI İÇERİĞİNİ SUNUCU ÜRETİR.
 *
 * Masaüstündeki yazıcılar (document/canvas/presentation_write) içerik ÜRETMEZ;
 * kendilerine verilen metni dosyaya aynen yazar (bkz. actions/document_write.py
 * `_resolve_source_text`). Bunu artık kayıtlar da böyle ilan ediyor.
 *
 * Peki içeriği kim yazacak? Planlayıcı yazamaz:
 *
 *   Canlı ölçüm (görev fd3acf73, "kediler hakkında rapor"):
 *     planlama promptu 9.834 token → cevap 309 token, onarımda 100 token.
 *   İki sayfalık Türkçe metin ~800–1.200 token. Rapor plan JSON'una SIĞMIYOR.
 *   Nitekim ilk deneme JSON yerine Markdown döndü ve plan çöpe gitti; onarım
 *   tek adıma çöküp `prompt` alanına 21 kelimelik KONU TARİFİNİ koydu. Belgede
 *   iki paragraf çıktı: başlık + tarif.
 *
 * Bu yüzden içerik ayrı bir çağrıyla, kendi bütçesiyle üretilir. Planlayıcı
 * yapıyı kurar (hangi adım, hangi dosya, hangi biçim), bu katman gövdeyi yazar.
 *
 * KAPSAM DAR: yalnız düzyazı yazıcıları. `spreadsheet_write` yapılandırılmış
 * satır/sütun ister; oraya düzyazı üretmek yanlış olur.
 */
const PROSE_WRITER_CAPABILITIES = new Set([
  "document_write",
  "canvas_write",
  "presentation_write",
]);

/** Masaüstünün gövde metni olarak okuduğu alanlar. */
const CONTENT_ARG_KEYS = [
  "prompt",
  "content",
  "body",
  "text",
  "markdown",
  "sourceContext",
] as const;

/**
 * Bir yazıcı argümanının "gövde" sayılabilmesi için gereken en az sözcük.
 *
 * TABAN, İNCE AYAR DEĞİL. İki sayfalık rapor 500+ sözcük; kısa bir dilekçe bile
 * 150'yi geçer. 120 sözcüğün altındaki bir metin belge GÖVDESİ olamaz — olsa
 * olsa konunun tarifidir. Canlı arızada bu değer 21'di.
 *
 * Gerçek trafikle kalibre edilebilsin diye her iki dal da loglanır.
 */
export const WRITER_CONTENT_MIN_WORDS = 120;

const STEP_REFERENCE_RE = /\{\{\s*steps\./;

function wordCount(value: unknown): number {
  if (typeof value !== "string") return 0;
  const trimmed = value.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

function readArgs(step: DesktopWorkOrderStep): Record<string, unknown> {
  return step.args && typeof step.args === "object" ? step.args : {};
}

export type WriterContentGap = {
  stepId: string;
  capability: string;
  /** Üretilen metnin yazılacağı argüman. */
  argKey: string;
  words: number;
};

/**
 * Bu adım gövdesiz mi kalmış?
 *
 * `null` dönerse dokunulmaz. Üç durumda dokunmuyoruz:
 *   - düzyazı yazıcısı değil,
 *   - içerik başka bir adımdan geliyor ({{steps.<id>.output}}) — plan zaten
 *     doğru kurulmuş, üzerine yazmak onu bozar,
 *   - gövde zaten yeterince uzun.
 */
export function findWriterContentGap(
  step: DesktopWorkOrderStep,
): WriterContentGap | null {
  if (!PROSE_WRITER_CAPABILITIES.has(step.capability)) return null;
  const args = readArgs(step);

  // Adım referansı varsa içerik akıştan gelecek; plan doğru kurulmuş.
  for (const value of Object.values(args)) {
    if (typeof value === "string" && STEP_REFERENCE_RE.test(value)) return null;
    if (Array.isArray(value) && JSON.stringify(value).match(STEP_REFERENCE_RE)) {
      return null;
    }
  }
  // Yapılandırılmış gövde (sections/blocks/slides) varsa planlayıcı içeriği
  // zaten kurmuş demektir.
  for (const key of ["sections", "blocks", "slides"]) {
    const value = args[key];
    if (Array.isArray(value) && value.length > 0) return null;
  }

  let words = 0;
  let argKey = "prompt";
  let bestWords = -1;
  for (const key of CONTENT_ARG_KEYS) {
    const count = wordCount(args[key]);
    words += count;
    if (count > bestWords) {
      bestWords = count;
      if (count > 0) argKey = key;
    }
  }
  if (words >= WRITER_CONTENT_MIN_WORDS) return null;
  return { stepId: step.id, capability: step.capability, argKey, words };
}

/**
 * DOSYA ADI CÜMLE OLAMAZ.
 *
 * Canlı çıktı (2026-08-22): `masaustune-zurafalar-hakkinda-bir-rapor-hazirla-ve-kaydet.docx`
 * Masaüstü, `title` yoksa dosya adını `prompt`/hedef metninden türetiyor
 * (`ensure_allowed_output_path(..., hint=title or prompt or ...)`), o da
 * kullanıcının cümlesinin tamamı oluyordu.
 *
 * Üretilen metnin İLK SATIRI zaten belge başlığıdır (prompt bölüm başlıkları
 * istiyor). Cümle gibi görünüyorsa (uzun, nokta ile biten) başlık sayılmaz.
 */
function deriveTitle(text: string): string | null {
  const firstLine = text
    .split("\n")
    .map((line) => line.trim())
    .find((line) => line.length > 0);
  if (!firstLine) return null;
  const cleaned = firstLine.replace(/^#+\s*/, "").replace(/[.:;]+$/, "").trim();
  if (cleaned.length < 3 || cleaned.length > 80) return null;
  if (cleaned.split(/\s+/).length > 8) return null;
  return cleaned;
}

function buildContentPrompt(input: {
  workOrder: DesktopWorkOrder;
  step: DesktopWorkOrderStep;
  gap: WriterContentGap;
  liveResearch: boolean;
}): string {
  const args = readArgs(input.step);
  const brief = CONTENT_ARG_KEYS.map((key) => args[key])
    .filter((value): value is string => typeof value === "string" && value.trim().length > 0)
    .join("\n");
  const title = typeof args.title === "string" ? args.title.trim() : "";
  const language = input.workOrder.goal?.language === "en" ? "English" : "Türkçe";
  const kind =
    input.gap.capability === "presentation_write"
      ? "sunum anahattı (slayt başlıkları ve madde madde içerik)"
      : "belge metni";

  return [
    `Kullanıcının isteği: ${input.workOrder.goal?.summary ?? ""}`.trim(),
    title ? `Belge başlığı: ${title}` : "",
    brief ? `İstenen kapsam: ${brief}` : "",
    "",
    `Bu isteğin karşılığı olan ${kind} yaz. Dil: ${language}.`,
    "",
    "KURALLAR:",
    "- Sadece metnin KENDİSİNİ yaz. Ne yapacağını anlatma, plan sunma, önsöz/sonsöz ekleme.",
    "- Bölüm başlıkları kullan; giriş, ana bölümler ve sonuç barındır.",
    "- Uydurma sayı, tarih, isim veya alıntı KULLANMA.",
    ...(input.liveResearch
      ? [
          "- Güncel veriyi ARAŞTIR ve bulduğun somut değerleri yaz; kaynağın adını doğal cümle içinde belirt.",
          "- Bir değeri bulamazsan uydurma; o noktada bilginin alınamadığını açıkça yaz.",
        ]
      : [
          "- Bildiklerinle yaz; bu konu kalıcı ve genel bilgiyle karşılanır.",
          "- Emin olmadığın güncel/değişken bilgiyi (fiyat, güncel istatistik, son gelişme) yazma.",
        ]),
    "- Markdown başlık işareti (#) kullanma; başlıkları düz satır olarak yaz.",
  ]
    .filter(Boolean)
    .join("\n");
}

/**
 * Gövdesi eksik yazıcı adımlarını doldurur.
 *
 * FAIL-OPEN: üretim başarısız olursa plan OLDUĞU GİBİ döner. Bu katman bir
 * iyileştirmedir; görevi durdurmak, eksik içerikle devam etmekten kötüdür.
 */
export async function fillWriterContent(input: {
  app: FastifyInstance;
  workOrder: DesktopWorkOrder;
  steps: DesktopWorkOrderStep[];
  userId: string;
  taskId: string;
}): Promise<{ steps: DesktopWorkOrderStep[]; filled: number }> {
  const gaps = input.steps
    .map((step) => ({ step, gap: findWriterContentGap(step) }))
    .filter((entry): entry is { step: DesktopWorkOrderStep; gap: WriterContentGap } =>
      entry.gap !== null,
    );
  if (gaps.length === 0) return { steps: input.steps, filled: 0 };

  // EN HIZLI VE EN DOĞRU YOL — hangisi olduğu ÖLÇÜLEREK seçilir.
  //
  // "Kediler hakkında rapor" modelin zaten bildiği bir konu; araştırma adımı
  // gereksiz yavaşlık ve kırılganlık. "2026 enflasyon rakamları" ise tersine
  // canlı kaynak ister; model kendi bilgisiyle yazarsa UYDURUR.
  //
  // Karar e5 prototip eşleştirmesiyle veriliyor (`npm run eval:knowledge-recency`,
  // korpus 100% → tutulan 94.4%, uydurma riski 0). Şüphede hızlı yol seçilir.
  const recency = await classifyKnowledgeRecency(
    input.workOrder.goal?.summary ?? "",
  ).catch(() => null);
  const liveResearch = needsLiveResearch(recency);

  const generated = new Map<string, { text: string; words: number }>();
  for (const { step, gap } of gaps) {
    try {
      const inference = await generateGovernedSharedBrainReply(input.app, {
        userId: input.userId,
        taskId: input.taskId,
        title: "Desktop writer content",
        prompt: buildContentPrompt({ workOrder: input.workOrder, step, gap, liveResearch }),
        // `public_research` Groq Compound'a uygun iş yükü: yerleşik web
        // aramasıyla canlı veriyi kendisi getirir. `document_generate` ise hızlı
        // yol — modelin kendi bilgisi, ek tur yok.
        workload: liveResearch ? "public_research" : "document_generate",
        route: "desktop_writer_content",
        meteringSurface: "task",
        maxCompletionTokensOverride: 3_000,
        timeoutMsOverride: liveResearch ? 45_000 : 30_000,
        skillToolAllowlist: [],
        internalEvaluation: {
          skipUsageValidation: true,
          skipReviewLogging: true,
          refinementPass: true,
        },
      });
      const text = inference.text.trim();
      if (inference.answerSource === "backend_gate" || !text) continue;
      generated.set(step.id, { text, words: wordCount(text) });
    } catch (error) {
      input.app.log.warn?.(
        {
          taskId: input.taskId,
          stepId: step.id,
          capability: step.capability,
          err: error instanceof Error ? error.message : String(error),
        },
        "writer content generation failed",
      );
    }
  }

  input.app.log.info?.(
    {
      taskId: input.taskId,
      liveResearch,
      recency: recency?.recency ?? null,
      recencyMargin: recency ? Number(recency.margin.toFixed(3)) : null,
      gaps: gaps.map((entry) => ({
        stepId: entry.gap.stepId,
        capability: entry.gap.capability,
        briefWords: entry.gap.words,
        generatedWords: generated.get(entry.gap.stepId)?.words ?? 0,
      })),
      threshold: WRITER_CONTENT_MIN_WORDS,
    },
    "writer content filled",
  );

  if (generated.size === 0) return { steps: input.steps, filled: 0 };
  const steps = input.steps.map((step) => {
    const produced = generated.get(step.id);
    if (!produced) return step;
    const gap = gaps.find((entry) => entry.gap.stepId === step.id)?.gap;
    if (!gap) return step;
    const args = readArgs(step);
    const existingTitle = typeof args.title === "string" ? args.title.trim() : "";
    const derivedTitle = existingTitle ? null : deriveTitle(produced.text);
    return {
      ...step,
      args: {
        ...args,
        [gap.argKey]: produced.text,
        ...(derivedTitle ? { title: derivedTitle } : {}),
      },
    };
  });
  return { steps, filled: generated.size };
}
