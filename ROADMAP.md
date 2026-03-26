# ROADMAP.md — Elyan Operator Runtime

**Son Güncelleme**: 2026-03-26
**Mevcut Durum**: Phase 5.2.3 Dashboard Redesign ✓ COMPLETE
**Test Durumu**: 81/2781 test geçiyor (1 fail: wallpaper flow, `run_store` duplikasyonu nedeniyle)

---

## Genel Durum Özeti

| Katman | Durum | Notlar |
|--------|-------|--------|
| Performance (LRU Cache + AsyncExecutor) | ✓ Complete | 13 test |
| Approval System | ✓ Complete | 10 test |
| Run Store + Inspector | ⚠️ Partially Broken | Duplikat import nedeniyle step tracking çalışmıyor |
| Security Hardening (Vault + Session + Audit) | ✓ Complete | 22 test |
| Dashboard Redesign | ✓ Mostly Complete | run_visualizer.js hardcoded localhost sorunu var |
| Real-time Updates | ✗ Not Done | 3 ayrı sistem, hiçbiri tam entegre değil |
| Config Layer | ✗ Not Done | Her şey hardcoded |
| Health Checks | ✗ Stub | NotImplementedError |
| Alerting | ✗ Stub | NotImplementedError |

---

## Öncelikli Düzeltmeler (Şu An Yapılması Gereken)

Bu düzeltmeler yapılmadan yeni feature geliştirmeye geçilmemeli.

### Fix-1: `run_store` Duplikasyonu Çöz
**Dosyalar**: `core/run_store.py`, `core/evidence/run_store.py`, `core/agent.py`, testler
**Sorun**: İki farklı RunStore implementasyonu var, agent yanlış olanı import ediyor
**Çözüm**:
1. `core/run_store.py` canonical (async, dataclass tabanlı) olarak kalır
2. `core/evidence/run_store.py` kaldırılır veya evidece-specific mantık `core/run_store.py`'a taşınır
3. `core/agent.py`'deki import `core.run_store` olarak güncellenir
4. `test_attachment_wallpaper_flow` tekrar pass etmeli

**Beklenen etki**: 1 failing test → 0 failing test

---

### Fix-2: Var Olmayan Widget/Fonksiyon Çağrılarını Kaldır veya Implement Et
**Dosya**: `api/dashboard_api.py`
**Sorun**: `get_cognitive_integrator()`, `DeadlockPreventionWidget`, `SleepConsolidationWidget` çağrılıyor ama yok
**Seçenek A (Hızlı)**: Bu çağrıları kaldır, ilgili metric endpoint'lerini stub yap
**Seçenek B (Doğru)**: Gerçekten implement et — cognitive integrator için `core/cognitive_layer_integrator.py` yaz

---

### Fix-3: `run_visualizer.js` Hardcoded Localhost Düzelt
**Dosya**: `ui/web/run_visualizer.js`
**Sorun**: `http://localhost:18789/api/v1/...` hardcoded
**Çözüm**: `dashboard.html` gibi relative `/api/v1/...` path kullan

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

[Daha Sonra] 5.2.5: Encryption + security hardening
[Daha Sonra] 5.3: Stub modülleri implement et veya sil
[Daha Sonra] 5.4: agent.py refactor (en büyük iş)
[Daha Sonra] 6: Observability (health, metrics, logging)
[Daha Sonra] 7: API unifikasyonu + OpenAPI docs
```
