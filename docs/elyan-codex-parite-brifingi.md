# Elyan Parite Brifingi — Ajan Döngüsü Olgunlaştırma (Codex görev dokümanı)

Hedef: Elyan'ın uçtan uca ajan döngüsünü (karar → plan → onay → yürütme →
görünürlük → devam ettirme) olgun bir kodlama-ajanı ürününün akışıyla aynı
kaliteye getirmek. Referans davranış modeli aşağıda "hedef döngü" olarak
TARİF edilmiştir — hiçbir üründen isim, marka, metin kopyalanmaz. Kullanıcıya
görünen her şey yalnızca **Elyan**'dır.

---

## 0. Çalışma sözleşmesi (bunlara uymadan tek satır yazma)

1. **Tek başına ürün kararı VERME.** Her iş paketinin sonunda "Kullanıcıya
   sorulacaklar" listesi var. Pakete başlamadan bu soruları kullanıcıya sor,
   cevapları aldıktan sonra kısa bir uygulama özeti yaz ve onaylat. Cevap
   gelmeden varsayılan seçme.
2. **Ölçmeden iyileştirme yapma.** Davranış değiştiren her iş: önce mevcut
   davranışı gösteren test/çıktı, sonra değişiklik, sonra yeni çıktı.
3. **Baz çizgi: `npm run check` temiz + 1387 test yeşil** (elyan-backend),
   `flutter analyze` temiz + 638 test yeşil (mobile-elyan). Bu sayılar düşerse
   sebebini açıkla.
4. **Sağlayıcı/ürün adları kullanıcıya asla sızmaz.** Codex, Claude, Gemini,
   Groq, OpenAI, Anthropic, Llama, model id'leri — hiçbiri kullanıcı-görünür
   metinde, blokta, hata mesajında, store metninde geçmez. Tek doğruluk
   kaynağı: `src/lib/elyan-public-identity.ts`. Bu brifingdeki işlerden biri
   bu taramayı otomatikleştirmek (WS6).
5. **Fail-closed kapıları zayıflatma.** Onay kapıları (`side_effect` staging,
   `connector-write-approvals.ts`), gizlilik sınıfları, kiracı izolasyonu
   (`tenant-isolation.test.ts`) aynen korunur; kısayol ekleme.
6. **Deploy yalnız kullanıcı açıkça isteyince.** `bash scripts/deploy-v1-release.sh`
   — çıkış kodunu `| tail` ile maskeleme, `DEPLOY_EXIT=$?` yakala.
7. **Regex yazacaksan** `src/lib/tr-word-boundary.ts` → `unicodeWordPattern`
   kullan ve Türkçe ekli biçimlerle test et (ham `\b` Türkçede sessizce ölür).
8. **Eşzamanlılık uyarısı:** Bu repoda yakın geçmişte iki ajan aynı anda
   çalışırken kayıp güncelleme yaşandı. Çalışırken başka ajan oturumu
   açık olmamalı. Her commit sonrası `git show HEAD --stat` ile içeriğin
   gerçekten commit'e girdiğini doğrula.
9. **Teslim formatı (her iş paketi):** ne değişti (dosya:satır) → öncesi/sonrası
   çalıştırma kanıtı → yanlış pozitif/regresyon kontrolü → test sonuçları →
   yapamadıkların/doğrulayamadıkların açıkça.

---

## 1. Hedef döngü (parite tanımı)

Kullanıcının bir isteği şu yaşam döngüsünden geçer ve **her aşama kullanıcıya
Elyan diliyle görünür**:

