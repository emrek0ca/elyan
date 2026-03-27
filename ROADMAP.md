# ROADMAP.md — Elyan Operator Runtime

**Son Güncelleme**: 2026-03-27
**Mevcut Durum**: Phase 5.2.7 cowork-first desktop + workspace billing + connector platform in progress
**Test Durumu**: Targeted compile checks, cowork/billing/workflow tests, desktop build ve Tauri cargo check bu seansta geçti

---

## Genel Durum Özeti

| Katman | Durum | Notlar |
|--------|-------|--------|
| Performance (LRU Cache + AsyncExecutor) | ✓ Complete | 13 test |
| Approval System | ✓ Complete | 10 test |
| Run Store + Inspector | ✓ Canonicalized | `core/run_store.py` canonical, read-model fallback aktif |
| Security Hardening (Vault + Session + Audit) | ✓ Complete | 22 test |
| Security Hardening Program v1 | ⚠️ In Progress | ingress firewall, encrypted run fields, HTTP/Tauri hardening, desktop security visibility |
| Dashboard Redesign | ✓ Mostly Complete | Runtime config helper eklendi, hardcoded API URL'ler temizleniyor |
| Real-time Updates | ⚠️ In Progress | Gateway telemetry desktop shell'e cowork delta event'leri taşır; selected thread patching ilerliyor |
| Config Layer | ⚠️ In Progress | Gateway/API base URL helper merkezi hale getirildi |
| Cowork Desktop | ⚠️ In Progress | chat-first thread/workstream UX canonical hale getiriliyor |
| Workspace Billing | ⚠️ In Progress | Stripe-backed subscription + entitlement cache + usage ledger aktif, production env config eksik olabilir |
| Connector Platform | ⚠️ In Progress | workspace-owned connector accounts ve traces aktif, deeper app actions sırada |
| Health Checks | ✗ Stub | NotImplementedError |
| Alerting | ✗ Stub | NotImplementedError |

---

## Current Implementation Snapshot

