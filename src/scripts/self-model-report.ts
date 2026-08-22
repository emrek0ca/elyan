import { desc } from "drizzle-orm";
import { buildApp } from "../app/build-app.js";
import { loadEnv } from "../config/env.js";
import { tasks } from "../db/schema.js";
import { buildSelfModel } from "../modules/tasks/self-model.js";
import { estimateToolSuccessBatch } from "../modules/tasks/tool-success-model.js";

/**
 * ELYAN KENDİSİ HAKKINDA NE BİLİYOR?
 *
 * Bu rapor elle yazılmış hiçbir cümle içermez; hepsi adım düzeyi deneyim
 * defterinden türetilir. Boş çıkması ARIZA DEĞİLDİR — henüz yeterli gözlem
 * yok demektir ve rapor bunu açıkça söyler.
 *
 *   npm run report:self-model
 */
async function main() {
  const app = await buildApp(loadEnv());
  try {
    const [latest] = await app.db
      .select({ userId: tasks.userId })
      .from(tasks)
      .orderBy(desc(tasks.createdAt))
      .limit(1);
    if (!latest?.userId) {
      console.log("görev yok — öğrenilecek deneyim de yok.");
      return;
    }

    const claims = await buildSelfModel(app, { userId: latest.userId, windowDays: 90 });
    console.log("=== SELF-MODEL ===");
    if (claims.length === 0) {
      console.log("(henüz yeterli gözlem yok — iddia üretilmedi)");
    }
    for (const claim of claims) {
      console.log(`  [${claim.kind}] ${claim.statement}`);
      console.log(`      gözlem: ${claim.evidence.observations}`);
    }

    const estimates = await estimateToolSuccessBatch(app, {
      userId: latest.userId,
      tools: [
        "document_write",
        "open_app",
        "close_app",
        "web_research",
        "shell_run",
        "desktop_operator.run",
      ],
    });
    console.log("\n=== P(success | tool) ===");
    if (estimates.length === 0) {
      console.log("(hiçbir araç için eşik gözleme ulaşılmadı)");
    }
    for (const estimate of estimates) {
      console.log(
        `  ${estimate.tool.padEnd(24)} ${(estimate.probability * 100).toFixed(1).padStart(5)}%  ` +
          `gözlem ${String(estimate.observations).padStart(3)}  temel: ${estimate.basis}`,
      );
    }
  } finally {
    await app.close();
  }
}

void main();
