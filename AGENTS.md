# Elyan Backend — Çalışma Sözleşmesi ve Aktif Oturum Devri

Bu dosya yeni bir oturumun mevcut işi sıfırdan araştırmadan güvenle sürdürmesi için tek başlangıç kaynağıdır. Önce tamamını oku, sonra repo durumunu doğrula.

## 1. Repo ve Kesin Checkpoint

- Repo: `/Users/emrekoca/elyan-backend`
- Branch: `perf/chat-first-token`
- HEAD: `4713a35454abcf761f87e532363b437b3a6bd0af`
- HEAD commit mesajı: `fix: C NLP takıldığında sessizce JS yedeğine düşüyorduk`
- Tarih: 2026-08-28
- Aktif değişiklikler commit edilmedi.
- Deploy yapılmadı.
- Bu değişikliklerde test, build, eval veya `tsc` çalıştırılmadı.
- Önceki HEAD için kullanıcı `tsc --noEmit` temiz bilgisini verdi; bu bilgi mevcut dirty diff'i doğrulamaz.

Yeni oturumun ilk komutları yalnız durum okumalıdır:

```bash
cd /Users/emrekoca/elyan-backend
git branch --show-current
git rev-parse HEAD
git status --short
git diff --check
```

Dirty worktree'yi resetleme, stashleme, geri alma veya başka branch'e taşıma. Mevcut değişikliklerin tamamı aktif işin parçasıdır.

### Sahibi Biz Olmayan Değişiklik

`DEVIR.md` silinmiş görünüyor. Bu silme bu çalışma sırasında başka bir aktör/kullanıcı tarafından ortaya çıktı. Dosyayı geri getirme, silmeyi stage etme, içeriğini değiştirme veya kendi işinmiş gibi raporlama. Olduğu gibi koru.

## 2. Kullanıcının Aktif Talimatı

Yalnız backend değiştirilecek:

- Mobile repo'suna dokunma: `/Users/emrekoca/Desktop/mobile-elyan`
- Desktop repo'suna dokunma: `/Users/emrekoca/Desktop/elyan`
- Yeni mimari veya paralel runtime kurma; mevcut Elyan yapısını geliştir.
- Dış REST, SSE ve `elyan_blocks.v2` sözleşmelerini kırma.
- Yeni kod içi açıklama satırı ekleme.
- Test dosyası ekleme.
- Kullanıcı talimatı değişmedikçe test, build, eval veya `tsc` çalıştırma.
- Kullanıcı ayrıca istemedikçe commit alma ve deploy yapma.
- Gereksiz sohbet veya plan tekrarı yapma; doğrudan kodu tamamla.

## 3. Elyan Mimari Sınırı

Elyan chatbot değil; anlayan, planlayan, araç kullanan, doğrulayan, state/hafıza yöneten bir ajan sistemidir.

```text
Mobile/Desktop client
  -> Backend control-plane
  -> canonical understanding + routing + safety
  -> server brain / retrieval / memory / read-only server tools
  -> typed result + event/state truth
  -> REST/SSE/elyan_blocks.v2
```

Backend:

- auth, billing, devices, routing, task state, retrieval, memory, learning, model orchestration ve realtime truth yönetir;
- private yerel dosya, browser, computer-use veya masaüstü aksiyonu çalıştırmaz;
- private local execution gereken işi mevcut desktop task flow'una yönlendirir;
- client metadata'yı authoritative state saymaz;
- kullanıcı/session kimliği eşleşmeyen state veya hafızayı prompt'a sokmaz.

Desktop local/private executor'dır. Mobile yalnız backend sözleşmesini tüketir; execution authority değildir.

## 4. Kırılmayacak Public Sözleşmeler

- `/v1/chat/messages`
- `/v1/realtime/stream`
- `/v1/tasks`
- `/v1/billing/*`
- SSE: `message.created`, `message.delta`, `message.completed`, `heartbeat`
- `elyan_blocks.v2`

Yeni alan eklemeli olabilir. Mevcut alan silinmez, yeniden adlandırılmaz veya sessizce farklı anlamda kullanılmaz.