- `core/run_store.py` canonical storage path olarak kullanılıyor.
- Telegram, CLI ve desktop komut yüzeyleri aynı normalized agent turn akışına bağlandı.
- `core/cowork_threads.py` ile canonical `CoworkThread` store eklendi; thread artık workspace/session truth, approvals, artifacts ve active mission/run referanslarını tek modelde taşır.
- `document`, `presentation` ve `website` lane'leri artık ayrı ürün adası değil; cowork thread içinden başlayan deterministic artifact akışlarıdır.
- Gateway artık resmi cowork API ailesini sunuyor: `/api/v1/cowork/home`, `/api/v1/cowork/threads`, `/api/v1/cowork/threads/{id}`, `/api/v1/cowork/threads/{id}/turns`, `/api/v1/cowork/approvals/{id}/resolve`.
- Command center artık canonical cowork yüzeyidir: thread listesi, follow-up composer, in-pane approvals, artifacts ve review state aynı workstream içinde görünür.
- Desktop websocket hattı artık cowork delta event ailesini (`cowork.thread.updated`, `cowork.turn.*`, `cowork.approval.*`, `cowork.artifact.added`) first-class olarak tüketir.
- Tool contract katmanı artık yalnızca parameter schema değildir; `execution_tier`, `required_permissions`, `preconditions`, `verification_method`, `rollback_strategy` ve `idempotency` alanlarıyla operational contract olarak tutulur.
- `core/billing/workspace_billing.py` ile workspace/team-owned hybrid billing katmanı eklendi; entitlement cache, usage ledger, checkout/portal/webhook uçları ve quota enforcement aynı katmanda çözülür.
- Gateway billing yüzeyi artık `/api/v1/billing/workspace`, `/api/v1/billing/usage`, `/api/v1/billing/entitlements`, `/api/v1/billing/checkout-session`, `/api/v1/billing/portal-session`, `/api/v1/billing/webhooks/stripe` rotalarını sunar.
- Desktop settings içinde workspace billing özeti ve upgrade/portal eylemleri first-class hale geldi; checkout veya portal açılışı Tauri shell üzerinden güvenli external URL launch ile yapılır.
- Connector platform workspace-owned modele taşındı; `/api/v1/connectors/*` ailesi Google Drive, Gmail, Google Calendar, Slack ve GitHub connector tanımı, hesap, health ve trace verisini tek contract altında sunar.
- Integrations ekranı artık mock-driven değildir; connector accounts, scopes, health, reconnect/revoke ve recent traces yüzeyde canlı görünür.
- `config/settings.py` içinde `get_gateway_api_base_url()` ve `get_gateway_root_url()` eklendi.
- `core/runtime_backends.py` ile opsiyonel Rust core / Go gateway / TS dashboard / Swift desktop backend registry tanımlandı.
- `apps/desktop` artık canonical ürün yüzeyi olarak ele alınıyor; `elyan desktop` Tauri shell'i öncelemeye başladı, PyQt yalnızca legacy fallback.
- Tauri shell managed sidecar komutları (`boot_runtime`, `restart_runtime`, `stop_runtime`, `get_runtime_health`, `get_runtime_logs`) ile Python runtime lifecycle'ını okuyup yönetebiliyor.
- Desktop runtime köprüsü sidecar health'e göre API base URL ayarlıyor; runtime online/offline/reconnecting durumu shell içinde first-class hale geldi.
- Home yüzeyi metric-first dashboard dilinden çıkarıldı; calm command home, 3 primary flow lane'i ve compact trust strip ile sadeleştirildi.
- Desktop artık kalıcı workflow launch profile taşıyor; dil, audience, tone, website stack ve export tercihleri home/settings/command center yüzeylerinde first-class hale geldi.
- Desktop project template katmanı eklendi; template seçimi artık default session, preferred task type, routing profile ve review strictness davranışını birlikte belirliyor.
- Desktop shell primitive'leri ve shell chrome'u artık daha sakin bir matte design system ile ilerliyor; primitive seviyede yapılan tasarım müdahaleleri home/command center/settings yüzeylerini aynı anda rafine ediyor.
- Desktop geliştirme kuralı netleştirildi: runtime/core ile desktop shell paralel ilerler; capability work tamamlanırken desktop görünürlüğü ve kontrol yüzeyi de aynı fazda ele alınır.
- `core/unified_model_gateway.py` ile specialist-aware, local-first unified model gateway eklendi; transport seçimi artık `operator.multi_llm.*` config'i üzerinden yapılır ve LiteLLM patlarsa native fallback uygulanabilir.
- `core/multi_agent/specialists.py` Next-Gen specialist profilleri (`code_agent`, `research_agent`, `document_agent`, `thinking_agent`) ile genişletildi.
- `core/multi_agent/handoff.py` typed handoff packet sözleşmesini tanımlıyor; handoff'lar artık SQLite-backed store'a yazılıyor ve process restart sonrası hydrate edilebiliyor.
- `core/semantic_memory.py` config-driven opsiyonel Qdrant backend destekli hale geldi; audit text + SQLite fallback korunuyor.
- `core/events/event_store.py` native event store adapter contract'ı ile future Rust acceleration'a hazırlandı.
- `/api/v1/system/backends` endpoint'i ile aktif backend ve fallback durumu görünür hale geldi.
- `/api/v1/metrics/multi-agent` artık handoff persistence, semantic memory backend ve unified model gateway durumunu döndürüyor.
- Web dashboard sayfaları için `ui/web/runtime_config.js` ile relative API çözümü eklendi.
- `core/task_engine.py` artık 3-tier intent router ile başlıyor; router fail olursa legacy parser fallback'e düşüyor.
- `core/agent.py` direct intent değerlendirmesinde yeni intent router ilk tercih; legacy parser fallback olarak kalıyor.
- `core/task_engine.py` complex task execution için checkpoint persistence yazıyor, resume için `resume_pipeline_id` / `checkpoint_execution_id` kabul ediyor.
- `core/pipeline_state.py` artık task status mark edebiliyor; pipeline ilerlemesi görünür.
- `core/agent.py` içinde tool execution öncesi schema validation ve sanitization aktif.
- Tier 1 fast-match, multi-step komutlarda single-intent yanlış pozitiflerini daha az tetikliyor.
- Approval path artık uncertainty fallback'i sessizce yutmuyor, debug event üretiyor.
- `core/security/contracts.py` ile ortak security decision sözleşmesi eklendi.
- `core/run_store.py` hassas alanları field-level encrypted envelope ile yazıyor.
- `core/security/session_security.py` disk-backed token persistence taşıyor.
- `api/http_server.py` explicit origin allowlist + security headers + browser mutation guard uyguluyor.
- Dashboard HTTP yüzeyi artık session token + CSRF taşıyıcısı üretir; browser/Desktop mutation istekleri auth ve CSRF ile korunur.
- Tauri shell artık `csp: null` kullanmıyor; minimal CSP aktif.
- Desktop home snapshot güvenlik posture ve approval queue bilgisini çekiyor.
- Gateway, Telegram, voice ve direct API/webhook ingress yolları artık prompt firewall kararından geçer.
- `/api/v1/security/events` ve desktop command center/logs/settings yüzeyleri security event timeline’ını görünür taşır.
- `core/workflow/contracts.py` ile document / presentation / website için canonical workflow lifecycle ve agent-role sahipliği tanımlandı.
- `core/workflow/state_machine.py` artık `received -> completed` lifecycle'ını resmi state değerleriyle taşırken legacy `IDLE/RUNNING/DONE` çağrılarını da kırmadan destekliyor.
- `core/workflow/vertical_runner.py` document / presentation / website akışlarını gerçek artifact pipeline olarak çalıştırıyor; sonuçlar canonical `core/run_store.py` üstüne timeline, review report ve artifact manifest ile yazılıyor.
- Gateway artık `/api/v1/runs`, `/api/v1/runs/{id}`, `/api/v1/runs/{id}/timeline`, `/api/v1/system/backends`, `/api/v1/security/*`, `/api/v1/metrics/*`, `/api/v1/approvals/*` ve `/api/v1/workflows/start` compatibility yüzeylerini aiohttp runtime içinde sunuyor.
- `apps/desktop` home ekranındaki 3 primary flow butonu artık gerçek workflow start mutation'ı yapıyor; command center son run için timeline + review gate + artifact browsing gösteriyor.
- Workflow start payload'ı artık user-owned launch preferences taşır; runtime scope/plan contract'i bu tercihleri run içine yazıp command center inspection'a açar.
- Workflow classify/scope contract'i artık project template, routing profile, review strictness ve candidate chain verisini de taşır; desktop inspection yüzeyi runtime selection mantığını artık doğrudan görebilir.
- Tauri managed sidecar admin token enjekte ediyor; runtime mutation rotaları desktop shell'den güvenli şekilde çağrılabiliyor.
- Gateway `ws/dashboard` endpoint'i artık desktop telemetry için tekrar aktif; Tauri shell managed admin token ile bağlanıp workflow/activity/tool event geldiğinde snapshot query'lerini invalidate ediyor.
- `core/workflow/vertical_runner.py` stage start/end/failure ve workflow completion olaylarını gateway telemetry hattına yayıyor; desktop artık yalnızca polling'e bağlı değil.
- Figma tasarım otoritesi olarak kabul edilir; runtime contract sabitlendikten sonra shell foundations, command home, cowork thread, billing ve connector surfaces Figma parity hedefiyle rafine edilir.

