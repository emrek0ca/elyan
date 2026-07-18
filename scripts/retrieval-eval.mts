/**
 * Retrieval kalite harness'ı — recall@k / MRR baz çizgisi.
 *
 * Brifing kuralı: "ölçmeden iyileştirme yapma". Bu harness, Türkçe sorgu →
 * beklenen belge eşlemeli sabit bir setle searchKnowledge'ın uçtan uca
 * kalitesini sayıya döker. Üç sorgu sınıfı ölçülür:
 *   - keyword: belgedeki kelimelerle sorulan sorular (lexical de bulmalı)
 *   - paraphrase: eş anlamlı/başka kelimelerle (semantik farkı burada görünür)
 *   - suffixed: Türkçe ekli/SOV biçimler
 *
 * Çalıştırma (DB + e5 model cache olan ortamda; tipik olarak sunucu konteyneri):
 *   npm run retrieval:eval            # ölç, yaz, eval verisini temizle
 *   RETRIEVAL_EVAL_KEEP=1 npm run retrieval:eval   # veriyi bırak
 */
import { createHash, randomUUID } from "node:crypto";
import { sql } from "drizzle-orm";
import { buildApp } from "../src/app/build-app.js";
import {
  backfillSemanticV2Embeddings,
  indexKnowledgeChunksForDocument,
  searchKnowledge,
} from "../src/modules/brain/retrieval.js";

const EVAL_USER_ID = "00000000-0000-4000-8000-00000000eea1";

type EvalDoc = { key: string; title: string; content: string };
type EvalCase = { kind: "keyword" | "paraphrase" | "suffixed"; query: string; expect: string };

const DOCS: EvalDoc[] = [
  { key: "arac-bakim", title: "Araç bakım rehberi", content: "Otomobilinizin motor yağı her 10.000 kilometrede bir değiştirilmelidir. Fren balatalarını yılda bir kontrol ettirin. Lastik basıncı ayda bir ölçülmeli, kışın kış lastiğine geçilmelidir." },
  { key: "kahve-demleme", title: "Kahve demleme teknikleri", content: "V60 ile filtre kahve demlerken 92-96 derece su kullanın. Çekirdekleri demlemeden hemen önce öğütün. 1:15 kahve-su oranı dengeli bir fincan verir. French press daha yoğun gövde sağlar." },
  { key: "uyku-hijyeni", title: "Uyku hijyeni önerileri", content: "Kaliteli uyku için yatak odası serin ve karanlık olmalı. Yatmadan iki saat önce ekranlardan uzaklaşın. Kafeini öğleden sonra kesmek gece uykuya dalmayı kolaylaştırır. Düzenli uyku saati sirkadiyen ritmi korur." },
  { key: "sirket-izin", title: "Şirket izin politikası", content: "Yıllık ücretli izin ilk yıl 14 gündür, beş yıldan sonra 20 güne çıkar. İzin talepleri en az bir hafta önceden yöneticinize iletilmelidir. Hastalık izni için rapor gerekir." },
  { key: "sunucu-yedek", title: "Sunucu yedekleme prosedürü", content: "Veritabanı yedekleri her gece 03:00'te otomatik alınır ve 30 gün saklanır. Geri yükleme testi ayda bir yapılmalıdır. Yedekler şifrelenmiş olarak ayrı bölgede tutulur." },
  { key: "toplanti-kurali", title: "Toplantı kültürü kuralları", content: "Toplantılar 25 veya 50 dakika olarak planlanır. Gündemsiz toplantı davet edilmez. Kararlar toplantı notuna yazılır ve sorumlusu atanır. Katılımcı sayısı yediyi geçmemelidir." },
  { key: "bitki-sulama", title: "Ev bitkileri sulama rehberi", content: "Sukulentler iki haftada bir, orkideler haftada bir sulanır. Toprağın üst iki santimi kuruduğunda sulama zamanı gelmiştir. Aşırı sulama kök çürümesinin en yaygın sebebidir." },
  { key: "vergi-beyan", title: "Serbest çalışan vergi beyanı", content: "Serbest meslek makbuzu kesen çalışanlar üç ayda bir geçici vergi beyannamesi verir. Giderler belgelendiğinde vergi matrahından düşülebilir. Yıllık beyanname mart ayında verilir." },
];

