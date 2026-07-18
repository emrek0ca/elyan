# Codex Görev Brifingi — Elyan Backend

Bu brifing, `v2-blocks` dalında yapılan bir hata avı oturumundan sonra yazıldı.
Aşağıdaki tespitler **varsayım değil, kodu çalıştırarak doğrulanmış** bulgulardır.
Önce "Zemin gerçekleri" bölümünü oku; oradaki her madde daha önce sessizce
üretime çıkmış gerçek bir hatanın kaynağıydı.

---

## 0. Çalışma kuralları (bunlara uy)

1. **Ölçmeden iyileştirme yapma.** Bu kod tabanındaki en pahalı hatalar,
   "iyileştirdim" sanılan ama hiç ölçülmemiş değişikliklerden çıktı. Bir
   davranışı değiştiriyorsan önce o davranışı ölçen bir test/harness yaz,
   sayıyı kaydet, sonra değiştir, sayıyı tekrar göster.
2. **Regex yazıyorsan Türkçe ile test et.** Bkz. Zemin gerçeği #1.
3. **Bir kalıbın çalıştığını varsayma — çalıştır.** Bu oturumda kimlik
   kapısının kalıplarının çoğu hiç eşleşmiyordu ve aylardır kimse fark
   etmemişti. Yeni kural eklediğinde, kuralın tetiklendiğini gösteren bir
   çalıştırma çıktısı üret.
4. **Yanlış pozitif kontrolü zorunlu.** Bir savunma/kapı kuralı eklediğinde,
   sıradan iş isteklerinin ("dosyayı yazdır", "sunumu göster", "raporu paylaş")
   o kurala takılmadığını da göster.
5. **Fail-closed davranışı bozma.** Güvenlik ve gizlilik kapılarında şüphe
   varsa reddet; sessizce geçirme.
6. `npm run check` (tsc) ve `npm test` yeşil olmadan iş bitmiş sayılmaz.
   Şu an baz çizgi: **1355 test geçiyor.**

---

## 1. Zemin gerçekleri (doğrulanmış)

### #1 — Türkçe kelime sınırı kusuru (kısmen düzeltildi, kalanı sende)

JS'de `\b` ASCII `\w` tabanlıdır. `ı ş ğ ü ö ç İ` kelime karakteri **sayılmaz**.
Sonuç: `\byarattı\b` gibi bir kalıp **hiçbir zaman eşleşmez** — hata vermez,
sessizce ölür.

Kanıt:
```js
/\bseni kim (yarattı|kurdu)\b/.test("seni kim yarattı") // false
/\bseni kim (yarattı|kurdu)\b/.test("seni kim kurdu")   // true
```

Bunun yol açtığı gerçek hatalar: kimlik kapısı pratikte devre dışıydı
(kullanıcıya "bu programın kurucusu Bill Gates" dendi, kaynak
`ebay-kleinanzeigen.de`), ve iç yapılandırma savunmalarında 5 kaçak vardı.

**Araç hazır:** `src/lib/tr-word-boundary.ts` → `unicodeWordPattern(source, flags)`
`\b`'yi Unicode karşılığıyla değiştirir, `/u` ekler, sınır semantiğini korur
("kediler" hâlâ `\bkedi\b` ile eşleşmez).

**Sende kalan iş:** `src/core/understanding/preference-extractor.ts` içindeki
Türkçe kalıplar (satır 157, 168-172, 268, 276-277, 368, 382, 725, 759) hâlâ ham
`\b` kullanıyor. Her birini `unicodeWordPattern` ile dönüştür ve **dönüşümden
önce/sonra hangi girdilerin eşleştiğini gösteren bir çıktı üret** — sessizce
değiştirme, hangi kuralların ölü olduğunu raporla.

### #2 — Türkçe SOV kelime sırası

Kalıplar İngilizce fiil-önce sırasına göre yazılmıştı. Türkçe nesne-fiil
sıralıdır: "yapılandırmayı yazdır" hiçbir kalıba takılmıyordu. Yeni kural
yazarken **her iki sırayı da** kapsa.