---

## Phase 5.2.5 — Security Hardening Program v1

### 5.2.5-A: Security Contracts
- `risk_level`
- `data_classification`
- `approval_policy`
- `cloud_eligibility`
- `audit_requirement`
- `verification_policy`

Bu metadata runtime guard, tool policy, handoff ve model gateway katmanlarında taşınmaya başlandı.

### 5.2.5-B: Secrets & Persistence
- Vault artık master key’i loglamıyor.
- Session store restart sonrası diskten geri yüklenebiliyor.
- Run store plaintext yerine encrypted field envelope kullanıyor.

### 5.2.5-C: HTTP/Desktop Hardening
- Wildcard CORS kaldırıldı.
- Browser mutation akışı origin/CSRF guard ile sıkılaştırıldı.
- Session-backed auth cookie/header köprüsü eklendi; desktop shell future mutation akışına hazır.
- Tauri CSP aktifleştirildi.
- Desktop shell home + command center + settings + logs yüzeylerinde security inspection göstermeye başladı.

---

## Öncelikli Düzeltmeler (Şu An Yapılması Gereken)

Bu düzeltmeler yapılmadan yeni feature geliştirmeye geçilmemeli.

### Fix-1: `run_store` Duplikasyonu Çöz
**Dosyalar**: `core/run_store.py`, `core/evidence/run_store.py`, `core/agent.py`, testler
**Durum**: Canonicalization tamamlandı; `core/evidence/run_store.py` kaldırıldı, agent `core/run_store.py` kullanıyor
**Not**: Bu alanın üstüne encryption/inspection iyileştirmeleri geliyor