```
istek
 → KARAR: niyet + rota + gerekçe (tek cümle, kullanıcı dilinde)
 → PLAN: adım listesi görünür bir kartta; her adımın durumu canlı
   (bekliyor → çalışıyor → bitti/başarısız/atlandı)
 → ONAY: yan-etkili adımlar (gönder/oluştur/sil/yaz) plan İÇİNDE onay
   rozetiyle durur; kullanıcı onaylayınca kaldığı yerden sürer
 → YÜRÜTME: her adımın insan-dili etiketi, süresi ve kısa sonucu akışta
   görünür; ham araç adı/JSON asla görünmez
 → DOĞRULAMA: sonuç kanıta bağlanır (araç sonucu/kaynak); kanıtsız iddia yok
 → CEVAP: kısa nesir + yapılandırılmış kart(lar); tek veri tek yüzey
 → DEVAM: oturum herhangi bir cihazdan açıldığında aynı plan, aynı adım
   durumları, aynı bağlamla kaldığı yerden devam eder; koşan görev varsa
   canlı izlenir
```

Bu döngünün parçaları Elyan'da **büyük ölçüde zaten var** — iş çoğunlukla
birleştirme, görünür kılma ve cilalama. Aşağıdaki envantere göre çalış.

---

## 2. Mevcut durum envanteri (doğrulanmış yollar)

