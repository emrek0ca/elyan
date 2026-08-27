/**
 * Hash embedding sözlüğünü `elyan_hash_v2`ye taşır (Türkçe kök).
 *
 * Sorgu tarafı v2 yazarken indekste v1 satır kaldığı sürece o satırlar
 * bulunamaz. Bu script o boşluğu kapatır; partili ve idempotenttir, yarıda
 * kesilebilir.
 *
 *   npm run retrieval:backfill-hash
 */
import { buildApp } from "../app/build-app.js";
import { backfillHashedEmbeddings } from "../modules/brain/retrieval.js";

const app = await buildApp();
try {
  let total = 0;
  for (;;) {
    const result = await backfillHashedEmbeddings(app, { maxBatches: 20 });
    total += result.processed;
    console.log(
      `işlenen=${result.processed} (toplam ${total}) parti=${result.batches} durum=${result.stopped}`,
    );
    if (result.stopped !== "batch_limit") break;
  }
} finally {
  await app.close().catch(() => undefined);
}
process.exit(0);
