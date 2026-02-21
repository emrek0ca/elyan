# ELYAN — Kapsamlı Geliştirme Yol Haritası

**Son Güncelleme:** 2026-02-18  
**Versiyon:** 18.0.0  
**Ürün Sınıfı:** Özerk AI Operatör / Dijital Çalışan

---

## 1. Ürün Vizyonu

Elyan bir sohbet botu değildir.  
Elyan = **bilgisayarda çalışan, teslimat odaklı dijital operatör.**

```
Goal → Contract → Plan → Execute → Verify → Deliver → Learn
```

Bu zincirin tamamı gerçekleşmeden görev tamamlanmış sayılmaz.

---

## 2. KRİTİK HATALAR — Acil Düzeltilmesi Gerekenler

> Bu bölüm mevcut kodda tespit edilen gerçek hataları içerir. Her biri üretim ortamında ciddi sorun yaratır.

### 2.1 Güvenlik Açıkları (CRITICAL)

#### BUG-SEC-001: Approval Manager — Bellek Sızıntısı & Race Condition
**Dosya:** `security/approval.py`  
**Satır:** 53, 112-138  
**Sorun:**
- `pending_requests` dict'i hiçbir zaman temizlenmiyor. Timeout olan istekler `del` ile silinse de exception durumunda dict'te kalıyor.
- `asyncio.wait_for` timeout'u yakalarken `del self.pending_requests[request_id]` satırı `finally` bloğunda değil, `try` bloğu dışında. Exception fırlarsa request dict'te sonsuza kadar kalır.
- Aynı kullanıcı için birden fazla pending request birikebilir — stale request temizleme yok.

**Düzeltme:**
```python
# finally bloğu zorunlu:
try:
    approved = await asyncio.wait_for(...)
except asyncio.TimeoutError:
    approved = False
finally:
    self.pending_requests.pop(request_id, None)
    self.approval_history.append(request)
```

#### BUG-SEC-002: Tool Policy — Bypass Açığı
**Dosya:** `security/tool_policy.py`  
**Satır:** 16-31  
**Sorun:**
- `is_allowed()` fonksiyonu `tool_group=None` ile çağrıldığında grup kontrolü tamamen atlanıyor.
- `"*"` wildcard allow listesinde varsa `denied_tools` kontrolü **önce** yapılıyor ama `tool_group` bazlı deny kontrolü sonra yapılıyor — sıra hatası.
- `check_access()` fonksiyonu `requires_approval` döndürüyor ama bu değer hiçbir yerde zorunlu olarak kullanılmıyor.

**Düzeltme:** Deny listesi her zaman allow listesinden önce kontrol edilmeli. Group-level deny, tool-level allow'u geçersiz kılmalı.

#### BUG-SEC-003: Rate Limiter — Thread Safety Yok
**Dosya:** `security/rate_limiter.py`  
**Satır:** 23-25, 38-62  
**Sorun:**
- `user_requests`, `burst_tracker`, `last_request` dict'leri `defaultdict` ile tanımlanmış ama `asyncio` ortamında concurrent erişim var.
- `is_allowed()` fonksiyonu async değil — blocking I/O içermiyor ama concurrent coroutine'ler aynı anda `user_requests[user_id]` listesini mutate edebilir.
- Burst tracker sıfırlama mantığı yanlış: `else: self.burst_tracker[user_id] = 0` — burst sayacı her normal istekte sıfırlanıyor, bu burst korumasını etkisiz kılıyor.

**Düzeltme:** `asyncio.Lock()` kullanımı veya `threading.Lock()` ile koruma.

#### BUG-SEC-004: Audit Logger — SQL Injection Riski & Bağlantı Yönetimi
**Dosya:** `security/audit.py`  
**Satır:** 44, 225-236  
**Sorun:**
- `sqlite3.connect(..., check_same_thread=False)` — thread safety devre dışı bırakılmış, WAL mode ile kısmen telafi edilmiş ama yetersiz.
- `get_operation_history()` fonksiyonunda `query` string'i `operation` parametresi ile dinamik olarak oluşturuluyor — parameterized query kullanılıyor ama `WHERE 1=1` pattern'i gereksiz.
- `self.conn` hiçbir zaman kapatılmıyor (context manager yok, `__del__` yok).
- Global `_audit_logger` singleton thread-safe değil — iki thread aynı anda `None` kontrolü yapıp iki instance oluşturabilir.

#### BUG-SEC-005: API Anahtarları .env'de Düz Metin
**Dosya:** `.env`  
**Sorun:** API anahtarları (Anthropic, OpenAI, Telegram token) düz metin olarak `.env` dosyasında saklanıyor. Keychain entegrasyonu (`security/keychain.py` mevcut) ama kullanılmıyor.

**Düzeltme:** `security/keychain.py` aktif olarak kullanılmalı. macOS Keychain'e migration yapılmalı.

---

### 2.2 Kritik Fonksiyonel Hatalar (HIGH)

#### BUG-FUNC-001: main.py — Async Loop Yönetimi
**Dosya:** `main.py`  
**Satır:** 47-66  
**Sorun:**
- `asyncio.new_event_loop()` + `asyncio.set_event_loop(loop)` pattern'i kullanılıyor ama `loop.close()` finally bloğunda çağrılmıyor.
- `KeyboardInterrupt` dışındaki exception'larda `server.stop()` çağrılmıyor — gateway temiz kapanmıyor.
- `--onboard` ve `--cli` flag'leri aynı anda verilebilir, öncelik tanımlanmamış.

**Düzeltme:**
```python
try:
    loop.run_forever()
except KeyboardInterrupt:
    pass
finally:
    loop.run_until_complete(server.stop())
    loop.close()
```

#### BUG-FUNC-002: Telegram Handler — Stale Approval Race
**Dosya:** `handlers/telegram_handler.py`  
**Sorun:** (Önceki oturumda kısmen düzeltildi)
- `call_soon_threadsafe` ile pending approval çözümleniyor ama callback'in gerçekten çağrıldığı doğrulanmıyor.
- `/cancel` komutu sadece en son pending request'i iptal ediyor, kullanıcının birden fazla pending request'i varsa diğerleri askıda kalıyor.

