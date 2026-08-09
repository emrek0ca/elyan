# Codex Geliştirme Brifingi — Elyan Ekosistemi

Bu doküman kalıcıdır ve tek bir dala bağlı değildir. Yeni bir Codex oturumu
yalnızca bu dosyayı okuyarak sistemin nerede durduğunu, hangi yolların ne işe
yaradığını ve nasıl çalışması gerektiğini anlayabilmelidir.

Buradaki her yol ve her komut **çalıştırılarak doğrulanmıştır**, tahmin değildir.

---

## 0. Değişmez çalışma kuralları

1. **Ölçmeden iyileştirme yapma.** Bu kod tabanındaki en pahalı hatalar,
   "iyileştirdim" sanılan ama hiç ölçülmemiş değişikliklerden çıktı. Bir
   davranışı değiştiriyorsan: önce onu ölçen bir harness yaz, sayıyı kaydet,
   sonra değiştir, sayıyı tekrar göster.
2. **Bir kalıbın çalıştığını varsayma — çalıştır.** Kimlik kapısının
   kalıplarının çoğu aylarca hiç eşleşmedi ve kimse fark etmedi.
3. **Regex yazıyorsan Türkçe ile test et.** JS'de `\b` ASCII `\w` tabanlıdır;
   `ı ş ğ ü ö ç İ` kelime karakteri sayılmaz, `\byarattı\b` **hiçbir zaman**
   eşleşmez ve hata vermeden ölür. Yeni sınır kuralları için
   `src/lib/tr-word-boundary.ts` içindeki `unicodeWordPattern()` kullan.