Streaming monotoniktir: yayımlanan delta geri alınmaz. Structured table/chart turunda doğrulama gerekiyorsa delta yayımlanmadan tamponlanır.

## 5. Aktif İş: Backend Bağlam, Hafıza ve RAG Onarımı

Amaç: model kullanıcıyı ve önceki typed cevabı kaybetmeden anlamalı; takip sorusunu gereksiz web aramasına çevirmemeli; hafıza tek semantik aramayla bütçe içinde gelmeli; tool sonucu normal evidence/factuality/finalization zincirinden geçmeli; uydurma tablo/grafik veya sahte clarification oluşmamalı.

Bulunan kök nedenler:

1. `mobile_chat_fast`, canonical understanding yerine `emptyUnderstanding` kullanıyordu.
2. Fast memory aynı sorgu ve adayları ikinci kez embed ediyordu; 320 ms dolunca hafıza yok oluyordu.
3. `sourceReference` alt katmanlarda tekrar türetiliyordu.
4. Önceki table/chart bloklarının gerçek satır ve noktaları modele taşınmıyordu.
5. Server tool-loop erken return ile evidence, factuality, memory write, goal ve typed-block zincirini atlıyordu.
6. `planIntent` tekrar hesaplanıp normal konuşmaya sahte clarification ekliyordu.
7. Free plan katalog limiti 5 saatlik pencerede yalnız 4 budget unit idi.

## 6. Uygulanmış Ancak Henüz Doğrulanmamış Değişiklikler

### Canonical Understanding ve Kaynak Referansı

- `buildFastTaskUnderstanding` eklendi; fast/durable chat yolları artık typed intent + understanding envelope üretiyor.
- Chat create aşamasında önceki konuşma server tarafından okunuyor.
- `authoritativeSourceReference` bir kez belirlenip output contract'a taşınıyor.
- “Az önce…”, “bunu…”, “son cevabını…”, “verdiğin/yazdığın/oluşturduğun…” takipleri önceki cevaba bağlanıyor.
- Eski fallback davranışı geriye uyumluluk için korunuyor.

### Typed Reference Context

- `elyan.reference_context.v1` eklendi.
- Alanlar: source reference, source message ID, block digest, bounded text, table rows/columns, chart series/points, artifact identity.
- Veri yalnız server'da saklanan normalize edilmiş `elyan_blocks.v2` bloklarından türetiliyor.
- Snapshot hash'i typed turn verisini kapsıyor.
- Snapshot verification, `priorAssistant` ve `referenceContext` değerlerini hash'e bağlı prior turns ile çapraz doğruluyor.
- Önceki typed table/chart takiplerinde retrieval ve web araçları kapatılıyor; kullanıcı açıkça güncel/harici kaynak isterse yeniden açılıyor.

### Fast Context ve Memory

- `elyan.fast_context.v1` paketi eklendi.
- Canonical facts/preferences, dialogue state/open loops, en fazla 3 semantik hafıza ve typed reference context taşınıyor.
- Dialogue state, canonical memory ve semantic memory aynı 320 ms deadline altında paralel okunuyor.
- Model prompt'una user/session/memory ID listesi değil, sınırlı güvenli state projeksiyonu giriyor.
- `searchBrainMemory` artık `semanticScore` döndürüyor ve opsiyonel `budgetMs` kabul ediyor.
- Fast path ikinci embedding/rerank yapmıyor.
- Eşik 0.86, aday 6, çıktı 3 ve bütçe 320 ms.
- Stale, contested, superseded, deleted veya inactive kayıtlar prompt'a girmiyor.
- `semanticScore` type alanı eski cache/test literal uyumluluğu için optional; fast path eksik değeri 0 sayıyor.

### RAG ve Query

- Retrieval sorgusu önce typed subject/topic, sonra entity, sonra bounded prompt fallback'inden kuruluyor.
- Kullanıcının tüm “Az önce verdiğin tabloda…” cümlesi web sorgusu yapılmıyor.
- Retrieval `lowConfidence`, semantic response gate'e `insufficient` evidence olarak taşınıyor.
- Low-confidence table/chart/web_search blokları reddediliyor.

