# DEVİR — 2026-08-16

Branch `codex/elyan-canonical-latest`, son commit `9941b219`; bu turdaki
değişiklikler henüz commit/push edilmedi. Çalışma ağacı bilerek değişik.
Üretime deploy yapılmadı; canlı bilgileri önceki devir kaydıdır.
Canlı: `https://api.elyan.dev` · VPS `root@84.247.172.213:2222`
(`/srv/elyan-backend`, git deposu değil — rsync ile beslenir).

## Önce bunu oku: baskın hata sınıfı

**Aynı karar iki yerde veriliyor ve ayrıştıklarında kimse fark etmiyor.**
Bu oturumda **altı** örneği ölçüldü ve her seferinde anlama katmanı DOĞRUYDU;
kararı yeniden türeten alt katman yanlış yapıyordu.

Kural: *bir karar bir yerde verilir; ikinci yerde yeniden türetiliyorsa o bir
hatadır.* Yeni bir hata görürsen önce bunu sor.

## İki ölçüm kapısı — değişiklikten önce ve sonra koş

```
npm run eval:routing          # --json (CI) · --full (sözcüksel + e5, ~15 dk)
npm run eval:understanding    # zarflı/zarfsız ayrışma
```

Taban (2026-08-16):

| | korpus | tutulan |
|---|---|---|
| sözcüksel | %97.1 · kritik 0 | %44.7 · kritik 4 |
| **tam boru hattı (e5)** | **%98.1** | **%70.7** |

Anlama ayrışması: **4/21**.

**KIRMIZI ÇİZGİ:** tutulan kümeye bakıp eşik/ağırlık oynatma. Vaka eklemek
serbest, ona göre ayar yapmak ölçümü öldürür.

## Bu oturumda canlıya çıkanlar (hepsi doğrulandı)

- **Görsel üretimi** — `\büret\b` Türkçe 'ü' yüzünden hiç eşleşmiyordu. Canlıda
  gerçek görsel üretilerek kanıtlandı.
- **e5 semantik katmanı** — model imajda gömülüydü ama ONNX oturumu ilk
  kullanıcı isteğinde kuruluyordu → timeout → 60 sn cooldown → her şey hash'e
  düşüyordu. Isıtma `buildApp`'e kondu (TEK yer), model vektörlerden ÖNCE.
  Altı süreç de `warmed=true`, timeout **0**.
- **"aç" → "kapat" karışması** — kelime torbasında token ağırlığı uzunlukla
  artıyor, "ac" (2 harf) 0 n-gram üretiyor ve nesne adı eylemi eziyordu.
  `capability-action-polarity.ts`: eylem artık tipli bir boyut. Sözcüksel VE
  e5 harmanının ikisinde de uygulanıyor (yalnız birinde yetmedi).
- **Word/docx belgesi**, **PDF başlığı** (`custom.pdf` → gerçek başlık),
  **zarfta olumsuzlama** ("görsel üretme" artık görsel istemiyor),
  **yüzey/chart çelişkisi**.
- **Araç döngüsü açıldı** (`ELYAN_SERVER_TOOL_LOOP_ENABLED=true`) — veri
  tablosu/grafiği zincirini besleyen tek kaynak buydu; kapalıyken
  `authoritativeArtifactData` hiç üretilmiyor ve her veri tablosu düşüyordu.
- **Modeller** doğrulanmış uçlara sabitlendi (hepsi HTTP 200):
  hızlı `gemini-2.5-flash-lite` · görme `gemini-3.1-flash-lite` ·
  görsel `gemini-3.1-flash-lite-image` · kalite `gemini-3.1-flash-image`.
  `GEMINI_FREE_ONLY=false`.
- **Sohbet hızı** — `mobile_chat_balanced` reasoning effort `high` → `medium`.
  Model küçülmedi, gizli düşünme bütçesi kısaldı.

## Sıradaki iş (öncelik sırasıyla)

1. **Sohbet hızını gerçek trafikte ölç.** Araç döngüsü gecikme EKLER, reasoning
   effort düşürmesi AZALTIR — ikisi ters yönde. Kabul edilemezse döngüyü
   kapatmak tek satırlık `.env` değişikliği.
2. **41 dosyalık `\b` süpürmesi.** Araç hazır: `trStemPattern()` (kök + sınırlı
   ek toleransı; kısa köklerde tolerans otomatik kapanır, `exclude` kapısı var).
   Mekanik süpürme DENENDİ ve geri alındı — eski kod iki yönde birden yanlış
   (`\bmasaüstü\b` "masaüstümde" ile yanlışlıkla eşleşiyor, `\bkelime\b` ekli
   hâlini hiç yakalamıyor). Her kalıp için ayrı karar gerekiyor; iki kapıdan
   geçirerek, parça parça yap.
3. **Veri zinciri uçtan uca ölç.** Araç döngüsü artık açık; "enflasyon tablosu
   iste" turunun gerçekten aradığını, kaynak gösterdiğini ve sayıların kaynakla
   tuttuğunu doğrula. Uydurma kapısı (`authoritative_table_data_unavailable`)
   çalışıyor — model uydurma sayıyla tablo basmıyor.