#### BUG-FUNC-003: Memory — Embedding Tipi Uyumsuzluğu
**Dosya:** `core/memory.py`  
**Sorun:** `prisma.memory.create` çağrısında `embedding` alanı `Json` tipinde tanımlanmış ama bazı yerlerde liste olarak, bazı yerlerde JSON string olarak gönderiliyor. Tip tutarsızlığı runtime hatasına yol açıyor.

#### BUG-FUNC-004: Intent Parser — Aşırı Büyük Dosya
**Dosya:** `core/intent_parser.py`  
**Boyut:** 100KB (!)  
**Sorun:** Tek dosyada 100KB+ kod — import süresi yavaş, test edilmesi imkansız, bakımı zor. Modüllere bölünmeli.

#### BUG-FUNC-005: Task Engine — Aşırı Büyük Dosya
**Dosya:** `core/task_engine.py`  
**Boyut:** 85KB (!)  
**Sorun:** Aynı sorun. Monolitik yapı — hata izolasyonu imkansız.

#### BUG-FUNC-006: Duplicate UI Dosyaları
**Dizin:** `ui/`  
**Sorun:** Aynı işlevi gören birden fazla dosya mevcut:
- `setup_wizard.py` + `enhanced_setup_wizard.py` + `apple_setup_wizard.py` (3 ayrı wizard)
- `main_app.py` + `clean_main_app.py` (2 ayrı main app)
- `chat_widget.py` + `clean_chat_widget.py` (2 ayrı chat widget)
- `settings_panel.py` + `settings_panel_ui.py` (2 ayrı settings)

Hangi dosyanın aktif olduğu belirsiz. Dead code riski yüksek.

#### BUG-FUNC-007: CLI Commands — Stub Implementasyonlar
**Dizin:** `cli/commands/`  
**Sorun:** Birçok CLI komutu stub/placeholder:
- `voice.py` — 377 byte, içi boş
- `agents.py` — 622 byte, içi boş  
- `browser.py` — 917 byte, minimal
- `memory.py` — 663 byte, minimal
- `dashboard.py` — 389 byte, sadece URL açıyor

#### BUG-FUNC-008: Cron/Scheduler — Persistence Yok
**Dosya:** `core/scheduler/`  
**Sorun:** Cron işleri yalnızca bellekte tutuluyor. Sistem yeniden başlatıldığında tüm zamanlanmış görevler kayboluyor. Disk'e persist edilmiyor.

#### BUG-FUNC-009: Gateway — Port Çakışması Yönetimi Yok
**Dosya:** `core/gateway/`  
**Sorun:** Port 18789 kullanımda ise gateway başlamıyor ve anlaşılır hata mesajı vermiyor. `elyan doctor` bu durumu tespit etmiyor.

#### BUG-FUNC-010: Config Manager — JSON5 Parse Hatası
**Dosya:** `core/config_manager.py`  
**Sorun:** `elyan.json` JSON5 formatında ama Python'da native JSON5 desteği yok. Yorum satırları (`//`) parse hatası yaratıyor. `json5` kütüphanesi `requirements.txt`'de yok.

---

### 2.3 Performans Sorunları (MEDIUM)

#### BUG-PERF-001: LLM Cache — Kısa Yanıt Cache'leme
**Dosya:** `core/llm_cache.py`, `core/response_cache.py`  
**Sorun:** Boş veya çok kısa yanıtlar cache'leniyor. Kullanıcı "tekrar dene" dediğinde cache'den aynı hatalı yanıt geliyor. (Önceki oturumda kısmen düzeltildi ama tam çözüm yok.)

**Düzeltme:** Min token threshold + cache bypass keyword listesi.

#### BUG-PERF-002: Intent Parser — Her İstekte Regex Derleme
**Dosya:** `core/intent_parser.py`  
**Sorun:** Regex pattern'leri her istek için yeniden derleniyor. `re.compile()` sonuçları modül seviyesinde cache'lenmeli.

#### BUG-PERF-003: Fuzzy Intent — 35KB Tek Dosya
**Dosya:** `core/fuzzy_intent.py`  
**Boyut:** 35KB  
**Sorun:** Fuzzy matching için gereksiz büyük dosya. Performans profili çıkarılmamış.

---

## 3. GÜVENLİK MİMARİSİ — Yapılacaklar

### 3.1 Acil Güvenlik Düzeltmeleri

| Öncelik | Görev | Dosya | Durum |
|---------|-------|-------|-------|
| P0 | Approval Manager finally bloğu | `security/approval.py` | ❌ Açık |
| P0 | Tool Policy deny-before-allow | `security/tool_policy.py` | ❌ Açık |
| P0 | Rate Limiter async lock | `security/rate_limiter.py` | ❌ Açık |
| P0 | API key → Keychain migration | `security/keychain.py` | ❌ Açık |
| P1 | Audit Logger connection pool | `security/audit.py` | ❌ Açık |
| P1 | Sandbox Docker entegrasyonu | `core/sandbox/` | ⚠️ Kısmi |
| P2 | Input sanitization (Telegram) | `handlers/telegram_handler.py` | ⚠️ Kısmi |
| P2 | Command injection koruması | `tools/terminal_tools.py` | ❌ Açık |

### 3.2 Güvenlik Katmanları (Hedef Mimari)

```
Kullanıcı Mesajı
    ↓
[1] Rate Limiter (async-safe)
    ↓
[2] Input Sanitizer (injection temizleme)
    ↓
[3] Intent Parser
    ↓
[4] Tool Policy Engine (deny-first)
    ↓
[5] Risk Classifier
    ↓
[6] Approval Gate (gerekirse)
    ↓
[7] Sandbox Executor
    ↓
[8] Audit Logger
    ↓
Sonuç
```

### 3.3 Operator Güvenlik Seviyeleri

| Seviye | Davranış | Otomatik İzin |
|--------|----------|---------------|
| Advisory | Sadece öneri | Hiçbir şey |
| Assisted | Komutla çalışır | Güvenli okuma |
| Confirmed | Onay ister | Düşük risk |
| Trusted | Otomatik yapar | Orta risk |
| Operator | Workflow başlatır | Yüksek risk |

---

## 4. CLI — TAM ÖZELLİK LİSTESİ

### 4.1 Kurulum & Başlangıç

```bash
# Tek komut kurulum (macOS/Linux)
curl -fsSL https://elyan.ai/install.sh | bash

# Windows PowerShell
iwr -useb https://elyan.ai/install.ps1 | iex

# Manuel kurulum
pip install elyan-cli
elyan onboard
elyan onboard --install-daemon    # Oto-başlatma ile
elyan onboard --headless          # UI olmadan (sunucu)
elyan onboard --channel telegram  # Sadece Telegram
elyan onboard --channel discord   # Sadece Discord
```