---

### Fix-2: Var Olmayan Widget/Fonksiyon Çağrılarını Kaldır veya Implement Et
**Dosya**: `api/dashboard_api.py`
**Sorun**: `get_cognitive_integrator()`, `DeadlockPreventionWidget`, `SleepConsolidationWidget` çağrılıyor ama yok
**Seçenek A (Hızlı)**: Bu çağrıları kaldır, ilgili metric endpoint'lerini stub yap
**Seçenek B (Doğru)**: Gerçekten implement et — cognitive integrator için `core/cognitive_layer_integrator.py` yaz

---

### Fix-3: `run_visualizer.js` Hardcoded Localhost Düzelt
**Dosyalar**: `ui/web/run_inspector.html`, `ui/web/approval.html`, `ui/web/runtime_config.js`
**Durum**: API base URL runtime helper ile tekilleştirildi; relative fallback aktif

---

### Fix-4: Async Lock Karışıklığı Düzelt
**Dosyalar**: `core/performance_cache.py`
**Sorun**: `threading.RLock()` async context'te kullanılıyor
**Çözüm**: `asyncio.Lock()` ile değiştir

---

### Fix-5: Async'ı Flask'ta Doğru Çağır
**Dosya**: `api/http_server.py`
**Sorun**: `asyncio.run()` Flask route handler'da thread pool'u bloke ediyor
**Çözüm A**: Quart (async Flask) kullan
**Çözüm B**: Async fonksiyonları sync wrapper'a al, thread pool için `concurrent.futures` kullan

---

## Phase 5.2.4 — Real-time Updates & Config Layer

**Önkoşul**: Fix-1 ile Fix-5 tamamlanmalı

### 5.2.4-A: Merkezi Config Layer
```
config/
  settings.py       # Tüm env-variable tabanlı config buraya
  defaults.py       # Default değerler
```
- `PORT`, `DATA_DIR`, `APPROVAL_TIMEOUT_SEC`, `CACHE_TTL_SEC` gibi sabitler buraya taşınır
- Tüm hardcoded değerler config'den okunur
- `.env` dosyası ile override edilebilir

### 5.2.4-B: Real-time Sistem Birleştirme
Şu an 3 ayrı sistem var: MetricsStore (thread), Socket.IO, EventBroadcaster
**Hedef**: Tek EventBus, diğerleri subscriber olarak çalışır
```
EventBus (singleton)
  ├── WebSocketAdapter (Socket.IO subscriber)
  ├── MetricsAdapter (metrikleri toplar)
  └── ApprovalAdapter (onay event'leri)
```

