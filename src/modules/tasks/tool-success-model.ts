import type { FastifyInstance } from "fastify";
import { and, eq, gte, sql } from "drizzle-orm";
import { learningEvents } from "../../db/schema.js";

/**
 * P(success | task, tool, context) — deneyimden araç başarısı tahmini.
 *
 * NEDEN DETERMİNİSTİK
 * -------------------
 * Kullanıcının istediği "küçük yardımcı model"in ilk hâli bir sinir ağı değil,
 * sayımdır. Sebep: bugün elde 60 görev var. Az veriyle model eğitmek, veriyi
 * ezberleyip kendinden emin yanlışlar üretmektir — bu projede "tahmin sert
 * sözleşmeye dönüşüyor" hata sınıfı defalarca tekrarlandı.
 *
 * Sayım şeffaftır, açıklanabilir ve veri arttıkça aynı arayüzle daha iyi bir
 * tahminciyle değiştirilebilir.
 *
 * BAŞARI TANIMI
 * -------------
 * Aracın "ok" demesi değil, GÖREVİN kullanıcı açısından karşılanması.
 * Defterdeki `confidence` alanı bunu taşır (0 / 50 / 75 / 100) — bkz.
 * `scoreStepOutcome`. Araç dosyayı yazdı ama içine konu tarifi yazıldıysa o
 * çağrı başarılı sayılmaz.
 *
 * BELİRSİZLİK GİZLENMEZ
 * ---------------------
 * Gözlem sayısı eşiğin altındaysa `null` döner. "Veri yok" ile "%50 ihtimal"
 * ASLA aynı şey değildir; çağıran bunu ayırt etmek zorundadır.
 */

/** Bu sayının altında tahmin ÜRETİLMEZ. */
export const TOOL_SUCCESS_MIN_OBSERVATIONS = 5;

/** Laplace düzeltmesi: tek bir başarısızlık aracı sıfırlamasın. */
const PRIOR_SUCCESS = 1;
const PRIOR_TOTAL = 2;

export type ToolSuccessEstimate = {
  tool: string;
  probability: number;
  observations: number;
  meanScore: number;
  /** Bağlam daraldıkça güven artar: tam eşleşme > yalnız araç. */
  basis: "tool_intent_device" | "tool_intent" | "tool";
};

type Row = { total: number; scoreSum: number };

async function aggregate(
  app: FastifyInstance,
  filters: ReturnType<typeof and>[],
): Promise<Row> {
  const rows = await app.db
    .select({
      total: sql<number>`count(*)::int`,
      scoreSum: sql<number>`coalesce(sum(${learningEvents.confidence}), 0)::int`,
    })
    .from(learningEvents)
    .where(and(...filters));
  const row = rows[0];
  return { total: Number(row?.total ?? 0), scoreSum: Number(row?.scoreSum ?? 0) };
}

function toEstimate(
  tool: string,
  row: Row,
  basis: ToolSuccessEstimate["basis"],
): ToolSuccessEstimate | null {
  if (row.total < TOOL_SUCCESS_MIN_OBSERVATIONS) return null;
  const meanScore = row.scoreSum / row.total / 100;
  const probability =
    (meanScore * row.total + PRIOR_SUCCESS) / (row.total + PRIOR_TOTAL);
  return {
    tool,
    probability: Number(Math.max(0, Math.min(1, probability)).toFixed(4)),
    observations: row.total,
    meanScore: Number(meanScore.toFixed(4)),
    basis,
  };
}

/**
 * Bağlamı kademeli gevşeterek tahmin ara.
 *
 * Önce tam bağlam (araç + görev türü + cihaz), sonra araç + görev türü, sonra
 * yalnız araç. İlk yeterli gözleme sahip olan kazanır; hangi temelde
 * konuşulduğu `basis` ile açıkça bildirilir.
 */
export async function estimateToolSuccess(
  app: FastifyInstance,
  input: {
    userId: string;
    tool: string;
    intentKind?: string | null;
    device?: string | null;
    /** Ne kadar geriye bakılsın (gün). Eski deneyim bugünü bağlamaz. */
    windowDays?: number;
  },
): Promise<ToolSuccessEstimate | null> {
  const tool = String(input.tool ?? "").trim();
  if (!tool || !input.userId) return null;
  const since = new Date(
    Date.now() - Math.max(1, input.windowDays ?? 90) * 24 * 60 * 60 * 1000,
  );
  const base = [
    eq(learningEvents.userId, input.userId),
    eq(learningEvents.type, "tool_outcome"),
    eq(learningEvents.key, tool),
    gte(learningEvents.createdAt, since),
    // Yalnız görev verdict'iyle bağlanmış tool_outcome kayıtları öğrenmeye
    // girer. Ham "tool ok" olayı, kullanıcı sonucu karşılanmadan başarı
    // kanıtı değildir.
    sql`${learningEvents.metadata}->>'taskVerdict' is not null`,
  ];

  try {
    if (input.intentKind && input.device) {
      const row = await aggregate(app, [
        ...base,
        sql`${learningEvents.metadata}->>'intentKind' = ${input.intentKind}`,
        sql`${learningEvents.metadata}->>'device' = ${input.device}`,
      ] as never);
      const estimate = toEstimate(tool, row, "tool_intent_device");
      if (estimate) return estimate;
    }
    if (input.intentKind) {
      const row = await aggregate(app, [
        ...base,
        sql`${learningEvents.metadata}->>'intentKind' = ${input.intentKind}`,
      ] as never);
      const estimate = toEstimate(tool, row, "tool_intent");
      if (estimate) return estimate;
    }
    const row = await aggregate(app, base as never);
    return toEstimate(tool, row, "tool");
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "tool success estimate failed",
    );
    return null;
  }
}

/**
 * Birden çok aday araç için tahminleri getir — planlayıcıya KANIT olarak.
 *
 * Sıralamayı DEĞİŞTİRMEZ. Bu bir gözlemdir; kararın nasıl kullanacağı ayrıca
 * ve ölçülerek belirlenir.
 */
export async function estimateToolSuccessBatch(
  app: FastifyInstance,
  input: {
    userId: string;
    tools: string[];
    intentKind?: string | null;
    device?: string | null;
  },
): Promise<ToolSuccessEstimate[]> {
  const unique = [...new Set(input.tools.map((tool) => tool.trim()).filter(Boolean))];
  const estimates = await Promise.all(
    unique.map((tool) =>
      estimateToolSuccess(app, {
        userId: input.userId,
        tool,
        intentKind: input.intentKind,
        device: input.device,
      }),
    ),
  );
  return estimates.filter((estimate): estimate is ToolSuccessEstimate => estimate !== null);
}
