import { desc, isNotNull } from "drizzle-orm";
import { buildApp } from "../app/build-app.js";
import { loadEnv } from "../config/env.js";
import { tasks } from "../db/schema.js";
import {
  recallRoutingEpisodes,
  recordRoutingEpisode,
} from "../modules/routing-policy/episodic-decisions.js";

/**
 * EPİZODİK KARAR HAFIZASINI GEÇMİŞ GÖREVLERLE DOLDUR VE ÖLÇ.
 *
 * Kayıt bundan sonra otomatik yazılıyor (terminal geçişte), ama geçmiş
 * görevler hafızada yok. Bu script onları bir kez taşır ve ardından geri
 * çağırmanın ANLAMLI komşu bulup bulmadığını ölçer.
 *
 *   npm run memory:routing-backfill              → doldur + ölç
 *   npm run memory:routing-backfill -- --measure → yalnız ölç
 */

function readPrompt(task: typeof tasks.$inferSelect): string {
  const payload = (task.payload ?? {}) as Record<string, unknown>;
  const prompt = typeof payload.prompt === "string" ? payload.prompt : "";
  return prompt.trim() || String(task.title ?? "").trim();
}

function readRoute(task: typeof tasks.$inferSelect): string {
  const payload = (task.payload ?? {}) as Record<string, unknown>;
  const metadata = (payload.metadata ?? {}) as Record<string, unknown>;
  const routeDecision = (metadata.routeDecision ?? {}) as Record<string, unknown>;
  const taskRoute = (routeDecision.taskRoute ?? {}) as Record<string, unknown>;
  if (typeof taskRoute.operationalRoute === "string") return taskRoute.operationalRoute;
  return typeof routeDecision.route === "string" ? routeDecision.route : "unknown";
}

async function main() {
  const config = loadEnv();
  const app = await buildApp(config);
  const measureOnly = process.argv.includes("--measure");

  try {
    if (!measureOnly) {
      const rows = await app.db
        .select()
        .from(tasks)
        .where(isNotNull(tasks.userId))
        .orderBy(desc(tasks.createdAt))
        .limit(500);

      let written = 0;
      let skipped = 0;
      for (const task of rows) {
        if (!["completed", "failed", "canceled", "expired"].includes(task.status)) {
          skipped += 1;
          continue;
        }
        const message = readPrompt(task);
        if (!message) {
          skipped += 1;
          continue;
        }
        const ok = await recordRoutingEpisode(app, {
          userId: task.userId,
          taskId: task.id,
          message,
          route: readRoute(task),
          outcome:
            task.status === "completed"
              ? "completed"
              : task.status === "canceled"
                ? "canceled"
                : "failed",
          failureReason: task.error ?? null,
        });
        if (ok) written += 1;
        else skipped += 1;
      }
      console.log(`taşınan görev: ${written}, atlanan: ${skipped}`);
    }

    // ÖLÇÜM: geri çağırma anlamlı komşu buluyor mu?
    //
    // "Bilgi yok" ile "kötü gitti" ayrı şeylerdir; rapor ikisini ayırır.
    const probeRows = await app.db
      .select({ userId: tasks.userId, payload: tasks.payload, title: tasks.title })
      .from(tasks)
      .orderBy(desc(tasks.createdAt))
      .limit(6);

    console.log("\n=== GERİ ÇAĞIRMA ÖLÇÜMÜ ===");
    for (const probe of probeRows) {
      const message = readPrompt(probe as never);
      if (!message) continue;
      const episodes = await recallRoutingEpisodes(app, {
        userId: probe.userId,
        message,
        limit: 4,
      });
      console.log(`\n"${message.slice(0, 70)}"`);
      if (episodes.length === 0) {
        console.log("   (komşu yok)");
        continue;
      }
      for (const episode of episodes) {
        console.log(
          `   ${episode.similarity.toFixed(3)}  ${episode.route.padEnd(16)} ${episode.outcome.padEnd(10)} "${episode.message.slice(0, 46)}"`,
        );
      }
    }
  } finally {
    await app.close();
  }
}

void main();