**Onboarding Adımları (Sihirbaz):**
1. Sistem gereksinimleri kontrolü (Node.js, Python, RAM)
2. AI sağlayıcı seçimi (Anthropic / OpenAI / Google / Yerel)
3. API anahtarı girişi ve doğrulama
4. Kanal seçimi ve bağlantı (Telegram, WhatsApp, Discord...)
5. Asistan kişiliği ve dil ayarı
6. Sandbox modu seçimi (Docker / Host / Restricted)
7. Oto-başlatma ayarı (launchd / systemd / PM2)
8. İlk sağlık kontrolü

---

### 4.2 Gateway Yönetimi

```bash
elyan gateway start               # Gateway başlat
elyan gateway start --port 8080   # Özel port
elyan gateway start --daemon      # Arka planda çalıştır
elyan gateway stop                # Gateway durdur
elyan gateway restart             # Yeniden başlat
elyan gateway status              # Durum göster
elyan gateway status --json       # JSON formatında
elyan gateway logs                # Canlı log akışı
elyan gateway logs --tail 100     # Son 100 satır
elyan gateway logs --level error  # Sadece hatalar
elyan gateway logs --filter telegram  # Kanal filtresi
elyan gateway reload              # Config yeniden yükle (restart olmadan)
elyan gateway health              # Sağlık endpoint'i
```

**Beklenen Çıktı (`elyan gateway status`):**
```
● Elyan Gateway v18.0.0
  Status:    RUNNING (PID: 12345)
  Uptime:    2h 34m 12s
  Port:      18789
  Dashboard: http://127.0.0.1:18789/dashboard

  Channels:
    ✓ Telegram    (@elyan_bot) — Connected
    ✓ Discord     (#general)  — Connected
    ✗ WhatsApp    — Disconnected (auth expired)

  Models:
    ✓ claude-opus-4-5  — Active (primary)
    ✓ gpt-4o           — Standby (fallback)

  Memory:    247 MB / 4096 MB
  Tasks:     3 active, 12 queued
```

---

### 4.3 Sistem Tanılama

```bash
elyan doctor                      # Tam sistem kontrolü
elyan doctor --fix                # Sorunları otomatik düzelt
elyan doctor --deep               # Derinlemesine analiz
elyan doctor --check security     # Sadece güvenlik kontrolü
elyan doctor --check network      # Sadece ağ kontrolü
elyan doctor --check models       # Model bağlantıları
elyan doctor --check channels     # Kanal bağlantıları
elyan doctor --check sandbox      # Sandbox durumu
elyan doctor --report             # Rapor dosyası oluştur
elyan health                      # Hızlı sağlık özeti
elyan status                      # Genel durum
elyan status --deep               # Detaylı durum analizi
elyan status --json               # JSON çıktı
elyan update                      # Sürümü güncelle
elyan update --check              # Güncelleme var mı kontrol et
elyan update --beta               # Beta sürüme geç
elyan version                     # Versiyon bilgisi
```

**`elyan doctor` Kontrol Listesi:**
- [ ] Python sürümü (3.11+)
- [ ] Gerekli paketler kurulu mu
- [ ] `.env` dosyası mevcut ve geçerli mi
- [ ] API anahtarları çalışıyor mu (test isteği)
- [ ] Port 18789 müsait mi
- [ ] Telegram bot token geçerli mi
- [ ] Docker/sandbox erişilebilir mi
- [ ] Disk alanı yeterli mi (>500MB)
- [ ] RAM yeterli mi (>2GB)
- [ ] Log dosyaları aşırı büyük mü (>100MB)
- [ ] Cron işleri çalışıyor mu
- [ ] Güvenlik açıkları var mı

---

### 4.4 Kanal Yönetimi

```bash
elyan channels list               # Tüm kanalları listele
elyan channels list --json        # JSON formatında
elyan channels status             # Bağlantı durumları
elyan channels add                # Etkileşimli kanal ekleme
elyan channels add telegram       # Telegram ekle
elyan channels add discord        # Discord ekle
elyan channels add whatsapp       # WhatsApp ekle
elyan channels add slack          # Slack ekle
elyan channels add signal         # Signal ekle
elyan channels remove telegram    # Kanal sil
elyan channels enable telegram    # Kanalı etkinleştir
elyan channels disable discord    # Kanalı devre dışı bırak
elyan channels login telegram     # Kimlik doğrulama
elyan channels logout telegram    # Oturumu kapat
elyan channels test telegram      # Bağlantı testi (mesaj gönder)
elyan channels info telegram      # Kanal detayları
elyan channels sync               # Tüm kanalları senkronize et
```

**Desteklenen Kanallar:**
| Kanal | Durum | Özellikler |
|-------|-------|------------|
| Telegram | ✅ Aktif | Bot, inline, grup, dosya |
| Discord | ✅ Aktif | Slash commands, embed |
| WhatsApp | ⚠️ Beta | DM, grup (QR auth) |
| Slack | ✅ Aktif | Bot DM, kanal mesajı |
| Signal | 🔧 Geliştirme | Özel sohbet |
| iMessage | 🔧 Geliştirme | BlueBubbles gerekli |
| Google Chat | 📋 Planlı | Workspace entegrasyonu |
| Teams | 📋 Planlı | Microsoft 365 |
| Matrix | 📋 Planlı | Federe sohbet |
| WebChat | ✅ Aktif | Tarayıcı arayüzü |

---

### 4.5 Beceri (Skill) Yönetimi

```bash
elyan skills list                 # Yüklü becerileri listele
elyan skills list --available     # Mevcut tüm beceriler
elyan skills list --enabled       # Sadece aktif beceriler
elyan skills info <name>          # Beceri detayları
elyan skills check                # Gereksinim kontrolü
elyan skills install <name>       # Beceri yükle
elyan skills install gog          # Gmail/Calendar
elyan skills install github       # GitHub entegrasyonu
elyan skills install notion       # Notion entegrasyonu
elyan skills enable <name>        # Beceriyi etkinleştir
elyan skills disable <name>       # Beceriyi devre dışı bırak
elyan skills update <name>        # Beceriyi güncelle
elyan skills update --all         # Tüm becerileri güncelle
elyan skills remove <name>        # Beceriyi kaldır
elyan skills search <query>       # ClawHub'da ara

# ClawHub (Beceri Marketi)
npx clawhub search calendar
npx clawhub install gog
npx clawhub list --category productivity
```

