# NEREDE KALDIK — Elyan Ajan Mimarisi

> **Yeni oturum buradan başlasın.** Bu dosya, durumu yeniden keşfetmek için
> harcanan token'ı sıfırlamak içindir. Önce bunu oku, kod taramaya sonra başla.
> Son güncelleme: 2026-07-25 (gece) · Branch: `codex/quantum-runtime-brain`
> **Bugünkü durum + ileri plan için §4.9'a bak.**

---

## 1. KÖK TEŞHİS (bunu yeniden türetme — bedeli yüksek)

Aylardır süren "bir türlü oturmuyor" hissinin tek bir mimari sebebi var:

> **Elyan bir *ajan* değil, bir *workflow motoruydu*.**

Eski akış: `anla → planla (bir kez) → planı uygula → doğrula → (hata olursa replan)`
Gereken akış: `gözlemle → düşün → TEK adım at → sonucu gözlemle → yeniden düşün` (10-50 tur)

Kanıt (koddan doğrulandı):
| Katman | Bulgu |
|---|---|
| `agent-loop.ts` (backend) | `iterations: 1` sabit — tek atış |
| `structured_planner.py` | Plan bir kez kurulur |
| `executor_core.py` | `replan_fn` yalnız HATA anında |
| `shell.py` | `subprocess.run` — kalıcı terminal oturumu YOK |

**İkinci kök sorun:** görev/sohbet ayrımı `_requires_tool_capable_route()` içinde
100+ satırlık keyword regex listesiydi ve mantığı TERSTİ — *herhangi bir* kelime
eşleşirse "görev" sayılıyordu. Türkçede "yaz" (fiil/mevsim), "ara" (fiil/"arada")
çakışmaları yüzünden düz sohbet araç çağrısına dönüşüyordu.
→ Her yeni cümle kalıbına desen eklemek **dipsiz kuyu**. Bu yüzden hiç bitmiyordu.

---

## 2. YAPILDI (çalışıyor, sıfır regresyon ile doğrulandı)

### P0 — Çok turlu ajan döngüsü ✅
| Dosya | Ne yapar |
|---|---|
| `runtime/agent_loop.py` | **YENİ.** Çok turlu döngü. Adım/süre bütçesi, takılma dedektörü, uydurma-araç yakalama, sınırlı bağlam (`_`-önekli iç bayraklar ayıklanır → sızıntı yok) |
| `runtime/agent_decider.py` | **YENİ.** Katı-JSON model sözleşmesi (`tool\|finish\|ask`), toleranslı JSON çıkarımı, fail-closed |
| `runtime/reasoning_policy.py` | `decide_execution_mode()` → `fast_path \| structured_plan \| agent_loop` |
| `runtime/bridge.py` | `_agent_loop_enabled()`, `_route_chat_agent_loop()`, karar noktasında `route_fn` dallanması |

**Tasarım:** araçlar çağıranın `execute_step`'inden geçer → safety_policy, onay,
doğrulama, kanıt kapıları **aynen devrede**. Yeni ayrıcalık yolu açılmadı.
Taşıma yoksa `None` döner → eski yola düşer (wiring canlı yolu kıramaz).

### Görev/Sohbet kapısı ✅
`runtime/intent_gate.py` **YENİ.** Mantık tersine çevrildi:
**varsayılan SOHBET; görev için pozitif kanıt (eylem fiili + hedef) şart.**
- Dispatch aktifken gelen mesaj varsayılan SOHBET; yalnız açık kontrol
  (`iptal`/`onayla`/`ne durumda`) görev kontrolü sayılır → *"dispatch aktifken
  normal sohbet edilemiyor"* hatası kökten çözüldü.
- Türkçe eklemeli dil toleransı (`rapora`, `dosyayı`, `ekranda`) — hedef
  desenlerinde `\w*` kullanılır, `\b` DEĞİL. Bunu bozma.