### #3 — RAG'ın asıl açığı (en yüksek getirili iş)

`src/modules/brain/retrieval.ts:14` → `RETRIEVAL_VECTOR_DIMENSIONS = 256`

Aday getirmede **birincil filtre 256 boyutlu SHA hash embedding**. Bu semantik
bir vektör değil, kelime hash'i — "araba" ile "otomobil"i yakın görmez.
Gerçek semantik model (`multilingual-e5-small`, 384-dim,
`src/modules/brain/semantic-embedder.ts`) yalnızca **rerank** aşamasında ve
yalnızca semantic compute worker ayaktaysa çalışıyor; worker düşerse sessizce
hash'e geri düşülüyor.

Kritik nokta — kodun kendi yorumu bunu söylüyor (`semantic-embedder.ts:12-13`):
**rerank, hash filtresinin kaçırdığı belgeyi geri getiremez.** Doğru bilgi aday
listesine hiç girmediyse cevap yanlış olur, model ne kadar iyi olursa olsun.

Elyan'ın "saçmalamasının" en büyük tek sebebi büyük olasılıkla budur.

İkincil: indeksler `ivfflat` (`drizzle/0016`, `0017`, `0035`); `hnsw` recall ve
gecikmede belirgin şekilde daha iyi.

**Ama önce ölçüm.** Şu an retrieval kalitesini ölçen **hiçbir şey yok**.
Sıra kesinlikle şu olmalı:
1. Değerlendirme seti: 50-100 gerçek Türkçe soru + beklenen kaynak belge.
2. `recall@k` / `MRR` ölçen bir harness (`npm run` ile çalışan).
3. Baz çizgi sayısını kaydet.
4. **Sonra** e5-384'ü birincil filtre yap, hash'i fallback'e indir.
5. Aynı harness'i çalıştır, öncesi/sonrası sayıyı raporla.
6. `ivfflat → hnsw` geçişini ayrı bir adımda ölç.

Adım 4'ü adım 1-3 olmadan yapma.

### #4 — inference.ts 9458 satır

`src/modules/brain/inference.ts` 9458, `chat/service.ts` ~2500,
`brain/memory.ts` 3999 satır. Kapılar, politikalar, guard'lar iç içe. Bu
oturumdaki sessiz regex ölümü tam olarak bu boyutun semptomuydu.

Yeni özellik eklerken bu dosyaları **büyütme**. Yeni mantığı ayrı modüle
çıkar ve inference.ts'ten çağır. Fırsat buldukça saf fonksiyonları dışarı al
(test edilebilirlik oradan geliyor).

### #5 — Akış metni ile nihai metin ayrışması (kısmen düzeltildi)

Aynı cevap dört ayrı sanitize hattından geçiyordu; kullanıcı akışta bir metin
görüp sonra başkasına dönüştüğüne tanık oluyordu.

Yapılan: `AssistantVisibleTextPolicy` (`src/modules/tasks/service.ts`) ile
opsiyon artık açık parametre; akış deltaları ve dört tamamlanma çağrısı aynı
nesneyi paylaşıyor. `message.completed` olayı artık `revised: boolean` taşıyor.

**Sende kalan iş:**
- Grounding sinyali ancak inference metadata'sıyla kesinleşiyor, bu yüzden akış
  muhafazakâr (`allowPublicProviderReferences: false`) başlıyor. Web araması
  yapılan turlarda kaynak referansları akışta kısıtlı, sonda açılıyor. Bunu
  tamamen yok etmek için grounding kararının üretimden **önce** akış katmanına
  taşınması gerekiyor.
- `revised` bayrağını tüketen bir mobil arayüz yok. Bayrak boşa gidiyor.

### #6 — Mükerrer tur koruması (düzeltildi, ama istemci bağımlılığı var)

`findRecentDuplicateChatTurn` yalnızca `taskId` taşıyan assistant satırlarını
arıyordu; düz sohbet cevaplarının taskId'si olmadığı için görev üretmeyen her
turda koruma **tamamen devre dışıydı**. Düzeltildi.