**Resmi Beceriler (53+):**
| Beceri | Açıklama | Durum |
|--------|----------|-------|
| gog | Gmail + Google Calendar | ✅ |
| mog | Microsoft 365 (Outlook, Teams) | ✅ |
| github | GitHub repo, PR yönetimi | ✅ |
| slack | Slack kanal işlemleri | ✅ |
| notion | Notion veritabanları | ✅ |
| obsidian | Not ve bilgi tabanı | ✅ |
| trello | Proje yönetimi | ✅ |
| spotify | Müzik kontrolü | ✅ |
| twitter | Sosyal medya | ✅ |
| hue | Philips akıllı ışıklar | ✅ |
| whoop | Fitness ve sağlık | ✅ |
| elevenlabs | Metin-konuşma sentezi | ✅ |
| whisper | Konuşma-metin çevirisi | ✅ |
| nano-nano | Ses işleme | ✅ |
| ifttt | Otomasyon kuralları | ✅ |

---

### 4.6 Bellek & Oturum Yönetimi

```bash
elyan memory status               # Bellek durumu
elyan memory status --size        # Boyut bilgisi
elyan memory index                # İndeksi yenile
elyan memory search "query"       # Bellekte ara
elyan memory search --user 123    # Kullanıcıya göre ara
elyan memory export               # Belleği dışa aktar
elyan memory export --format json # JSON formatında
elyan memory import <file>        # Bellek içe aktar
elyan memory clear                # Belleği temizle (onay ister)
elyan memory clear --user 123     # Kullanıcı belleğini temizle
elyan memory stats                # İstatistikler

elyan sessions list               # Aktif oturumlar
elyan sessions list --all         # Tüm oturumlar
elyan sessions history            # Geçmiş oturumlar
elyan sessions history --limit 50 # Son 50 oturum
elyan sessions info <id>          # Oturum detayı
elyan sessions kill <id>          # Oturumu sonlandır
elyan sessions export <id>        # Oturumu dışa aktar
```

---

### 4.7 Yapılandırma

```bash
elyan config                      # Etkileşimli yapılandırma sihirbazı
elyan config show                 # Tüm yapılandırmayı göster
elyan config show --masked        # API key'leri maskeli göster
elyan config get models.default.provider   # Değer oku
elyan config set models.default.model "claude-opus-4-5"  # Değer ayarla
elyan config set tools.deny '["exec"]'     # JSON değer
elyan config unset tools.deny     # Değeri sil
elyan config validate             # Yapılandırmayı doğrula
elyan config reset                # Varsayılana sıfırla (onay ister)
elyan config export               # Yapılandırmayı dışa aktar
elyan config import <file>        # Yapılandırmayı içe aktar
elyan config edit                 # Editörde aç ($EDITOR)

# Model yapılandırması
elyan config set models.default.provider anthropic
elyan config set models.default.model claude-opus-4-5-20251101
elyan config set models.fallback.provider openai
elyan config set models.fallback.model gpt-4o

# Güvenlik yapılandırması
elyan config set tools.allow '["group:fs","group:web","browser"]'
elyan config set tools.deny '["exec","delete_file"]'
elyan config set sandbox.enabled true
elyan config set sandbox.mode docker
```

---

### 4.8 Otomasyon — Cron & Webhook

```bash
# Cron işleri
elyan cron list                   # Tüm cron işleri
elyan cron status                 # Cron durumu
elyan cron add                    # Etkileşimli ekleme
elyan cron add --expression "47 6 * * *" --prompt "Sabah brifing"
elyan cron add --expression "0 18 * * *" --prompt "Haber özeti"
elyan cron add --expression "0 */6 * * *" --prompt "Heartbeat görevi"
elyan cron rm <id>                # Cron işi sil
elyan cron enable <id>            # Etkinleştir
elyan cron disable <id>           # Devre dışı bırak
elyan cron run <id>               # Manuel çalıştır
elyan cron history <id>           # Çalışma geçmişi
elyan cron next <id>              # Sonraki çalışma zamanı

# Webhook yönetimi
elyan webhooks list               # Tüm webhook'lar
elyan webhooks gmail setup        # Gmail Pub/Sub kur
elyan webhooks gmail setup --account user@gmail.com
elyan webhooks add <name> <url>   # Özel webhook ekle
elyan webhooks remove <name>      # Webhook sil
elyan webhooks test <name>        # Webhook test et
elyan webhooks logs <name>        # Webhook logları

# Mesaj gönderme
elyan message send "Merhaba"      # Varsayılan kanala gönder
elyan message send "Merhaba" --channel telegram
elyan message send "Merhaba" --channel discord --channel slack
elyan message poll "Soru?" --options "Evet,Hayır" --channel slack
elyan message broadcast "Duyuru"  # Tüm kanallara gönder
```

---

### 4.9 Tarayıcı Kontrolü

```bash
elyan browser snapshot            # Sayfa ekran görüntüsü
elyan browser screenshot          # Tam sayfa görüntüsü
elyan browser click "[element]"   # Öğeye tıkla
elyan browser type "[text]"       # Metin yaz
elyan browser navigate "url"      # URL'ye git
elyan browser extract-text        # Sayfa metnini çıkar
elyan browser extract-links       # Sayfa linklerini çıkar
elyan browser fill-form           # Form doldur (etkileşimli)
elyan browser scroll down         # Aşağı kaydır
elyan browser scroll up           # Yukarı kaydır
elyan browser back                # Geri git
elyan browser forward             # İleri git
elyan browser refresh             # Sayfayı yenile
elyan browser profiles list       # Tarayıcı profillerini listele
elyan browser profiles add        # Yeni profil ekle
elyan browser profiles switch <n> # Profile geç
elyan browser close               # Tarayıcıyı kapat
```

---

### 4.10 Güvenlik & Denetim