### Tool Loop

- Server tool-loop artık erken return etmiyor.
- Araç istemeyen ilk model yanıtı ikinci provider çağrısı yapılmadan normal zincirde kullanılıyor.
- Tool sonuçları `AgentToolResult` biçimine normalize edilip dialogue, memory/goal ve completion metadata yollarına aktarılıyor.
- Table/chart isteklerinde tool sonuçlarından `authoritativeArtifactData` üretiliyor.
- Request-scoped allowlist artık yalnız modele gösterimde değil execution anında da uygulanıyor.
- Model, advertise edilmemiş veya write/side-effect bir tool adını uydurursa çalıştırılmıyor.
- Son turda tool call kabul edilmiyor.
- Provider timeout ve request key seed tool-loop turlarına taşınıyor.
- Tool kullanılmış ama final text boş kalmışsa unguided ikinci normal provider çağrısına düşülmüyor; bounded retry yoluna kalıyor.

### Table, Chart ve Clarification

- Önceki typed table/chart verisi `VerifiedNumericPoint` olarak çıkarılıyor.
- “En yüksek/en düşük” cevabı model nesrinden değil typed noktalardan deterministik üretiliyor.
- Yüzde/para birimli hücreler mevcut `coerceFiniteNumber` ile okunuyor.
- Numeric table/chart blokları prompt/context/tool/reference kanıtı olmadan yayımlanmıyor.
- Chart bloğu yoksa “işte grafik/trend” vaat cümlesi temizleniyor; doğrulanmış veri yoksa açık fallback veriliyor.
- Generic plan clarification branch kaldırıldı.
- `planIntent` yalnız canonical turn contract'tan okunuyor.

### Kota

- Free plan `fiveHourBudgetUnits`: 4 -> 12.
- `dailyBudgetUnits`: 4 -> 12 ve mevcut 5 saatlik pencere alias'ı olarak kalıyor.
- `weeklyBudgetUnits`: 72, değişmedi.

## 7. Değişen Dosyalar

- `src/core/understanding/output-contract.ts`
- `src/core/understanding/user-understanding-service.ts`
- `src/modules/billing/catalog.ts`
- `src/modules/brain/fast-path-memory.ts`
- `src/modules/brain/inference.ts`
- `src/modules/brain/memory.ts`
- `src/modules/brain/semantic-response-gate.ts`
- `src/modules/brain/tool-loop.ts`
- `src/modules/chat/chat-context-snapshot.ts`
- `src/modules/chat/service.ts`
- `src/modules/tasks/completion-blocks.ts`
- `src/modules/tasks/service.ts`

`AGENTS.md` bu devir için yeniden yazıldı. `DEVIR.md` silinmesi bu çalışmanın parçası değildir.

## 8. Tam Kesilen Nokta ve Sonraki Adım

Oturum tam olarak tool sonucu evidence zinciri incelenirken kesildi.

Mevcut durum:

- Server tool-loop sonuçları `AgentToolResult` oluyor.
- `summarizeToolResultsForMetadata` yalnız tool adı, durum, digest, output key'leri ve result count taşıyor.
- `factuality-gate.ts::collectEvidenceSources`, `metadata.toolResults` okuyor ama gerçek bounded tool değerlerini görmüyor.
- Table/chart için `authoritativeArtifactData` sayısal kanıt sağlıyor.
- Genel read-only tool sonuçlarındaki isim/tarih/sayı iddiaları için factuality gate'in güvenli bir içerik kanalı hâlâ tamamlanmalı.

Kritik güvenlik kuralı:

- Ham/private connector veya tool output'unu `result.metadata` içine koyma.
- Governed response review logging, `activeInference.metadata` alanını spread ediyor; raw tool verisi oraya konursa log/public metadata sızıntısı olabilir.
- Çözüm internal-only bounded evidence packet/channel olmalı ve public/review metadata oluşmadan çıkarılmalı; alternatif olarak doğrulanmış typed source block üretip gate'in yalnız o bounded bloğu okuması sağlanmalı.
- `evidence-packet.ts` mevcut typed packet yapısını kullanıyor; yeni paralel sözleşme icat etme.

