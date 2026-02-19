# ELYAN — Geliştirme Oturum Takibi

**Proje:** `/Users/emrekoca/Desktop/bot`  
**Versiyon:** 18.0.0
**Son Güncelleme:** 2026-02-18

---

## SPRINT G — TAMAMLANDI ✅
| Bug | Dosya | Düzeltme |
|-----|-------|----------|
| BUG-SEC-001 | `security/approval.py` | finally bloğu, stale clear, asyncio.Lock |
| BUG-SEC-002 | `security/tool_policy.py` | deny-before-allow |
| BUG-SEC-003 | `security/rate_limiter.py` | asyncio.Lock, async is_allowed, burst fix |
| BUG-SEC-004 | `security/audit.py` | threading.local, double-checked singleton |
| BUG-SEC-005 | `config/settings.py` | Keychain first, .env fallback |
| BUG-FUNC-001 | `main.py` | loop.close() finally, port check |
| BUG-FUNC-008 | `core/scheduler/cron_engine.py` | JSON persistence |
| BUG-FUNC-009 | `main.py` + `doctor.py` | Port availability check |
| BUG-FUNC-010 | `config/elyan_config.py` + `requirements.txt` | json5 |

## SPRINT H — TAMAMLANDI ✅
- `cli/commands/voice.py` — start/stop/status/test/transcribe/speak
- `cli/commands/memory.py` — status/index/search/export/clear/stats
- `cli/commands/agents.py` — list/status/add/remove/start/stop/logs
- `cli/commands/browser.py` — snapshot/screenshot/navigate/click/type/extract/scroll
- `cli/commands/doctor.py` — port check, dependency labels, config check

## SPRINT I — TAMAMLANDI ✅
- `core/llm_cache.py` — bypass keywords, min-token threshold, module-level regex

## SPRINT J — TAMAMLANDI ✅
**Canonical UI dosyaları:** `clean_main_app.py`, `apple_setup_wizard.py`, `clean_chat_widget.py`, `settings_panel_ui.py`

**Shim'ler:** `main_app.py`, `setup_wizard.py`, `enhanced_setup_wizard.py`, `chat_widget.py`, `settings_panel.py`, `main_window.py`

## SPRINT K — TAMAMLANDI ✅ (BUG-FUNC-004 + BUG-FUNC-005)
**`core/intent_parser/` paketi** — 100KB tek dosya → 7 modüle bölündü:
- `_base.py` — alias tabloları, 50 compiled regex, yardımcı metodlar
- `_system.py` — screenshot, volume, brightness, wifi, power, clipboard
- `_apps.py` — open/close app, URL, browser search, YouTube, greeting
- `_files.py` — create_folder, list_files, write_file, search_files
- `_research.py` — research, web_search, summarize, translate
- `_documents.py` — Word, Excel, PDF, website, presentation
- `_media.py` — email, calendar, reminder, music, code_run, help
- `__init__.py` — IntentParser (çoklu miras), pipeline, singleton
- `core/intent_parser.py` → backward-compat shim

**`core/task_engine/` paketi** — dataclass'lar ve sabitler ayrıldı:
- `_state.py` — TaskResult, TaskDefinition dataclass'ları
- `_constants.py` — _NON_TOOL_ACTIONS, _EXPLICIT_APPROVAL_ACTIONS
- `__init__.py` — paket entry point

## Sprint L — Dashboard Yenileme ✅
**`core/gateway/server.py`** — 5 yeni endpoint + WebSocket:
- `/api/analytics` — işlem sayısı, başarı oranı, model, maliyet
- `/api/tasks` + `POST /api/tasks` — aktif/geçmiş görevler, hızlı görev oluşturma
- `/api/memory/stats` — bellek istatistikleri
- `/api/activity` — aktivite log
- `/ws/dashboard` — WebSocket canlı aktivite akışı
- CORS middleware