```bash
elyan security audit              # Tam güvenlik denetimi
elyan security audit --fix        # Sorunları düzelt
elyan security audit --report     # Rapor oluştur
elyan security status             # Güvenlik durumu
elyan security events             # Güvenlik olayları
elyan security events --severity critical  # Kritik olaylar
elyan security events --last 24h  # Son 24 saat

elyan auth add                    # Kimlik doğrulama ekle
elyan auth list                   # Kimlik bilgileri listesi
elyan auth remove <name>          # Kimlik bilgisi sil
elyan auth setup-token            # Token başlat
elyan auth rotate                 # Token yenile
elyan auth test                   # Kimlik doğrulama testi

elyan sandbox list                # Sandbox ortamları
elyan sandbox status              # Sandbox durumu
elyan sandbox create              # Yeni sandbox oluştur
elyan sandbox recreate            # Sandbox'u yeniden oluştur
elyan sandbox destroy             # Sandbox'u sil
elyan sandbox exec "command"      # Sandbox'ta komut çalıştır
elyan sandbox logs                # Sandbox logları
```

---

### 4.11 Model Yönetimi

```bash
elyan models list                 # Mevcut modeller
elyan models list --provider anthropic  # Sağlayıcıya göre
elyan models status               # Model durumu
elyan models test                 # Model bağlantı testi
elyan models set-default <model>  # Varsayılan model ayarla
elyan models set-fallback <model> # Fallback model ayarla
elyan models cost                 # Maliyet tahmini
elyan models cost --last 30d      # Son 30 gün maliyet

# Yerel model (Ollama)
elyan models ollama list          # Ollama modelleri
elyan models ollama pull llama3   # Model indir
elyan models ollama start         # Ollama başlat
elyan models ollama stop          # Ollama durdur
```

---

### 4.12 Multi-Agent Yönetimi

```bash
elyan agents list                 # Agent listesi
elyan agents status               # Agent durumları
elyan agents add                  # Yeni agent ekle
elyan agents remove <id>          # Agent sil
elyan agents start <id>           # Agent başlat
elyan agents stop <id>            # Agent durdur
elyan agents logs <id>            # Agent logları
elyan agents route <id> --channel telegram  # Kanal yönlendirme
```

**Multi-Agent Yapılandırması (`elyan.json`):**
```json5
{
  "agents": [
    {
      "id": "work",
      "workspace": "./work-workspace",
      "routes": ["slack", "github"],
      "model": "claude-opus-4-5"
    },
    {
      "id": "personal",
      "workspace": "./personal-workspace",
      "routes": ["telegram", "whatsapp"],
      "model": "gpt-4o"
    }
  ]
}
```

---

### 4.13 Ses & Multimodal

```bash
elyan voice start                 # Ses modunu başlat
elyan voice stop                  # Ses modunu durdur
elyan voice status                # Ses durumu
elyan voice test                  # Mikrofon testi
elyan voice set-wake-word "elyan" # Uyandırma kelimesi
elyan voice set-tts elevenlabs    # TTS sağlayıcı
elyan voice set-stt whisper       # STT sağlayıcı
elyan voice transcribe <file>     # Ses dosyasını metne çevir
elyan voice speak "Merhaba"       # Metni seslendir
```

---

### 4.14 Hızlı Başvuru Tablosu

```bash
# En sık kullanılan komutlar
elyan onboard                     # İlk kurulum
elyan gateway start               # Başlat
elyan gateway status              # Durum
elyan doctor                      # Sorun giderme
elyan update                      # Güncelle
elyan skills list                 # Beceri listesi
elyan channels list               # Kanal listesi
elyan config show                 # Yapılandırma
elyan security audit              # Güvenlik kontrolü

# Hızlı test
echo "Merhaba" | elyan message send --channel telegram

# Üretime geçiş
elyan onboard --install-daemon    # Oto-başlatma kur
elyan security audit              # Güvenlik kontrol
elyan doctor --fix                # Sorunları düzelt
elyan gateway start --daemon      # Arka planda başlat
```

---

## 5. WEB ARAYÜZÜ (Dashboard) — TAM ÖZELLİK LİSTESİ

```bash
elyan dashboard                   # Dashboard'u aç (http://127.0.0.1:18789)
elyan dashboard --port 8080       # Özel port
elyan dashboard --no-browser      # Tarayıcı açma
```

### 5.1 Ana Ekran (Overview)

**Sol Sidebar:**
- Logo + versiyon
- Navigasyon menüsü (ikonlu)
- Sistem durumu göstergesi (yeşil/sarı/kırmızı)
- Aktif görev sayısı (badge)