`buildChatTurnAdmissionLockKey` artık idempotency anahtarına bağlanıyor.
**Doğrulanması gereken:** mobil istemci `Idempotency-Key` başlığını gerçekten
gönderiyor mu? Göndermiyorsa koruma eski içerik-hash davranışına düşer ve
20 saniyelik pencereye mahkûm kalır. Bunu kontrol et ve gerekiyorsa istemci
tarafını da düzelt.

---

## 2. Gemini yolu

### Mevcut durum

Ücretsiz katman altyapısı **zaten kapsamlı**:
`gemini-free-tier-guard.ts`, `gemini-intent-router.ts`, `gemini-quality-judge.ts`,
`gemini-execution-validator.ts`, `gemini-utility-client.ts`,
`gemini-web-synthesizer.ts`.

`gemini-free-tier-guard.ts` içinde `GeminiDataSensitivity` ve
`GeminiFreeDataLineage` tipleri var (profil, bellek, konnektör, ek dosya
izleme). Bunlar tesadüf değil: **ücretsiz katmanda Google veriyi model
eğitiminde kullanır.** Bu koruma katmanı bilerek yazılmış — kaldırma, zayıflatma.

### Sert kısıt

```
GEMINI_FREE_DAILY_REQUEST_LIMIT=200      # tüm sistem, günde
GEMINI_FREE_USER_DAILY_REQUEST_LIMIT=25  # kullanıcı başına
GEMINI_FREE_UTILITY_SAMPLE_PERCENT=10
```

**Bu kotayla ana beyin taşınamaz.** 20 aktif kullanıcıda kişi başı 10 istek
düşer. "Beyni Gemini'ye geçir" bir iyileştirme değil, kullanıcıların gün
ortasında limite çarpması demektir.

### Doğru kullanım — Gemini beynin kendisi değil, beyni iyileştiren araç

1. **Çevrimdışı/toplu işler.** RAG değerlendirme seti üretimi, altın-cevap
   etiketleme, zor vaka madenciliği. Kotayı yormaz, gerçek kullanıcı verisi
   gerektirmez. **En yüksek öncelik bu.**
2. **Embedding fine-tune için eğitim verisi üretimi.** Bir kez çalışır, asıl
   RAG sıçramasını besler.
3. **Quality judge'ı örneklemeyle tut** (zaten %10). Yeterli sinyal verir.

Gemini'yi sıcak yola (her turda çağrılan) koyarken çok dikkatli ol: her ekleme
kotadan yer. Yeni bir Gemini çağrısı ekliyorsan, kaç istek/gün tükettiğini
hesapla ve brifingde belirt.

---

## 3. Groq yolu

`ELYAN_SHARED_BRAIN_PROVIDER=groq` — ana üretim yolu burası.
Model seçimi: `groq-models.ts`, `model-resolution.ts`, `provider-selection.ts`.
Workload'a göre model ayrımı var (fast / balanced / planning / vision).

İyileştirme alanları:
- **Workload→model eşlemesi ölçülmemiş.** Hangi workload'da hangi modelin
  gerçekten daha iyi olduğu ölçülmedi; `benchmarks/` ve
  `npm run brain:benchmark` altyapısı var, kullan.
- **Fallback davranışı.** `ELYAN_SHARED_BRAIN_FALLBACK_PROVIDER` boş. Groq
  kesintisinde ne oluyor? Fail-closed mı, sessiz bozulma mı? Test et.
- Yönlendirme kararlarını regex yerine öğrenilmiş sınıflandırıcıya taşımak
  orta vadede en değerli iş (bkz. Zemin gerçeği #1 — regex tabanlı yönlendirme
  kırılgan olduğunu kanıtladı).

---

## 4. MCP yolu

`src/modules/integrations/`: `mcp-probe.ts` (464 satır), `provider-registry.ts`,
`service.ts`, `tenant-isolation.test.ts`.

Dikkat edilecekler:
- **Kiracı izolasyonu birinci sınıf kısıt.** `tenant-isolation.test.ts` var;
  yeni konnektör eklerken bu testi genişlet. Bir kullanıcının konnektör verisi
  başka bir kullanıcının turuna asla sızmamalı.