**`ui/web/dashboard.html`** — tam yenileme:
- 6 canlı durum kartı (API'den gerçek veri)
- WebSocket aktivite akışı
- 5 sekme: Genel Bakış / Kanallar / Görevler / Güvenlik / Ayarlar
- Hızlı görev oluşturma formu
- CPU/RAM canlı çubukları (5s polling)

## SPRINT M — CLI Tam İmplementasyon ✅
**Önceki Oturum Hata Düzeltmesi:**
- `ui/settings_panel.py` — boş shim'di, `SettingsPanel` (config.settings_manager) + `SettingsWindow` export eklendi
- `ui/chat_widget.py`, `ui/main_app.py`, `ui/setup_wizard.py`, `ui/enhanced_setup_wizard.py`, `ui/main_window.py` — hepsi boştu, canonical dosyalara yönlendiren shim'ler yazıldı

**CLI komutları genişletildi:**
- `cli/commands/channels.py` — list/status/add/remove/enable/disable/test/login/logout/info/sync (hepsi implemente)
- `cli/commands/security.py` — audit(--fix)/status/events(--severity/--last)/sandbox subcommandlar
- `cli/commands/skills.py` — list/info/install/enable/disable/update/remove/search
- `cli/commands/cron.py` — list/status/add/rm/enable/disable/run/history/next
- `cli/commands/models.py` — list/status/test/use/set-default/set-fallback/cost/ollama/add
- `cli/commands/config.py` — show(--masked)/get/set/unset/validate/reset/export/import/edit
- `cli/commands/webhooks.py` — YENİ DOSYA: list/add/remove/test/logs/gmail
- `cli/commands/memory.py` — argparse uyumlu `run(args)` wrapper eklendi
- `cli/main.py` — tam yenileme: 21 komut (channels/cron/models/webhooks/memory/health/status/update/version)

## SPRINT N — Dashboard Analytics + Security ✅
**`ui/web/dashboard.html`** — Analytics sekmesi eklendi (6. sekme):
- 4 özet kart: Toplam Görev / Başarı Oranı / Ort. Süre / Token Tüketimi
- Kanal kullanım dağılımı (progress bar'lı)
- Maliyet analizi (bütçe bar, tahmin)
- Performans metrikleri tablosu
- Model kullanım dağılımı

**Security sekmesi güçlendirildi:**
- Bekleyen Onaylar kartı (Onayla/Reddet butonları)
- Denetim Logu (filtrelenebilir, risk severity göstergeli)
- `loadAuditLog()`, `approveAction()` fonksiyonları

**`core/gateway/server.py`** — 3 yeni endpoint:
- `GET /api/security/events` — audit log (severity filtresi)
- `GET /api/security/pending` — bekleyen onaylar
- `POST /api/security/approve` — onayla/reddet
- `handle_analytics` genişletildi: total_tasks, tokens, channel/model breakdown, budget

## SPRINT O — Üretim Hazırlığı (Kısmi) ✅
- **BUG-FUNC-002** `handlers/telegram_handler.py` — `_resolve_pending_request`: running_loop tespiti ile `set_result` vs `call_soon_threadsafe` ayrımı; `cmd_cancel` log iyileştirme
- **`requirements.txt`** — `click`, `croniter`, `groq`, `google-generativeai`, `cryptography`, `keyring` eklendi; `rumps` macOS-only constraint
- **`setup.py`** — tam yenileme: `install_requires`, `extras_require` (ui/voice/browser/dev), entry point `elyan=cli.main:main`
- **`Dockerfile`** — çok aşamalı build (builder + slim runtime), non-root `elyan` user, HEALTHCHECK, `EXPOSE 18789`
- **`.dockerignore`** — `.venv`, `__pycache__`, `logs`, `.env`, `.wiqo`, `tests` hariç tutuluyor
- **`install.sh`** — tam yenileme: `--headless`/`--no-ui`, Python 3.11+ kontrolü, shell completion auto-install, etkileşimli onboarding
- **`cli/commands/completion.py`** — YENİ: zsh native, bash, fish completion; show/install/uninstall; `~/.zshrc` / `~/.bashrc` otomatik patch
- **`cli/main.py`** — `completion` komutu eklendi (22. komut)
- **BUG-PERF-002/003** `core/fuzzy_intent.py` — `_RE_APOSTROPHE`, `_RE_TR_SUFFIX`, `_RE_WHITESPACE`, `_TR_SUFFIX_STOP` modül seviyesinde pre-compile; `normalize_turkish()` güncellendi

## SPRINT K — Kanal Genişletme ✅
**Yeni Adapter Dosyaları:**
- `core/gateway/adapters/signal_adapter.py` — signald unix socket + HTTP proxy; polling, send, grup/DM
- `core/gateway/adapters/matrix_adapter.py` — matrix-nio AsyncClient; sync loop, Markdown/HTML, E2E hazır
- `core/gateway/adapters/teams_adapter.py` — Azure Bot Framework webhook; Activity dispatch, Bearer token
- `core/gateway/adapters/google_chat_adapter.py` — Webhook modu + Bot modu (Pub/Sub, service account)
- `core/gateway/adapters/imessage_adapter.py` — BlueBubbles REST API + WebSocket; Socket.IO parse; tapback desteği

**`core/gateway/adapters/__init__.py`** — ADAPTER_REGISTRY (10 kanal); `get_adapter_class()` helper

**`requirements.txt`** — discord.py, slack-bolt eklendi; Teams/Matrix/Google Chat isteğe bağlı yorum olarak eklendi

## SPRINT L — Üretim Hazırlığı ✅
**`.github/workflows/ci.yml`** — 8 job'lı tam CI/CD pipeline:
1. lint (ruff + black + isort)
2. typecheck (mypy, non-blocking)
3. security (bandit SAST + pip-audit CVE tarama)
4. test (Python 3.11 + 3.12 matrix, pytest-cov, Codecov)
5. regression (capability pipeline)
6. docker (multi-stage build + GHA cache)
7. integration (PR'larda çalışır)
8. release (main push → ghcr.io push)

**`.github/dependabot.yml`** — pip (haftalık, ai-libraries/security/web grupları) + GitHub Actions güncellemeleri

**`helm/elyan/`** — Tam Helm chart:
- `Chart.yaml`, `values.yaml` (replicaCount, ingress, persistence, HPA, secrets, probes)
- `templates/`: deployment, service, ingress, secret, pvc, hpa, serviceaccount, _helpers.tpl

**`mkdocs.yml`** — Material theme, TR dil desteği, mermaid diyagram, 8 bölüm, nav tree
**`docs/`** — index.md, installation.md, quickstart.md, kubernetes.md, docker.md, signal.md, matrix.md, imessage.md
**`.github/workflows/release.yml`** — Tag push → GitHub Release + multi-arch Docker push (amd64+arm64) + MkDocs gh-pages deploy
**`scripts/benchmark.py`** — 7 suite (intent/fuzzy/cache/settings/quick_intent/fast_response/memory); p50/p95/p99 metrikleri; baseline karşılaştırma; JSON çıktı
**`scripts/load_test.py`** — Gateway yük testi; concurrent HTTP; health/api/message suite; RPS + gecikme metrikleri
**`tests/unit/`** — test_gateway_adapters.py (Signal/Matrix/Teams/GChat/iMessage), test_fuzzy_intent.py, test_gateway_router.py, test_response_cache.py
**`tests/integration/`** — test_intent_to_tool_pipeline.py (25 senaryo)
**`.github/workflows/ci.yml`** — benchmark job eklendi (her push'ta otomatik çalışır, JSON artifact olarak yüklenir)

## SPRINT M (Docs) — Dokümantasyon Tamamlandı ✅
**Oluşturulan tüm eksik `docs/` sayfaları (33 dosya):**

**CLI Referansı (9 dosya):**
- `docs/cli/overview.md` — Tüm komutların özeti, hızlı başlangıç
- `docs/cli/gateway.md` — start/stop/restart/status/logs/reload/health
- `docs/cli/channels.md` — 10 kanal tipi, list/add/remove/enable/disable/test
- `docs/cli/models.md` — Groq/Gemini/Ollama; add/use/cost/ollama
- `docs/cli/skills.md` — list/install/enable/disable/update/remove
- `docs/cli/memory.md` — status/index/search/export/import/clear/stats
- `docs/cli/security.md` — audit/status/events/sandbox
- `docs/cli/cron.md` — list/add/rm/enable/disable/run/history/next + cron ifadeleri
- `docs/cli/doctor.md` — --fix/--deep/--report/--check + health/status

**Kanallar (7 dosya):**
- `docs/channels/telegram.md` — BotFather, polling/webhook, grup desteği
- `docs/channels/discord.md` — Geliştirici Portalı, Message Content Intent
- `docs/channels/slack.md` — Socket Mode + Webhook Mode, scopes
- `docs/channels/whatsapp.md` — Meta Cloud API, 24s kuralı, şablonlar
- `docs/channels/webchat.md` — Widget gömme, WebSocket API, nginx proxy
- `docs/channels/teams.md` — Azure Bot Framework, Adaptive Cards
- `docs/channels/google-chat.md` — Webhook vs Bot (Pub/Sub) modu

**Dashboard (3 dosya):**
- `docs/dashboard/overview.md` — 5 sekme, WebSocket aktivite akışı, uzaktan erişim
- `docs/dashboard/analytics.md` — API endpoint, grafikler, maliyet takibi
- `docs/dashboard/security.md` — Onay yönetimi, rate limit, audit log

**Güvenlik (5 dosya):**
- `docs/security/architecture.md` — 7 katman güvenlik mimarisi diyagramı
- `docs/security/operator-modes.md` — strict/balanced/permissive; kullanıcı bazlı
- `docs/security/sandbox.md` — none/restricted/container modu; macOS Seatbelt
- `docs/security/tool-policy.md` — JSON5 kurallar; deny-before-allow; koşullar
- `docs/security/audit.md` — Log formatı, olay tipleri, PII maskeleme, SIEM

**Dağıtım (2 dosya):**
- `docs/deployment/systemd.md` — sistem kullanıcısı, unit file, güncelleme scripti
- `docs/deployment/vps.md` — DigitalOcean kurulum; nginx HTTPS; Telegram webhook

**Geliştirme (4 dosya):**
- `docs/development/architecture.md` — Tam mimari diyagramı, yanıt akışı
- `docs/development/contributing.md` — Fork, commit mesajı, PR şablonu
- `docs/development/testing.md` — pytest, async testler, coverage, benchmark
- `docs/development/writing-adapters.md` — BaseChannelAdapter, lazy import, UnifiedMessage

**API Referansı (2 dosya):**
- `docs/api/gateway.md` — 6 REST endpoint, webhook yolları, hata kodları
- `docs/api/websocket.md` — /ws/chat + /ws/dashboard; mesaj formatları; Python/JS örnek

**Getting Started (1 dosya):**
- `docs/getting-started/onboarding.md` — 6 adım sihirbaz akışı, headless mod

## ÇALIŞMA KOMUTU
```bash
cd /Users/emrekoca/Desktop/bot && source .venv/bin/activate
python main.py          # UI modu
python main.py --cli    # Gateway modu
python main.py --onboard  # Kurulum sihirbazı
```

```bash
# Docs sunucusu (mkdocs)
pip install mkdocs-material mkdocs-minify-plugin
mkdocs serve
```

## OTURUM GÜNCELLEMESİ — 2026-02-19 ✅
- `core/llm_cache.py` — `LLMCache.set()` geriye uyumlu hale getirildi: `dict` + `str` response desteği, bypass kontrolü başa alındı (AttributeError fix).
- `core/gateway/adapters/__init__.py` — opsiyonel bağımlılık güvenli lazy import eklendi; eksik paketlerde fallback adapter ile registry/import crash önlendi.
- `requirements.txt` — test ortamı için `pytest` + `pytest-asyncio` bağımlılıkları eklendi.
- `main.py` — kullanılmayan `TELEGRAM_TOKEN` importu kaldırılarak giriş noktası sadeleştirildi.
- Repo temizliği: `__pycache__`, `*.pyc` ve `.DS_Store` dosyaları silindi (kaynak kod dışı sadeleştirme).
- `tests/conftest.py` — internet/kurulum kısıtı nedeniyle `pytest-asyncio` yokken de async testlerin çalışması için yerel coroutine test hook'u eklendi.
- `core/gateway/adapters/teams_adapter.py` — webhook callback dönüşü coroutine ise `create_task` ile çalıştırma düzeltildi; Task dönen callback'te 500 hatası fixlendi.
- `core/gateway/adapters/signal_adapter.py` — `send_message` HTTP çağrısında coroutine/context-manager uyumluluğu eklendi (AsyncMock warning fix).
- `core/gateway/adapters/google_chat_adapter.py` — webhook ve API gönderiminde coroutine/context-manager uyumluluğu eklendi (AsyncMock warning fix).
- `core/gateway/adapters/imessage_adapter.py` — mesaj/reaksiyon gönderiminde coroutine/context-manager uyumluluğu eklendi (AsyncMock warning fix).
- `tools/terminal_tools.py` — command injection sertleştirmesi: shell control operator bloklama + yorumlayıcı inline execution flag (`-c`, `-m`, `-e`, vb.) bloklama.
- `tests/unit/test_terminal_tools.py` — injection koruması için 3 yeni birim test eklendi.
- `handlers/telegram_handler.py` — input sanitization güçlendirildi: `sanitize_input` + `validate_input` eklendi; `RateLimiter` async çağrı uyumu için `await rate_limiter.is_allowed(...)` düzeltildi.
- `security/audit.py` — sorgu iyileştirmesi: `WHERE 1=1` kaldırıldı, filtre bazlı güvenli query builder eklendi; `params/result/details` JSON alanları decode edilerek döndürülüyor; `atexit` ile bağlantı kapanışı eklendi.
- `tests/unit/test_audit_logger.py` — audit logger için filtreleme + JSON decode davranışını doğrulayan 2 yeni test eklendi.
- `core/embedding_codec.py` — YENİ: embedding normalize/serialize/deserialize katmanı (list/tuple/JSON string/dict destekli tek canonical format).
- `core/memory.py` — BUG-FUNC-003 standardizasyonu: `conversation_embeddings` tablosu eklendi; `store_conversation` embedding gelirse canonical JSON olarak persist ediyor; `store_embedding()` ve `get_user_embeddings()` API’leri eklendi; read-only DB durumunda `.elyan_memory/memory.db` fallback eklendi.
- `tests/unit/test_embedding_codec.py` + `tests/unit/test_memory_embeddings.py` — embedding format ve bellek persist davranışları için 6 yeni test eklendi.
- `security/keychain.py` — plaintext secret denetimi (`audit_env_plaintext`) ve `.env`→Keychain migration (`migrate_from_env`) eklendi; keychain availability kontrolü güçlendirildi.
- `config/settings_manager.py` — BUG-SEC-005: macOS Keychain aktifse `telegram_token` ve provider API key `.env` yerine Keychain'e yazılıyor; `.env` secret alanları boş tutuluyor.
- `cli/commands/security.py` + `cli/main.py` — `elyan security keychain` subcommand eklendi (`--fix`, `--clear-env` destekli migration).
- `cli/commands/doctor.py` — Secret Storage Check eklendi: keychain durumu + `.env` plaintext secret tespiti.
- `tests/unit/test_keychain_migration.py` — keychain plaintext audit/migration davranışları için 2 yeni test eklendi.
- `handlers/telegram_handler.py` — BUG-FUNC-002 tamamlandı: kullanıcı başına çoklu pending approval ID takibi eklendi; stale request temizleme genişletildi; `/cancel` artık kullanıcıya ait tüm bekleyen onayları tek seferde iptal ediyor.
- `security/keychain.py` — güvenlik log sertleştirmesi: keychain yazma hatalarında secret sızdırabilecek komut detayları loglanmıyor; yalnızca return code/type bilgisi tutuluyor.
- `security/tool_policy.py` — `tool_group=None` bypass kapatıldı: tool adı üzerinden otomatik grup çıkarımı eklendi; group-level deny/approval kuralları artık çağıran group vermese de uygulanıyor.
- `core/task_engine.py` — Tool policy enforcement merkezileştirildi: `_security_check` içinde `tool_policy.check_access()` zorunlu; `requires_approval` sonucu task seviyesine taşınıp execution akışında kullanıcı onayına zorlanıyor.
- `tests/unit/test_tool_policy.py` — deny-before-allow, group deny ve group-level approval için 3 yeni birim test eklendi.
- Doğrulama: `tests/unit/test_gateway_adapters.py` (31 passed), `tests/unit/test_gateway_router.py` (7 passed), `tests/unit/test_response_cache.py` (8 passed).
- `security/keychain.py` — canonical env↔keychain mapping (`ENV_TO_KEYCHAIN`, `key_for_env`) eklendi; `.env` plaintext audit genişletildi; `~/.elyan/elyan.json` içindeki plaintext `channels[*].token` için audit + migration (`migrate_config_channel_tokens`) eklendi.
- `config/elyan_config.py` — secret-ref çözümleme eklendi: config değerleri `"$ENV_KEY"` formatındaysa önce environment, yoksa keychain üzerinden otomatik resolve ediliyor.
- `cli/onboard.py`, `cli/commands/channels.py`, `core/model_orchestrator.py` — provider/channel secret anahtar adları canonical env-key adlarına hizalandı; keychain başarılıysa config’e plaintext yerine `$ENV_KEY` referansı yazılıyor.
- `cli/commands/security.py` + `cli/commands/doctor.py` — keychain denetimi config plaintext token taramasını da kapsayacak şekilde genişletildi.
- `tests/unit/test_keychain_config_migration.py` + `tests/unit/test_elyan_config_secret_resolution.py` — config token migration ve `$ENV_KEY` resolve akışı için yeni testler eklendi.
- `tests/unit/test_fuzzy_intent.py` — araştırma intent’i için güncel tool yönlendirmesi (`advanced_research`) test beklentisine eklendi.
- `core/memory.py` — kullanıcı başına yerel hafıza kotası eklendi (varsayılan 10GB, `ELYAN_MAX_USER_MEMORY_GB`/`ELYAN_MAX_USER_MEMORY_BYTES` ile override); kota aşımında en eski konuşmaları prune ederek yazmaya devam; boyut takibi (`size_bytes`) eklendi; CLI uyumu için `MemoryManager` facade sınıfı eklendi.
- `cli/commands/memory.py` — `memory status` ve `memory stats` komutlarına `--user` detayı eklendi; kullanıcı bazlı kullanım/limit yüzdesi raporlanıyor.
- `tests/unit/test_memory_quota.py` — kullanıcı kotası (prune + oversize reject + manager stats) için 3 yeni birim test eklendi.
- Doğrulama: `.venv/bin/python -m pytest -q tests/unit` → **88 passed**, 1 warning.
- `core/domain/models.py` — `AppConfig` roadmap alanlarıyla genişletildi (`tools/sandbox/cron/heartbeat/memory/security/gateway/skills`); `extra="allow"` ile bilinmeyen alan korunuyor; pydantic v2 için `ConfigDict` geçişi yapıldı (deprecation warning kaldırıldı).
- `config/elyan_config.py` — `_default_config()` eklendi: roadmap başlangıç ayarları (anthropic+fallback+ollama, local memory, sandbox docker, gateway 18789, security confirmed) tek yerden üretiliyor; dosya yok/bozuk durumunda bu baseline ile otomatik reset.
- `tests/unit/test_config_defaults.py` — config model extra-field koruması ve default local-memory/10GB/user baseline doğrulaması için 2 yeni test eklendi.
- Doğrulama: `.venv/bin/python -m pytest -q tests/unit` → **90 passed**.
- `core/memory.py` — default DB yolu `~/.elyan/memory/memory.db` olarak canonical hale getirildi; eski `~/.config/cdacs-bot/memory.db` için otomatik migration (copy) eklendi.
- `core/memory.py` — per-user limit çözümleme genişletildi: env override yoksa `~/.elyan/elyan.json` içindeki `memory.maxUserStorageGB` değeri okunuyor; fallback 10GB.
- `core/memory.py` — sandbox/kısıtlı ortamlarda `unable to open database file` ve `permission denied` hatalarında otomatik fallback (`.elyan_memory/memory.db`) eklendi.
- `core/memory.py` — `get_top_users_storage()` eklendi: kullanıcı bazında persisted storage, embedding sayısı ve kullanım yüzdesi sıralı raporlanıyor.
- `core/gateway/server.py` — `/api/memory/stats` endpoint’i gerçek memory DB metriklerine bağlandı (total_items, size_mb, db_path, default_user_limit_bytes, top_users).
- `ui/web/dashboard.html` — Bellek kartına kullanıcı kotası/Top User alt satırı eklendi; `pollMemory()` endpointten gelen gerçek değerleri gösteriyor.
- `tests/unit/test_memory_quota.py` — top-users sıralama ve config-based limit çözümleme için 2 yeni test eklendi (toplam 5 test).
- Doğrulama: `.venv/bin/python -m pytest -q tests/unit` → **92 passed**.
- `core/gateway/server.py` — `handle_status` uptime formatı düzeltildi (`gün/saat/dk/sn`); önceki hatalı `h}s {m}d` formatı kaldırıldı.
- Doğrulama: `.venv/bin/python -m pytest -q tests/unit/test_gateway_router.py tests/unit/test_memory_quota.py tests/unit/test_config_defaults.py` → **14 passed**.
- `core/gateway/router.py` — kanal dayanıklılığı için adapter supervisor eklendi: initial connect + arka planda health loop + exponential backoff reconnect (`reconnect_base_sec`, `reconnect_max_sec`, `health_interval_sec`, `connect_grace_sec`).
- `core/gateway/router.py` — adapter health telemetrisi eklendi (`status/connected/retries/failures/last_error/last_attempt_ts/last_connected_ts/next_retry_in_s`) ve `get_adapter_health()`, `get_adapter_status()` API’leri eklendi.
- `core/gateway/server.py` — `/api/status` çıktısına `adapter_health` eklendi; `/api/channels` endpoint’i config kanallarını runtime status/health ile zenginleştiriyor (`connected`, `status`, `health` alanları).
- `cli/commands/channels.py` — `elyan channels status` çıktısı artık kanal bazında `status`, `retry`, `fail`, `last_error` gösteriyor (gateway canlı health verisinden).
- `cli/commands/doctor.py` — `Channel Resilience Check` eklendi: enabled kanallar için zorunlu auth/config alanları, unresolved `$ENV_KEY` secret referansları ve reconnect ayar tutarlılığı kontrol ediliyor.
- `ui/web/dashboard.html` — Channels sekmesi runtime health metriklerini gösteriyor (`status/retry/fail` + `Connected/Degraded/Offline` rozetleri).
- `tests/unit/test_gateway_router.py` — reconnect/backoff health davranışı için `test_adapter_health_exposes_retry_and_failure` eklendi; start/stop testleri supervisor akışına uyumlu hale getirildi.
- `tests/unit/test_memory_quota.py` — önceki tura eklenen top-user/config-limit testleri korundu ve router+gateway değişiklikleriyle birlikte regresyon geçti.
- Doğrulama: `.venv/bin/python -m pytest -q tests/unit` → **93 passed**.
- `core/gateway/adapters/discord.py` — connection lifecycle sertleştirildi: `on_disconnect`/`on_resumed` eventleri ile status güncelleme, tekil `_connect_task` guard (duplicate start engeli), güvenli disconnect/cancel akışı ve `is_closed()` tabanlı status kontrolü eklendi.
- `core/gateway/adapters/telegram.py` — `get_status()` iyileştirildi: `Application.running` + `Updater.running` birlikte kontrol edilerek false-positive connected durumları engellendi.
- `core/gateway/adapters/slack.py` — connect/send hata akışında `_is_connected` güncelleniyor; Socket Mode bağlantı hataları supervisor tarafından tekrar denenebilecek şekilde propagate ediliyor.
- `cli/commands/doctor.py` — canlı çalıştırma doğrulaması: `elyan doctor --check channels` çıktısında yeni `Channel Resilience Check` bölümü ve auth/reconnect validasyonları görünür durumda.
- Doğrulama: `.venv/bin/python -m pytest -q tests/unit` → **93 passed** (reconnect + adapter lifecycle değişiklikleri dahil).
- `core/gateway/router.py` — kanal health metrikleri genişletildi: `received_count`, `sent_count`, `send_failures`, `processing_errors`, `last_message_in_ts`, `last_message_out_ts`; message processing/send akışlarında sayaçlar güncelleniyor.
- `core/gateway/server.py` — `/api/channels` yanıtı message metrikleriyle zenginleştirildi (`message_metrics`, `failure_rate_pct`, `last_activity`); kanallar sekmesinde performans izlenebilir hale geldi.
- `ui/web/dashboard.html` — Channels listesinde `in/out`, `err%`, `Son aktivite` alanları eklendi; runtime kalite görünürlüğü arttırıldı.
- `cli/commands/gateway.py` — `gateway status` tamamen yenilendi: process + runtime API birleşik durum, adapter health satırları, JSON çıktı desteği (`--json`); ayrıca `gateway health` komutu gerçek sağlık çıktısı üretiyor (JSON/text).
- `cli/main.py` — `elyan gateway` parser’ına `--json` eklendi; `start/restart` için `--port` desteği aktif hale getirildi (`ELYAN_PORT` env propagate); `gateway health` artık placeholder değil gerçek kontrol çalıştırıyor.
- `tests/unit/test_gateway_cli.py` — yeni CLI gateway durum/health JSON davranışı için 2 test eklendi.
- Doğrulama: `.venv/bin/python -m pytest -q tests/unit` → **95 passed**.
- `cli/commands/channels.py` + `cli/commands/gateway.py` — status çıktılarında `None`/beklenmeyen tiplerde format hatasını önlemek için `status` alanları string’e normalize edildi (CLI crash önleme hardening).
- `cli/commands/gateway.py` — `gateway status --json` çıktısı `/api/channels` verisini de içeriyor (`channels`, `channels_available`, `channels_error`); tek çağrıda kanal health/err% metrikleri alınabiliyor.
- `tests/unit/test_gateway_cli.py` — status JSON testleri kanal verisi dahil yeni payload ile güncellendi.
- `cli/commands/gateway.py` — runtime kapalıyken `channels_error` alanı runtime hata mesajını devralacak şekilde düzeltildi (diagnostics tutarlılığı).
- `cli/commands/completion.py` — zsh completion scripti `compdef` mevcut değilse otomatik `compinit` çalıştıracak şekilde düzeltildi (`compdef: command not found` fix).
- `cli/daemon.py` — launchd kurulum akışı yenilendi: güvenilir binary çözümleme (`.venv/bin/elyan` öncelikli), `launchctl bootstrap/bootout` kullanımı, servis doğrulama (`launchctl print`) ve uninstall’da `bootout` geçişi.
- `cli/daemon.py` — `elyan` binary bulunamazsa güvenli fallback: `python -m cli.main gateway start`.
- `tests/unit/test_daemon_manager.py` — daemon program argument çözümleme için 2 yeni test eklendi.
- Doğrulama: `.venv/bin/python -m pytest -q tests/unit` → **97 passed**.
- `install.sh` — macOS varsayılan eski bash uyumluluğu için `${ans,,}` kullanımı kaldırıldı; onboarding prompt cevabı `tr` ile lowercase edilerek `bad substitution` hatası giderildi.
- `core/neural_router.py` — `get_model_for_role()` eklendi (BUGFIX): LLM client/model orchestrator çağrısında `AttributeError` üreten eksik metod tamamlandı; `route()` artık bu metod üzerinden provider/model seçiyor.
- `core/model_orchestrator.py` — role-based seçimde neural router metod yoksa güvenli fallback eklendi; provider-model tutarsızlıklarına karşı normalize katmanı eklendi (örn. openai + llama3 -> gpt-4o).
- `cli/onboard.py` — provider seçimi sonrası `models.default.model` artık otomatik set ediliyor; router aktifken `models.roles` seçilen provider/model ile hizalanıyor (ilk kurulumda OpenAI seçip dashboard’da llama görünmesi düzeltildi).
- `cli/commands/models.py` — `models status` provider/model tutarsızlıklarını uyarı olarak gösteriyor.
- `core/gateway/server.py` — kanal API çıktılarında secret alanlar maskeleniyor (`token/key/secret/password`); `/api/channels` ve `gateway status --json` çıktısında düz token sızıntısı engellendi.
- `tests/unit/test_model_routing_consistency.py` — neural router disable/default davranışı, orchestrator fallback ve openai model normalize için 3 test eklendi.
- `tests/unit/test_gateway_security_output.py` — gateway secret masking helper için 2 test eklendi.
- Operasyonel düzeltme: kullanıcı ortamında config eşitlendi (`models.default=openai/gpt-4o`, roles/fallback openai/gpt-4o) ve gateway yeniden başlatıldı; `gateway status --json` runtime online + token masked doğrulandı.
- Doğrulama: `.venv/bin/python -m pytest -q tests/unit` → **102 passed**.
- `core/neural_router.py` — model tutarlılığı sertleştirildi: hardcoded `ollama/llama` role fallback kaldırıldı; role map artık `models.default` tabanlı üretiliyor ve her `get_model_for_role()` çağrısında config ile yeniden senkronlanıyor (router açıkken default modelden sapma engellendi).
- `cli/commands/models.py` — `elyan models use` davranışı genişletildi: provider/model birlikte canonical set ediliyor, provider-only kullanımında varsayılan model otomatik atanıyor; `models.roles` tüm rollerde default model ile otomatik senkronlanıyor (dashboard/runtime/model status tutarlılığı).
- `cli/commands/gateway.py` — gerçek log akışı eklendi: `gateway_logs()` ile `--tail`, `--level`, `--filter` destekli log okuma; sabit `LOG_FILE` kullanımı.
- `cli/main.py` — yeni top-level `elyan logs` komutu eklendi; `elyan gateway logs` artık placeholder değil gerçek log çıktısı veriyor.
- `tests/unit/test_model_routing_consistency.py` — router enabled + `models.roles` boşken default modele dönme davranışı için yeni regresyon testi.
- `tests/unit/test_models_cli.py` — `models use` komutunun default + role map senkronizasyonu için 2 yeni test.
- `tests/unit/test_gateway_cli.py` — `gateway_logs()` level/filter davranışı için yeni test.
- Doğrulama: `.venv/bin/python -m pytest -q tests/unit/test_model_routing_consistency.py tests/unit/test_models_cli.py tests/unit/test_gateway_cli.py` → **9 passed**.
- Canlı doğrulama: `elyan logs` ve `elyan gateway logs` komutları çalışıyor; `elyan gateway health --json` sağlıklı; `/api/analytics` yanıtı model=`gpt-4o`, provider=`openai`.
- `install.sh` — ilk kullanım deneyimi sadeleştirildi: global launcher (`~/.local/bin/elyan`) otomatik oluşturuluyor; shell RC dosyasına (`~/.zshrc`/`~/.bashrc`/`~/.profile`) PATH satırı idempotent ekleniyor; böylece `.venv` activate etmeden `elyan` komutu her yeni terminalde direkt çalışıyor.
- `install.sh` — kurulum özeti güncellendi: başlangıç adımı `source <rc_file>` olarak netleştirildi.
- Doğrulama: `bash -n install.sh` → **OK**.
- `core/agent.py` — görev yürütme katmanı güçlendirildi: deterministic `IntentParser` artık chat yolundan önce çalışıyor; tek-adımlı operasyonlarda doğrudan tool execution akışı eklendi (dosya listeleme, araştırma, URL/komut vb.).
- `core/agent.py` — `ACTION_TO_TOOL` canonical eşleme tablosu eklendi (örn. `research -> advanced_research`); bu tablo TaskEngine normalizasyonu ile de uyumlu.
- `core/agent.py` — registry dışı araçlar için `AVAILABLE_TOOLS` fallback execution eklendi; böylece `Tool not found` hatası alan plan adımları lazy tool havuzundan çalıştırılıyor.
- `core/agent.py` — tool parametre normalizasyonu eklendi (`list_files` default path, `advanced_research` topic/depth normalize, `web_search` query derive, `open_url` query->google URL, `create_visual_asset_pack` default project/brief/output).
- `core/agent.py` — sonuç biçimleme güvenli hale getirildi (`_format_result_text`): dict çıktılar insan okunur metne çevriliyor; ham dict stringlerinden kaynaklı Telegram Markdown parse hataları azaltıldı.
- `core/agent.py` — `summarize_url`, `summarize_file`, `summarize_text`, `translate`, `show_help` için doğrudan yürütme handler'ları eklendi.
- `core/gateway/adapters/telegram.py` — gönderim dayanıklılığı artırıldı: Markdown parse hatasında otomatik plain-text retry eklendi.
- `core/intelligent_planner.py` — fallback action inference genişletildi: `görsel/gorsel/image/logo/tasarla` anahtarları `create_visual_asset_pack` aracına yönleniyor.
- `core/task_engine/__init__.py` — package/module isim çakışması için legacy bridge eklendi: `get_task_engine()` ve `TaskEngine()` artık `core/task_engine.py` dosyasını lazy-load ederek export ediyor.
- `tests/unit/test_agent_routing.py` — yeni test dosyası: direct intent execution, `research` action mapping, tool fallback ve task_engine bridge davranışları doğrulandı.
- Doğrulama: `python -m pytest -q tests/unit/test_agent_routing.py tests/unit/test_gateway_cli.py tests/unit/test_model_routing_consistency.py tests/unit/test_models_cli.py` → **13 passed**.
- Operasyonel doğrulama: local dry-run'da `Agent.process('masaüstünde ne var')` gerçek dosya listesini döndürüyor; `Agent.process('iphone araştır')` `advanced_research` aracı ile kaynak toplayıp özet üretiyor.
- `core/agent.py` — `_format_result_text` iyileştirildi: `success + path/url` çıktıları ham dict yerine insan okunur metne çevriliyor (`İşlem tamamlandı: ...`), böylece Telegram markdown/plain fallback'te sonuçlar daha temiz gösteriliyor.
- Doğrulama: `python -m py_compile core/agent.py` + `pytest tests/unit/test_agent_routing.py` → **4 passed**.
- `core/intent_parser/_files.py` — `list_files` yanlış pozitifleri düzeltildi: artık sadece dosya sistemi bağlamı varsa (`dosya/klasör/path alias`) tetikleniyor; `bugün takvimde ne var` gibi cümleler file-listing’e düşmüyor.
- `core/intent_parser/_media.py` — yeni `visual generation` parser eklendi: `görsel oluştur / logo tasarla / image generate` komutları `create_visual_asset_pack` aracına yönleniyor.
- `core/intent_parser/__init__.py` — sequential komut ayrıştırma eklendi (`ve sonra / ardından / sonra`): parser artık `multi_task` planı üretip adımları bağımlılıkla sıralıyor.
- `core/agent.py` — `multi_task` direct execution desteği eklendi: basit çok-adımlı istekler planner’a düşmeden sırayla tool çağrısı ile yürütülüyor.
- `core/gateway/server.py` — model görünürlüğü tutarlılaştırıldı: analytics/status artık router’ın aktif modeli + config modeli birlikte dönüyor (`model_consistent`, `configured_model/provider`, `model_source`).
- `ui/web/dashboard.html` — header model etiketi tutarsızlık durumunda aktif model yanında config modelini de gösteriyor (`cfg: provider:model`).
- `cli/commands/gateway.py` — `gateway start --daemon` sonrası sağlık bekleme döngüsü eklendi (20sn); erken `connection refused` karmaşası azaltıldı, process erken düşerse log yönlendirmesi veriliyor.
- `cli/commands/dashboard.py` + `cli/main.py` — `elyan dashboard --no-browser` ve `--port` artık gerçekten uygulanıyor.
- `tests/unit/test_intent_parser_and_dashboard.py` — yeni testler: calendar/list_files regresyonu, visual intent routing, multi-task split, dashboard no-browser davranışı.
- `tests/unit/test_agent_routing.py` — `multi_task` direct execution regresyon testi eklendi.
- Doğrulama: `python -m py_compile core/intent_parser/__init__.py core/intent_parser/_files.py core/intent_parser/_media.py core/agent.py core/gateway/server.py cli/commands/gateway.py cli/commands/dashboard.py cli/main.py` → **OK**.
- Doğrulama: `pytest -q tests/unit/test_agent_routing.py tests/unit/test_intent_parser_and_dashboard.py tests/unit/test_gateway_cli.py tests/unit/test_model_routing_consistency.py tests/unit/test_models_cli.py` → **18 passed**.
- `core/tool_usage.py` — YENİ: tool telemetry katmanı eklendi (`record_tool_usage`, `get_tool_usage_snapshot`); çağrı sayısı, başarı oranı, latency ve son hata bilgileri tutuluyor.
- `core/agent.py` — tool execution sertleştirildi: her tool çağrısı telemetry’ye yazılıyor; hallucinated tool isimleri için alias + fuzzy çözümleme (`_resolve_tool_name`) eklendi.
- `core/intent_parser/_base.py` — uygulama alias’ları genişletildi: `kamera/camera/webcam` komutları `Photo Booth` açılışına yönleniyor.
- `security/tool_policy.py` — policy uyumluluğu geliştirildi: `tools.requireApproval` (camelCase) + `tools.require_approval` birlikte destekleniyor; varsayılan allow seti `ui/runtime/messaging/automation/memory` gruplarını da kapsayacak şekilde genişletildi; `infer_group()` public API eklendi.
- `core/gateway/server.py` — Tool Management API eklendi:
  - `GET /api/tools` (tool envanteri + policy durumu + kullanım metrikleri)
  - `POST /api/tools/policy` (allow/deny/approval güncelleme; tool veya group bazlı toggle)
  - `POST /api/tools/test` (dashboard’dan güvenli tool test yürütme)
- `core/gateway/server.py` — policy listesi normalize edildi; `requireApproval`/`require_approval` uyumu server tarafında da garantilendi.
- `config/elyan_config.py` — roadmap default tool allow listesi genişletildi (`group:ui`, `group:runtime`, `group:messaging`, `group:automation`, `group:memory`).
- `ui/web/dashboard.html` — YENİ “Araçlar” sekmesi eklendi:
  - canlı tool özeti (total/allowed/denied/approval)
  - filtrelenebilir tool tablosu (group/policy/search)
  - web arayüzünden allow/deny/approval toggle yönetimi
  - dashboard üzerinden JSON parametreli tool test çalıştırma paneli
- `tests/unit/test_tool_usage.py` — telemetry sayaç/başarı oranı testleri eklendi.
- `tests/unit/test_gateway_tools_helpers.py` — gateway policy helper testleri eklendi.
- `tests/unit/test_tool_policy.py` — camelCase `requireApproval` uyumluluğu ve group inference testleri eklendi.
- `tests/unit/test_agent_routing.py` — tool alias çözümleme testi eklendi.
- Doğrulama: `python -m py_compile config/elyan_config.py security/tool_policy.py core/gateway/server.py core/agent.py core/tool_usage.py` → **OK**.
- Doğrulama: `pytest -q tests/unit/test_tool_policy.py tests/unit/test_tool_usage.py tests/unit/test_gateway_tools_helpers.py tests/unit/test_agent_routing.py tests/unit/test_intent_parser_and_dashboard.py tests/unit/test_model_routing_consistency.py tests/unit/test_gateway_cli.py` → **25 passed**.
- Canlı doğrulama: `POST /api/tools/test` ile `get_system_info` dashboard test çağrısı başarılı (`ok=true`, `group=runtime`, JSON sonuç döndü).
- `tools/__init__.py` — lazy tool loader boşlukları kapatıldı: `email_tools`, `code_execution_tools`, `ai_tools` ve `visualization` araçları için yükleme branch’leri eklendi (`send_email`, `get_emails`, `execute_python_code`, `debug_code`, `ollama_list_models`, `create_chart` vb. artık gerçekten callable).
- `core/kernel.py` — registry yapısı geliştirildi: `AVAILABLE_TOOLS` içinden callable araçlar otomatik registry’ye ekleniyor (`_auto_register_lazy_tools`), böylece planner/registry görünürlüğü sadece 22 tool ile sınırlı kalmıyor.
- `core/agent.py` — tool isim çözümleme sertleştirildi: `tool:/action:` prefix temizleme, quote/simge normalizasyonu, geniş alias/fallback zinciri (özellikle `advanced_research`/`deep_research`/`web_search`) ve fuzzy eşleşmede callable doğrulaması eklendi.
- `cli/commands/gateway.py` — daemon stabilitesi artırıldı:
  - stale PID temizleme (`_read_pidfile/_clear_pidfile`),
  - port listener PID keşfi (`_find_listener_pid`),
  - gerçek çalışma tespiti (`_running_gateway_pid`),
  - daemon süreçlerini terminalden bağımsızlaştırma (`start_new_session=True`),
  - `stop` için PID+port tabanlı güvenli sonlandırma,
  - `health` çıktısına `starting` durumu (process var ama API henüz hazır değil).
- `cli/main.py` — `gateway stop/restart` akışında `--port` parametresi `stop_gateway()` fonksiyonuna geçiriliyor.
- `cli/commands/completion.py` — completion güvenilirliği iyileştirildi:
  - non-interactive `compdef` hatasını engelleyen guard,
  - zsh için `compinit -i` kullanımı,
  - top-level `logs` ve `skills check` tamamlamaları,
  - fish completion’da gateway alt komutları (`reload`, `health`) güncellendi.
- `core/gateway/server.py` — model yönetimi API eklendi:
  - `GET /api/models` (default/fallback/roles/router + runtime active/config tutarlılığı),
  - `POST /api/models` (default/fallback/router güncelleme + opsiyonel role sync),
  - provider→default model helper (`_default_model_for_provider`).
- `ui/web/dashboard.html` — Settings sekmesi gerçek model yönetimine geçirildi:
  - statik dummy select’ler kaldırıldı,
  - default/fallback provider+model formu,
  - router enable + role sync toggle,
  - runtime model vs config model tutarlılık göstergesi,
  - `loadModelSettings()` / `saveModelSettings()` ile `/api/models` entegrasyonu,
  - ayarlar sekmesinde otomatik refresh.
- `security/tool_policy.py` — tool group hints genişletildi (`execute_*`, `debug_code`, `send_email`, `get_emails`, `create_chart` vb.) böylece policy/infer_group doğruluğu arttı.
- `tests/unit/test_tools_lazy_loader.py` — yeni regresyon testleri: eksik lazy-loader branch’leri için callable doğrulaması.
- `tests/unit/test_gateway_cli.py` — gateway health için `starting` senaryosu eklendi; status/health testleri yeni PID keşif akışına uyarlandı.
- `tests/unit/test_gateway_tools_helpers.py` — model default mapping helper için test eklendi.
- Doğrulama:
  - `python -m py_compile core/gateway/server.py core/kernel.py core/agent.py cli/commands/gateway.py cli/commands/completion.py cli/main.py security/tool_policy.py tools/__init__.py` → **OK**
  - `pytest -q tests/unit/test_gateway_cli.py tests/unit/test_gateway_tools_helpers.py tests/unit/test_tool_policy.py tests/unit/test_tools_lazy_loader.py tests/unit/test_skill_manager.py tests/unit/test_agent_routing.py` → **23 passed**
  - Canlı kontrol: `elyan gateway start --daemon --port 18789` + `elyan gateway health --json` → **healthy=true**; `/api/tools` toplam tool: **119**; `/api/models` GET/POST akışları başarılı.

## OTURUM GÜNCELLEMESİ — 2026-02-19 (ROUTINES++) ✅
- `core/scheduler/routine_engine.py` — rutin motoru operatör seviyesi genişletildi:
  - Deterministik adım çalıştırma eklendi (tarayıcı aç, panel login, veri kontrol, Excel oluştur, rapor özeti, teslim adımı).
  - Panel URL desteği eklendi (`panels` alanı; adım metninden URL çıkarımı + normalize).
  - Rutin template sistemi eklendi (`ecommerce-daily`, `agency-daily`, `academic-daily`, `office-daily`).
  - `create_from_template()` / `list_templates()` / `get_template()` API’leri eklendi.
  - Çalışma raporu dosyaya yazma eklendi (`~/.elyan/reports/routines/YYYYMMDD/*.md`).
  - Artifacts/findings toplama ve daha güçlü rapor formatı eklendi.
- `core/gateway/server.py` — rutin API genişletildi:
  - `GET /api/routines/templates`
  - `POST /api/routines/from-template`
  - `POST /api/routines` içinde `panels` + `template_id` kabulü.
  - `GET /api/routines` çıktısına template listesi ve template sayısı eklendi.
  - Cron rapor gönderimi güvenli kısaltma + başlık standardizasyonu (mesaj limiti için 3500 karakter).
- `cli/main.py` — `elyan routines` parser güncellendi:
  - Yeni action: `templates`
  - Yeni parametreler: `--template-id`, `--panels`
- `cli/commands/routines.py` — CLI rutin yönetimi geliştirildi:
  - `elyan routines templates`
  - `elyan routines add --template-id ...` ile template tabanlı rutin oluşturma
  - `--panels` ile panel URL listesi gönderimi
- `cli/commands/completion.py` — completion rutin action listesi güncellendi (`templates` eklendi).
- `handlers/telegram_routines_commands.py` — Telegram rutin komutları genişletildi:
  - `/routine_templates`
  - `/routine_from <template_id> <HH:MM> [panel1,panel2]`
  - `/routine_add` formatına opsiyonel panel bloğu eklendi (`|| panel1,panel2`).
- `handlers/telegram_handler.py` — yeni Telegram rutin komutları register edildi ve `/help` metni güncellendi.
- `ui/web/dashboard.html` — otomasyon paneli geliştirildi:
  - Template dropdown eklendi (seçince adımlar otomatik dolar)
  - Panel URL input alanı eklendi
  - `createRoutine()` template/custom akışını otomatik API’ye yönlendirir hale getirildi
  - Rutin listesinde template/panel bilgisi gösterimi eklendi.
- `tests/unit/test_routine_engine.py` — yeni testler eklendi:
  - template’ten rutin oluşturma
  - deterministik tool tabanlı rutin akışı (panel + fetch + excel + rapor)

**Doğrulama:**
- `python3 -m py_compile core/scheduler/routine_engine.py core/gateway/server.py cli/main.py cli/commands/routines.py cli/commands/completion.py handlers/telegram_routines_commands.py handlers/telegram_handler.py tests/unit/test_routine_engine.py`
- `pytest -q tests/unit/test_routine_engine.py tests/unit/test_gateway_cli.py` → **9 passed**
- `pytest -q tests/unit/test_tools_lazy_loader.py tests/unit/test_skill_manager.py` → **5 passed**
- `install.sh` — ilk kurulum sonrası `elyan` bulunamadı durumunu azaltmak için özet çıktıya anlık PATH export satırı + tam path ile doğrulama komutu eklendi.
- `cli/commands/completion.py` — completion komut listesi `service` komutunu da kapsayacak şekilde hizalandı.
- `cli/commands/gateway.py` — `gateway start --daemon` servis/launchd çakışmasına dayanıklı hale getirildi:
  - launchd servis aktifse bilgilendirici uyarı mesajı eklendi.
  - spawn edilen süreç erken çıkarsa portta çalışan başka gateway süreci devralma (takeover) kontrolü eklendi.
  - takeover durumunda startup artık false-negative hata yerine sağlıklı durum olarak raporlanıyor.
- `tools/office_tools/excel_tools.py` — `pandas` bağımlılığı opsiyonel hale getirildi:
  - üst seviye import crash’i kaldırıldı (pandas yoksa modül yüklenmeye devam eder).
  - `read_excel` openpyxl fallback ile çalışır.
  - `analyze_excel_data` pandas yoksa anlaşılır hata döndürür.
- `core/scheduler/routine_engine.py` — rutin dayanıklılığı artırıldı:
  - panel erişim hataları hard-fail yerine uyarı olarak ele alınıyor (günlük rutin fail’e düşmüyor).
  - panel URL olmayan login adımı uyarı+skip davranışına çekildi.
  - web search başarısızlığında soft-warning dönüşü eklendi.
  - Excel adımı başarısızsa `write_file` ile `.md` özet fallback üretimi eklendi (`*_summary.md`).

**Doğrulama (2026-02-19):**
- `pytest -q tests/unit/test_routine_engine.py tests/unit/test_gateway_cli.py` → **9 passed**
- `elyan gateway restart --daemon --port 18789` → healthy
- `elyan routines run 740f6f2e-3` → **SUCCESS** (panel erişim uyarıları + summary dosyası fallback)

## OTURUM GÜNCELLEMESİ — 2026-02-19 (AGENT UX/STABILIZATION) ✅
- `core/agent.py` — tool çağrı dayanıklılığı artırıldı:
  - `_execute_tool` içinde erken tool-name çözümleme eklendi (`openapp`/`launchapp` gibi alias’lar artık canonical tool’a düşüyor).
  - planner/LLM param alias normalizasyonu eklendi (`appname/application/name` → `app_name`).
  - `open_app`/`close_app` için otomatik `app_name` çıkarımı eklendi (user_input + step_name üzerinden Safari/Chrome/Terminal vb. algılama).
- `core/agent.py` — konu çıkarımı (`_extract_topic`) profesyonelleştirildi:
  - "X’i aç ve Y araştır" yapısındaki uygulama-açılış prefix’i temizleniyor.
  - token temizleme word-boundary ile düzeltildi; `araştırma` kelimesinden `ma` artık kalmıyor.
- `core/agent.py` — alias kapsamı genişletildi:
  - `openapp/open_application/launchapp` → `open_app`
  - `closeapp/close_application` → `close_app`
  - `openbrowser` → `open_url`
- `tools/system_tools.py` — `open_app` / `close_app` fail-safe hale getirildi:
  - `app_name` opsiyonel parametreye çekildi.
  - eksik app adı durumunda Python `TypeError` yerine anlaşılır hata mesajı dönüyor.
- `tools/research_tools/advanced_research.py` — araştırma özeti sadeleştirildi:
  - iddialı/şişkin metin yerine kısa, ölçülebilir ve okunabilir özet formatı.
  - bulgu temizleme + dedupe ile daha profesyonel çıktı.
- `tests/unit/test_agent_routing.py` — 4 yeni regresyon testi:
  - `openapp` alias çözümleme
  - `open_app` için app adı çıkarımı
  - `openapp + appname` param normalizasyonu
  - topic extraction’ta app-open prefix temizliği

**Doğrulama:**
- `python -m py_compile core/agent.py tools/system_tools.py tools/research_tools/advanced_research.py tests/unit/test_agent_routing.py` → **OK**
- `pytest -q tests/unit/test_agent_routing.py` → **9 passed**

- `core/intent_parser/__init__.py` — plain `"ve"` bağlacı için güvenli multi-task fallback eklendi; "safariyi aç ve köpekler hakkında araştırma yap" artık deterministic olarak `open_app -> research` iki adıma ayrılıyor.
- `tests/unit/test_intent_parser_and_dashboard.py` — `"safariyi aç ve ... araştır"` plain-`ve` multi-task split regresyon testi eklendi.

**Ek Doğrulama:**
- `python -m py_compile core/intent_parser/__init__.py tests/unit/test_intent_parser_and_dashboard.py` → **OK**
- `pytest -q tests/unit/test_agent_routing.py tests/unit/test_intent_parser_and_dashboard.py` → **14 passed**

## OTURUM GÜNCELLEMESİ — 2026-02-19 (GATEWAY RESTART STABILITY) ✅
- `cli/commands/gateway.py` — port/PID tespiti güçlendirildi:
  - `_find_listener_pids()` eklendi (psutil + `lsof` fallback).
  - `_find_listener_pid()` bu yeni listeleyiciyi kullanacak şekilde güncellendi.
  - `_is_port_listening()`, `_is_elyan_like_process()`, `_describe_process()` yardımcıları eklendi.
- `cli/commands/gateway.py` — daemon startup failure yolu iyileştirildi:
  - ilk process erken çıkarsa takeover PID Elyan değilse net hata + süreç bilgisi gösteriliyor (sessiz false-negative yerine açıklayıcı çıktı).
  - portu tutan process için `lsof` ile kontrol komutu öneriliyor.
- `cli/commands/gateway.py` — `stop_gateway()` portu dinleyen **tüm** PID’leri sonlandıracak şekilde güncellendi (tek PID varsayımı kaldırıldı).
- `cli/commands/gateway.py` — yeni `restart_gateway()` eklendi:
  - `stop` sonrası port serbest kalana kadar kısa bekleme + sonra `start`.
- `cli/main.py` — `gateway restart` akışı doğrudan `gateway.restart_gateway(...)` kullanacak şekilde güncellendi.
- `tests/unit/test_gateway_cli.py` — 2 yeni test eklendi:
  - `lsof` fallback ile listener PID tespiti.
  - `restart_gateway()` çağrı sırası (`stop` → `start`) doğrulaması.

**Doğrulama:**
- `python -m py_compile cli/commands/gateway.py cli/main.py tests/unit/test_gateway_cli.py` → **OK**
- `pytest -q tests/unit/test_gateway_cli.py` → **6 passed**
- Canlı doğrulama: `elyan gateway restart --daemon --port 18789` + `elyan gateway health --json --port 18789` → **healthy=true**

## OTURUM GÜNCELLEMESİ — 2026-02-19 (NLU + TOOL RELIABILITY HARDENING) ✅
- `core/agent.py` — kritik parametre kaybı düzeltildi:
  - `_execute_tool` artık `message` alanını global olarak silmiyor (`send_notification` / `create_reminder` / benzeri tool parametreleri korunuyor).
- `core/agent.py` — param hazırlama katmanı güçlendirildi:
  - `read_file`: kullanıcı metninden `*.ext` dosya adı çıkarımı (örn. `not.txt içinde ne var`).
  - `write_file`: içerik boşsa “bunu kaydet” senaryosunda son assistant çıktısından otomatik doldurma; boş içerik fallback metni eklendi.
  - `write_word`: içerik/path/title otomatik doldurma (son assistant çıktısı fallback).
  - `write_excel`: veri boşsa son assistant çıktısından satır bazlı tablo üretimi (`[{\"Veri\": ...}]`).
  - `send_notification`: `title/message` zorunlu normalize ve akıllı fallback.
  - `create_reminder`: `title/due_time/due_date` normalize + doğal dilden saat çıkarımı.
  - `create_event`: `time`/metinden `start_time` eşleme.
- `core/agent.py` — yeni yardımcılar:
  - `_extract_time_from_text()` (TR doğal dil saat parse),
  - `_get_recent_assistant_text()` (konuşma geçmişinden son yanıt çekme).
- `core/intent_parser/_files.py` — dosya NLU iyileştirildi:
  - `write_file`: `bunu kaydet`, `dosya olarak kaydet`, `masaüstüne kaydet` tetikleyicileri eklendi.
  - dosya adı çıkarımı artık uzantılı adları da yakalıyor (`not.txt`, `rapor.md`).
  - path çıkarımı `self._extract_path` ile daha tutarlı.
  - `read_file`: `içinde ne var` kalıbı desteklendi.
- `core/intent_parser/_system.py` — notification/reminder çakışması azaltıldı:
  - zaman içeren `hatırlat` cümleleri reminder parser’a bırakılıyor.
  - `... hatırlat` cümle sonu kalıbı için bildirim içeriği çıkarımı eklendi.
- `core/intent_parser/_media.py` — reminder parser profesyonelleştirildi:
  - `"Saat 22 de bana ilaç içmem gerekiyor hatırlat"` gibi cümlelerde `create_reminder` + `due_time=22:00` üretimi.
  - içerik temizleme (`bana/beni/lütfen` vb.) ve başlık fallback.
- `core/intent_parser/__init__.py` — `"Planlanmış görevler"` gibi doğal sorgular için yeni parser adımı (`_parse_scheduled_tasks`) pipeline’a eklendi.
- `tools/__init__.py` — office lazy loader dayanıklılığı artırıldı:
  - Word/Excel/PDF/Summarizer importları modül bazında `try/except` ile ayrıldı; optional dependency eksik olsa da `write_excel`/`write_word` callable kalıyor.
- `tools/office_tools/__init__.py` — package exportları optional dependency-safe hale getirildi (PDF/OCR bağımlılığı yoksa word/excel tarafı kırılmıyor).
- `tools/office_tools/excel_tools.py` — boş veri ile dosya yaratma davranışı düzeltildi:
  - `data` boşsa artık `success=False` ile anlaşılır hata dönüyor (sessiz boş dosya yerine).
- `tools/system_tools.py` — `send_notification` fail-safe:
  - `title/message` opsiyonel default + boş message fallback.
- `core/gateway/adapters/telegram.py` — markdown parse hataları azaltıldı:
  - Telegram mesaj gönderimi plain text (`parse_mode=None`) ile standartlaştırıldı.

**Yeni/ güncellenen testler:**
- `tests/unit/test_agent_routing.py`
  - `send_notification` için `message` parametresi korunumu.
  - `write_file` için geçmiş assistant çıktısından içerik fallback.
- `tests/unit/test_intent_parser_and_dashboard.py`
  - `not.txt içinde ne var` → `read_file`.
  - zamanlı hatırlatma cümlesi → `create_reminder` + `due_time`.
  - `Planlanmış görevler` → `list_plans`.
- `tests/unit/test_tools_lazy_loader.py`
  - office lazy loader callable kapsamı genişletildi (`read/write_word`, `read/write_excel` vb.).

**Doğrulama:**
- `python -m py_compile core/agent.py core/intent_parser/_files.py core/intent_parser/_system.py core/intent_parser/_media.py core/intent_parser/__init__.py tools/__init__.py tools/system_tools.py tools/office_tools/excel_tools.py core/gateway/adapters/telegram.py tests/unit/test_agent_routing.py tests/unit/test_intent_parser_and_dashboard.py tests/unit/test_tools_lazy_loader.py` → **OK**
- `pytest -q tests/unit/test_tools_lazy_loader.py tests/unit/test_agent_routing.py tests/unit/test_intent_parser_and_dashboard.py` → **20 passed**

## OTURUM GÜNCELLEMESİ — 2026-02-19 (CLI UX + RESEARCH TOPIC HARDENING) ✅
- `cli/main.py` — ilk kullanım UX iyileştirildi:
  - top-level komut yazım hatalarında yakın komut önerisi eklendi.
  - örn. `elyan gatewat logs` → `"Şunu mu demek istediniz: 'gateway'?"`.
  - `main(argv=None)` imzasına taşındı; test edilebilirlik arttı.
- `core/agent.py` — araştırma konusu normalize edildi:
  - `_sanitize_research_topic()` eklendi.
  - `advanced_research` param hazırlığında parser’dan gelen kirli topic temizleniyor.
  - `"safariyi aç ve köpekler hakkında araştırma yap"` benzeri girdilerde topic artık `"köpekler"`.
- `tools/office_tools/word_tools.py` — boş Word dosyası üretimi engellendi:
  - title/content/paragraphs tamamen boşsa artık `success=False` + anlaşılır hata dönüyor.
- `tests/unit/test_cli_main.py` — yeni CLI UX testleri:
  - typo komut önerisi testi.
  - `version` komutu smoke testi.
- `tests/unit/test_office_tools.py` — yeni Word güvenlik davranışı testi:
  - boş payload ile `write_word` hata dönüşü doğrulandı.
- `tests/unit/test_agent_routing.py` — `advanced_research` topic sanitize regresyon testi eklendi.

**Doğrulama:**
- `pytest -q tests/unit/test_cli_main.py tests/unit/test_office_tools.py tests/unit/test_agent_routing.py tests/unit/test_intent_parser_and_dashboard.py tests/unit/test_tools_lazy_loader.py tests/unit/test_gateway_cli.py` → **30 passed**

## OTURUM GÜNCELLEMESİ — 2026-02-19 (SPEED + PROFESSIONAL EXECUTION UPGRADE) ✅
- `tools/research_tools/advanced_research.py` — araştırma motoru hız/güvenilirlik yükseltildi:
  - depth bazlı adaptif evaluation eklendi (`eval_cap`, `concurrency`, `timeout` haritaları).
  - web arama sonuçlarında URL+title dedupe eklendi (aynı kaynak tekrarlarını azaltır).
  - her araştırma çalışmasında otomatik **hızlı Markdown rapor** persist edilir:
    - `~/.elyan/reports/research/YYYYMMDD/...md`
    - `report_paths` artık `generate_report=False` olsa bile anlamlı çıktı içerir.
  - son araştırma sonucu cache’i eklendi (`_last_research_result`, `get_last_research_result`).
  - `get_research_result` davranışı tutarlılaştırıldı: yalnızca tamamlanan araştırmayı döner; pending ise progress ile hata döner.
  - modüldeki çift `get_research_result` tanımı kaynaklı tutarsızlık temizlendi (snapshot fonksiyonu ayrıştırıldı).
- `tools/office_tools/excel_tools.py` — Excel yazımı profesyonel veri normalize katmanı ile güçlendirildi:
  - `dict` veri artık tek satır olarak doğru yazılır.
  - `list[dict]`, `list[list/tuple]`, `list[scalar]`, scalar veri tipleri otomatik normalize edilir.
  - `row_count` doğru hesaplanır; boş veride başarısızlık açık hata ile döner.
- `core/intent_parser/_apps.py` — doğal dilde birleşik komutlar iyileştirildi:
  - `"safariyi aç köpekler hakkında araştırma yap"` gibi **bağlaçsız** cümleler de `multi_task` (open_app + research) üretir.
  - research topic çıkarımında Türkçe ek/artık token temizliği eklendi (`safariyi` kalıntısı gibi parçalar temizlenir).
- `core/intent_parser/_documents.py` — Word/Excel kaydetme cümleleri daha toleranslı:
  - `"word olarak kaydet"` / `"word kaydet"` tetikleyicileri eklendi.
  - `"word aç"` / `"excel aç"` ile belge üretim parser çakışması engellendi.
- `core/scheduler/routine_engine.py` — rutin ID çözümleme geliştirildi:
  - prefix ile tekil eşleşmede rutin ID resolve edilir (`match_routine_ids`, `resolve_routine_id`).
  - `get_routine`, `set_enabled`, `remove_routine`, `get_history`, `run_routine` prefix destekler.
- `core/gateway/server.py` — routines API prefix ID desteği:
  - `run/toggle/history/remove` endpointleri ID prefix kabul eder.
  - ambiguous prefix durumunda net `409` hata döner.

**Yeni testler / güncellenen testler:**
- `tests/unit/test_advanced_research.py`
  - hızlı rapor persist testi
  - pending araştırma sonucu için strict getter testi
- `tests/unit/test_office_tools.py`
  - `write_excel` dict/sparse veri tipi testleri
- `tests/unit/test_intent_parser_and_dashboard.py`
  - bağlaçsız open+research multi-task testi
- `tests/unit/test_routine_engine.py`
  - rutin ID prefix resolution testi

**Doğrulama:**
- `pytest -q tests/unit/test_advanced_research.py tests/unit/test_office_tools.py tests/unit/test_intent_parser_and_dashboard.py tests/unit/test_routine_engine.py tests/unit/test_agent_routing.py tests/unit/test_gateway_cli.py tests/unit/test_cli_main.py tests/unit/test_tools_lazy_loader.py` → **41 passed**
- `python -m py_compile tools/research_tools/advanced_research.py tools/office_tools/excel_tools.py core/intent_parser/_apps.py core/intent_parser/_documents.py core/scheduler/routine_engine.py core/gateway/server.py tests/unit/test_advanced_research.py tests/unit/test_office_tools.py tests/unit/test_intent_parser_and_dashboard.py tests/unit/test_routine_engine.py` → **OK**
- Ek regresyon: `pytest -q tests/unit/test_intent_parser_and_dashboard.py tests/unit/test_advanced_research.py tests/unit/test_office_tools.py tests/unit/test_routine_engine.py` → **20 passed**

## OTURUM GÜNCELLEMESİ — 2026-02-19 (ADAPTIVE AGENT + SKILL-AWARE LEARNING) ✅
- `core/agent.py` — sürekli öğrenen ve skill-aware ajan akışı eklendi:
  - yeni entegrasyonlar:
    - `get_learning_engine()` (yerel davranış öğrenme)
    - `get_capability_router()` (domain fallback)
    - `skill_registry` + `skill_manager` (aktif skill’lere göre fallback intent üretimi)
    - `get_user_profile_store()` (kullanıcı profili yerel güncelleme)
  - doğal dil ön-normalizasyonu eklendi:
    - `ss al` gibi kısa/argo komutlar normalize edilerek intent başarımı artırıldı.
  - parser chat/unknown döndüğünde yeni fallback sırası:
    1. `learning.quick_match()` ile güvenli parametresiz hızlı aksiyonlar,
    2. aktif skill’lerden command-level intent çıkarımı (`research/files/office/browser/system/calendar`),
    3. capability-router tabanlı domain fallback.
  - turn-finalization merkezi hale getirildi:
    - `_finalize_turn()` ile her yanıtta:
      - konuşma belleğine kayıt,
      - user profile güncelleme,
      - learning engine’e interaction kaydı.
  - yerel tercihlerin araç parametrelerine etkisi eklendi:
    - `preferred_output` ile `write_file` default uzantısı,
    - `response_length` ile `advanced_research` depth (short→quick, detailed→comprehensive).
- `tests/unit/test_agent_routing.py` — yeni regresyon testleri:
  - learning quick-match fallback (`chat` parse olsa bile güvenli aksiyona düşüş),
  - skill fallback ile araştırma intent’i üretimi,
  - learning preference’in research depth’e uygulanması.

**Doğrulama:**
- `PYTHONPATH=. pytest -q tests/unit/test_agent_routing.py tests/unit/test_intent_parser_and_dashboard.py tests/unit/test_office_tools.py tests/unit/test_advanced_research.py tests/unit/test_routine_engine.py tests/unit/test_gateway_cli.py tests/unit/test_cli_main.py` → **43 passed**
- `python -m py_compile core/agent.py core/skills/registry.py core/learning_engine.py tests/unit/test_agent_routing.py` → **OK**

## OTURUM GÜNCELLEMESİ — 2026-02-19 (OFFICE-STYLE DASHBOARD UI REFRESH) ✅
- `ui/web/dashboard.html` — dashboard arayüzü roadmap hedeflerine uygun şekilde ofis uygulaması hissiyle yenilendi:
  - Tipografi güncellendi: `Inter` yerine `IBM Plex Sans + IBM Plex Mono`.
  - Arka plan/surface sistemi yenilendi: çok katmanlı gradient + modern kart yüzeyleri.
  - Üst alan yeniden tasarlandı:
    - daha güçlü top bar (workspace başlığı, model chip, sistem metrikleri),
    - yeni **Ribbon** satırı (hızlı sekme geçişleri + tek tık yenile + saat + bağlantı durumu).
  - Alt **status bar** eklendi:
    - aktif sekme,
    - son senkron zamanı,
    - model sağlayıcı/model,
    - gateway runtime bilgisi.
  - Sol menü ergonomisi iyileştirildi (aktif durum vurgusu, hover derinliği).
  - Responsive davranış güçlendirildi:
    - dar ekranlarda sidebar compact moda düşer,
    - toolbar yatay kaydırılabilir,
    - düşük öncelikli status alanları gizlenir.
- `ui/web/dashboard.html` script güncellemeleri:
  - `switchTab()` artık ribbon/status bar aktif sekmesini senkronlar.
  - WebSocket open/close olayları yeni status chip’lerine bağlandı (`WS Connected/Disconnected`).
  - `pollStatus()` son senkron zamanı + runtime durumunu günceller.
  - `pollAnalytics()` model bilgisi status bar’a yansıtılır.
  - `updateRibbonClock()` eklendi (periyodik saat güncellemesi).

**Doğrulama:**
- `PYTHONPATH=. ./.venv/bin/pytest -q tests/unit/test_intent_parser_and_dashboard.py` → **9 passed**
- `./.venv/bin/python -m py_compile main.py core/gateway/server.py` → **OK**

## OTURUM GÜNCELLEMESİ — 2026-02-19 (CLI ENTRYPOINT FIX + INSTALL HARDENING) ✅
- `install.sh` — ilk kurulumda `elyan` komutunun bazı Python 3.12 ortamlarda kırılmasına neden olan editable kurulum sorunu giderildi:
  - `pip install -e .` yerine **compat editable** kullanımı eklendi:
    - `pip install -e . --config-settings editable_mode=compat`
  - kurulum sonrası zorunlu CLI smoke-check eklendi:
    - `.venv/bin/elyan version` başarısızsa otomatik fallback:
      - `pip uninstall -y elyan`
      - `pip install .` (non-editable)
  - son doğrulama başarısızsa kurulum `err` ile kesiliyor (sessiz bozuk kurulum engellendi).
- `install.sh` — global launcher dayanıklılığı artırıldı:
  - `~/.local/bin/elyan` artık `.venv/bin/elyan` yerine doğrudan:
    - `cd <project>`
    - `.venv/bin/python3 -m cli.main`
  - böylece script entrypoint bozulsa bile launcher çalışmaya devam eder.

**Kök neden (tespit):**
- bazı ortamlarda `__editable__.elyan-*.pth` yüklenmediği için `from cli.main import main` importu başarısız oluyordu.
- sonuç: `.venv/bin/elyan` çalışırken `ModuleNotFoundError: No module named 'cli'`.

**Doğrulama:**
- `bash -n install.sh` → **OK**
- `/Users/emrekoca/Desktop/bot/.venv/bin/elyan version` (repo dışından da) → **Elyan CLI v18.0.0**
- `source .venv/bin/activate && elyan version` → **Elyan CLI v18.0.0**

## OTURUM GÜNCELLEMESİ — 2026-02-19 (TOOL RELIABILITY HOTFIX + GATEWAY STARTUP HARDENING) ✅
- `tools/system_tools.py` — tool imza/çalıştırma hataları giderildi:
  - `set_volume()` artık `mute` parametresini destekliyor (`mute/unmute` + seviye ayarı).
  - AppleScript çağrıları doğru sözdizimiyle ve dönüş kodu kontrolüyle çalıştırılıyor.
  - `get_process_info()` artık `process_name` olmadan da çalışıyor (top process listesi fallback).
- `core/intent_parser/_system.py` — doğal dilde process sorguları daha doğru route ediliyor:
  - `"hangi uygulamalar çalışıyor"` ve benzeri cümleler artık `get_running_apps` aksiyonuna düşüyor.
- `core/agent.py` — fallback yürütme ve sonuç kalitesi güçlendirildi:
  - `_execute_tool()` içinde resolved tool unavailable durumunda `NoneType callable` crash engellendi.
  - `_prepare_tool_params()` içinde `set_volume`/`get_process_info` param normalizasyonu geliştirildi.
  - `_format_result_text()` insan-dostu çıktı iyileştirmeleri:
    - çalışan uygulama listesi,
    - WiFi durum mesajı,
    - ses durumu mesajı,
    - sistem özeti.
- `cli/commands/gateway.py` — non-editable (wheel) kurulumda gateway start çökmesi düzeltildi:
  - proje kök dizini artık `_resolve_project_root()` ile güvenli şekilde bulunuyor.
  - `main.py` bulunamazsa net yönlendirici hata veriliyor.
  - böylece `site-packages/main.py bulunamadı` tipi startup hataları temizlendi.
- `install.sh` — launcher dayanıklılığı artırıldı:
  - global launcher artık `ELYAN_PROJECT_DIR` export ediyor.

**Ek testler / güncellemeler:**
- `tests/unit/test_agent_routing.py`
  - set_volume mute param hazırlığı testi,
  - get_process_info default param testi,
  - unavailable resolved tool için güvenli hata testi.
- `tests/unit/test_intent_parser_and_dashboard.py`
  - "hangi uygulamalar çalışıyor" → `get_running_apps` yönlendirme testi.

**Doğrulama:**
- `PYTHONPATH=. ./.venv/bin/pytest -q tests/unit/test_agent_routing.py tests/unit/test_intent_parser_and_dashboard.py` → **28 passed**
- `PYTHONPATH=. ./.venv/bin/pytest -q tests/unit/test_gateway_cli.py tests/unit/test_cli_main.py` → **8 passed**
- canlı smoke (agent):
  - `sesi kapat` → başarılı,
  - `hangi uygulamalar çalışıyor` → uygulama listesi döndü,
  - `wifi durumu` → anlamlı durum çıktısı döndü,
  - `safariyi aç ve köpekler hakkında araştırma yap` → open_app + research birlikte başarılı.
- gateway doğrulama:
  - `elyan gateway restart --daemon --port 18789`
  - `elyan gateway health --json --port 18789` → **healthy: true**

## OTURUM GÜNCELLEMESİ — 2026-02-19 (NATURAL-LANGUAGE TOOL FIXES + ROUTINE ID RELIABILITY) ✅
- `core/intent_parser/_system.py` — yanlış intent eşleşmesi düzeltildi:
  - `get_system_info` parser’ı artık substring ile değil **word-boundary regex** ile tetikleniyor.
  - kritik hata giderildi: `Telegramı aç...` cümlesindeki `ram` substring’i nedeniyle `get_system_info` tetiklenmesi artık yok.
- `core/intent_parser/_apps.py` — uygulama adı yakalama profesyonelleştirildi:
  - `_parse_open_app` içinde alias eşleşmesi Türkçe eklerle (`-ı/-i/-yi/-dan/...`) regex tabanlı hale getirildi.
  - `telegramı`, `safariyi` gibi doğal kullanımlar daha stabil yakalanıyor.
- `core/agent.py` — çok adımlı görev yürütme güçlendirildi:
  - `multi_task` akışında boş içerikli doküman adımı (Word/Excel/TXT), gerekiyorsa araştırma/özet adımından **sonra** çalışacak şekilde yeniden sıralanıyor.
  - önceki adım çıktısı doküman yazım adımına otomatik hydrate ediliyor:
    - `write_word`/`write_file` için `content`,
    - `write_excel` için satırlaştırılmış `data`.
  - `write_word` ve `write_excel` param hazırlığında `filename` artık tool call’a forward edilmiyor (unexpected keyword hatası giderildi).
  - inline içerik çıkarımı eklendi (`"içine ... yaz"`, `"içerik: ..."`), boş dosya üretme riski düşürüldü.
  - araştırma topic temizleme iyileştirildi (`araştırmasını`, `yaz`, `kaydet`, `içine` gibi gürültüler temizleniyor).
- `cli/commands/routines.py` — rutin ID kullanımında güvenilirlik artırıldı:
  - `rm/enable/disable/run/history` için prefix-aware ID çözümleme eklendi.
  - belirsiz prefix durumunda anlaşılır hata veriliyor; geçerli eşleşmede tam ID kullanılıyor.
  - `routines list` tablo ID kolonu genişletildi.
- `tests/unit/test_intent_parser_and_dashboard.py`
  - `Telegramı aç ve bana mesaj gönder` ifadesinin `get_system_info`’ya düşmemesi için regresyon testi eklendi.
- `tests/unit/test_agent_routing.py`
  - boş Word adımı + araştırma kombinasyonunda doğru sıra/hydration davranışı için regresyon testi eklendi.

**Doğrulama:**
- `PYTHONPATH=. ./.venv/bin/pytest -q tests/unit/test_agent_routing.py tests/unit/test_intent_parser_and_dashboard.py` → **30 passed**
- `PYTHONPATH=. ./.venv/bin/pytest -q tests/unit/test_gateway_cli.py tests/unit/test_cli_main.py tests/unit/test_routine_engine.py` → **14 passed**

## OTURUM GÜNCELLEMESİ — 2026-02-19 (TOOL HEALTH VISIBILITY + OFFICE TOOL STABILITY) ✅
- `tools/office_tools/document_summarizer.py` — `summarize_document` kırığı giderildi:
  - hatalı `from config.settings import OLLAMA_HOST, OLLAMA_MODEL` importu kaldırıldı.
  - özetleme çağrısı tek-provider bağımlılığından çıkarıldı; artık `core.llm_client.LLMClient` üzerinden aktif sağlayıcıyla çalışıyor (OpenAI/Groq/Gemini/Ollama).
  - PDF için yanlış parametre (`max_chars`) kullanımı düzeltildi.
  - Excel içeriği stringe dönüştürme eklendi (satır/sheet bazlı normalize).
- `tools/__init__.py` — lazy tool yükleme gözlemlenebilirliği artırıldı:
  - tool yüklenemezse `_tool_load_errors` içine standart hata sebebi yazılıyor.
  - `items()` / `values()` toplu yüklemelerinde import hataları artık swallow edilmeden hata listesine kaydediliyor.
- `core/gateway/server.py` — tool health API geliştirildi:
  - `GET /api/tools/diagnostics` route’u aktive edildi.
  - diagnostics endpoint varsayılanı `probe=0` yapıldı (takılma riskini azaltan hızlı mod).
  - `/api/tools` summary `health` sayıları artık uygulanan filtreyle tutarlı hesaplanıyor (`ready`, `needs_params`, `broken`).
- `ui/web/dashboard.html` — Araçlar sekmesi profesyonelleştirildi:
  - yeni health kartları: `Ready`, `Needs Params`, `Broken`.
  - yeni health filtresi (`ready / needs_params / broken`).
  - tool tablosuna `Health` ve `Params` sütunları eklendi.
  - tool load error metni tabloda görünür hale getirildi.

**Doğrulama:**
- `source .venv/bin/activate && python -m py_compile core/gateway/server.py tools/__init__.py tools/office_tools/document_summarizer.py` → **OK**
- `source .venv/bin/activate && PYTHONPATH=. pytest -q tests/unit/test_agent_routing.py tests/unit/test_intent_parser_and_dashboard.py` → **30 passed**
- tool callable smoke:
  - `total=118`, `callable=118`, `broken=0`
- gateway + API smoke:
  - `elyan gateway start --daemon --port 18789` + `elyan gateway health --json --port 18789` → **healthy: true**
  - `GET /api/tools` → `total=119`, `health.broken=0`
  - `GET /api/tools/diagnostics` → `probe=false`, `broken_tools=0`
- summarize tool smoke (mocked LLM):
  - `summarize_document(content=...)` → **success=true**, import/runtime kırığı yok

## OTURUM GÜNCELLEMESİ — 2026-02-20 (GATEWAY STARTUP STABILITY + CLI PACKAGE SYNC) ✅
- `cli/commands/gateway.py` — startup dayanıklılığı artırıldı:
  - `start_gateway --daemon` içinde erken process exit durumunda otomatik **1 retry** eklendi.
  - health hazır kabulü, sadece port dinlenmesine değil `/api/status` yanıtına bağlandı.
  - `restart_gateway` tekrar sadeleştirildi (stop + port release bekleme + tek start), retry mantığı `start_gateway` içinde merkezileştirildi.
- CLI import kaynak tutarsızlığı giderildi (geliştirme ortamı):
  - `.venv` içinde paket editable olarak yeniden kuruldu: `pip install -e .`
  - böylece `elyan` komutu yerel repo kodunu (güncel `cli/commands/gateway.py`) çalıştırır hale getirildi.

**Doğrulama:**
- `PYTHONPATH=. pytest -q tests/unit/test_gateway_cli.py tests/unit/test_cli_main.py` → **8 passed**
- canlı smoke:
  - `elyan gateway restart --daemon --port 18789`
  - `elyan gateway health --json --port 18789`
  - başarısız başlangıç senaryosunda retry mesajı doğrulandı.

## OTURUM GÜNCELLEMESİ — 2026-02-20 (LAUNCHD/DAEMON ÇAKIŞMA DÜZELTMESİ + STARTUP STABILIZATION) ✅
- `cli/commands/gateway.py` — servis ve manuel daemon çakışması giderildi:
  - launchd servis algısı için sabit `LAUNCHD_LABEL` + servis ref helper eklendi.
  - yeni `_kickstart_launchd_service()` ile launchd aktifse başlat/restart artık doğrudan launchd üzerinden yapılıyor.
  - yeni `_wait_until_gateway_ready()` ile health readiness bekleme tek noktaya alındı.
  - `start_gateway --daemon` davranışı:
    - launchd aktifse manuel process spawn yerine launchd kickstart + health wait.
    - başarısız durumda net yönlendirme: `elyan service uninstall` sonrası manuel mod.
  - `restart_gateway --daemon` davranışı:
    - launchd aktifse stop/start yerine launchd kickstart ile çakışmasız restart.
  - `stop_gateway` launchd aktifken KeepAlive auto-restart hakkında anlaşılır uyarı veriyor.
- `tests/unit/test_gateway_cli.py` — yeni davranış için regresyon testleri eklendi:
  - launchd aktif değilken mevcut stop→start akışı korunuyor.
  - launchd aktifken restart’ın kickstart yoluna gittiği doğrulanıyor.

**Doğrulama:**
- `source .venv/bin/activate && python -m py_compile cli/commands/gateway.py tests/unit/test_gateway_cli.py main.py` → **OK**
- `source .venv/bin/activate && PYTHONPATH=. pytest -q tests/unit/test_gateway_cli.py tests/unit/test_cli_main.py` → **9 passed**
- canlı smoke:
  - `elyan gateway restart --daemon --port 18789` → **healthy**
  - `elyan gateway health --json --port 18789` → **healthy: true**
  - `GET /api/tools/diagnostics` → `broken_tools=0`
