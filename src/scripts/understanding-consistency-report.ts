import { classifyIntent } from "../core/understanding/intent-classifier.js";
import { buildTypedUnderstandingEnvelope } from "../core/understanding/understanding-envelope.js";
import { parseArtifactIntent } from "../modules/artifacts/parser.js";
import { decideStructuredResponseDecision } from "../core/understanding/structured-output-policy.js";
import { compileOutputContract } from "../core/understanding/output-contract.js";

/**
 * ANLAMA TUTARLILIK KAPISI.
 *
 * NEDEN
 * -----
 * Bu projede tekrar tekrar aynı hata sınıfı çıkıyor: AYNI karar iki yerde,
 * iki farklı yöntemle veriliyor ve ayrıştıklarında kimse fark etmiyor. Bir
 * günde dördü ölçüldü — widget biçimi, görsel kapısı, aç/kapat kutbu, docx
 * artefaktı. Dördünde de anlama katmanı DOĞRUYDU; aşağıdaki katman kararı
 * yeniden türetip yanlış yaptı.
 *
 * Zarf (`understanding-envelope`) üretimde otorite ve açık
 * (`ELYAN_UNDERSTANDING_ENVELOPE_V2_ENABLED=true`). Ama yanında hâlâ bir
 * GÖLGE YOL var: zarf yoksa/boşsa kelime listeleri devreye giriyor. O yol
 * yanlış olduğunda sistem "bozulmuş" gibi değil, "yanlış cevap vermiş" gibi
 * davranıyor — teşhis edilemez arıza tam olarak budur.
 *
 * NE ÖLÇER
 * --------
 * Her mesaj için iki yolu da koşar ve AYRIŞMALARI raporlar:
 *   • zarflı artefakt tipi   vs  zarfsız (kelime listesi) artefakt tipi
 *   • zarfın istediği çıktı  vs  widget kararı
 *
 * Ayrışma bir hata DEĞİL, bir hata ADAYIDIR: hangi tarafın doğru olduğu
 * incelenmelidir. Ama ayrışma sayısının artması kesinlikle regresyondur.
 *
 *   npm run eval:understanding
 */

type Case = { message: string; note?: string };

const CASES: Case[] = [
  // Belge / dosya
  { message: "tanıtım raporunu word belgesi olarak hazırla" },
  { message: "bu raporu word belgesi yap" },
  { message: "bunu docx yap" },
  { message: "şirket raporu hazırla pdf olarak" },
  { message: "sözleşmeyi pdf olarak çıkar" },
  { message: "dokümanı word formatında istiyorum" },
  { message: "teklif dosyasını hazırlar mısın" },
  // Tablo / grafik
  { message: "2020-2025 enflasyonu tablo olarak ver" },
  { message: "bunları yan yana koyup karşılaştır" },
  { message: "satışların zamana göre nasıl değiştiğini göster" },
  { message: "bu verilerin grafiğini çiz" },
  { message: "her birinin fiyatını ve özelliğini düzenli göster" },
  // Görsel
  { message: "yeni bir görsel üret kedi resmi olsun" },
  { message: "bana bir logo tasarla" },
  { message: "görsel üretme, sadece anlat", note: "olumsuzlama" },
  // Matematik / kod
  { message: "z = x^2 + y^2 yüzeyini 3 boyutlu çiz" },
  { message: "şu denklemin köklerini bul" },
  // Sohbet — hiçbir artefakt beklenmemeli
  { message: "merhaba nasılsın bugün" },
  { message: "kuantum bilgisayarları kısaca açıkla" },
  { message: "bana güzel bir belgesel öner", note: "belgesel ≠ belge" },
  { message: "teşekkürler çok yardımcı oldun" },
];

type Row = {
  message: string;
  envelopeOutputs: string;
  withEnvelope: string | null;
  withoutEnvelope: string | null;
  widget: string;
  contract: string;
  disagrees: boolean;
};

function analyze(testCase: Case): Row {
  const intent = classifyIntent({ userId: "consistency", message: testCase.message });
  const envelope = buildTypedUnderstandingEnvelope({
    userId: "consistency",
    message: testCase.message,
    intent,
    source: "typed_extractor",
  });
  const withEnvelope = parseArtifactIntent({
    userRequest: testCase.message,
    metadata: {},
    understandingEnvelope: envelope,
  }).type;
  const withoutEnvelope = parseArtifactIntent({
    userRequest: testCase.message,
    metadata: {},
  }).type;
  const widget = decideStructuredResponseDecision({ prompt: testCase.message });
  const contract = compileOutputContract({ message: testCase.message, metadata: {} });
  return {
    message: testCase.message,
    envelopeOutputs:
      (envelope.desired_outputs ?? [])
        .map((output) => `${output.kind}/${output.format ?? "-"}`)
        .join(",") || "(boş)",
    withEnvelope,
    withoutEnvelope,
    widget: widget.primaryBlockType,
    contract: `${contract.outputKind ?? "-"}/${contract.outputFormat ?? "-"}`,
    disagrees: withEnvelope !== withoutEnvelope,
  };
}

const rows = CASES.map(analyze);
const disagreements = rows.filter((row) => row.disagrees);

if (process.argv.includes("--json")) {
  console.log(
    JSON.stringify(
      {
        generatedAt: new Date().toISOString(),
        cases: rows.length,
        disagreements: disagreements.length,
        rows,
      },
      null,
      2,
    ),
  );
} else {
  console.log(`ANLAMA TUTARLILIĞI — ${rows.length} mesaj\n`);
  for (const row of rows) {
    const flag = row.disagrees ? "AYRIŞMA" : "       ";
    console.log(`${flag} | zarflı=${String(row.withEnvelope ?? "-").padEnd(12)} zarfsız=${String(row.withoutEnvelope ?? "-").padEnd(12)} widget=${row.widget.padEnd(16)} | ${row.message}`);
  }
  console.log(
    `\nAYRIŞMA: ${disagreements.length}/${rows.length}` +
      (disagreements.length === 0
        ? "  — gölge yol zarfla aynı kararı veriyor."
        : "  — bu satırlarda zarf kapalıysa sistem YANLIŞ cevap verir."),
  );
}