| Katman | Ne var | Nerede |
|---|---|---|
| Karar | routeDecision (intent, rota, gerekçe, `userFacingMessage`) | `src/modules/routing-policy/service.ts`, inference metadata |
| Plan | `turn_envelope.agent_plan.steps` (tool_request'li adımlar), `goal_progress` bloğu, desktop work-order `planPreview.steps` | `src/modules/brain/agent-plan.ts`, `turn-envelope.ts`, `src/modules/tasks/desktop-work-order.ts` |
| Onay | `side_effect` staging + onay kartı + runtime token'lı onay rotası; autonomy faz flag'leri (Faz 2-4 kapalı, `enable-autonomy-phase.sh`) | `src/modules/brain/connector-write-approvals.ts`, tool-registry `sideEffectBlocked` |
| Yürütme | agent tool loop (read inline, write onaylı), tipli sonuçlar, `connector_result` kartı | `src/modules/brain/agent-loop.ts`, `tool-registry.ts`, `connector-result-blocks.ts` |
| Görünürlük | `task_trace` bloğu (intent/route/plan/context/tool/verify/response adımları, canlı checklist), reasoning stream kanalı, trace telemetri rozetleri | `src/modules/chat/task-trace.ts` civarı, mobil `task_trace` widget'ı |
| Devamlılık | chat sessions + `rollingSummary` + `lastDerivedContextDigest` + dialogue state + continuity summary; mobil oturum listesi | `src/modules/chat/service.ts` (`enrichChatMetadataForRequest`, `buildSessionChatContextMetadata`) |
| Cihazlar arası | desktop dispatch (targetDeviceId, work order, pairing), runtime WS | `src/modules/tasks/service.ts`, `/v1/realtime/runtime` |
| Kimlik | kamu kimliği ve sağlayıcı-adı redaksiyonu | `src/lib/elyan-public-identity.ts`, `response-policy.ts` |
| Mobil | blok tabanlı chat (blocks v2), plan-adımlı+inline onay kartları, connector kartı, trace çipleri | `mobile-elyan/lib/features/tasks/...` |

Bilinen eksikler (bu brifingdeki işlerin çekirdeği):
- Plan, onay ve yürütme üç AYRI görsel dil kullanıyor (goal_progress /
  approval kartı / task_trace) — tek tutarlı "görev kartı" yok.
- `message.completed` içindeki `revised: boolean` bayrağını mobil tüketmiyor.
- Onay "modu" kavramı yok: her yan-etki her zaman soruyor; kullanıcı
  başına otonomi seviyesi seçilemiyor (flag'ler var ama ürünleşmedi).
- Koşan bir görevi başka cihazdan açınca canlı adım durumu garantili değil.
- Sağlayıcı-adı sızıntısı taraması manuel; CI kapısı yok.

---

## 3. İş paketleri

Sırayla yap; her paketten önce sorularını sor, onay al, bitince kanıtla teslim et.

### WS1 — Tek görünür görev kartı: plan + adım durumları + inline onay

**Hedef:** Çok adımlı her turda kullanıcı TEK bir görev kartı görür: başlık,
adım listesi, her adımın canlı durumu, yan-etkili adımda inline onay düğmesi.
`task_trace`, `goal_progress` ve onay kartı bu tek kartın içinde birleşir
(ayrı üç kart üst üste düşmez).

**Yapılacak:**
- Backend: `agent_plan.steps` + tool loop sonuçları + staged approval'ı tek
  bir blokta birleştiren yapı. Yeni blok tipi İCAT ETMEDEN önce mevcut
  `task_trace` bloğunu genişletmek mümkün mü değerlendir (adımlara
  `approval?: {token, title, lines}` ve `resultSummary?` alanı eklemek gibi).
  Şema `src/contracts/domain.ts`'te; mobil parser `assistant_message_block.dart`.
- SSE akışında adım durumu değiştikçe blok güncellenmeli (stableBlockId
  korunarak replace); mobil tarafta aynı kartın yerinde güncellenmesi.
- Onaylanan adım sonrası yürütme kaldığı adımdan sürmeli (mevcut approval
  resume akışına bağlan; yeni yürütme yolu yazma).

**Kabul kriteri:** "Yarın 9'a toplantı koy ve Ali'ye mail at" tek kartta:
2 adım, ikisi de onay rozetli; ilki onaylanınca adım 1 "bitti"ye döner,
kart aynı kalır. Ekran kaydı + test.

**Kullanıcıya sor:**
1. Kart yoğunluğu: her turda mı görünsün, yalnız 2+ adımlı/onaylı turlarda mı?
2. Biten görevin kartı ne olsun: tek satıra mı çöksün (mevcut trace davranışı),
   açık mı kalsın?
3. Onay düğmeleri kartın içinde mi, ayrı alt-sayfa (sheet) mi?

### WS2 — Onay modları (kullanıcı-başına otonomi seviyesi)

**Hedef:** Kullanıcı ayarlardan seçer: **(a) Hep sor** (bugünkü davranış),
**(b) Okumalar serbest, yazmalar sorsun** (fiilen bugünkü davranış —
adlandırıp görünür kıl), **(c) Güvenli yazmalar da serbest** (yalnız
geri-alınabilir/idempotent yazmalar; gönder/sil her zaman sorar).

**Yapılacak:**
- Backend: kullanıcı ayarı (DB alanı + `/v1` ayar endpoint'i) → tool-registry
  kapılarına bağla. `side_effect` + `non_idempotent` HER MODDA onay ister —
  bu değişmez. (c) modu yalnız `idempotent_write` sınıfını serbest bırakır.
  Mevcut autonomy faz flag'leriyle (enable-autonomy-phase.sh) çakışma var mı
  incele; varsa faz flag'lerini bu ayara bağlayarak TEK mekanizmaya indir.
- Mobil: Ayarlar'da "Elyan'ın onay davranışı" bölümü; mevcut ayar diline uy
  (`settings_screen.dart`, ElyanKit bileşenleri).

**Kabul kriteri:** Mod (a)'da gmail.send onay kartı üretir; mod değişimi
oturum ortasında etkili olur; `non_idempotent` hiçbir modda onaysız geçmez
(test). Quota/limit kapıları etkilenmez.

**Kullanıcıya sor:**
1. Varsayılan mod hangisi olsun?
2. (c) modunda hangi işlemler "güvenli yazma" sayılsın? (örn. takvime etkinlik
   ekleme geri alınabilir mi sizce?)
3. Mod değişimi ek doğrulama istesin mi (örn. (c)'ye geçerken uyarı)?

### WS3 — Yürütme görünürlüğü: insan-dili adım transkripti

**Hedef:** Her araç çağrısı akışta insan-dili bir satır olarak görünür:
"Gelen kutunu tarıyorum… (0.4sn) — 5 e-posta bulundu". Ham araç adı, JSON,
argüman asla görünmez.

**Yapılacak:**
- Backend: araç → kullanıcı-dili etiket sözlüğü (TR öncelik; `gmail.search`
  → "Gelen kutusu taranıyor" gibi) + sonuç özetleyici (tool output →
  tek cümle). `summarizeToolResultsForMetadata` çıktısını kullanıcı-görünür
  değil, İÇ veri olarak koru; görünür satırlar ayrı ve redaksiyon
  (`elyan-public-identity`) süzgecinden geçmiş olmalı.
- Bu satırlar WS1 kartındaki adımların alt metni olur (ayrı mesaj basma).
- Hata halinde: teknik kod değil, `connectorFailureReply` sınıfı dürüst
  Türkçe metin (mevcut sınıflandırma `connectorFailureKind`'ı kullan).

**Kabul kriteri:** "Mailleri oku" akışında kullanıcı şunu görür: kart →
"Gelen kutusu taranıyor…" → "5 e-posta bulundu" → kısa özet + connector
kartı. Ham `gmail.search` metni hiçbir yüzeyde yok (test + ekran kaydı).

**Kullanıcıya sor:**
1. Süreler görünsün mü ("0.4sn") yoksa sade mi kalsın?
2. Web araması da aynı transkripte girsin mi ("Web'de araştırıyorum…")?

### WS4 — Karar şeffaflığı: "neden böyle yaptım"

**Hedef:** Cevabın altında isteğe bağlı, katlanabilir tek satır:
"Elyan bunu sohbet olarak işledi çünkü…" / "Masaüstünde çalıştırdım çünkü…".
Mevcut `routeDecision.userFacingMessage` + reasoning kanalı bunun hammaddesi.

**Yapılacak:** `userFacingMessage`'ı blok olarak taşı (mevcut `context_signal`
veya trace kartının başlık altı; YENİ blok tipi açmadan önce mevcutları
değerlendir). Reasoning stream'iyle çakışmasın: reasoning "düşünme süreci",
bu ise "rota gerekçesi" — ikisi tek yerde birleşecekse WS1 kartının başlığı
altına.

**Kullanıcıya sor:**
1. Bu satır varsayılan görünür mü, ayarla mı açılsın?
2. Reasoning (düşünme süreci) ile aynı katlanır bölümde mi birleşsin?

### WS5 — Oturum devamlılığı ve `revised` tüketicisi

**Hedef:** Mobilden herhangi bir oturum açıldığında: geçmiş bloklar aynen
(kart durumlarıyla) gelir; koşan görev varsa karta canlı bağlanılır; akışta
gösterilen metin sonradan revize edildiyse kullanıcı bunu fark eder.

**Yapılacak:**
- `message.completed` içindeki `revised: boolean` bayrağına mobil tüketici:
  revize edilen mesajda sessiz, küçük bir "güncellendi" rozeti (tasarım
  ElyanKit diline uygun). Bayrağın backend'de doğru set edildiğini testle
  doğrula (`AssistantVisibleTextPolicy`, `src/modules/tasks/service.ts`).
- Koşan görev: oturum açılışında `status=running` mesaj varsa SSE'ye
  yeniden abone olup kartın canlı güncellenmesi — mevcut RealtimeController
  akışında bunun koptuğu senaryoları bul (uygulama kill → aç, cihaz değiş).
  Bulduklarını ÖNCE listeyle kullanıcıya göster, sonra düzelt.
- `GET /messages` çıktısının canlı akışla AYNI blokları vermesi zaten
  büyük ölçüde sağlandı (compose passthrough); WS1 kartı için de aynı
  garantiyi test altına al.

**Kabul kriteri:** Görev koşarken uygulamayı kapatıp açınca kart aynı
adım durumlarıyla gelir ve canlı sürer; revize mesajda rozet görünür.

**Kullanıcıya sor:**
1. "Güncellendi" rozeti nasıl görünsün — dokununca eski metni gösteren bir
   ayrıntı ister misin, yoksa yalnız rozet mi?
2. Cihazlar arası: telefonda başlayan sohbete masaüstünden devam etme bu
   pakete girsin mi, ayrı paket mi olsun?

### WS6 — Kimlik hijyeni: otomatik sızıntı taraması

**Hedef:** Kullanıcı-görünür hiçbir yüzeyde sağlayıcı/ürün adı geçmediğini
CI'da otomatik kanıtlamak.

**Yapılacak:**
- Backend: kullanıcı-görünür string üretim noktaları için test — blok
  builder çıktıları, `connectorFailureReply` sınıfı metinler, humanize
  katmanı, onay kartı metinleri `containsProtectedElyanDisclosure`
  süzgecinden geçirilir; yasak adlar listesine codex/claude/gemini/groq/
  openai/anthropic/llama + model id kalıpları dahil (TR ekli biçimleriyle,
  `unicodeWordPattern` ile).
- Mobil: `lib/` altında kullanıcı-görünür literal'lerde aynı tarama
  (basit bir dart test + allowlist mekanizması; örn. package adları gibi
  meşru teknik geçişler allowlist'te).
- Mevcut sızıntı bulursan: listeyi kullanıcıya göster, metinleri ONAYLATIP
  değiştir (kendi kafana göre yeni ürün adı uydurma).

**Kabul kriteri:** `npm test` + `flutter test` içinde çalışan, yasak-ad
sızıntısında kırmızıya düşen testler; mevcut ihlaller temizlenmiş.

**Kullanıcıya sor:**
1. İç loglarda/telemetride sağlayıcı adı kalabilir mi (öneri: evet, yalnız
   kullanıcı-görünür yüzeyler taransın)?
2. Bulunan sızıntı metinleri için önerilen Elyan karşılıklarını tek tek mi
   onaylamak istersin, toplu mu?

### WS7 — Mobil cila: kart etkileşimleri

WS1-5'in mobil ayağı ayrı paket olarak: görev kartı widget'ı, adım satırları,
inline onay, "güncellendi" rozeti, koşan göreve yeniden bağlanma. UI Kit
kuralına uy: ortak bileşenler `lib/ui/kit/elyan_kit.dart`'tan; ad-hoc
buton/menü kopyası yazma. Blok şeması değişirse `block_registry.dart` +
`assistant_message_block.dart` + `block_renderer_test.dart` birlikte güncellenir.

**Kullanıcıya sor:** WS1 sorularıyla birlikte tasarım tercihleri (kart
köşe/blur dili mevcut Cupertino+glass çizgisiyle aynı mı kalsın vb.).

---

## 4. Başlamadan sorulacak İLK sorular (hepsini tek mesajda sor)

1. Paket sırası önerim WS1 → WS3 → WS5 → WS2 → WS4 → WS6 → WS7. Onaylıyor
   musun, değiştirmek istediğin öncelik var mı?
2. WS1: görev kartı her turda mı, yalnız çok-adımlı/onaylı turlarda mı?
3. WS2: varsayılan onay modu ne olsun? "Güvenli yazma" tanımına ne girsin?
4. WS3: adım sürelerini gösterelim mi? Web araması transkripte girsin mi?
5. WS4: rota gerekçesi varsayılan görünür mü?
6. WS5: cihazlar arası devam bu kapsama girsin mi?
7. WS6: sızıntı bulunursa metin onayını tek tek mi istersin?
8. Deploy politikası: her paket sonunda mı deploy edeyim, hepsi bitince mi?
9. Masaüstü runtime (`/Users/emrekoca/Desktop/elyan`) bu pariteye şimdi
   dahil mi, yalnız backend+mobil mi?

---

## 5. Yapılmayacaklar

- Sağlayıcı/ürün adı hiçbir kullanıcı-görünür yüzeye yazılmaz; "hedef ürünün"
  metinleri/markası kopyalanmaz — davranış paritesi, içerik kopyası değil.
- Onay kapısını atlatan hiçbir kısayol; `non_idempotent` her modda onaylı.
- Mock/sahte veri yok; her şey gerçek API ve gerçek durumla test edilir.
- `inference.ts`/`chat/service.ts`/`memory.ts` BÜYÜTÜLMEZ — yeni mantık ayrı
  modülde, saf fonksiyon, testli.
- Kullanıcıya sorulmadan görsel dil/dizayn değişikliği yapılmaz.
