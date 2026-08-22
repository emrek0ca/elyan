import type { FastifyInstance } from "fastify";
import { and, eq, isNull, sql } from "drizzle-orm";
import { brainMemoryEpisodes } from "../../db/schema.js";
import { embedQueryForStorage } from "../brain/semantic-embedder.js";

/**
 * EPİZODİK KARAR HAFIZASI — sistem kendi geçmiş kararlarını okusun.
 *
 * NEDEN VAR
 * ---------
 * Ölçüm (2026-08-22): yönlendirme karar katmanı 3.642 satır, 184 dal,
 * 393 regex. Bu gecenin her düzeltmesi bir dal daha ekledi.
 *
 * Aynı anda veritabanında 45.676 öğrenme olayı, 2.622 epizot, 2.502 olgu
 * duruyor — ve karar katmanı BUNLARIN HİÇBİRİNİ okumuyor
 * (`brainMemoryEpisodes` referansı: routing/tasks içinde 0 dosya).
 *
 * Yani sistem öğrenmesi için gereken her şeyi kaydediyor, sonra kararı elle
 * yazılmış dallarla veriyor. Geri besleme döngüsündeki eksik halka insandı:
 * kullanıcı bildiriyor, geliştirici log okuyup dal ekliyor.
 *
 * Canlı kanıt — aynı cümle, iki farklı sonuç:
 *   b2845b50 (14:59) "masaüstüne … pdf hazırla ve kaydet" → desktop_runtime
 *   63553c0b (17:02) AYNI CÜMLE                          → server_brain
 * Hiçbir yerde "bu ifade daha önce şuraya gitti ve şu oldu" bilgisi yok.
 *
 * NE YAPAR
 * --------
 * Biten her görevi (istek metni + rota + sonuç) epizot olarak yazar; karar
 * anında isteğin e5 komşularını geri çağırır.
 *
 * NE YAPMAZ
 * ---------
 * Kararı ZORLAMAZ. Bu projede "tahmin sert sözleşmeye dönüşüyor" hata sınıfı
 * defalarca tekrarlandı. Bu katman kanıt üretir; kanıtın karara nasıl
 * gireceği ayrıca ve ölçülerek yapılır.
 *
 * KAPSAM: epizotlar kullanıcıya özeldir (`userId` filtresi zorunlu).
 * Kullanıcı metni asla kullanıcılar arası havuza girmez.
 */

export const ROUTING_EPISODE_TYPE = "routing_decision";

/** Aynı yeniden yazımı iki kez saklamamak için kısa bir özet biçimi. */
function buildEpisodeSummary(input: {
  message: string;
  route: string;
  outcome: string;
}): string {
  const message = input.message.replace(/\s+/g, " ").trim().slice(0, 400);
  return `[${input.route} → ${input.outcome}] ${message}`;
}

export type RoutingEpisode = {
  message: string;
  route: string;
  outcome: string;
  /** 0..1 — 1 en yakın. pgvector kosinüs mesafesinden türetilir. */
  similarity: number;
  failureReason?: string;
  observedAt: string;
};

function parseSummary(summary: string): { route: string; outcome: string; message: string } | null {
  const match = /^\[([^\s\]]+)\s*→\s*([^\]]+)\]\s*(.*)$/s.exec(summary);
  if (!match) return null;
  return { route: match[1], outcome: match[2].trim(), message: match[3] };
}

/**
 * Biten bir görevi epizot olarak yaz.
 *
 * FAIL-OPEN: yazamazsa görev akışı etkilenmez — hafıza bir iyileştirmedir,
 * yürütmenin ön koşulu değildir.
 */
export async function recordRoutingEpisode(
  app: FastifyInstance,
  input: {
    userId: string;
    taskId?: string | null;
    message: string;
    route: string;
    outcome: "completed" | "failed" | "canceled";
    failureReason?: string | null;
  },
): Promise<boolean> {
  const message = String(input.message ?? "").replace(/\s+/g, " ").trim();
  if (!message || !input.userId) return false;
  try {
    const embedding = await embedQueryForStorage(message);
    if (!embedding) return false;
    await app.db.insert(brainMemoryEpisodes).values({
      userId: input.userId,
      scope: "user",
      sourceTaskId: input.taskId ?? null,
      episodeType: ROUTING_EPISODE_TYPE,
      summary: buildEpisodeSummary({
        message,
        route: input.route,
        outcome: input.outcome,
      }),
      // Gizlilik: kullanıcı isteği metni epizotta durur, kapsam `user`.
      privacyLevel: "sensitive",
      confidence: input.outcome === "completed" ? 80 : 60,
      importanceScore: input.outcome === "completed" ? 50 : 70,
      // vector384 sütunu metin literali bekliyor (bkz. db/schema.ts customType).
      embeddingV2: `[${embedding.join(",")}]`,
      embeddingV2Model: "multilingual-e5-small",
      metadata: {
        contract: "elyan.routing_episode.v1",
        route: input.route,
        outcome: input.outcome,
        ...(input.failureReason ? { failureReason: input.failureReason.slice(0, 240) } : {}),
      },
    });
    return true;
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "routing episode not recorded",
    );
    return false;
  }
}

/**
 * Bu isteğe benzeyen geçmiş kararları getir.
 *
 * Boş dizi = bilgi yok. "Bilgi yok" ile "kötü gitti" ASLA karıştırılmamalı;
 * çağıran taraf bunu ayırt etmek zorunda.
 */
export async function recallRoutingEpisodes(
  app: FastifyInstance,
  input: { userId: string; message: string; limit?: number },
): Promise<RoutingEpisode[]> {
  const message = String(input.message ?? "").replace(/\s+/g, " ").trim();
  if (!message || !input.userId) return [];
  try {
    const embedding = await embedQueryForStorage(message);
    if (!embedding) return [];
    const vectorLiteral = `[${embedding.join(",")}]`;
    const rows = await app.db
      .select({
        summary: brainMemoryEpisodes.summary,
        metadata: brainMemoryEpisodes.metadata,
        observedAt: brainMemoryEpisodes.observedAt,
        distance: sql<number>`${brainMemoryEpisodes.embeddingV2} <=> ${vectorLiteral}::vector`,
      })
      .from(brainMemoryEpisodes)
      .where(
        and(
          eq(brainMemoryEpisodes.userId, input.userId),
          eq(brainMemoryEpisodes.episodeType, ROUTING_EPISODE_TYPE),
          eq(brainMemoryEpisodes.lifecycleStatus, "active"),
          isNull(brainMemoryEpisodes.deletedAt),
        ),
      )
      .orderBy(sql`${brainMemoryEpisodes.embeddingV2} <=> ${vectorLiteral}::vector`)
      .limit(Math.max(1, Math.min(20, input.limit ?? 5)));

    return rows.flatMap((row): RoutingEpisode[] => {
      const parsed = parseSummary(String(row.summary ?? ""));
      if (!parsed) return [];
      const metadata = (row.metadata ?? {}) as Record<string, unknown>;
      const distance = Number(row.distance ?? 1);
      return [
        {
          message: parsed.message,
          route: String(metadata.route ?? parsed.route),
          outcome: String(metadata.outcome ?? parsed.outcome),
          similarity: Number(Math.max(0, Math.min(1, 1 - distance)).toFixed(4)),
          ...(typeof metadata.failureReason === "string"
            ? { failureReason: metadata.failureReason }
            : {}),
          observedAt: row.observedAt instanceof Date
            ? row.observedAt.toISOString()
            : String(row.observedAt ?? ""),
        },
      ];
    });
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "routing episode recall failed",
    );
    return [];
  }
}