**Ana Panel — Durum Kartları:**
```
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  Gateway        │ │  Aktif Görevler │ │  Bellek         │
│  ● ÇALIŞIYOR   │ │  3 aktif        │ │  247 MB         │
│  2h 34m uptime  │ │  12 kuyrukta    │ │  %6 kullanım    │
└─────────────────┘ └─────────────────┘ └─────────────────┘
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  Model          │ │  Bu Ay Maliyet  │ │  Başarı Oranı   │
│  claude-opus-4  │ │  $12.45         │ │  %94.2          │
│  Anthropic      │ │  Limit: $50     │ │  ↑ %2.1         │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

**Canlı Aktivite Akışı:**
- Son 10 işlem (timestamp, kanal, işlem tipi, durum)
- Gerçek zamanlı güncelleme (WebSocket)
- Filtre: kanal, işlem tipi, başarı/hata

---

### 5.2 Sohbet Arayüzü (Chat)

**Özellikler:**
- Çoklu kanal seçimi (dropdown)
- Mesaj geçmişi (sayfalama)
- Dosya yükleme (sürükle-bırak)
- Ses kaydı (push-to-talk butonu)
- Markdown render (kod bloğu, tablo, liste)
- Kod kopyalama butonu
- Mesaj düzenleme / silme
- Tepki ekleme (emoji)
- Arama (mesaj içinde)
- Dışa aktarma (JSON, Markdown, PDF)

**Canvas Modu:**
- Yapılacak listesi (interaktif checkbox)
- Takvim görünümü (haftalık/aylık)
- Grafik ve veri görselleştirmesi
- Dinamik formlar
- Kod editörü (syntax highlighting)

---

### 5.3 Kanal Yönetimi (Channels)

**Kanal Listesi:**
- Her kanal için: ikon, isim, durum, son aktivite, mesaj sayısı
- Bağlan / Bağlantıyı Kes butonu
- Ayarlar (kanal başına)
- Test mesajı gönder

**Kanal Ekleme Sihirbazı:**
1. Platform seçimi (görsel ikonlar)
2. Kimlik doğrulama (token / QR kod / OAuth)
3. Bağlantı testi
4. Bildirim ayarları
5. Tamamlandı

---

### 5.4 Beceri Yönetimi (Skills)

**Beceri Galerisi:**
- Kategori filtresi (Üretkenlik, Entegrasyon, Medya, Otomasyon)
- Arama kutusu
- Her beceri kartı: ikon, isim, açıklama, yıldız, yüklü/değil
- Tek tıkla yükleme / kaldırma
- Beceri detay sayfası (dokümantasyon, gereksinimler, örnekler)

**Yüklü Beceriler:**
- Etkinleştir / Devre Dışı Bırak toggle
- Yapılandırma (beceriye özel ayarlar)
- Kullanım istatistikleri
- Güncelleme bildirimi

---

### 5.5 Bellek Yönetimi (Memory)

**Bellek Görüntüleyici:**
- Kullanıcı bazlı bellek listesi
- Arama kutusu (semantic search)
- Bellek öğesi detayı (içerik, tarih, kaynak)
- Düzenleme / Silme
- Etiket sistemi

**Bellek İstatistikleri:**
- Toplam öğe sayısı
- Boyut kullanımı
- En çok erişilen öğeler
- Zaman çizelgesi grafiği

---

### 5.6 Görev Yönetimi (Tasks)

**Aktif Görevler:**
- Görev adı, başlangıç zamanı, tahmini süre
- İlerleme çubuğu
- Adım detayları (genişletilebilir)
- İptal butonu
- Öncelik değiştirme

**Görev Geçmişi:**
- Tamamlanan görevler listesi
- Başarı / Hata durumu
- Süre, maliyet, kalite skoru
- Çıktıyı görüntüle
- Yeniden çalıştır

**Görev Oluşturma:**
- Serbest metin girişi
- Şablon seçimi (Araştırma, Kod, Belge, Otomasyon)
- Zamanlama (hemen / belirli saat / cron)
- Öncelik (Düşük / Normal / Yüksek / Acil)
- Kanal seçimi (sonuç nereye gönderilsin)

---

### 5.7 Otomasyon (Automation)

**Cron İşleri:**
- Görsel cron builder (takvim arayüzü)
- Cron expression yardımcısı
- Sonraki çalışma zamanı gösterimi
- Çalışma geçmişi (başarı/hata grafiği)
- Etkinleştir / Devre Dışı Bırak toggle
- Manuel çalıştır butonu

**Webhook'lar:**
- Webhook URL'leri listesi
- Gelen istek logları (gerçek zamanlı)
- Test aracı (payload gönder)
- Güvenlik (secret key, IP whitelist)

**Heartbeat:**
- Heartbeat aralığı ayarı (slider)
- Son uyandırma zamanı
- Heartbeat görevi yapılandırması

---

### 5.8 Güvenlik (Security)

**Güvenlik Paneli:**
- Genel güvenlik skoru (0-100)
- Açık sorunlar listesi (öncelikli)
- Son güvenlik olayları
- Denetim logu (filtrelenebilir)

**Onay Yönetimi:**
- Bekleyen onaylar (bildirim badge)
- Onay geçmişi
- Güvenilir kullanıcılar listesi
- Otomatik onay kuralları

**Tool Politikaları:**
- Görsel allow/deny listesi
- Sürükle-bırak ile araç ekleme/çıkarma
- Risk seviyesi göstergesi
- Sandbox ayarları

---

### 5.9 Ayarlar (Settings)

**AI Modeli:**
- Sağlayıcı seçimi (Anthropic / OpenAI / Google / Yerel)
- Model seçimi (dropdown, mevcut modeller)
- API anahtarı (maskeli, test butonu)
- Fallback model yapılandırması
- Maliyet limiti (aylık)
- Token limiti (istek başına)

**Kişilik & Davranış:**
- Asistan adı
- Dil seçimi (Türkçe / İngilizce / ...)
- Yanıt tonu (Resmi / Gündelik / Teknik)
- Operator modu (Advisory → Operator)
- Plan onayı toggle
- Heartbeat ayarları

**Bildirimler:**
- Kanal bazlı bildirim ayarları
- Görev tamamlama bildirimi
- Hata bildirimi
- Güvenlik olayı bildirimi
- Maliyet uyarısı eşiği

**Sistem:**
- Oto-başlatma toggle
- Sandbox modu
- Log seviyesi
- Veri saklama süresi
- Yedekleme ayarları
- Tema (Açık / Koyu / Sistem)

---

### 5.10 Analitik (Analytics)

**Kullanım Grafikleri:**
- Günlük/haftalık/aylık görev sayısı
- Kanal bazlı kullanım dağılımı (pasta grafik)
- Başarı oranı trendi
- Ortalama görev süresi

**Maliyet Analizi:**
- Model bazlı maliyet dağılımı
- Günlük maliyet grafiği
- Tahmin (mevcut kullanım hızına göre)
- İndirilebilir rapor (CSV/PDF)

**Performans Metrikleri:**
| Metrik | Hedef | Mevcut |
|--------|-------|--------|
| Oturum yükleme | <50ms | - |
| İlk token | <500ms | - |
| Bash komutu | <100ms | - |
| Tarayıcı snapshot | <3s | - |
| Web fetch (50KB) | <2s | - |

---

## 6. MASAÜSTÜ UYGULAMASI (PyQt6) — ÖZELLİK LİSTESİ

### 6.1 Tray (Menü Çubuğu) Uygulaması

```
Menü Çubuğu İkonu:
  ● Elyan — Çalışıyor
  ─────────────────
  💬 Sohbet Aç
  📊 Dashboard Aç
  ─────────────────
  ⚡ Hızlı Görev...
  🎤 Ses Modu
  ─────────────────
  ⚙️ Ayarlar
  🔄 Yeniden Başlat
  ✕ Çıkış