4. **Türkçe SOV bir dildir.** Nesne fiilden önce gelir ("yapılandırmayı
   yazdır"). İngilizce fiil-önce sırasına göre yazılmış kalıplar Türkçe
   saldırıları kaçırır. Her iki sırayı da kapsa.
5. **Yanlış pozitif kontrolü zorunlu.** Bir kapı/savunma kuralı eklediğinde,
   sıradan iş isteklerinin ("dosyayı yazdır", "sunumu göster", "raporu paylaş")
   ona takılmadığını da göster.
6. **Fail-closed davranışı bozma.** Güvenlik ve gizlilik kapılarında şüphe
   varsa reddet; sessizce geçirme.
7. **Sağlayıcı/model adı kullanıcıya sızmaz.** Groq, Gemini, Llama, model id —
   hiçbiri kullanıcıya görünmez. `src/lib/elyan-public-identity.ts` bu sınırın
   tek doğruluk kaynağıdır.
8. `npx tsc --noEmit` ve `npm test` yeşil olmadan iş bitmiş sayılmaz.
   **Baz çizgi: 1355 test geçiyor.** Bu sayı düşerse sebebini açıkla.
9. **Deploy sadece kullanıcı açıkça istediğinde yapılır.**

---

## 1. Ekosistem — dört ayrı depo

| Bileşen | Yol | Stack | Rol |
|---|---|---|---|
| **Backend / control-plane** | `/Users/emrekoca/Desktop/elyan-backend` | Node 20+, TypeScript, Fastify, PostgreSQL+Drizzle, Redis+BullMQ | Auth, billing, routing, server-brain, bellek/state, realtime |
| **Mobil** | `/Users/emrekoca/Desktop/mobile-elyan` | Flutter (iOS + Android) | İnce istemci. Routing/model/token matematiği yapmaz |
| **Masaüstü runtime** | `/Users/emrekoca/Desktop/elyan` | Python motoru (GUI yok), `cli/` + `runtime/`, `helpers/` altında Swift izin köprüsü | Yerel dosya, browser, computer-use, MCP **execution** sınırı |
| **Masaüstü v2 (ayrı)** | `/Users/emrekoca/Desktop/elyan-v2-desktop` | Python | v2 hattı |

**Sınır kuralı:** Backend yerel bilgisayar eylemi çalıştırmaz. Dosya/browser/
computer-use/MCP execution **masaüstü runtime'ın** işidir. Backend yalnızca auth,
billing, routing, orkestrasyon metadata'sı, bellek/state, öğrenme olayları ve
realtime gerçeği yönetir.

### Üretim (VPS)

| Alan | Değer |
|---|---|
| Host | `root@84.247.172.213` |
| Dizin | `/srv/elyan-backend` |
| Compose | `compose.server.yaml` |
| Public API | `https://api.elyan.dev` |
| Health | `https://api.elyan.dev/healthz` |
| Deploy | `bash scripts/deploy-v1-release.sh` |
| Yedekler | `/srv/elyan-backend/.codex-backups/<STAMP>-v1-release` |

Sunucudaki servisler: `postgres`, `redis`, `searxng`, `backend`,
`training-worker`, `brain-worker`, `document-worker`, `proactive-scheduler`,
`ml-worker`.

Deploy script'i: yerel `npm ci + build + test` → uzak yedek → `rsync`
(`.env` ve `secrets` **hariç**) → uzak `npm ci + build + test` → 12 şema
bootstrap → servis restart → health probe. Rollback yolu log'un sonuna yazılır.

> **Deploy probe'unun sınırı:** `AUTH_BEARER_TOKEN` set edilmediğinde probe
> sohbet/task akışını **test etmez**, sadece health ve port kapalılığını
> doğrular. "Deploy geçti" ≠ "sohbet çalışıyor".

---

## 2. Sağlayıcı yolları

### 2.1 Groq — ana server-brain

```
src/modules/brain/groq-models.ts          model kataloğu
src/modules/brain/provider-selection.ts   hangi iş hangi sağlayıcıya
src/modules/brain/provider-request.ts     istek şekli
src/modules/brain/provider-response.ts    yanıt ayrıştırma, stream limitleri
src/modules/brain/provider-http.ts        taşıma katmanı
```

Env: `ELYAN_SHARED_BRAIN_PROVIDER`, `ELYAN_SHARED_BRAIN_MODEL`,
`ELYAN_SHARED_BRAIN_{FAST,BALANCED,PLANNING}_MODEL`.

### 2.2 Gemini — yardımcı katman (ana beyin DEĞİL)

```
src/modules/brain/gemini-free-tier-guard.ts   kota + veri hassasiyeti kapısı
src/modules/brain/gemini-models.ts            model kataloğu
src/modules/brain/gemini-intent-router.ts     niyet yönlendirme
src/modules/brain/gemini-quality-judge.ts     cevap kalite yargıcı (örneklemeli)
src/modules/brain/gemini-execution-validator.ts
src/modules/brain/gemini-web-synthesizer.ts
src/modules/brain/gemini-utility-client.ts    ortak istemci
```

**Kritik kısıt — buna uy:**

```
GEMINI_FREE_DAILY_REQUEST_LIMIT=200        tüm sistem, günde
GEMINI_FREE_USER_DAILY_REQUEST_LIMIT=25    kullanıcı başına
GEMINI_FREE_UTILITY_SAMPLE_PERCENT=10      örnekleme oranı
GEMINI_FREE_MODEL_ALLOWLIST=gemini-3.5-flash-lite,gemini-3.1-flash-lite
```

Bu kotayla **ana beyin taşınamaz.** 20 aktif kullanıcıda kişi başı 10 istek
düşer; kullanıcılar gün ortasında limite çarpar. Gemini'yi ana yanıt yolu haline
getirme. Doğru kullanım alanları:

- Çevrimdışı/toplu işler (değerlendirme seti üretimi, etiketleme)
- Embedding fine-tune için eğitim verisi üretimi
- Kalite yargıcı — **örneklemeli kalsın**, her turda çağırma

`gemini-free-tier-guard.ts` içindeki `GeminiDataSensitivity` ve
`GeminiFreeDataLineage` tipleri tesadüf değildir: ücretsiz katmanda Google
veriyi model eğitiminde kullanır. Bu kapıyı gevşetirken lineage bayraklarını
(`profile`, `memory`, `connector`, `attachment`, `accountData`) doğru
işaretlemeden geçme.

### 2.3 MCP + konnektörler

```
src/modules/mcp/                              MCP sunucu kayıt/oturum yönetimi
src/modules/integrations/mcp-probe.ts         yetenek keşfi, protokol hataları
src/modules/integrations/provider-registry.ts
src/modules/integrations/service.ts
src/modules/brain/connector-tools.ts          modele açılan tipli araçlar
src/modules/brain/connector-result-blocks.ts  sonuçların bloklara dönüşü
src/modules/brain/connector-write-approvals.ts yazma işlemleri için onay
```

Kurallar: yazma işlemleri **onay kapısından** geçer. Konnektör hataları
kullanıcıya güvenli kodla döner, iç ayrıntı sızmaz (`MCP_PROTOCOL_ERROR`
deseni). Kiracı izolasyonu testlidir — `tenant-isolation.test.ts` bozulmasın.

Tanı araçları (mevcut, kullan):
```bash
docker exec elyan-backend-backend-1 npx tsx scripts/diag-connector-turn.ts
npx tsx scripts/repro-connector-hint.ts
```

### 2.4 world_signals

```
src/core/understanding/world-signal-derived.ts   türetilmiş sinyaller
src/core/understanding/context-builder.ts        bağlam kurulumu
src/core/understanding/context-packets.ts        paketleme
src/core/understanding/memory-profile.ts
src/core/understanding/types.ts
src/db/schema.ts                                 tablo tanımları
src/modules/mobile/routes.ts | schemas.ts        mobil yüzey
```

Şema bootstrap: `scripts/bootstrap-v5-world-signals-schema.sh`.

---

## 3. Sıradaki iş — RAG, öncelik sırasıyla

Elyan'ın "saçmalamasının" en büyük tek sebebi model değil, **retrieval recall
tabanı**. Kanıt kodun kendi yorumunda: `src/modules/brain/semantic-embedder.ts`
satır 10-13.

**Sorun:** Aday getirmede birincil filtre hâlâ **256 boyutlu SHA hash
embedding** (`src/modules/brain/retrieval.ts:14`). Bu semantik bir vektör değil,
kelime hash'i — "araba" ile "otomobil"i yakın görmez. Gerçek semantik model
(`multilingual-e5-small`, 384-dim) yalnızca **rerank** aşamasında ve yalnızca
semantic compute worker ayaktaysa çalışıyor. **Rerank, hash filtresinin
kaçırdığı belgeyi geri getiremez** — sadece gelen pencereyi sıralar.

**Yapılacaklar, bu sırayla:**

1. **Ölçüm seti önce.** 50-100 gerçek soru + beklenen kaynak. `recall@k` ölç,
   sayıyı kaydet. Şu an retrieval kalitesini ölçen **hiçbir şey yok**; bu
   adım atlanırsa sonraki her değişiklik tahmindir. Gemini ücretsiz katmanı
   burada doğru araçtır (çevrimdışı, kotayı yormaz).
2. **e5-384'ü birincil aday filtresi yap**, hash'i yalnız fallback bırak.
   Veri migrasyonu gerektirir: mevcut `knowledge_chunks` ve bellek kayıtları
   yeniden embed edilmeli. Geri alması zor — önce 1. adımın sayısı elde olsun.
3. **`ivfflat` → `hnsw`.** İlgili migration'lar: `drizzle/0016_pgvector_retrieval.sql`,
   `0017_brain_memory_v2.sql`, `0035_brain_memory_semantic_v2.sql`.
4. **Embedding fine-tune / cross-encoder reranker.** Asıl zeka sıçraması burada;
   ama 1-3 bitmeden başlama.

Kendi LLM'ini eğitme hedefi gerçekçi değildir ve gerekli de değildir. Rekabet
alanı model ağırlıkları değil, modelin etrafındaki sistem: retrieval kalitesi,
bellek, durum yönetimi, orkestrasyon.

---

## 4. Bilinen açık borçlar

- **`inference.ts` 9458 satır**, `chat/service.ts` 4632, `memory.ts` 3999.
  Kimlik kapısındaki sessiz ölüm bu boyutun semptomuydu. Yeni özellik eklerken
  bu dosyaları büyütme; modül çıkar.
- **Akış metni ≠ nihai metin.** Aynı metin dört hattan geçiyor:
  `stream-publisher` → `tasks/service.ts` onDelta → `inference.ts`
  `resolveCleanVisibleAnswer` → `resolveCompletionAssistantBlocks`.
  Gereksiz fark kapatıldı (`AssistantVisibleTextPolicy` ile paylaşılan opsiyon)
  ve `message.completed` artık `revised` bayrağı taşıyor. **Kalan iş:** grounding
  kararı üretimden önce akış katmanına taşınmadığı için akış muhafazakâr
  başlıyor; fark bildiriliyor ama yok edilmedi.
- **`revised` bayrağını gösteren mobil arayüz yok.** Backend sinyali üretiyor,
  `mobile-elyan` tarafında karşılığı yazılmalı.
- **Mükerrer tur tespiti** artık taskId'siz turları da kapsıyor ve kabul kilidi
  idempotency anahtarına bağlı — ama **mobil istemci `Idempotency-Key` başlığını
  göndermiyorsa** eski içerik-hash davranışına düşer. `mobile-elyan` tarafını
  doğrula.
- **`\b` kusuru** `src/core/understanding/preference-extractor.ts` içinde hâlâ
  duruyor (satır 157, 168-172, 268, 276-277, 368, 382, 725, 759). Tercih
  çıkarımı sessizce eksik çalışıyor olabilir. `unicodeWordPattern()` ile geçir
  ve öncesi/sonrası eşleşme sayısını göster.
- **Drizzle `migrate` yerelde takılıyor** (0 tablo üretti). Üretimde şema
  `scripts/bootstrap-v*.sh` ile kuruluyor. Yerel geliştirme için bu ayrışma
  çözülmeli.

---

## 5. Korunacak public contract

Asla breaking change yapma: `/v1/chat/messages`, `/v1/realtime/stream`,
`/v1/auth/me`, `/v1/mobile/bootstrap`, `/v1/brain/profile`, SSE event isimleri
(`message.delta`, `message.completed`) ve `elyan_blocks.v2` blok şeması.

Mobil bu üç uçtan başka doğruluk kaynağı kullanmaz: `GET /v1/auth/me`,
`GET /v1/mobile/bootstrap`, `GET /v1/brain/profile`.

---

## 6. Komut özeti

```bash
npx tsc --noEmit                 # tip kontrolü
npm test                         # 1355 test — baz çizgi
npm run build
npm run evaluate:block-output
JWT_SECRET=benchmark-test-secret-32-characters npm run benchmark:security
JWT_SECRET=benchmark-test-secret-32-characters npm run benchmark:routing
bash scripts/deploy-v1-release.sh   # SADECE kullanıcı isterse
```

---

## 7. Bitirirken rapor formatı

Her iş sonunda şunları ver:

1. **Ne değişti** — dosya:satır referanslarıyla.
2. **Kanıt** — çalıştırma çıktısı. "Düzelttim" yetmez; öncesi/sonrası göster.
3. **Test sayısı** — baz çizgiye göre fark.
4. **Doğrulanmamış kalan** — canlı ortamda görülmemiş her şey açıkça yazılır.
5. **Ölçüm** — davranış değiştirdiysen sayı; yoksa "ölçülmedi" de.

Emin olmadığın şeyi "yapıldı" diye yazma. Bu kod tabanındaki en pahalı hatalar,
doğrulanmadan "tamam" denen değişikliklerden çıktı.