4. **Zarfı tam otorite yap.** Zarf açık ve doğru
   (`ELYAN_UNDERSTANDING_ENVELOPE_V2_ENABLED=true`), ama yanında kelime-listesi
   GÖLGE YOLU duruyor. Ayrışan 4 satır `eval:understanding` çıktısında.
5. **Eğitim en son.** Ölçüm oturmadan eğitim hatayı hızlandırmaktan başka işe
   yaramaz.

## Bilinen tuzaklar

- **`\b` Türkçe'de çalışmaz.** ASCII `\w` tabanlı. Denetim:
  `grep -rnP '/\\b[^/\n]*[çğıöşüÇĞİÖŞÜ]' src --include='*.ts'`
- **Deploy:** ağır script (`npm test` iki uçta bir saati aşar) yerine cerrahi
  yol: yedek → rsync (`--exclude .env` ŞART) → uzak `npm run build` →
  `docker compose up -d --build` → sağlık. Docker build'i SSH'a BAĞLAMA:
  bağlantı düşerse build ölür. `setsid nohup ... &` ile ayrık başlat.
- **SSH hız sınırı:** art arda bağlantı `Connection refused` verir; aralık bırak.
- **Canlıdaki commit git ile bulunmaz** (VPS git deposu değil):
  `grep -rl "<yeni fonksiyon adı>" dist/`. Sunucu saati **CEST**, commit'ler +03.
- **Log gürültüsü:** postgres `__health__` string'ini uuid diye sorgulayıp
  saniyede bir hata basıyor. Uygulama hatası için servisi daralt + seviye filtrele:
  `docker compose logs --since 24h backend brain-worker chat-worker | grep -E '"level":(50|60)'`
- **Testler** `npx tsx --test <dosya>` (vitest değil). `inference.test.ts` çok
  yavaş (e5 yüklüyor, 30 dk+) — tam paket kapısını beklemeye alma.

## 2026-08-16 — uygulama öncesi üretim baseline'ı

Bu kayıt önceki tabanları silmez; bu turdaki canlı/yerel ölçüm sonuçlarını ayrı
tutar. Ölçüm zamanı: **2026-08-16 11:35:07Z**.

- Hızlı model (`gpt-oss-20b`): ilk parça P50/P95 **512/608 ms**, tamamlanma
  P50/P95 **547/663 ms**.
- Dengeli (`gpt-oss-120b`): tek örnek yaklaşık **13 sn**.
- Genel chat tamamlanma P50/P95: **700/5020 ms**.
- Son 7 gün: **23 failed task**, **33 rejected provider** denemesi,
  **15 invalid JSON/output**.
- Task'siz `queued/running` assistant chat satırı: **51**.
- Routing heldout: sözcüksel **%44.7**, tam E5 **%70.2**; understanding
  ayrışması **4/21**.
- Tam E5 ölçümü sonuçlarını yazdırdıktan sonra süreç **9+ dakika** kapanmadı;
  ölçüm SIGTERM ile sonlandırıldı. Evaluator worker cleanup'ı bu turdaki kod
  kapsamına alındı.

Uygulama hedefi: normal sohbet hızlı lane'de kalacak; açık deep/zor görev,
planning ve üretim işleri deep lane'e yükselecek; katı JSON çağrıları uyumsuz
model fallback'lerini denemeyecek; task'siz aktif kayıtlar Redis kilitli bounded
sweep ile silinmeden `failed` + event terminal durumuna getirilecek. Bu turda
üretim deploy edilmedi.

## 2026-08-16 — uygulama sonrası doğrulama

Ölçüm zamanı: **2026-08-16 14:06:09Z**. Önceki baseline korunmuştur.

- Sözcüksel routing: corpus **%98.1**, heldout **%57.5**, kritik ihlal **0**.
- Tam E5 routing: corpus **%99.0** (102/103), heldout **%83.0** (39/47),
  kritik ihlal **0**. Süreç raporu yazdıktan sonra temiz kapandı.
- Understanding consistency: **4/21** ayrışma; mevcut kabul eşiği korunuyor.
- Model/provider, planning fallback, tool-selection, semantic worker ve orphan
  sweep odaklı **114 test** geçti; deep workload ve chat servis testleri de geçti.
- `npm run build`, `git diff --check` ve `docker compose -f compose.server.yaml
  config` geçti. Compose çıktısında backend, brain-worker, chat-worker,
  document-worker ve proactive-scheduler aynı 20B/120B/routing kataloğunu aldı.
- Tam repo test paketi build sonrasında başladı; bilinen uzun `inference.test.ts`
  koşusu nedeniyle tamamlanmadan durduruldu. `env.test.ts` içindeki mevcut
  Gemini 2.5/3.5 varsayılan uyuşmazlığı bu turdaki diff'in dışındadır.
- Hızlı modelin canlı provider P50/P95'i değişiklik sonrası yeniden ölçülmedi;
  deploy yapılmadığı için başlangıçtaki **512/608 ms** ve **547/663 ms** tabanı
  karşılaştırma referansı olarak bırakıldı.
- Canlı veritabanına migration/deploy uygulanmadı; başlangıçta ölçülen **51**
  task'siz aktif satırın canlıda sıfırlandığı bu turda doğrulanmadı. Kod yolu
  satır silmeden CAS ile `failed` durumuna geçirip event yayınlar.