const CASES: EvalCase[] = [
  // keyword — belgedeki kelimelerle
  { kind: "keyword", query: "motor yağı ne zaman değiştirilir", expect: "arac-bakim" },
  { kind: "keyword", query: "V60 filtre kahve su sıcaklığı", expect: "kahve-demleme" },
  { kind: "keyword", query: "yıllık ücretli izin kaç gün", expect: "sirket-izin" },
  { kind: "keyword", query: "veritabanı yedekleri ne zaman alınır", expect: "sunucu-yedek" },
  { kind: "keyword", query: "sukulent sulama sıklığı", expect: "bitki-sulama" },
  { kind: "keyword", query: "geçici vergi beyannamesi ne zaman", expect: "vergi-beyan" },
  // paraphrase — eş anlamlı, belge kelimeleri YOK
  { kind: "paraphrase", query: "arabamın periyodik servisini ne sıklıkla yaptırmalıyım", expect: "arac-bakim" },
  { kind: "paraphrase", query: "güzel bir espresso alternatifi nasıl hazırlanır elle", expect: "kahve-demleme" },
  { kind: "paraphrase", query: "geceleri daha iyi dinlenmek için ne yapmalıyım", expect: "uyku-hijyeni" },
  { kind: "paraphrase", query: "tatile çıkmak için kaç gün hakkım var", expect: "sirket-izin" },
  { kind: "paraphrase", query: "felaket durumunda verileri nasıl kurtarırız", expect: "sunucu-yedek" },
  { kind: "paraphrase", query: "verimli bir mitingin kuralları neler", expect: "toplanti-kurali" },
  { kind: "paraphrase", query: "saksıdaki çiçeğim solmasın diye ne yapayım", expect: "bitki-sulama" },
  { kind: "paraphrase", query: "freelancer olarak devlete ne ödemem gerekiyor", expect: "vergi-beyan" },
  // suffixed / SOV — ekli biçimler ve nesne-önce sıra
  { kind: "suffixed", query: "lastiklerimi kışın değiştirmeli miyim", expect: "arac-bakim" },
  { kind: "suffixed", query: "kahvemi daha lezzetli demleyebilmek istiyorum", expect: "kahve-demleme" },
  { kind: "suffixed", query: "uykumu düzene sokamıyorum", expect: "uyku-hijyeni" },
  { kind: "suffixed", query: "iznimi nasıl talep ederim", expect: "sirket-izin" },
  { kind: "suffixed", query: "yedeklerimizi test ediyor muyuz", expect: "sunucu-yedek" },
  { kind: "suffixed", query: "toplantılarımızı kısaltmalıyız", expect: "toplanti-kurali" },
];

async function main() {
  const app = await buildApp();
  const docIdByKey = new Map<string, string>();
  try {
    // Eski eval kalıntılarını temizle (idempotent koşum).
    await app.db.execute(sql`delete from knowledge_chunks where owner_user_id = ${EVAL_USER_ID}`);
    await app.db.execute(sql`delete from knowledge_documents where owner_user_id = ${EVAL_USER_ID}`);

    for (const doc of DOCS) {
      const documentId = randomUUID();
      docIdByKey.set(doc.key, documentId);
      const contentHash = createHash("sha256").update(doc.content).digest("hex");
      await app.db.execute(sql`
        insert into knowledge_documents (id, owner_user_id, scope, source_type, title, summary, status, content_hash, metadata, created_at, updated_at)
        values (${documentId}, ${EVAL_USER_ID}, 'user', 'note', ${doc.title}, ${doc.title}, 'ready', ${contentHash}, '{"evalSet":"retrieval-v1"}', now(), now())
      `);
      await app.db.execute(sql`
        insert into knowledge_chunks (id, document_id, owner_user_id, scope, ordinal, content, token_estimate, metadata, created_at)
        values (${randomUUID()}, ${documentId}, ${EVAL_USER_ID}, 'user', 0, ${doc.content}, ${Math.ceil(doc.content.length / 4)}, '{"evalSet":"retrieval-v1"}', now())
      `);
      await indexKnowledgeChunksForDocument(app, { documentId });
    }
    const backfill = await backfillSemanticV2Embeddings(app, { maxBatches: 10 });
    console.log("v2 backfill:", JSON.stringify(backfill));

    const byKind = new Map<string, { n: number; hitAt1: number; hitAt5: number; rrSum: number }>();
    const misses: string[] = [];
    for (const evalCase of CASES) {
      const results = await searchKnowledge(app, { userId: EVAL_USER_ID, query: evalCase.query, limit: 5 });
      const expectedId = docIdByKey.get(evalCase.expect)!;
      const rank = results.results.findIndex((row: { documentId: string }) => row.documentId === expectedId) + 1;
      const bucket = byKind.get(evalCase.kind) ?? { n: 0, hitAt1: 0, hitAt5: 0, rrSum: 0 };
      bucket.n += 1;
      if (rank === 1) bucket.hitAt1 += 1;
      if (rank >= 1 && rank <= 5) bucket.hitAt5 += 1;
      bucket.rrSum += rank >= 1 ? 1 / rank : 0;
      byKind.set(evalCase.kind, bucket);
      if (rank !== 1) misses.push(`${evalCase.kind} | rank=${rank || "-"} | ${evalCase.query}`);
    }

    let totalN = 0, totalHit1 = 0, totalHit5 = 0, totalRr = 0;
    for (const [kind, bucket] of byKind) {
      totalN += bucket.n; totalHit1 += bucket.hitAt1; totalHit5 += bucket.hitAt5; totalRr += bucket.rrSum;
      console.log(
        `${kind.padEnd(11)} n=${bucket.n}  recall@1=${(bucket.hitAt1 / bucket.n).toFixed(2)}  recall@5=${(bucket.hitAt5 / bucket.n).toFixed(2)}  MRR=${(bucket.rrSum / bucket.n).toFixed(3)}`,
      );
    }
    console.log(
      `TOPLAM      n=${totalN}  recall@1=${(totalHit1 / totalN).toFixed(2)}  recall@5=${(totalHit5 / totalN).toFixed(2)}  MRR=${(totalRr / totalN).toFixed(3)}`,
    );
    if (misses.length > 0) {
      console.log("\nrank!=1 olan sorgular:");
      for (const miss of misses) console.log("  " + miss);
    }
  } finally {
    if (process.env.RETRIEVAL_EVAL_KEEP !== "1") {
      await app.db.execute(sql`delete from knowledge_chunks where owner_user_id = ${EVAL_USER_ID}`).catch(() => undefined);
      await app.db.execute(sql`delete from knowledge_documents where owner_user_id = ${EVAL_USER_ID}`).catch(() => undefined);
    }
    await app.close().catch(() => undefined);
  }
  process.exit(0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