- **MCP araç sonuçları güvenilmez girdidir.** Araç çıktısında gelen metni
  talimat gibi işleme. `inference.ts:7208` civarındaki yorum bu sınıf bir
  sorunu zaten not ediyor ("araç sonucuyla asla…"). Bu ilkeyi koru ve
  genişlet: harici içerik veri'dir, komut değil.
- `mcp-probe.ts` protokol hatalarını tipli kodlara çeviriyor
  (`MCP_PROTOCOL_ERROR`). Yeni sağlayıcı eklerken aynı fail-closed kalıbı izle.
- Yazma (write) işlemleri `connector-write-approvals.ts` üzerinden onaya
  bağlı — bu kapıyı atlatan kısayol ekleme.

---

## 5. world_signals yolu

`src/core/understanding/world-signal-derived.ts` (491 satır).
`DERIVED_SIGNAL_ALLOWLIST` ile sınırlı türetilmiş sinyaller
(`energy_rhythm`, `planning_style`, `schedule_pressure_pattern`,
`mobility_context`, …) → `situationalHints` / `behavioralHints` /
`environmentHints` kovalarına dönüşüyor ve context packet'e giriyor.

İyileştirme alanları:
- **Allowlist bilinçli bir kısıt.** Yeni sinyal türü eklerken allowlist'e
  eklemeyi unutma, ama gizlilik sınıflandırmasını da (`privacy` alanı)
  doldur. Sinyal ne kadar kişiselse o kadar dar kapsamda kullanılmalı.
- **Sinyal→ipucu dönüşümü ölçülmemiş.** Bu ipuçlarının cevap kalitesini
  gerçekten artırıp artırmadığı bilinmiyor. A/B ölçümü kurulabilir: aynı
  soruyu ipuçlu/ipuçsuz çalıştırıp `evaluateBrainAnswer` skorlarını karşılaştır.
- **Güven eşiği.** `confidence` alanı var ama düşük güvenli sinyallerin prompt'a
  girip girmediğini kontrol et. Zayıf sinyal, gürültüden kötüdür — modeli
  yanlış yönlendirir.
- Sinyaller kişisel veri taşıyor; Gemini ücretsiz katmanına giden yollarda
  `GeminiFreeDataLineage.worldContext` bayrağının doğru işaretlendiğini doğrula.

---

## 6. Önerilen sıra

| # | İş | Neden önce |
|---|---|---|
| 1 | `preference-extractor.ts` `\b` dönüşümü | Ölü kurallar, düşük efor, hemen ölçülebilir |
| 2 | Retrieval değerlendirme harness'i + baz çizgi | Bundan sonraki her şeyin ön koşulu |
| 3 | e5-384 birincil filtre, hash fallback | En yüksek getiri — ama 2 olmadan yapma |
| 4 | `ivfflat → hnsw` | Ucuz, ölçülebilir kazanç |
| 5 | Mobil `Idempotency-Key` doğrulaması | Çift cevap korumasını tamamlar |
| 6 | Grounding kararını akış öncesine taşı | `revised` farkını kökten kaldırır |
| 7 | world_signals ipuçlarının A/B ölçümü | Fayda kanıtlanmamış, ölçülmeli |

Her adımda: değişiklikten **önce** ve **sonra** sayıyı göster. Sayı yoksa iş
bitmemiştir.

---

## 7. Teslim formatı

Her görev için şunu üret:
1. Ne değişti (dosya:satır).
2. Hangi hatayı/eksiği kapattığının **çalıştırma kanıtı** (öncesi/sonrası çıktı).
3. Yanlış pozitif / regresyon kontrolü çıktısı.
4. `npm run check` ve `npm test` sonucu.
5. Yapamadığın veya doğrulayamadığın şeyi **açıkça** yaz. Doğrulanmamış bir
   değişikliği "tamam" diye teslim etme — bu kod tabanındaki en pahalı hatalar
   böyle birikti.