- Doğrulama: 9/10 senaryo doğru. ("ekranda ne var" → chat çıkıyor ama router
  onu 0.95 güvenle fast-path'te yakalıyor, sorun değil.)

### Önceki turlardan ✅
- `runtime/error_recovery.py` — deterministik öz-düzeltme (transient retry,
  path normalize, permission **fail-closed**). Belirsiz hatalar replan'a düşer.
- `actions/_write_common.py` — `desktop_dir()` tüm OS (macOS/Windows `~/Desktop`,
  Linux XDG + yerelleştirilmiş). Varsayılan çıktı masaüstü; açık yol verilirse oraya.
- Backend `src/modules/brain/groq-compound.ts` — Compound + atıf çıkarımı.

---

### P0.5 — Onay yayını + kapsam genişletme ✅
Ajan döngüsü artık **yan etkili adımda durup onay istiyor** (`stop_reason =
"needs_approval"` + `pending_action`), bridge bunu `planPreview` + `pendingPlan`
sözleşmesine çeviriyor. Salt-okunur adımlar serbest akar → döngü keşif yapar,
**yan etki asla onaysız çalışmaz** (`run_agent_loop(require_approval=True)`).

**Kapsam iki kademeli** (`bridge.py`, `agent_loop_ready` / `agent_loop_fallback`):
- **(a) ÖN ALMA** — `route_capability_mismatch`: rota zaten yanlış, döngü hemen devralır.
- **(b) GERİ DÜŞÜŞ** — diğer novel/düşük güvenli işler: ÖNCE semantik planlayıcı
  çalışır (netleştirme + izin yüzeyi + agentPlan orada), **yalnız o başarısız
  olursa** `_with_agent_loop_fallback()` döngüyü devreye sokar.

> **NEDEN BÖYLE:** Doğrudan devralmayı denedim → **13 regresyon**. Semantik
> planlayıcının zengin UX'i (clarification, permission surface, agentPlan)
> taklit edilemedi. Geri-düşüş deseni hem kapsamı açtı hem sıfır regresyon verdi.
> `retrievalUsed` gibi telemetri geri düşüşte korunur (yoksa "kaynak kullanılmadı"
> yalanı olur).

### P1 — Kalıcı terminal oturumu ✅
| Dosya | Ne yapar |
|---|---|
| `runtime/shell_session.py` | **YENİ.** `ShellSessionManager` — cwd + env çağrılar arası KORUNUR. `cd` deterministik yorumlanır, kök dışına çıkış engellenir, etkileşimli komutlar (vim/ssh/less) bloklu, komut/süre/çıktı sınırlı |
| `actions/shell_terminal.py` | **YENİ.** `shell_session_open/run/close` yetenek sarmalayıcıları |

Doğrulandı: `cd proje` → `pwd` cwd'yi koruyor, bir komutta yazılan dosya sonraki
komutta okunabiliyor, hata çıktısı (`ZeroDivisionError`) yakalanıyor → **"test
çalıştır → oku → düzelt → tekrar" döngüsü artık mümkün.**

**Güvenlik:** `shell_session_run`, `shell_run` ile **aynı izin dalını** paylaşır
(`safety_policy.py`: `DESTRUCTIVE_OR_SENSITIVE_TOOLS` + `allow_shell` + onay).
Ayrı/gevşek yol açılmadı. Onaysız çağrı → `PERMISSION_REQUIRED`. `open`/`close`
yan etkisiz olduğu için `KNOWN_SAFE_TOOLS`ta.

**PARİTE TUZAĞI (dikkat):** yeni yetenek eklerken 5 yer güncellenir —
`_tool_decl` bildirimi, `_ADAPTER_SPECS`, `_handlers()`, display-name, ilgili
`_SIDE_EFFECT_*`/safety listeleri. Sonra **mutlaka**:
```bash
PYTHONPATH=. python scripts/export_capability_manifest.py \
  /Users/emrekoca/elyan-backend/src/modules/tasks/desktop-capability-manifest.ts
```
Aksi halde `test_capability_manifest_export.py` kırılır (backend↔desktop paritesi).

### Semantik anlama — desen otoritesi KALDIRILDI ✅
`runtime/understanding.py` **YENİ.** Niyet artık kelime deseniyle değil, modelle
**anlamlandırılıyor**. Yapılandırılmış zarf: `intent` (chat/task/task_control/
clarify) + `entities` (role=target/source) + `deliverables` + `constraints` +
`missingInformation` + `risk` + `confidence`.

> **KURAL:** `intent_gate.py`'deki desenler artık ana karar yolu DEĞİL — yalnız
> model erişilemediğinde devreye giren yedektir ve sonuç `degraded=True`,
> `source="deterministic_fallback"` ile işaretlenir. **Kalite sessizce düşmez.**
> Yeni cümle kalıbı için desen EKLEME; model zaten anlıyor.

Bağlantı: `bridge.py` → `intent_gate.understand(send_prompt=<backend transport>)`.
Backend yoksa ya da `ELYAN_DETERMINISTIC_ONLY=1` ise yedek yol.

### P2 — Bilgisayar kullanımı döngüsü ✅ (CANLI YOLDA)
`runtime/computer_use_loop.py` **YENİ.** `algıla → karar → TEK eylem → YENİDEN
algıla → değişti mi?` Grounding sırası **a11y önce, vision sonra** (a11y ucuz ve
kararlı; koordinat çözünürlük/tema/ölçekle bozulur). Ekran imzası (`signature`)
değişim kanıtıdır; 3 tur değişiklik yoksa `no_progress` ile durur → **kör tekrar yok.**

**Bağlantı:** `actions/desktop_operator.py::run()` adım döngüsü — her eylem
sonrası gözlemde `build_screen_state(...).signature` karşılaştırılır; üst üste
`NO_CHANGE_LIMIT` (3) değişmezse `stopReason="no_screen_progress"` ile güvenle
durur. Önceden operatör yanlış yerde sessizce "çalışmaya" devam ediyordu.

### P3 — İteratif RAG ✅ (CANLI YOLDA)
`runtime/retrieval_orchestrator.py` **YENİ.** `ayrıştır → getir → YETERLİLİK →
eksikse hedefli 2. tur → rerank`. Yeterlilik **kanıta** bakar (alt soruların kaçı
terim örtüşmesiyle karşılandı), model özgüvenine değil.

**Bağlantı:** `bridge.py::_shared_brain_context_for_conversation` →
`_augment_retrieval_if_insufficient()`. Kritik: **yeterliyse hiç ek çağrı yapılmaz**
→ mevcut gecikme aynen korunur. Yetersizse yalnız karşılanmayan alt sorular için
ek arama yapılır ve sonuç ORİJİNAL `results` şeklinde döner (aşağı akış sözleşmesi
değişmez). Hata olursa sessizce ana yola düşer.
Doğrulandı: "faiz kararı ve enflasyon" → 2. tur yalnız `['enflasyon orani kac']`
için çalıştı, sonuç 1→2.

---

## 4. YAPILMADI (sıradaki fazlar)

| Faz | İş | Not |
|---|---|---|
| **P1+** | Repo haritası + otomatik test-komutu keşfi (`pytest`/`npm test` sezimi) → ajanın repoda kendi başına gezinmesi | P1 altyapısı hazır, üstüne kurulur |
| **P2+** | `computer_use_loop.run_computer_use_loop()` tam döngüsünü operatörün planlayıcısıyla değiştirmek (şu an yalnız ilerleme kanıtı bağlı; planlama hâlâ `_plan_operator_steps`) | Değer/risk oranı düşünülmeli |
| **Ölçüm** | Gerçek benchmark koşusu yok. Frontier/OSWorld/RAG iddiaları **ölçülmedi**; yalnız birim davranışlar doğrulandı | Önce küçük bir eval seti kur |
| — | **ARC-AGI: ATLA.** Program sentezi + test-time training isteyen ayrı problem; ürün değerine transferi ~sıfır | Token yakma |

---

## 4.5 GERÇEK GÖREV SINAVI — BULGULAR (2026-07-25)

Görev: *"testleri çalıştır → başarısızları bul → analiz et → rapor yaz"*, gerçek
gpt-oss-120b kararlarıyla, gerçek araçlarla.

**Bulunan ve DÜZELTİLEN 2 gerçek hata:**
1. **Yapılandırılmış sonuç geri beslenmiyordu.** Ajan döngüsü modele yalnız
   metin çıktısını veriyordu; `result` (içinde `sessionId`, `path`, id'ler) yoktu.
   Model önceki adımın kimliğini göremeyip **uyduruyordu** → `NOT_FOUND` → kısır
   döngü. Düzeltme: `AgentObservation.result` + `_bounded_result()` ile geri besleme.
   *Zincirleme gerektiren HER çok adımlı iş bundan etkileniyordu.*
2. **Sıfır olmayan exit kodu araç hatası sayılıyordu.** `pytest` exit=1 =
   "testler kırık" bilgisidir, arıza değil. Hataya çevirince "çalıştır → oku →
   düzelt" döngüsü imkânsızlaşıyordu (model 5 turunu bununla harcadı).
   Düzeltme: `shell_terminal.py` artık exit≠0'ı `commandFailed: true` ile
   BAŞARILI gözlem olarak döndürür; yalnız TIMEOUT gerçek arızadır.

**Sınavın gösterdiği yetenek seviyesi (dürüst):** görevi anlıyor, terminal açıyor,
testleri çalıştırıyor, 50 başarısızlığı buluyor, detayları okuyor — **ama teslimatı
güvenilir şekilde kapatmıyor.** Zayıf halka altyapı değil, **model yönlendirmesi**:
aynı bilgiyi farklı komutlarla tekrar tekrar topluyor. Kısmi çare olarak
`agent_decider` prompt'una teslimat-odaklılık kuralları eklendi (6. ve 7. madde).

**Açık:** `json_validate_failed` (bilinen reasoning-token tuzağı — bkz.
[[project_model_and_tone]]) düşük `max_tokens`ta tekrar üretilebiliyor; ajan
karar çağrılarında token tabanı yeterli tutulmalı.

---

## 4.6 CANLILIK + İSRAF KESME (2026-07-25, son tur)

**İsraf kesildi, SONRA bütçe artırıldı** (sıra önemliydi):
- Katalog kısaltma: her turda ~80 araç yerine hedefe göre 8-15 (~%90 tasarruf),
  `capability_shortlist` üzerinden. **Tuzak:** kısa liste terminal araçlarını
  içermiyordu → P1'i sessizce öldürecekti; yazılım/terminal keyword grubu eklendi.
- Bütçe: adım 24→**32**, süre 900s→**1200s**.
- Token tabanı: ajan karar çağrılarında düşük `max_tokens` → `json_validate_failed`
  (bilinen reasoning tuzağı). Tabanı yüksek tut.

**Durumsal bağlam füzyonu** — `runtime/situational_context.py` (YENİ)
"Robot hissi"nin teknik kaynağı: takvim/konum/aktif uygulama/son dosyalar
sinyalleri vardı ama anlama katmanına HİÇ ulaşmıyordu; Elyan bilebileceğini
soruyordu. Şimdi:
- `gather_situation()` → sınırlanmış durum özeti
- `derive_defaults()` → soru yerine varsayım (başlık = yaklaşan toplantı)
- `liveness_cues()` → uydurma samimiyet değil, doğrulanabilir gerçek
  ("Yatırımcı sunumu için 30 dakikan var")

**Bağlantılar (hepsi canlı):**
| Hat | Nerede |
|---|---|
| Durum → niyet çözümü | `intent_gate.understand` → `understanding.analyze` |
| Durum → belge başlığı | `bridge._execute_step_with_telemetry` (tek huni: router + ajan) |
| Backend digest → state | `bridge._absorb_world_signals` |

**Değişmez kurallar (bozma):** kullanıcının verdiği başlık asla ezilmez; sinyal
yoksa alan üretilmez (uydurma yok); hassas sinyal (sağlık/kesin konum) ham
taşınmaz, yalnız kaba "yoğun gün" işareti üretir. Türetilmiş başlık
`_titleSource` ile denetlenebilir.

**Zincir KAPANDI (backend tarafı da bağlandı):**
`/v1/brain/profile` artık son dünya sinyallerinin sınırlı digest'ini döndürüyor
(`brain/service.ts::getRecentWorldSignalDigest` + `brain/routes.ts`). Tam yol:

```
world_signals tablosu → /v1/brain/profile → bridge._absorb_world_signals
  → STATE.runtime.worldSignals → gather_situation() → niyet çözümü + belge başlığı
```

**Gizlilik KAYNAKTA uygulanır** (yalnız alıcıda değil): `health` ve
`location_precise` yalnız TÜR olarak bildirilir, özet metni DB katmanından
çıkmadan düşürülür. Özet 160 karakterle sınırlı; sorgu patlarsa boş digest döner
(profil isteği düşmez); sinyal yoksa alan hiç eklenmez.
Testler: `src/modules/brain/world-signal-digest.test.ts` (redaksiyon değişmezi,
hata yolu, uzunluk sınırı).

---

## 4.7 CANLI MOBİL ARIZA — TEŞHİS (2026-07-25, 14:07)

Kullanıcı mobilden 3 komut verdi, üçü de başarısız:

| Girdi | Çıktı | Ne demek |
|---|---|---|
| "Terminali aç" | "Terminal açıldı." | Plan/onay/UI yok — fast-path'ten geçmiş |
| "off device komutu çalıştır" | "Yanıt katmanı bu tur tamamlanamadı…" | **Yedek metin** (`tasks/service-helpers.ts:1199`) |
| "Kapat terminali" | `desktop_operator.run` | Ham yetenek adı sızdı → **DÜZELTİLDİ** (`0e86f440`) |

**LOG KANITI (kritik — teşhisi değiştirir):** `chat-worker` loglarında saatler
boyunca `inference_total.count = 2`, restart sonrası `stages: {}`. Yani **chat
generation neredeyse hiç çağrılmıyor.** Worker ayakta ("chat generation worker
ready") ama trafik ona ulaşmıyor.

→ **Arıza modelde/generation'da DEĞİL, ondan ÖNCE.** Mobil istekler inference'a
varmadan düşüyor (routing/dispatch/kuyruk katmanı). Bu yüzden "modeli/prompt'u
düzeltmek" yanlış katman olur.

**SIRADAKİ OTURUMUN İLK İŞİ** (tahmin değil, bu sırayla):
1. Mobil isteğin hangi yolda düştüğünü bul — `chat` kuyruğa giriyor mu?
   ```bash
   ssh root@84.247.172.213 'docker logs --since 15m elyan-backend-backend-1 2>&1 | grep -iE "chat|dispatch|route|queue|enqueue" | tail -40'
   ```
   Sonra mobilden TEK mesaj at, aynı komutu tekrar çalıştır, farkı karşılaştır.
2. Kuyruğa girmiyorsa: route kararı / cihaz eşleşmesi. Giriyor ama işlenmiyorsa:
   worker claim / lease. İşleniyor ama yanıt dönmüyorsa: SSE/stream fence.
3. Katman bulunmadan mobil UI'a DOKUNMA.

---

## 4.8 ⚑ BİR HAFTALIK TIKANIKLIĞIN KÖK NEDENİ — ÇÖZÜLDÜ (2026-07-25)

**Belirti:** mobilden ne yazılsa "İsteğini aldım. Yanıt katmanı bu tur
tamamlanamadı…" yedek metni geliyordu. Desktop/mobil tarafında yapılan HİÇBİR
düzeltme fark etmiyordu.

**Kök neden (production logundan):**
```
reason: "required_connector_tool_missing"   ← 4 denemenin HEPSİ
attemptedModels: [gpt-oss-120b ×2, gpt-oss-20b ×2] → hepsi reddedildi
→ "shared brain inference unavailable" → continuity fallback
```
`requiredConnectorReadHint.enforcement === "require"` iken model connector
çağırmazsa cevap geçersiz sayılıyordu. "Zaman yönetimi için 30 maddelik kontrol
listesi yaz" gibi DÜZ bir yazma isteğinde model haklı olarak connector
çağırmıyor, geçerli cevabını üretiyor — ve o cevap dört kez çöpe atılıp
sağlayıcı zinciri tükeniyordu.

**Düzeltme** (`b3fc21ca`, `inference.ts` — streaming + non-streaming iki yol):
zorlama artık YALNIZ ilk denemede (`retryIndex === 0`). Aracı bir kez teşvik et,
sonra dürüst cevabı teslim et.

**KORUNAN AYRIM (bozma):** uydurma iddiası (`fabricatedConnectorRead` —
"mailini okudum" derken aracı çağırmamak) HER denemede reddedilmeye devam eder.
Fark: *aracı kullanmamak* ile *kullandığını iddia etmek* aynı şey değildir.

**Ders:** istemci tarafında haftalarca düzeltme yapmak, cevabın backend'de
üretilip çöpe atıldığı bir kapı varken hiçbir şeyi değiştirmiyordu. Belirti
istemcide, sebep sunucudaydı. **Önce üretim hattının cevabı TESLİM ettiğini
doğrula, sonra istemciyi iyileştir.**

Doğrulandı: deploy sonrası "30 maddelik kontrol listesi" isteği ekrana doğrudan
30 maddeyle cevaplandı.

---

## 4.9 DURUM ÖZETİ + İLERİ PLAN (2026-07-25 sonu)

### ŞU AN NE ÇALIŞIYOR

Bugün üç katmanda birbirine bağlı arızalar kapandı ve **dispatch gerçekten iş
yapıyor** (canlı kanıt: "Masaüstüne yeni klasör oluştur" → `/Users/emrekoca/
Desktop/Yeni Klasör` gerçekten oluştu).

| Katman | Neydi | Ne oldu |
|---|---|---|
| Backend plan | ">=2 adıma bölünemiyorsa boş plan" → tek yetenekli görevler ADIMSIZ gidiyordu | Tek adımlı plan geçerli (`materialize-plan.ts`) |
| Desktop yürütme | Adımsız görevde hiç yürütmüyor, plan etiketini cevap sanıp yansıtıyordu | Adımsızsa YERELDE planlayıp yürütüyor (`bridge._execute_deterministic_remote_task`) |
| Cevap teslimi | Yetenek etiketi ("Klasör ağacı") cevap olarak gidiyordu | Backend sınırında tek kapı (`capability-label-guard.ts`) |
| Üretim hattı | `required_connector_tool_missing` geçerli cevabı 4 kez çöpe atıyordu | Zorlama yalnız ilk denemede (`inference.ts`) |
| Süreklilik | `recentArtifacts` HEP null — "o klasörü sil" çözülemiyordu | Yürütme ürettiği yolları kaydediyor + kural promptta |

**Değişmezler (bozma):** uydurma iddiası her denemede reddedilir · kullanıcının
verdiği başlık ezilmez · sinyal yoksa alan üretilmez · hassas sinyal ham taşınmaz
· etiket cevap olamaz · kaynak yoksa sorulur.

### İLERİ PLAN — "doğru zamanda doğru şeyi hatırlamak"

Hedef **her şeyi hatırlamak değil**; alakalı olanı, alakalı olduğu anda
yüzeye çıkarmak. Sıra önem/maliyet dengesine göre:

**1. Alaka kapılı hatırlama (en yüksek değer)**
Bugün bağlam *itiliyor* (var olan her şey prompt'a giriyor). Olması gereken:
*çekilen* bağlam — o turun ihtiyacına göre skorlanmış. Skor = alaka × tazelik ×
görev-tipi uyumu. Alakasız hatırlatma, hatırlamamaktan kötüdür: modeli dağıtır.
→ `situational_context.gather_situation()` + `understanding` arasına bir seçici
katman; her alan "neden dahil edildi" gerekçesiyle girsin (izlenebilirlik).

**2. Çalışma belleği ≠ uzun süreli bellek**
Farklı ömür, farklı kural:
- **Çalışma belleği** (bu görev): son çıktılar, çözülmemiş göndermeler, aktif
  plan durumu → agresif dahil et, iş bitince TEMİZLE.
- **Uzun süreli**: tercihler, tekrar eden kalıplar → yalnız eşleşince çağır.
`recentOutputs` şu an ikisinin arasında duruyor; ayrılmalı.

**3. Unutma ✅ (2026-07-25 gece — bkz. §4.10)**
TTL + varlık doğrulaması uygulandı. Kalan parça: görev bitince çalışma
belleğini açıkça boşaltma (TTL şimdilik bunu dolaylı karşılıyor).

**4. Gönderme çözümü birinci sınıf adım ✅ (2026-07-25 gece — bkz. §4.10)**
`resolvedTarget` alanı + kanıt kapısı uygulandı. Kalan parça: planlayıcıların
(structured_planner / agent_loop) zarfa gelen çözülmüş yolu doğrudan
TÜKETMESİ — şu an alan zarfla taşınıyor, unresolved→clarify canlı.

**5. Canlılık: hak edilmiş olsun**
`liveness_cues()` yazıldı ama cevaplara BAĞLANMADI — bilinçliydi: her turda
"toplantına 30 dk var" demek yapmacıktır. Doğrusu: ipucu ancak o turun işiyle
ALAKALIYSA yüzeye çıksın (ör. belge üretilirken yaklaşan toplantı adı). Bağlama
kuralı: alaka yoksa sus.

**6. Kendi durumunun farkındalığı ✅ kısmen (2026-07-25 gece — bkz. §4.10)**
`selfState` (taskRunning + lastTask{ok,detail,minutesAgo}) durumsal bağlama
bağlandı; niyet çözümü artık bunu görüyor. Kalan parça: "izin eksik" sinyali
ve backend cevap-üretim tarafının selfState'i alması.

**7. ÖLÇÜM (bunsuz gerisi tahmin)**
Bugüne kadar hiçbir iyileştirme uçtan uca ÖLÇÜLMEDİ. Küçük bir senaryo seti
(10-15 gerçek görev) + geçti/kaldı tablosu kurulmalı. Aksi halde her oturum
"düzelttim sanıyorum" ile geçiyor — bu oturumda üç kez böyle oldu.

### 4.10 UNUTMA + GÖNDERME ÇÖZÜMÜ ✅ (2026-07-25 gece)

İleri planın 3. ve 4. maddeleri uygulandı, sıfır regresyonla (17 baseline
hata değişmedi, `comm` yöntemiyle ölçüldü):

**Unutma (bayat referans tehlikesi kapandı):**
- `situational_context.recent_output_is_fresh()` — üç kapı: `recordedAt` VAR ve
  TTL (240 dk) içinde; yol boş değil; yol diskte hâlâ mevcut. Zamansız kayıt
  bayat sayılır (**fail-closed**).
- `executor_core._record_recent_outputs` artık `recordedAt` yazar ve önceki
  TAZE kayıtları korur (yeni önce, yol bazında tekil, en çok 6) — "bir önceki
  dosya" göndermesi yeni görev çalışınca kaybolmaz, bayatlar düşer.
- `gather_situation` okurken aynı filtreyi uygular → silinmiş/eski dosya
  bağlama hiç girmez.

**Gönderme çözümü (`understanding.py`):**
- Zarfa `resolvedTarget` alanı eklendi: `{path,kind,name,source}` |
  `{"status":"unresolved"}` | `null`. Prompt kuralı 9 + şema güncellendi.
- **KANIT KAPISI** (`_ground_resolved_target`): modelin verdiği yol yalnız
  (a) `recentOutputs` listesindeyse (`source="recent_output"`) ya da
  (b) kullanıcı mesajında açıkça geçiyorsa (`source="user_message"`) kabul
  edilir. İkisi de değilse → `unresolved` + `resolved_target_ungrounded`
  sinyali. **Uydurma yol asla geçmez.**
- Hedefi çözülemeyen gönderme ile görev ÇALIŞMAZ: intent `clarify`ya düşürülür,
  `missingInformation` doldurulur → bridge'in mevcut netleştirme kapısı tek
  soru sorar. (Bu davranış CANLI — bridge'de ek wiring gerekmedi.)

Testler: `tests/test_reference_memory_contract.py` (9 senaryo — TTL, silinmiş
yol, zamansız kayıt, kanıt kapısının üç dalı, unresolved→clarify, gönderme
yokken dokunulmama).

**Kendi durumunun farkındalığı (madde 6, aynı gece):**
- `SituationalContext`'e `active_task_count` + `last_task_ok/detail/minutes_ago`
  eklendi; kaynak `runtime.executor.{activeExecutionCount,lastExecutionAt,
  lastExecutionOk,lastExecutionDetail}` (executor_core zaten yazıyordu).
- `to_prompt_context()` → `selfState: {taskRunning, taskCount?, lastTask?}`.
  **Tazelik kapısı:** 60 dakikadan eski son-görev sonucu taşınmaz (bayat
  "başarısız" bugünün sorusuna gürültü olurdu).
- Anlama sözleşmesine kural eklendi: selfState SENİN durumundur — "ne durumda"
  → task_control, "neden olmadı" → lastTask'a bakar; bilmiyormuş gibi davranma.
- Testler: `tests/test_self_state_context.py` (4 senaryo).

**Bitmedi (dürüst):** planlayıcılar `resolvedTarget`'ı henüz doğrudan
tüketmiyor (zarf taşıyor, tüketici backend/planner tarafında); görev sonunda
açık çalışma-belleği temizliği yok (TTL dolaylı karşılıyor); "izin eksik"
sinyali selfState'te yok; backend cevap-üretimi selfState'i henüz almıyor
(şimdilik yalnız niyet çözümü görüyor).

### 4.11 ZEKÂ EĞİTİMİ TURU ✅ (2026-07-25 gece, ikinci blok)

**Kural teyidi:** hiçbir maddede desen/keyword eklenmedi. Yöntem: bağlam
üretimi, kanıt kapıları, metadata türetimi, ölçüm.

**1. Eval seti** — `runtime/intelligence_eval.py` (14 senaryo) +
`scripts/run_intelligence_eval.py`. Model erişilemezse `degraded_skip`
(sahte hüküm yok). Testler: `tests/test_intelligence_eval_contract.py`.
> **İLK KOŞU 4 CANLI P0 BULDU** (hepsi backend, hepsi düzeltildi + deploy):
> (a) anlama zarfının şablon metni `external_send_request` kalıbına takılıp
> HER `/desktop/plan` çağrısını kapıda blokluyordu → `userText` eklendi,
> kapılar kullanıcının cümlesini denetliyor (`gatePromptOverride`);
> (b) skill router zarfı kullanıcı isteği sanıp iç içe üretim başlatıyordu →
> desktop_plan skill yönlendirmesini atlıyor; (c) `planning` workload'ının
> 560 token tabanı reasoning modelinin gizli turunu kesiyordu →
> `json_validate_failed(boş)`; taban 30s/2400 (2400 override'ı `Math.min`
> ile tabana EZİLİYORDU); (d) sohbet sanitizasyonu plan JSON'unu silip
> "doğrulanmış veri alamadım" yedeğini koyuyordu → planning muaf.
> Backend 1605/1605 test geçti. **Kanıt: eval önce 0/14, düzeltmelerden sonra
> senaryo geçmeye başladı (1 geçti / 13 atlandı).**
> **Sağlayıcı zinciri ÇÖZÜLDÜ** (aynı gece, `c536946a`) — üç ayrı sebep
> üst üsteydi: (i) `groq/compound` bir ARAÇ-AJANI modeli; katı JSON
> döndürmez, zincirin başında iki kez boş dönüp gerçek modele sıra
> bırakmıyordu → yapısal çıktı isteyen rotalarda zincire hiç alınmıyor
> (`structuredOutputRequired`); (ii) sohbetin **turn envelope** katı şeması
> planlama rotasına dayatılıyordu, model iki şema arasında sıkışıp hiçbir
> şey üretmiyordu → makine-JSON rotalarında envelope kapalı; (iii) `planning`
> workload'u `high` reasoning effort'a eşleniyor, uzun zarfla gizli düşünme
> tüm bütçeyi yiyip görünür çıktıyı boş bırakıyordu (Groq
> `json_validate_failed`, `failed_generation:""`) → `reasoningEffortOverride:
> "medium"`. Gemini'nin `data_sharing_consent_required` reddi KASITLI
> gizlilik kapısıdır, dokunulmadı.

### 4.12 ⚑ EVAL-GÜDÜMLÜ ZEKÂ TURU — 0/14 → 13/14 (2026-07-26)

Sağlayıcı zinciri açılınca eval GERÇEKTEN ölçmeye başladı ve kalan hatalar
transport değil **anlama** hataları çıktı. Üç turda ölçerek düzeltildi
(`07b440a9`), **hiç desen eklenmeden**:

| Tur | Sonuç | Ne düzeltildi |
|---|---|---|
| 1 | 9 geçti / 4 kaldı | (başlangıç ölçümü) |
| 2 | 11 geçti / 1 kaldı | grounding kapısı + ayrım ilkesi |
| 3 | **13 geçti / 0 kaldı** | gönderme kuralı zorunlu kılındı |

1. **Grounding kapısı yanlış tetikleniyordu:** model gönderme OLMAYAN
   isteklerde de `unresolved` işaretleyince görev netleştirmeye düşüyordu
   ("masaüstüne Faturalar klasörü oluştur" → gereksiz soru). Artık zarfın
   KENDİ kanıtına bakıyor: somut hedef varlığı varsa sorulacak şey yoktur.
2. **Ayrım ilkesi öne alındı:** "kullanıcı bu turun sonunda ELİNDE BİR ŞEY
   mi bekliyor, yoksa BİLGİ mi?" Belirsizlik kuralının açık emirleri sohbete
   çekmesi bitti — *yıkıcı işi chat'e çevirmek onu güvenli yapmaz; onay
   kapısı ayrı katmandadır.*
3. **Gönderme kuralı üstün:** hedefi çözülemeyen gönderme, emir ne kadar açık
   olursa olsun `clarify`. Böylece task yolunu gevşetmek "onu sil"i tahminle
   çalıştırmıyor.

### 4.13 EKOSİSTEM FARKINDALIĞI + TESLİMAT SÖZLEŞMESİ (`a530a7a0`)

**`runtime/ecosystem_model.py` (YENİ)** — Elyan üç yüzeyli TEK organizmadır:
mobil = yüz, backend = paylaşılan beyin, masaüstü = eller. Anatomi mimari
bilgidir (desen değil); **durum canlı sinyalden** okunur (`pairing.
connectedDevices`, `runtime.ready/lifecycleState`, runtime token/ws) — "bağlı"
asla varsayılmaz. `delivery_outlook()` gereken yüzey kapalıysa dürüstlük
direktifi üretir.

> **KAPSAM KURALI (bozma):** ekosistem bilgisi NİYETİ DEĞİŞTİRMEZ. İlk
> denemede değiştirdi ve "selam nasılsın" → `task` çıktı. Sözleşmede artık
> açıkça yazılı: ekosistem yalnız işin NEREDE yapılacağını ve nasıl
> konuşulacağını belirler. Eller kapalıysa iş reddedilmez ama "yaptım" da
> denmez; açıksa "yapamam" denmez.

**Teslimat sözleşmesi** — `agent_loop`: anlama zarfının `deliverables` beyanı
döngüye taşınır (`bridge` iki çağrı yerinde de besliyor) ve `finish` KAPIDAN
geçer: hiçbir şey üretilmemişse bir kez uyarır ("önce üret; üretemiyorsan
neyin engellediğini söyle, iddia etme") ve döngüye döner. Kanıt tanımı
KASITLI geniş (herhangi bir artifact ya da yol taşıyan adım sonucu) — dar
eşleme yanlış pozitif üretir, o da kural yazma tuzağının aynısıdır.

Eval'e iki ekosistem senaryosu eklendi (`ekosistem_eller_kapali/acik`) →
toplam 16.

**AÇIK (deploy bekliyor):** anlama prompt'u büyüdükçe `medium` effort +
2400 token tavanı da yetmemeye başladı (`empty_response`). Tavan yerelde
**4096**'ya çıkarıldı (`workloads.ts`, `workload-policy.ts`,
`desktop-plan.ts` + testi) ama **VPS'e deploy EDİLMEDİ**. Deploy komutu:
```bash
cd /Users/emrekoca/elyan-backend && npm run build && scp src/modules/brain/workloads.ts src/modules/brain/workload-policy.ts src/modules/brain/workload-policy.test.ts src/modules/brain/desktop-plan.ts root@84.247.172.213:/srv/elyan-backend/src/modules/brain/ && ssh root@84.247.172.213 "cd /srv/elyan-backend && docker compose -f compose.server.yaml up -d --build backend brain-worker chat-worker"
```
Deploy edilene kadar eval koşuları yüksek `degraded_skip` verir.

**Değişkenlik uyarısı (dürüst):** tek eval koşusu gürültülüdür — sağlayıcı
tökezlemesi `degraded_skip` üretir (son koşuda 1). Bir düzeltmeyi tek koşuya
bakarak "oldu/olmadı" diye yargılama; en az iki koşu ya da `--only` ile
hedefli tekrar kullan.

**2. Öz-model** — `runtime/self_model.py`: yetenek sayısı/grupları
`capability_registry`den, izinler state'ten TÜRETİLİR (elle liste yok →
bayatlamaz). **Kapalı izinler açıkça bildirilir** → model "yaparım" deyip
izin duvarına çarpmaz.

**3. Dünya modeli** — `runtime/environment_model.py`: platform/kabuk/paket
yöneticisi/mevcut araçlar bir kez keşfedilir (12s TTL cache). Terminal
komutları artık bu makinenin gerçeğine dayanır.
(2 ve 3 `intent_gate.understand` üzerinden anlamaya bağlı;
testler: `tests/test_self_and_environment_model.py`.)

**4. Ders damıtma** — `runtime/lesson_store.py`: biten işten TEK cümlelik ders
damıtılır, **yalnız o turun yetenek/hata bağlamıyla örtüşürse** geri çağrılır
(alaka kapısı). Ham içerik yok, en çok 24 kayıt, tekrar yazılmaz. Bağlantı:
`remote_task_runner` (terminal sonuç) → kayıt; `agent_loop` → karar bağlamına
enjeksiyon.

**5. Anlamsal araç seçimi** — `agent_loop._tool_guidance()`: her araç için
izin/idempotency/retry/ön koşul/platform ipuçları **spec metadata'sından
türetilir**. Araca özel elle yazılmış kural yok; keyword kısa listesi kaba
ön-filtre olarak kalır, otorite olmaz.

Hepsi sıfır regresyonla (17 baseline hata sabit, `comm` yöntemi).

### 4.14 ⚑ ÖZNE HIRSIZLIĞI + TURLAR ARASI İÇERİK (2026-07-26)

**Kök teşhis — tek bir yapısal hata, üç ayrı belirti.** Anlama prompt'unda
sınıflanacak mesaj, bağlam zarfının İÇİNE bir JSON anahtarı olarak gömülüydü.
Model "kullanıcı" sözcüğünün kime işaret ettiğini yanlış çözüp **kendi iş
ürününü** (şema uyumlu JSON) kullanıcının teslimatı sayıyordu.

| Belirti | Ölçüm (önce) | Ölçüm (sonra) |
|---|---|---|
| "selam, nasılsın bugün?" → `task` | **1/5** | **5/5** |
| "bunu belge yap" → `chat` (önceki turun SORUSU sınıflanıyordu) | **0/5** | **4/5** |
| "ne durumda, bitti mi?" → `chat`/`clarify` | **0/5** | **4/4** |

**Üç kademeli düzeltme (sıra önemliydi):**
1. **Çit** — mesaj kendi sınırına alındı (`fence_message`), sözleşmeye "şema
   SENİN iş ürünün, sınıflanan teslimat değil" yazıldı.
2. **`json_object` kipi** (backend) — çit mesajı belirginleştirince model onu
   *cevaplamaya* başladı; düzyazı masaüstünde ayrıştırılamayıp sessizce desen
   yedeğine düşüyordu (soru biçimli mesajlarda ~%40). Makine-JSON rotalarında
   artık `response_format: {type:"json_object"}` isteniyor — **şema
   dayatmadan** düzyazıyı yasaklar, dolayısıyla §4.11'deki "iki şema arasında
   sıkışma" arızasını yeniden üretemez.
3. **SIRA** — çit tek başına yetmedi: bağlam bloğu mesajdan SONRA geldiği için
   önceki turlar daha yakın konumda kalıp özneyi geri çalıyordu. Artık
   `ARKA PLAN → ŞİMDİ SINIFLA(çit) → ÇIKTI ŞEMASI`.

> **KURAL (bozma):** taşınan içeriğin METNİ bağlama konmaz — yalnız VARLIĞI
> (`available`, `chars`, `topic`). Önizleme koymak denendi: 240 karakterlik
> alıntı özneyi yeniden çaldı ve "bunu belge yap" 5/5 `chat` oldu. Gövde ayrı
> yoldan yazıcıya gider; modelin onu okuması gerekmez.

**Turlar arası içerik — `runtime/conversation_source.py` (YENİ).** İki ölü alan
bağlandı: (a) `recent_turns` her iki imzada VARDI ve prompt'ta işleniyordu ama
**hiçbir çağıran doldurmuyordu** (`recentOutputs` ile aynı sınıf); (b) yazıcılar
yalnız AYNI plandaki adımları görüyordu (`_dependencyResults`), turlar arası
içerik hiç taşınmıyordu — bu yüzden "bunu belge yap" kullanıcının KOMUT
cümlesini belgeliyordu.

Artık: `sourceKind` kapalı kümesine **`conversation`** eklendi; yürütme hunisi
(`bridge._fill_writer_source_from_conversation`) yazıcının BOŞ gövdesini o turun
konuşmasından doldurur. **Üç koşul birden** aranır (yetenek yazıcı + elde hiç
içerik yok + konuşmada gerçek metin var); biri tutmazsa hiçbir şey değişmez —
plan içi zincirleme ve kullanıcının verdiği içerik asla ezilmez. Metin yoksa
**sorma davranışı aynen sürer** (uydurma yok).

**Sınıflandırma kapsamı — izin niyeti değiştirmiyor.** `permissionsDenied`
görev isteğini `chat`e çeviriyordu ("terminal kapalı, yapamam"). Bu, §4.13'te
ekosistem için bir kez düzeltilmiş hatanın aynısıydı: yetenek durumu **ne
söyleyeceğini** belirler, **kullanıcının ne istediğini** değil. İzin kapısı ayrı
katmandadır.

**Diğer ilkeler:** `missingInformation` artık ENGEL listesidir (makul
varsayılanı olan hiçbir şey girmez); `clarify` SON ÇAREdir (iki koşul birden);
keşfedilebilir bilgi eksik bilgi değildir — **sınırı**: bakılacak bir yerin
gerçekten var olması (elimizde olmayan içerik hâlâ `user_private` → sorulur).
Rule 8'deki `tablo/belge/liste` isim listesi **kaldırıldı**, yerine ilke geldi.

**Ölçüm (18 senaryo × 5 koşu, `scripts/run_eval_stability.py` YENİ):**
`17/18` senaryo ≥4/5. Orijinal 16 senaryonun **tamamı** eşiği tutturuyor.
Tek koşuya bakarak yargı verme — bu araç tam bunun için yazıldı.

**Format matrisi 12/12:** docx/pdf/xlsx/pptx/txt/md — her biri için bir yazma +
bir okuma. Not: eksik opsiyonel bağımlılıklar kuruldu (`reportlab openpyxl
python-pptx markitdown mammoth pymupdf`) → desktop baseline **57 → 38** hata.

### 4.15 MOBİL SÜREKLİLİK HALKASI BAĞLANDI (2026-07-26)

**Boru döşenmişti, iki UCU birden bağlı değildi.**
`understanding_envelope.conversation_state.lastAssistantSummary` alanı şemada
vardı; zarf kurucusu okuyordu, `buildDesktopWorkOrder` onu `contextPack`e
koyuyordu, iş emri masaüstüne dispatch ediliyordu. Ama:

| Uç | Durum (önce) |
|---|---|
| Alanı YAZAN | **yok** — mobil istemci göndermiyor (0 eşleşme), backend türetmiyor |
| Alanı OKUYAN | **yok** — masaüstünde `contextPack` kullanım sayısı **0** |

Yani ara segmentler yıllardır duruyordu, iki uç boştu. Bağlanan:
- **Kaynak ucu** (`chat/task-sync.ts::getLastAssistantMessageText`): önceki
  cevap sohbet oturumundan **sunucu tarafında** türetilir — istemcinin bir şey
  göndermesine bağlı değil. İstemci açıkça verirse onunki kazanır. Sorgu
  patlarsa `null` döner: süreklilik bir kolaylıktır, görev oluşturmayı düşürmez.
- **Alıcı ucu** (`bridge._execute_deterministic_remote_task`):
  `conversation_source.from_work_order()` ile `_CURRENT_CONVERSATION_SOURCE`
  doldurulur; yazıcı hunisi zaten kalanını yapıyordu.

Doğrulama: gerçek `validate_payload`tan geçirilen iş emrinde `contextPack`
hayatta kalıyor → içerik çıkarılıyor → yazıcıya `_sourceContextOrigin=
conversation_turn` olarak giriyor. Backend 1609/1609, `dist`te doğrulandı.

**Kalan ölü alanlar (tarandı, KASITLI bırakıldı).** `contextPack`in diğer
alanlarının masaüstü kullanımı 0: `toolSkillDecision`, `privacyRouting`,
`intentGraph`, `executionPlan`, `failurePolicy`, `localContextNeeded`,
`workType`, `turnKind`, `carryForward`, `userCorrection`,
`lastArtifactSummary`, `lastImagePrompt`. Bunlar **engelleyici değil**: her
birinin masaüstünde kendi otoritesi var (`safety_policy`, `reasoning_policy`,
`error_recovery`, `task_router`) ve o otoriteler canlı yolda çalışıyor.
Blokaj yaratan tek alan `lastAssistantSummary`ydi; o bağlandı.

> **UYARI:** kalanları "boş duruyor" diye toplu bağlama. Bugün ölçüldü:
> ölçmeden yapılan her ek bağlama sınıflandırmayı bozdu (bkz. §4.14 geri
> alınan denemeler). Bir alanı ancak onu talep eden SOMUT bir arıza varken
> bağla ve bağladığını 5 koşuyla ölç.

### BU OTURUMUN DERSİ
Aynı belirti (etiket cevabı) **üç ayrı katmandan** besleniyordu ve her seferinde
tek katmanı düzeltip "bitti" sandım. Kullanıcı haklı olarak "hiçbir şey
değişmiyor" dedi. **Belirtiyi değil, belirtinin ulaştığı TÜM yolları kapat;
kapattığını da o yolun kendisiyle doğrula.**

---

## 5. AÇIK SORUNLAR

0. **BİTMEDİ (2026-07-26, dürüst liste):**
   - `belge_onceki_turdan_pdf` **1/4** — "bunu pdf yap" isteğinde model
     `conversationContent`i kaynak saymayıp "hangi içerik/dosya?" diye soruyor
     ("pdf" isteği onu *dosya dönüştürme* çerçevesine sokuyor). Kardeşi
     `belge_onceki_turdan` geçiyor (3/3), yani zincir çalışıyor; takılan tek
     şey bu biçim.
     > **DENENDİ, GERİ ALINDI (tekrarlama):** rule 4'ü "ENGEL listesi" diye
     > yeniden yazmak ve "çıktı yolu eksik bilgi değildir" cümlesini eklemek
     > bu senaryoyu düzeltmedi, üstelik **ask-gate'i zayıflattı**:
     > `ozel_kaynak_sorulur` 5/5 → 3/5 (`task`) — yani uydurma koruması
     > gevşedi. Toplam 17/18 → 14/18. Ölçülüp geri alındı.
   - **Mobil cihazdan uçtan uca DENENMEDİ.** Zincir masaüstünde ölçüldü
     (anlama → huni → yazıcı → geri okuma); gerçek telefondan üç akışın
     doğrulanması ve mobil blok render'ı **açık kaldı**.
   - Sağlayıcı tökezlemesi sürüyor: yoğun eval koşularında bazı turlar
     tamamen `degraded_skip` dönüyor (rate-limit şüphesi, ölçülmedi).
   - **Mobil halka BAĞLANDI** (bkz. §4.15) ama **gerçek cihazda denenmedi**:
     kod yolu birim+entegrasyon testleriyle doğrulandı, telefondan uçtan uca
     akış ve mobil blok render'ı hâlâ açık.
   - `useDirectDesktopFastPath` yolunda anlama zarfı `emptyUnderstanding`
     olduğu için `contextPack` boş kalır → o hızlı yolda süreklilik taşınmaz.
     Ölçülmedi; deterministik hızlı yol zaten kısa/net işler içindir.

1. **Baseline test hatası: 57 → 38** — eksik opsiyonel bağımlılıklar kurulunca
   19 test düzeldi (`reportlab openpyxl python-pptx markitdown mammoth
   pymupdf`). Kalan 38 hâlâ bizden değil (sympy/ses/latex).
   `PYTHONPATH=. python -m pytest tests/ -q`
2. **Groq Compound hiç çalışmadı** — kod hatası değil, **ops**: `GROQ_COMPOUND_ENABLED`
   varsayılan `false` ve VPS `.env`'inde yok. Ayrıca uygun workload yalnız
   `planning` + `mobile_chat_deep_refine`. Bayrağı açmadan etkisi olmaz.
3. **VPS deploy YAPILDI** (2026-07-25, `4d71adac` dahil). Sunucuda 1591/1591 test
   geçti, container'lar healthy, `api.elyan.dev/healthz` 200. Yeni kodun canlıda
   olduğu doğrulandı (`getRecentWorldSignalDigest` dist'te mevcut).
   **Deploy tuzağı:** `deploy-v1-release.sh` art arda çok SSH açtığı için sunucu
   rate-limit'e takılıyor ve script "Remote install and test" adımında
   `kex_exchange_identification: Connection reset` ile düşüyor. Bu ARIZA DEĞİL —
   dosyalar zaten senkronlanmış olur. Çözüm: bekle (ban penceresi kısa), sonra
   kalan 2 adımı keepalive ile ELLE çalıştır:
   ```bash
   ssh -o ServerAliveInterval=30 root@84.247.172.213 "cd /srv/elyan-backend && \
     ONNXRUNTIME_NODE_INSTALL=skip npm ci && npm run compile:nlp && npm run build && npm test"
   # sonra: şema bootstrap script'leri + docker compose up -d --build --remove-orphans
   ```
   Production bu süreçte etkilenmez; eski container'lar çalışmaya devam eder.
4. **Commit'ler atıldı** (2026-07-25 oturumu, hepsi sıfır regresyonla):
   Desktop — `ca196778` ajan yığını · `900869c8` zincirleme+exit kodu+teslimat ·
   `0babc6f6` kısa liste+bütçe · `32ca3ae8` durumsal füzyon · `60c24acc` başlık
   bağlama · `1f1b8bc8` sinyal köprüsü.
   Backend — `fc1bb58c` manifest paritesi · `2ad9d6a0` bayat test · `4d71adac`
   world signal digest.

5. **Ölçülmemiş:** digest'in GERÇEK kullanıcı verisiyle dolduğu görülmedi
   (`world_signals` tablosunda kaydı olan hesapla profil çağrısı yapılmadı).
   Mantık + gizlilik testlerle sabit, canlı veri akışı ölçülmedi.

---

## 6. BAYRAKLAR / KOMUTLAR

```bash
# Ajan döngüsünü kapat (eski davranışa dön)
ELYAN_AGENT_LOOP=0

# Saf deterministik mod (dış beyin yok; ajan döngüsü otomatik kapalı)
ELYAN_DETERMINISTIC_ONLY=1

# Groq Compound (backend .env)
GROQ_COMPOUND_ENABLED=true
```

```bash
source .venv/bin/activate && PYTHONPATH=. python -m pytest tests/ -q
```

**Regresyon ölçme yöntemi** (bunu kullan, "kaç test kırıldı" diye tahmin etme):
```bash
PYTHONPATH=. python -m pytest <suite> -q 2>&1 | grep ^FAILED | sort > /tmp/on.txt
ELYAN_AGENT_LOOP=0 PYTHONPATH=. python -m pytest <suite> -q 2>&1 | grep ^FAILED | sort > /tmp/off.txt
comm -23 /tmp/on.txt /tmp/off.txt   # boşsa sıfır regresyon
```

---

## 7. ÇALIŞMA İLKELERİ (acı deneyimle öğrenildi)

1. **Onay/plan-önizleme UX'ini asla atlama.** Yan etkili iş onaysız çalışmamalı.
   Bir "iyileştirme" bu kapıyı atlıyorsa yanlıştır.
2. **Regex/desen ekleyerek sorun çözme — YASAK.** Dipsiz kuyu; aylardır
   bitmemesinin sebebi buydu. Anlama işi `understanding.py`'de MODELE aittir;
   router ve `intent_gate` desenleri yalnız **yüksek güvenli hızlı yol** ve
   **bozulmuş mod yedeği**dir. Yeni cümle kalıbı için desen ekleme — model anlıyor;
   anlamıyorsa prompt/şema düzelt.
3. **Belirsizlik → sohbet.** Yanlış yan etki üretmektense kullanıcı tekrar sorsun.
4. **Her değişiklikten sonra regresyonu yukarıdaki `comm` yöntemiyle ölç.**
5. **Ne yapıldığını abartma.** Yarım wiring canlıyı bozar; bitmediyse "bitmedi" yaz.
