/**
 * Sürekli öğrenme geçmiş taraması (backfill).
 *
 * NEDEN
 * -----
 * `learning_events` bir yıla yakın birikmiş (canlıda 44k+) ama boru hattı
 * yalnız BİR günlük pencere işliyor: günlük iş, dünü işleyip bırakıyor.
 * Dolayısıyla birikintinin tamamı hiç değerlendirilmemiş durumda. Bu script
 * aynı boru hattını geçmişteki her gün için sırayla koşturur.
 *
 * GÜVENLİK
 * --------
 *  - Yalnız GÖLGE modda çalışır. `ELYAN_CONTINUOUS_LEARNING_V2_ENABLED=true`
 *    ise script kendini durdurur: backfill bir ÖLÇÜMdür, terfi değil. Geçmiş
 *    veriyi toptan "onaylanmış eğitim kümesi" hâline getirmek, tam da
 *    kaçınmak istediğimiz şey.
 *  - Boru hattı (scope + pencere) üzerinde dedup yapıyor; script tekrar
 *    koşulabilir, aynı gün ikinci kez işlenmez.
 *  - Yazdığı tek şey `dataset_manifests` + `continuous_learning_runs` satırı;
 *    ikisi de taslak/rapor. Kullanıcı verisi değişmez.
 *
 * PARTİ SINIRI
 * ------------
 * Varsayılan günlük sınır 2000. Canlıda en yoğun gün 2397 kayıt taşıyor —
 * varsayılanla koşmak o günün 397 kaydını SESSİZCE düşürürdü. Bu yüzden
 * varsayılan burada 5000 ve `--limit` ile yükseltilebilir.
 *
 * KULLANIM (backend konteyneri içinde)
 *   npx tsx scripts/backfill-continuous-learning.ts
 *   npx tsx scripts/backfill-continuous-learning.ts --from 2026-05-25 --to 2026-08-10
 *   npx tsx scripts/backfill-continuous-learning.ts --dry-run
 */
import { sql } from "drizzle-orm";
import { buildApp } from "../src/app/build-app.js";
import { processContinuousLearningDailyBuild } from "../src/modules/brain/continuous-learning-pipeline.js";

const DAY_MS = 86_400_000;

function readFlag(name: string): string | null {
  const index = process.argv.indexOf(`--${name}`);
  if (index < 0) return null;
  const value = process.argv[index + 1];
  return value && !value.startsWith("--") ? value : "";
}

function parseDay(value: string, label: string): Date {
  const parsed = new Date(`${value}T00:00:00.000Z`);
  if (Number.isNaN(parsed.getTime())) {
    throw new Error(`${label} geçersiz tarih: ${value} (YYYY-MM-DD bekleniyor)`);
  }
  return parsed;
}

const dryRun = process.argv.includes("--dry-run");
const limit = Number(readFlag("limit") ?? "5000");

let app: Awaited<ReturnType<typeof buildApp>> | null = null;
try {
  app = await buildApp();
  app.log.level = "warn";

  if (app.config?.ELYAN_CONTINUOUS_LEARNING_V2_ENABLED === true) {
    throw new Error(
      "V2 (gerçek eğitim) AÇIK. Backfill yalnız gölge modda koşar — " +
        "geçmişi toptan terfi ettirmek bilinçli olarak engellendi.",
    );
  }
  if (app.config?.ELYAN_CONTINUOUS_LEARNING_SHADOW_ENABLED !== true) {
    throw new Error(
      "Gölge mod KAPALI. ELYAN_CONTINUOUS_LEARNING_SHADOW_ENABLED=true olmadan " +
        "boru hattı hiçbir şey üretmez.",
    );
  }

  // Aralığı veriden türet: elle tarih girmek, kaydı olmayan günleri boşuna
  // koşturmaya ya da kenarları kaçırmaya yol açıyor.
  const bounds = await app.db.execute<{ ilk: string | null; son: string | null }>(
    sql`select min(created_at)::date::text as ilk, max(created_at)::date::text as son from learning_events`,
  );
  const row = (bounds as unknown as Array<{ ilk: string | null; son: string | null }>)[0]
    ?? (bounds as { rows?: Array<{ ilk: string | null; son: string | null }> }).rows?.[0];
  if (!row?.ilk || !row?.son) {
    console.log("learning_events boş — işlenecek bir şey yok.");
    process.exit(0);
  }

  const fromDay = parseDay(readFlag("from") || row.ilk, "--from");
  const toDay = parseDay(readFlag("to") || row.son, "--to");
  if (fromDay > toDay) throw new Error("--from, --to tarihinden sonra olamaz");

  const totalDays = Math.round((toDay.getTime() - fromDay.getTime()) / DAY_MS) + 1;
  console.log(
    `backfill: ${row.ilk} → ${row.son} (${totalDays} gün), limit=${limit}` +
      (dryRun ? " [DRY-RUN]" : ""),
  );

  if (dryRun) {
    console.log("dry-run: hiçbir şey yazılmadı.");
    process.exit(0);
  }

  let built = 0;
  let skipped = 0;
  let failed = 0;
  let acceptedTotal = 0;
  let trainTotal = 0;
  let dedupedTotal = 0;

  for (let index = 0; index < totalDays; index += 1) {
    const day = new Date(fromDay.getTime() + index * DAY_MS);
    // Pencere `now`un GÜNÜNDEN bir önceki günü kapsar (windowEnd = o günün
    // 00:00'ı). O yüzden X gününü işlemek için X+1 veriyoruz.
    const asOf = new Date(day.getTime() + DAY_MS);
    const label = day.toISOString().slice(0, 10);

    try {
      const result = await processContinuousLearningDailyBuild(app, {
        now: asOf,
        limit,
      });
      if (result.processed === false) {
        if (result.reason === "already_built") {
          skipped += 1;
        } else {
          failed += 1;
          console.log(`  ${label}: işlenmedi (${result.reason})`);
        }
        continue;
      }
      built += 1;
      const { acceptedEventCount, trainRecordCount, dedupedEventCount } =
        result.candidate;
      acceptedTotal += acceptedEventCount;
      trainTotal += trainRecordCount;
      dedupedTotal += dedupedEventCount;
      if (acceptedEventCount > 0) {
        console.log(
          `  ${label}: kabul=${acceptedEventCount} train=${trainRecordCount} yinelenen=${dedupedEventCount}`,
        );
      }
    } catch (error) {
      failed += 1;
      console.log(`  ${label}: HATA ${(error as Error).message}`);
    }
  }

  console.log(
    `\nbitti — üretilen: ${built}, zaten vardı: ${skipped}, hata: ${failed}`,
  );
  console.log(
    `toplam kabul edilen olay: ${acceptedTotal}, train kaydı: ${trainTotal}, ` +
      `yinelenen (elenen): ${dedupedTotal}`,
  );
  process.exit(0);
} catch (error) {
  console.error("backfill başarısız:", (error as Error).message);
  process.exit(1);
} finally {
  await app?.close().catch(() => undefined);
}