```

### 6.2 Ana Pencere

**Sekme Yapısı:**
1. **Sohbet** — Ana chat arayüzü
2. **Görevler** — Aktif ve geçmiş görevler
3. **Beceriler** — Skill yönetimi
4. **Ayarlar** — Yapılandırma

**Sohbet Sekmesi:**
- Kanal seçici (üst bar)
- Mesaj listesi (bubble tasarım)
- Kod bloğu (syntax highlighting + kopyala)
- Dosya önizleme (resim, PDF)
- Giriş alanı (çok satırlı, Shift+Enter yeni satır)
- Gönder butonu + Ses butonu (push-to-talk)
- Emoji picker
- Dosya ekle butonu

### 6.3 Kurulum Sihirbazı (Setup Wizard)

**Adımlar:**
1. Hoş Geldiniz (logo, açıklama)
2. Sistem Gereksinimleri Kontrolü (otomatik)
3. AI Sağlayıcı Seçimi (görsel kartlar)
4. API Anahtarı Girişi (doğrulama butonu)
5. Kanal Seçimi (çoklu seçim)
6. Kanal Yapılandırması (seçilen kanallar için)
7. Sandbox Ayarları
8. Oto-Başlatma
9. Tamamlandı (test mesajı gönder)

**Mevcut Sorun:** 3 farklı wizard implementasyonu var (`setup_wizard.py`, `enhanced_setup_wizard.py`, `apple_setup_wizard.py`). Tek bir canonical wizard'a birleştirilmeli.

### 6.4 Ayarlar Paneli

- **Genel:** Dil, tema, başlangıç davranışı
- **AI Modeli:** Sağlayıcı, model, API key, maliyet limiti
- **Kanallar:** Her kanal için ayrı ayar sayfası
- **Güvenlik:** Operator modu, onay ayarları, sandbox
- **Beceriler:** Yüklü beceriler, yapılandırma
- **Bildirimler:** Bildirim kuralları
- **Gelişmiş:** Log seviyesi, debug modu, geliştirici seçenekleri

---

## 7. TEMEL ARAÇLAR (Tools) — TAM LİSTE

### 7.1 Dosya Sistemi (group:fs)
| Araç | Açıklama |
|------|----------|
| `read` | Dosya/klasör oku |
| `write` | Dosya oluştur/yaz |
| `edit` | Dosya düzenle |
| `apply_patch` | Çok parçalı düzeltme |
| `delete` | Dosya/klasör sil (onay gerekli) |
| `move` | Taşı/yeniden adlandır |
| `copy` | Kopyala |
| `list` | Dizin listele |
| `search` | Dosya ara |
| `watch` | Dosya değişikliklerini izle |

### 7.2 Çalıştırma (group:runtime)
| Araç | Açıklama |
|------|----------|
| `exec` | Shell komutu çalıştır (onay gerekli) |
| `bash` | Bash script çalıştır |
| `python` | Python kodu çalıştır |
| `process` | Sistem işlemlerini yönet |

### 7.3 Web (group:web)
| Araç | Açıklama |
|------|----------|
| `web_search` | İnternet arama |
| `web_fetch` | URL'den içerik al (45K+ karakter) |
| `web_screenshot` | Web sayfası ekran görüntüsü |

### 7.4 Tarayıcı (group:ui)
| Araç | Açıklama |
|------|----------|
| `browser_navigate` | URL'ye git |
| `browser_click` | Öğeye tıkla |
| `browser_type` | Metin yaz |
| `browser_screenshot` | Ekran görüntüsü |
| `browser_extract` | İçerik çıkar |
| `browser_fill_form` | Form doldur |
| `browser_scroll` | Kaydır |
| `browser_wait` | Bekle |

### 7.5 Mesajlaşma (group:messaging)
| Araç | Açıklama |
|------|----------|
| `send_message` | Mesaj gönder |
| `edit_message` | Mesaj düzenle |
| `delete_message` | Mesaj sil |
| `add_reaction` | Tepki ekle |
| `send_file` | Dosya gönder |
| `send_image` | Resim gönder |

### 7.6 Otomasyon (group:automation)
| Araç | Açıklama |
|------|----------|
| `cron_add` | Cron işi ekle |
| `cron_remove` | Cron işi sil |
| `cron_list` | Cron işlerini listele |
| `webhook_trigger` | Webhook tetikle |
| `heartbeat` | Düzenli uyandırma |

### 7.7 Bellek (group:memory)
| Araç | Açıklama |
|------|----------|
| `memory_store` | Bilgi kaydet |
| `memory_recall` | Bilgi geri çağır |
| `memory_search` | Semantik arama |
| `memory_forget` | Bilgi sil |
| `memory_summarize` | Bağlamı özetle |

---

## 8. YAPILANDIRMA DOSYASI (elyan.json)

```json5
{
  // AI Modeli
  models: {
    default: {
      provider: "anthropic",  // anthropic | openai | google | local
      model: "claude-opus-4-5-20251101",
      apiKey: "$ANTHROPIC_API_KEY",
      maxTokens: 8192,
      temperature: 0.7
    },
    fallback: {
      provider: "openai",
      model: "gpt-4o",
      apiKey: "$OPENAI_API_KEY"
    },
    local: {
      provider: "ollama",
      model: "llama3",
      baseUrl: "http://localhost:11434"
    }
  },

  // Araç politikaları
  tools: {
    allow: ["group:fs", "group:web", "browser", "group:messaging"],
    deny: ["exec"],  // Komut çalıştırmayı engelle
    requireApproval: ["delete_file", "write_file"],
    exec: { requireApproval: true }
  },

  // Sandbox
  sandbox: {
    enabled: true,
    mode: "docker",  // docker | host | restricted
    image: "elyan-sandbox:latest",
    memoryLimit: "512m",
    cpuLimit: 0.5
  },

  // Kanallar
  channels: [
    {
      type: "telegram",
      token: "$TELEGRAM_BOT_TOKEN",
      enabled: true,
      allowedUsers: [],  // Boş = herkese açık
      adminUsers: [123456789]
    },
    {
      type: "discord",
      token: "$DISCORD_BOT_TOKEN",
      enabled: true,
      guildId: "$DISCORD_GUILD_ID"
    }
  ],

  // Cron görevleri
  cron: [
    {
      id: "morning-brief",
      expression: "47 6 * * *",
      prompt: "Günlük brifing: takvim, e-posta, hava durumu",
      channel: "telegram",
      enabled: true
    }
  ],

  // Heartbeat
  heartbeat: {
    enabled: true,
    intervalMinutes: 360,
    prompt: "Bekleyen görevleri kontrol et"
  },

  // Bellek
  memory: {
    enabled: true,
    path: "~/.elyan/memory/",
    maxSizeMB: 500,
    autoSummarize: true,
    summarizeAfterMessages: 50
  },

  // Güvenlik
  security: {
    operatorMode: "Confirmed",  // Advisory|Assisted|Confirmed|Trusted|Operator
    requirePlanApproval: true,
    auditLog: true,
    rateLimitPerMinute: 20
  },

  // Gateway
  gateway: {
    port: 18789,
    host: "127.0.0.1",
    corsOrigins: ["http://localhost:3000"],
    webhookSecret: "$WEBHOOK_SECRET"
  }
}
```

---

## 9. GELİŞTİRME SPRINT PLANI

### Sprint G — Kritik Hata Düzeltmeleri (Öncelik: ACIL)
- [ ] BUG-SEC-001: Approval Manager finally bloğu
- [ ] BUG-SEC-002: Tool Policy deny-before-allow sırası
- [ ] BUG-SEC-003: Rate Limiter async lock ekleme
- [ ] BUG-SEC-004: Audit Logger connection pool
- [ ] BUG-SEC-005: API key → macOS Keychain migration
- [ ] BUG-FUNC-001: main.py loop.close() finally bloğu
- [ ] BUG-FUNC-008: Cron persistence (disk'e kaydet)
- [ ] BUG-FUNC-009: Port çakışması yönetimi
- [ ] BUG-FUNC-010: JSON5 parse — `json5` paketi ekle

### Sprint H — Kod Kalitesi & Refactor
- [ ] BUG-FUNC-004: `intent_parser.py` modüllere böl
- [ ] BUG-FUNC-005: `task_engine.py` modüllere böl
- [ ] BUG-FUNC-006: Duplicate UI dosyalarını birleştir (tek wizard, tek main app)
- [ ] BUG-FUNC-007: CLI stub komutlarını implement et (voice, agents, memory, browser)
- [ ] BUG-PERF-001: Cache bypass keyword listesi
- [ ] BUG-PERF-002: Regex pattern'leri modül seviyesinde compile et

### Sprint I — CLI Tamamlama
- [ ] `elyan voice` komutları tam implementasyon
- [ ] `elyan agents` komutları tam implementasyon
- [ ] `elyan memory` komutları tam implementasyon
- [ ] `elyan browser` komutları tam implementasyon
- [ ] `elyan security events` komutu
- [ ] `elyan models` komutları
- [ ] `elyan webhooks` komutları
- [ ] CLI çıktı formatları (--json, --table, --quiet)
- [ ] CLI renk teması ve progress bar'lar
- [ ] CLI otomatik tamamlama (bash/zsh completion)

### Sprint J — Dashboard Tamamlama
- [ ] Analitik sayfası (grafikler)
- [ ] Görev yönetimi sayfası (oluştur/iptal/yeniden çalıştır)
- [ ] Güvenlik sayfası (onay yönetimi, denetim logu)
- [ ] Kanal yönetimi (wizard ile ekleme)
- [ ] Beceri galerisi (ClawHub entegrasyonu)
- [ ] Gerçek zamanlı bildirimler (WebSocket)
- [ ] Mobil uyumlu tasarım

### Sprint K — Kanal Genişletme
- [ ] Signal entegrasyonu
- [ ] iMessage/BlueBubbles entegrasyonu
- [ ] Google Chat entegrasyonu
- [ ] Microsoft Teams entegrasyonu
- [ ] Matrix entegrasyonu

### Sprint L — Üretim Hazırlığı
- [ ] Docker imajı oluşturma
- [ ] Kubernetes helm chart
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Otomatik güvenlik taraması (Dependabot)
- [ ] Performans benchmark suite
- [ ] Yük testi
- [ ] Dokümantasyon sitesi (MkDocs)

---

## 10. BAŞARMA METRİKLERİ

### Sistem Metrikleri
| Metrik | Hedef |
|--------|-------|
| Görev başarı oranı | >%95 |
| Doğrulama geçme oranı | >%90 |
| Ortalama retry sayısı | <1.5 |
| Oturum yükleme süresi | <50ms |
| İlk token süresi | <500ms |

### Kullanıcı Değer Metrikleri
| Metrik | Hedef |
|--------|-------|
| Kullanıcı müdahalesi azalma | >%40 |
| Tekrar kullanılan çıktı oranı | >%60 |
| Görev tamamlama süresi kısalması | >%50 |

### Maliyet Tahminleri
| Kullanım Tipi | Aylık Tahmin |
|---------------|--------------|
| Hafif (sadece sohbet) | $5-20 |
| Aktif (daily briefs + tarayıcı) | $50-150 |
| Ağır (heartbeat + otomasyon) | $100-500+ |
| Yerel model (Ollama) | $0 |

---

## 11. GÜVENLİK UYARILARI

> ⚠️ **Kişisel bilgisayara kurma tavsiye edilmez.** Sistem tam dosya sistemi ve komut çalıştırma erişimine sahiptir.

**Önerilen Dağıtım Seçenekleri:**
1. **Dedicated VPS** (DigitalOcean, AWS, Hetzner) — En güvenli
2. **Raspberry Pi** (izole ağda) — Fiziksel kontrol
3. **Eski bilgisayar** (fiziksel erişim kontrollü)
4. **Docker container** (sandbox modunda)

**Minimum Güvenlik Gereksinimleri:**
```json5
{
  "tools": {
    "deny": ["exec", "delete_file"],
    "requireApproval": ["write_file", "run_command"]
  },
  "sandbox": { "enabled": true, "mode": "docker" },
  "security": { "operatorMode": "Confirmed" }
}
```

---

## 12. ÇALIŞMA KOMUTLARI (Geliştirici)

```bash
# Temiz başlatma
cd /Users/emrekoca/Desktop/bot
source .venv/bin/activate
pkill -f "python.*main.py|python.*elyan.py" 2>/dev/null || true
python main.py

# CLI modu
python main.py --cli

# Onboarding
python main.py --onboard

# Canlı log izleme
tail -f logs/*.log | grep -E "ERROR|WARNING|approval"

# Onay akışı izleme
tail -f logs/*.log | grep -E "Approval request|Approval button|Approval resolved"

# Syntax kontrolü
python3 -m py_compile handlers/telegram_handler.py security/approval.py

# Regresyon testleri
python scripts/regression_capability_pipeline.py


# Tüm testler
python -m pytest tests/ -v

# Bağımlılık kontrolü
pip check
pip list --outdated
```

---

*Son güncelleme: 2026-02-18 | Elyan v18.0.0*
