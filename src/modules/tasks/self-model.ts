import type { FastifyInstance } from "fastify";
import { and, desc, eq, gte, sql } from "drizzle-orm";
import { learningEvents } from "../../db/schema.js";

/**
 * SELF-MODEL — Elyan'ın kendisi hakkında BİLDİĞİ şeyler.
 *
 * "PDF konusunda iyiyim." · "Bu araç son üç görevde hata verdi."
 * "Bu görev türünde önce X aracı daha başarılı."
 *
 * TÜRETİLİR, YAZILMAZ. Her cümlenin arkasında sayılabilir gözlem vardır;
 * gözlem yoksa cümle de yoktur. Elle yazılmış bir "ben şunu iyi yaparım"
 * listesi, bu projede defalarca görülen "tahmin sert sözleşmeye dönüşüyor"
 * hatasının kendisidir.
 *
 * Kaynak: adım düzeyi deneyim defteri (`type='tool_outcome'`), başarı ölçütü
 * aracın "ok" demesi değil GÖREVİN kullanıcı açısından karşılanmasıdır.
 */

export const SELF_MODEL_MIN_OBSERVATIONS = 5;
/** Bir aracı "şu an sorunlu" saymak için gereken ardışık başarısızlık. */
export const SELF_MODEL_RECENT_FAILURE_STREAK = 3;

export type SelfModelClaim = {
  kind: "strength" | "weakness" | "broken_tool" | "preferred_tool";
  statement: string;
  evidence: { observations: number; successRate?: number; scope?: string };
};

function rate(scoreSum: number, total: number): number {
  return total > 0 ? scoreSum / total / 100 : 0;
}

export async function buildSelfModel(
  app: FastifyInstance,
  input: { userId: string; windowDays?: number },
): Promise<SelfModelClaim[]> {
  const since = new Date(
    Date.now() - Math.max(1, input.windowDays ?? 30) * 24 * 60 * 60 * 1000,
  );
  const claims: SelfModelClaim[] = [];

  try {
    // 1) GÖREV TÜRÜ BAŞARISI — "PDF konusunda iyiyim / zorlanıyorum."
    const byIntent = await app.db
      .select({
        intentKind: sql<string>`${learningEvents.metadata}->>'intentKind'`,
        total: sql<number>`count(*)::int`,
        scoreSum: sql<number>`coalesce(sum(${learningEvents.confidence}),0)::int`,
      })
      .from(learningEvents)
      .where(
        and(
          eq(learningEvents.userId, input.userId),
          eq(learningEvents.type, "tool_outcome"),
          gte(learningEvents.createdAt, since),
        ),
      )
      .groupBy(sql`${learningEvents.metadata}->>'intentKind'`);

    for (const row of byIntent) {
      const total = Number(row.total ?? 0);
      if (total < SELF_MODEL_MIN_OBSERVATIONS) continue;
      const kind = String(row.intentKind ?? "").trim() || "unknown";
      if (kind === "unknown") continue;
      const successRate = rate(Number(row.scoreSum ?? 0), total);
      if (successRate >= 0.8) {
        claims.push({
          kind: "strength",
          statement: `"${kind}" görevlerinde başarılıyım (${Math.round(successRate * 100)}%).`,
          evidence: { observations: total, successRate: Number(successRate.toFixed(3)) },
        });
      } else if (successRate <= 0.5) {
        claims.push({
          kind: "weakness",
          statement: `"${kind}" görevlerinde zorlanıyorum (${Math.round(successRate * 100)}%).`,
          evidence: { observations: total, successRate: Number(successRate.toFixed(3)) },
        });
      }
    }

    // 2) ŞU AN BOZUK ARAÇ — "Bu araç son üç görevde hata verdi."
    //
    // Ortalama değil ARDIŞIKLIK aranır: uzun vadede iyi olan bir araç şu anda
    // bozuk olabilir (API değişti, izin kalktı). Ortalama bunu gizler.
    const recent = await app.db
      .select({
        tool: learningEvents.key,
        confidence: learningEvents.confidence,
        createdAt: learningEvents.createdAt,
      })
      .from(learningEvents)
      .where(
        and(
          eq(learningEvents.userId, input.userId),
          eq(learningEvents.type, "tool_outcome"),
          gte(learningEvents.createdAt, since),
        ),
      )
      .orderBy(desc(learningEvents.createdAt))
      .limit(400);

    const streaks = new Map<string, { failures: number; closed: boolean }>();
    for (const row of recent) {
      const tool = String(row.tool ?? "");
      if (!tool) continue;
      const entry = streaks.get(tool) ?? { failures: 0, closed: false };
      if (entry.closed) continue;
      if (Number(row.confidence ?? 0) === 0) entry.failures += 1;
      else entry.closed = true;
      streaks.set(tool, entry);
    }
    for (const [tool, entry] of streaks) {
      if (entry.failures >= SELF_MODEL_RECENT_FAILURE_STREAK) {
        claims.push({
          kind: "broken_tool",
          statement: `"${tool}" son ${entry.failures} çağrıda başarısız oldu; şu an güvenilmez.`,
          evidence: { observations: entry.failures },
        });
      }
    }

    // 3) GÖREV TÜRÜNE GÖRE TERCİH EDİLEN ARAÇ.
    const byIntentTool = await app.db
      .select({
        intentKind: sql<string>`${learningEvents.metadata}->>'intentKind'`,
        tool: learningEvents.key,
        total: sql<number>`count(*)::int`,
        scoreSum: sql<number>`coalesce(sum(${learningEvents.confidence}),0)::int`,
      })
      .from(learningEvents)
      .where(
        and(
          eq(learningEvents.userId, input.userId),
          eq(learningEvents.type, "tool_outcome"),
          gte(learningEvents.createdAt, since),
        ),
      )
      .groupBy(sql`${learningEvents.metadata}->>'intentKind'`, learningEvents.key);

    const best = new Map<string, { tool: string; successRate: number; total: number }>();
    for (const row of byIntentTool) {
      const total = Number(row.total ?? 0);
      if (total < SELF_MODEL_MIN_OBSERVATIONS) continue;
      const kind = String(row.intentKind ?? "").trim();
      const tool = String(row.tool ?? "").trim();
      if (!kind || kind === "unknown" || !tool) continue;
      const successRate = rate(Number(row.scoreSum ?? 0), total);
      const current = best.get(kind);
      if (!current || successRate > current.successRate) {
        best.set(kind, { tool, successRate, total });
      }
    }
    for (const [kind, entry] of best) {
      if (entry.successRate < 0.7) continue;
      claims.push({
        kind: "preferred_tool",
        statement: `"${kind}" görevlerinde "${entry.tool}" en iyi sonucu veriyor (${Math.round(entry.successRate * 100)}%).`,
        evidence: {
          observations: entry.total,
          successRate: Number(entry.successRate.toFixed(3)),
          scope: kind,
        },
      });
    }
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "self model build failed",
    );
    return [];
  }

  return claims;
}