Sonraki oturum:

1. `src/modules/brain/inference.ts`, `tool-loop.ts`, `factuality-gate.ts`, `evidence-packet.ts` akışını bu noktadan tamamla.
2. Tool evidence'i kullanıcı/log yüzeyine sızdırmadan factuality gate'e bağla.
3. `authoritativeArtifactData`, typed block ve low-confidence kararlarının aynı kanıtı kullandığını statik olarak kontrol et.
4. Son küçük patch'leri statik incele:
   - execution allowlist map,
   - timeout/requestKeySeed,
   - empty final text retry davranışı,
   - snapshot reference cross-check,
   - optional `semanticScore` uyumluluğu.
5. Yeni yorum satırı eklenmediğini ve yalnız izinli dosyaların değiştiğini diff üzerinden kontrol et.
6. Kullanıcının test yasağı devam ediyorsa yalnız `git diff --check` ve diff/status incelemesi yap.
7. Commit/deploy yapmadan sonucu kısa raporla.

## 9. Kabul Senaryoları

Kodun hedef davranışı:

- Selamlama normal cevap üretir; clarification kartı üretmez.
- “Beni nasıl tanıyorsun?” canonical memory kullanır ve web araması yapmaz.
- “Az önce verdiğin tabloda en yüksek yıl hangisi?” önceki typed tabloyu okuyup doğru yılı söyler; “Az” web sorgusu oluşmaz.
- “Son cevabını kısalt” önceki asistan cevabını kaynak kabul eder.
- “Bunu grafik olarak göster” aynı typed tablo verisinden chart üretir veya doğrulanmış veri yoksa açıkça yapılamadığını söyler.
- Tool tabanlı tablo gerçek tool/reference/prompt verisi olmadan tamamlanmış sayılmaz.
- Low-confidence RAG sonucu kanıtlanmamış isim, tarih veya sayı iddiası üretmez.
- Fast memory tek semantic query/embedding ile 320 ms içinde tamamlanır veya sessizce yok sayılır.
- Normal task en az 1 unit tüketmeye devam eder; free kullanıcı 5 saatlik pencerede 12 unit alır.

## 10. Genel Kırmızı Çizgiler

- Aynı karar ikinci yerde yeniden türetilmez.
- Canonical state ve typed JSON authoritative; düz metin yalnız son yüzeydir.
- Türkçe desenlerde yeni `\b` kullanma; Unicode harf lookaround veya mevcut Turkish normalization/stem yardımcılarını kullan.
- Prompt, private içerik, secret, raw local path veya raw tool output loglanmaz.
- Provider/model/system prompt kullanıcıya sızmaz.
- Tool çağrısı registry + request allowlist + permission/safety policy eşleşmeden çalışmaz.
- Backend private yerel bilgisayar aksiyonu çalıştırmaz.
- Missing dependency kullanıcı akışını çökertmez.
- Long-running işlem bounded timeout/retry/cancel davranışı taşır.
- UI/mobile için execution truth türetilmez; backend typed contract tek kaynaktır.

## 11. Commit ve Deploy Disiplini

Şu anda commit/deploy yetkisi yoktur.

Kullanıcı daha sonra commit isterse:

- `DEVIR.md` silinmesini kendi değişikliğin gibi dahil etme; önce kullanıcı sahipliğini açıkça bildir.
- Aktif backend diff'ini eksiksiz koru.
- Commit SHA, branch, çalıştırılan/çalıştırılmayan kontroller ve deploy durumunu net raporla.

Kullanıcı deploy isterse ancak o zaman mevcut release akışını incele ve uygula. Deploy başarısı yalnız commit veya `healthz` ile iddia edilmez; readiness ve gerçek authenticated chat/task/history akışı ayrıca doğrulanır. Kullanıcının o andaki doğrulama talimatı her zaman bu dosyadan üstündür.
