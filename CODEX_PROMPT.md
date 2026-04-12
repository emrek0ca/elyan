# CODEX — ELYAN GELİŞTİRME DİREKTİFİ

## Proje Nedir?
Elyan, local-first kişisel AI ajan framework'ü. macOS desktop app (Tauri + React) + Python async backend (aiohttp, port 18789) + SQLite WAL.

- **venv**: `.venv/bin/python`
- **DB**: `~/.elyan/runtime.db` — SQLAlchemy 2.0, tüm raw SQL `text()` + `:named_param`
- **Entry**: `main.py` → `core/gateway/server.py` → `core/agent.py`

---

## Mimari Özeti

```
cli/main.py          → 72+ Typer komutu
core/agent.py        → Ana ajan orkestratörü, learning loop
core/gateway/
  server.py          → HTTP + auth (header/cookie/admin-token)
  adapters/
    telegram.py      → Telegram bot (940 satır)
    discord.py       → Discord bot
core/model_orchestrator.py     → 11+ LLM provider yönetimi
core/unified_model_gateway.py  → Local-first facade, security redaction
core/scheduler/
  cron_engine.py     → APScheduler, ~/.elyan/cron_jobs.json
  routine_engine.py  → Workflow yürütme
core/nl_cron.py      → Doğal dil → cron parse
core/persistence/runtime_db.py → Tablo tanımları (LOCAL_METADATA)
integrations/        → Google, email, browser, social, Turkey connectors
handlers/            → telegram_handler.py + 8 Telegram handler
```

---

## Kritik Kurallar

1. **SQLAlchemy 2.0** — `text()` + `:named_param`, asla `?` kullanma
2. **Auth sırası** — `_require_user_session()` → header → cookie → admin-token (loopback zorunlu)
3. **Routing guard sırası** — `onboardingComplete=false` → `/onboarding`, `isAuthenticated=false` → `/login`, her ikisi true → `/home`
4. **Learning loop** — `_finalize_turn()` sonunda `record_task_outcome()` çağrısını bozma
5. **Yeni DB tabloları** — `core/persistence/runtime_db.py`'de `Table(...)` ile `LOCAL_METADATA`'ya ekle
6. **Frontend API** — `apps/desktop/src/services/api/client.ts`'den `apiClient` import et
7. **CSS** — Tailwind değil, CSS değişkenleri: `var(--text-primary)`, `var(--bg-surface)`, `var(--border-subtle)`

---

## Mevcut Özellikler (zaten var)

| Özellik | Konum |
|---|---|
| Learning loop | `core/agent.py` → `_finalize_turn()` |
| Kullanıcı belleği | `.elyan/user_profiles.json` + evidence ledger |
| Terminal CLI | `cli/main.py` (Typer, 72+ komut) |
| Telegram | `core/gateway/adapters/telegram.py` + `handlers/` |
| Discord | `core/gateway/adapters/discord.py` |
| Multi-LLM (11 provider) | `core/model_orchestrator.py` + `unified_model_gateway.py` |
| Doğal dil zamanlama | `core/nl_cron.py` + `core/scheduler/cron_engine.py` |

---

## Açık Görevler

### P0 — Yayın öncesi bug fix
1. **`getCurrentLocalUser()` boş email** → `apps/desktop/src/services/api/elyan-service.ts` ~1889 — email boşsa `null` döndür
2. **`OnboardingScreen 2.tsx` sil** → `apps/desktop/src/screens/onboarding/OnboardingScreen 2.tsx`
3. **Frontend build doğrula** → `cd apps/desktop && PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/vite build`
4. **`.env.example` güncelle** → `ELYAN_ADMIN_TOKEN=` ve `ELYAN_PORT=18789` ekle

### P1 — Eksik implementasyonlar

#### 1. ProviderPool (test-driven, eksik)
Test: `tests/unit/test_provider_pool.py`
Konum: `core/llm/provider_pool.py` oluşturulmalı

```python
class ProviderPool:
    # failure_threshold kadar başarısızlık → cooldown
    # exponential backoff: base_cooldown_seconds → max_cooldown_seconds
    def can_attempt(self, provider: str, model: str) -> bool: ...
    def record_outcome(self, provider: str, model: str, success: bool, error_text: str = "") -> None: ...
```
`UnifiedModelGateway` cooldown'daki provider'ı atlamalı.

#### 2. Cloud / Serverless Deployment
- **Fly.io** veya **Railway** için `Dockerfile` + `fly.toml` / `railway.json`
- Idle'da sıfır maliyet (scale-to-zero)
- Ortam değişkenleri: `ELYAN_ADMIN_TOKEN`, `ELYAN_PORT`, `DATABASE_URL`
- Telegram/Discord webhook'ları cloud URL ile güncellenmeli

#### 3. `model switch` CLI Komutu
`cli/commands/models.py`'de `switch` subcommand:
```
elyan model switch openrouter/mistral-7b
elyan model switch openai/gpt-4o
elyan model list
```
`unified_model_gateway.py`'deki varsayılan provider'ı runtime'da değiştirmeli, yeniden başlatma gerektirmemeli.

#### 4. Günlük Rapor Scheduled Task Örneği
`core/nl_cron.py` üzerinden:
```
elyan schedule "her sabah 08:00'de günlük özet gönder" --channel telegram
```
Bu, `cron_engine.py`'e persist edilmeli ve Telegram'a delivery yapmalı.

---

## Test Protokolü (her değişiklik sonrası)

```bash
# Python syntax
.venv/bin/python -c "import ast; ast.parse(open('core/gateway/server.py').read()); print('OK')"

# TypeScript
cd apps/desktop && PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/tsc --noEmit

# Backend sağlık
.venv/bin/python main.py start --port 18789 &
sleep 6 && curl -s http://127.0.0.1:18789/healthz | python3 -m json.tool

# Frontend build
cd apps/desktop && PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/vite build 2>&1 | tail -10
```