### 5.2.4-C: Approval Persistence
- Pending approvals in-memory dict'ten SQLite'a taşınır
- `core/security/audit_approval.py` altyapısı zaten var, genişletilecek
- Process crash sonrası onay bekleyen request'ler kaybolmaz

### 5.2.4-D: Dashboard Real-time
- Approval tab: WebSocket ile canlı güncelleme (şu an 5s polling var, yeterli olabilir)
- Runs tab: Run durumu event-driven güncelleme
- Metrics: Server-Sent Events veya WebSocket ile live metrics

---

## Phase 5.2.5 — Run Store Şifreleme + Security Hardening

**Önkoşul**: 5.2.4 tamamlanmalı

### 5.2.5-A: Run Payload Şifreleme
- `core/run_store.py` JSON'a yazarken `EncryptedVault` kullan
- Hassas field'lar (tool outputs, LLM responses) şifreli saklanır
- Decrypt sadece inspector görüntülerken yapılır

### 5.2.5-B: Web UI Security
- CSRF token implementasyonu
- Content Security Policy (CSP) header'ları
- XSS sanitization için DOMPurify veya benzeri entegrasyonu
- Rate limiting dashboard API'ye

### 5.2.5-C: Session Persistence
- Session güvenlik modülü disk-backed storage'a geçirilir
- Token blacklist SQLite'ta tutulur

---

## Phase 5.3 — Stub Modülleri Implement Et veya Kaldır

Bu modüller ya gerçekten implement edilmeli ya da codebase'den temizlenmeli:

### Implement Edilecekler:
- **`core/health_checks.py`**: Agent, API server, session engine, tool registry sağlık kontrolleri
- **`core/alerting.py`**: Approval timeout, run failure, tool error alertleri

### Kaldırılacaklar (dead code):
- **`core/realtime_actuator/`**: Hiçbir yere bağlı değil, implement planı yoksa silinmeli

---

## Phase 5.4 — `core/agent.py` Refactor

**Bu en riskli ve en büyük iş.**
14.766 satır, 254 fonksiyon. Dokunmak tehlikeli ama zorunlu.

### Hedef Yapı:
```
core/
  agent/
    __init__.py         # Ana Agent class (ince, orchestration only)
    router.py           # Intent → Handler routing
    executor.py         # Handler → Tool execution
    validator.py        # Safety + policy checks
    context_builder.py  # Context assembly
    memory_writer.py    # Memory update logic
    session_handler.py  # Session lifecycle
```

### Strateji:
1. Önce test coverage artır (agent.py için integration testler)
2. Her bölümü ayrı dosyaya extract et, orijinal agent.py delegate etsin
3. Bir bölüm çalışıyor mu doğrulandıktan sonra bir sonrakine geç
4. Hiçbir test kırılmamalı (2781 test güvencesi)
5. Shared intent router contract'ı mission_control, pipeline ve llm_client fallback yüzeyleriyle aynı kalacak şekilde korunmalı

---

## Phase 6 — Observability & Operations

