import {
  classifyKnowledgeRecency,
  type KnowledgeRecency,
} from "../core/understanding/knowledge-recency.js";
import { resetSemanticComputeWorkerForTests } from "../modules/brain/semantic-compute-client.js";

/**
 * BİLGİ TAZELİĞİ ÖLÇÜM KAPISI.
 *
 * TUTULAN kümeye BAKIP AYAR YAPMA. Örnek cümleleri tutulan kümeye göre
 * düzenlemek genelleme payını yok eder ve ölçüm anlamsızlaşır.
 *
 * KRİTİK YÖN: "canlı veri gerekiyorken model kendi bilgisiyle yazmak" =
 * UYDURMA riski. "Gereksiz araştırma" ise yalnız yavaşlık. İkisi eşit ağırlıkta
 * değil; rapor ikisini ayrı sayar.
 */
type Case = { text: string; expected: KnowledgeRecency };

const CORPUS: Case[] = [
  { text: "masaüstüne kediler hakkında bir rapor hazırla ve kaydet", expected: "stable_knowledge" },
  { text: "köpek bakımı hakkında iki sayfalık yazı", expected: "stable_knowledge" },
  { text: "türkiye'nin coğrafi bölgeleri hakkında belge", expected: "stable_knowledge" },
  { text: "ingilizce öğrenme yöntemleri üzerine rapor", expected: "stable_knowledge" },
  { text: "sağlıklı beslenme rehberi yaz", expected: "stable_knowledge" },
  { text: "iş yerinde iletişim üzerine sunum hazırla", expected: "stable_knowledge" },
  { text: "javascript closure kavramını anlatan doküman", expected: "stable_knowledge" },
  { text: "kahvenin tarihçesi hakkında kısa bir metin", expected: "stable_knowledge" },
  { text: "bir kira sözleşmesi taslağı hazırla", expected: "stable_knowledge" },
  { text: "verimli ders çalışma teknikleri", expected: "stable_knowledge" },

  { text: "bugünkü altın fiyatlarını raporla", expected: "current_facts" },
  { text: "bu ayki enflasyon verisi hakkında not hazırla", expected: "current_facts" },
  { text: "son dakika haberlerini özetle", expected: "current_facts" },
  { text: "güncel euro kuru ile bir tablo yap", expected: "current_facts" },
  { text: "bu sezonun puan durumunu belgeye aktar", expected: "current_facts" },
  { text: "dün açıklanan faiz kararını yaz", expected: "current_facts" },
  { text: "şu anki borsa endeksini raporla", expected: "current_facts" },
  { text: "bu haftaki hava tahminini kaydet", expected: "current_facts" },
];

const HELDOUT: Case[] = [
  { text: "arıların yaşam döngüsü hakkında rapor hazırla", expected: "stable_knowledge" },
  { text: "roma imparatorluğunun çöküş nedenleri üzerine belge", expected: "stable_knowledge" },
  { text: "ev taşırken dikkat edilecekler listesi", expected: "stable_knowledge" },
  { text: "bir teşekkür mektubu yaz", expected: "stable_knowledge" },
  { text: "temel muhasebe kavramlarını açıklayan doküman", expected: "stable_knowledge" },
  { text: "bu çeyrekte açıklanan büyüme rakamlarını raporla", expected: "current_facts" },
  { text: "en son çıkan yapay zeka modellerini karşılaştır", expected: "current_facts" },
  { text: "bugün yayınlanan deprem raporunu özetle", expected: "current_facts" },
  { text: "güncel akaryakıt fiyatlarını tabloya dök", expected: "current_facts" },
  { text: "geçen hafta yapılan seçim sonuçlarını yaz", expected: "current_facts" },

  // SINIRA YAKIN VAKALAR. İlk küme iki sınıfı da %100 ayırdı — ayrım kolaydı,
  // yani ölçüm sınırı zorlamıyordu. Bunlar zorluyor: konu aynı olabilir,
  // ayrım "kalıcı bilgi mi, değişken değer mi" ekseninde.
  { text: "yapay zekanın tarihçesi hakkında bir belge yaz", expected: "stable_knowledge" },
  { text: "kripto paraların nasıl çalıştığını anlatan rapor", expected: "stable_knowledge" },
  { text: "elektrikli araçların çalışma prensibi üzerine doküman", expected: "stable_knowledge" },
  { text: "diyabet hastalığı hakkında bilgilendirme metni", expected: "stable_knowledge" },
  { text: "elektrikli araç pazarının bu yılki satış rakamları", expected: "current_facts" },
  { text: "şu an piyasadaki en iyi telefon modellerini karşılaştır", expected: "current_facts" },
  { text: "bu yılki bitcoin fiyat hareketlerini raporla", expected: "current_facts" },
  { text: "yapay zeka alanında bu ay çıkan yenilikleri özetle", expected: "current_facts" },
];

async function run(label: string, cases: Case[]) {
  let correct = 0;
  let fabricationRisk = 0;
  let wastedResearch = 0;
  let undecided = 0;
  const rows: string[] = [];
  for (const testCase of cases) {
    const decision = await classifyKnowledgeRecency(testCase.text);
    if (!decision) {
      undecided += 1;
      rows.push(`  KARAR YOK  "${testCase.text}"`);
      continue;
    }
    if (decision.recency === testCase.expected) {
      correct += 1;
      continue;
    }
    if (testCase.expected === "current_facts") {
      fabricationRisk += 1;
      rows.push(
        `  UYDURMA RİSKİ  "${testCase.text}" → ${decision.recency} (marj ${decision.margin.toFixed(3)})`,
      );
    } else {
      wastedResearch += 1;
      rows.push(
        `  fazla arama    "${testCase.text}" → ${decision.recency} (marj ${decision.margin.toFixed(3)})`,
      );
    }
  }
  console.log(`\n===== ${label} (${cases.length} vaka) =====`);
  console.log(`doğru                          ${correct}/${cases.length} (${((correct / cases.length) * 100).toFixed(1)}%)`);
  console.log(`UYDURMA RİSKİ (canlı gerekiyordu, model bilgisi seçildi): ${fabricationRisk}`);
  console.log(`fazla arama (zararsız, yalnız yavaş):                     ${wastedResearch}`);
  console.log(`karar yok:                                                ${undecided}`);
  for (const row of rows) console.log(row);
  return { correct, total: cases.length, fabricationRisk };
}

async function main() {
  const corpus = await run("KORPUS", CORPUS);
  const heldout = await run("TUTULAN", HELDOUT);
  console.log(
    `\nGENELLEME PAYI: korpus ${((corpus.correct / corpus.total) * 100).toFixed(1)}%` +
      ` → tutulan ${((heldout.correct / heldout.total) * 100).toFixed(1)}%`,
  );
  await resetSemanticComputeWorkerForTests();
}
void main();