### 6.1: Unified Metrics Dashboard
- Cache hit rate (CacheManager'dan)
- Async executor stats (AsyncExecutor'dan)
- Approval workflow metrics (ApprovalEngine'den)
- Run success/fail rate (RunStore'dan)
- Tool call latency distribution

### 6.2: Structured Logging
- Her component için aynı log format
- Log level: `DEBUG | INFO | WARNING | ERROR | CRITICAL`
- Log destination: file + optionally external (Loki, etc.)
- Correlation ID: her request bir `trace_id` taşır

### 6.3: Health Endpoint
- `GET /api/v1/health` → tüm subsystem'ların durumu
- Agent loop, approval engine, run store, cache, session manager
- Dashboard'da görünür health panel

---

## Phase 7 — Refactor: Response Contract & API Unifikasyonu

### Şu An:
- `dashboard_api.py`: `{"success": bool, "data": ...}`
- `http_server.py`: `(dict, int)` tuple
- `EventBroadcaster`: dataclass

### Hedef:
```python
# Tek response format
{
  "ok": bool,
  "data": any | null,
  "error": str | null,
  "trace_id": str,
  "timestamp": str
}
```

Tüm endpoint'ler bu format'a geçer. OpenAPI/Swagger dökümantasyonu eklenir.

---

## Test Stratejisi

### Şu An (2026-03-26):
- 2781 test toplandı
- 81 geçiyor
- 1 fail (wallpaper flow)

### Hedef Test Piramidi:
```
Unit Tests (hızlı, izole)
  - Her core module için
  - Mock kullanılabilir ama dikkatli (C-1 hatası gibi wrong mock riski var)

Integration Tests (gerçek bileşenler)
  - HTTP route'ları (Flask test client)
  - ApprovalEngine + RunStore birlikte
  - Dashboard API endpoint'leri

E2E Tests (tam flow)
  - Mevcut e2e/ klasörü var, genişletilmeli
  - Wallpaper flow fix sonrası tekrar çalışmalı
```

### Öncelikli Eksik Testler:
- `test_http_routes.py`: Flask route'ları için
- `test_event_broadcaster.py`: WebSocket delivery için
- `test_dashboard_api_integration.py`: Dashboard API uçtan uca
- `test_config.py`: Config layer doğrulaması
- `test_run_store_encryption.py`: Encrypted payload için

---

## Yapılmaması Gerekenler (Anti-Patterns)

Bu projenin geçmişinde yapılan hatalar, tekrar edilmemeli:

1. **Widget import'larını silent except ile yutma** — fail fast ol
2. **Yeni feature başlamadan önce broken test'i geçiyor saymak** — C-1 önce fix edilmeli
3. **Aynı module'ü iki yerde implement etmek** — run_store gibi
4. **`asyncio.run()` Flask handler'da** — deadlock üretiyor
5. **Phase complete demek ama hardcoded URL bırakmak** — run_visualizer.js gibi
6. **Config'i hardcode etmek** — port, path, timeout

---

## Özet: Ne Yapılmalı, Hangi Sırada

```
[Şimdi]     Fix-1: run_store duplikasyonu → 1 failing test düzelir
[Şimdi]     Fix-2: var olmayan widget çağrıları → metrics sistemi çalışır
[Şimdi]     Fix-3: run_visualizer.js hardcode → dashboard tam çalışır
[Şimdi]     Fix-4: async lock → deadlock riski kalkar
[Şimdi]     Fix-5: asyncio.run() flask'ta → blocking kalkar

[Sonra]     5.2.4-A: Config layer → hardcoded değerler temizlenir
[Sonra]     5.2.4-B: Real-time birleştirme → tek EventBus
[Sonra]     5.2.4-C: Approval persistence → crash-safe
[Aktif]     UI/runtime sync → desktop home backend health strip canlı registry verisiyle beslenir
[Aktif]     Tauri-first desktop shell → `apps/desktop` altında React/TS premium shell, 8 ekran ve typed API layer
[Aktif]     Parallel delivery rule → runtime capability işleri ile desktop inspection/control surfaces birlikte geliştirilir
[Aktif]     Next-gen multi-agent foundation → unified model gateway + specialist registry + typed handoff protocol

[Daha Sonra] 5.2.5: Encryption + security hardening
[Daha Sonra] 5.3: Stub modülleri implement et veya sil
[Daha Sonra] 5.4: agent.py refactor (en büyük iş)
[Daha Sonra] 6: Observability (health, metrics, logging)
[Daha Sonra] 7: API unifikasyonu + OpenAPI docs
```
