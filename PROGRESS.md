# Elyan — Codex Çalışma Brifing

> Bu dosya Codex'in bağlamı kaybetmeden tam olarak devam edebilmesi için yazılmıştır.
> Tüm değişiklikler `codex/cowork-desktop-platform` branch'inde yapılır.

---

## Proje Özeti

**Elyan**, macOS masaüstü için yerel çalışan bir AI ajan çerçevesidir.
- **Backend**: Python 3.11+ async (aiohttp), SQLite WAL (SQLAlchemy 2.0), port 18789
- **Frontend**: React 18 + TypeScript + Vite + Tailwind + Tauri (desktop app)
- **DB**: `~/.elyan/runtime.db` — `LOCAL_METADATA.create_all()` ile otomatik migrate
- **venv**: `.venv/bin/python` (Python 3.11.15)
- **Node**: `/opt/homebrew/bin/node`

---

## Nasıl Çalıştırılır

```bash
# Backend
cd /Users/emrekoca/Desktop/Bot\ \&\ Ticaret/bot
.venv/bin/python main.py start --port 18789

# Frontend (geliştirme)
cd apps/desktop
PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/vite dev

# Frontend (build test)
cd apps/desktop
PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/vite build

# TypeScript tip kontrolü
cd apps/desktop
PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/tsc --noEmit
```

---

## Git Durumu

**Branch**: `codex/cowork-desktop-platform`
**Main**: `main`

### Son commit'ler (en yeni → en eski)
| Hash | İçerik |
|------|--------|
| `13f937cb` | Production-readiness: auth flow, onboarding, billing, startup validation |
| `6ea5fe54` | PersonalContextEngine OS polling at backend startup |
| `cab23ff9` | SQLAlchemy 2.0 text() fixes + prompt_fragment API |
| `1b0afec1` | Workspace learning loop: record outcomes, inject into LLM |
| `d0d4dd08` | 4-layer intelligence stack (workspace, personal context, task continuity) |
| `06424f82` | Billing auth stabilized |
| `f20a4a25` | Iyzipay real API |

---

## Mimari — Kilit Dosyalar

| Dosya | Rol |
|-------|-----|
| `main.py` | Backend entry point, `_run_gateway()` |
| `core/gateway/server.py` | Tüm HTTP endpoint'leri, auth middleware |
| `core/agent.py` | Ana ajan — `_finalize_turn()` learning loop |
| `core/pipeline.py` | `StageContext` — LLM prompt assembly |
| `core/workspace/intelligence.py` | Workspace learning engine |
| `core/task_continuity.py` | Stalled task surface |
| `core/personal_context_engine.py` | OS context (AppleScript, 30s polling) |
| `core/persistence/runtime_db.py` | SQLite DB — tüm tablolar burada |
| `core/billing/iyzico_provider.py` | Iyzico payment provider |
| `apps/desktop/src/app/providers/AppProviders.tsx` | Frontend auth hydration |
| `apps/desktop/src/app/routes.tsx` | Routing — onboarding/login/home guard'ları |
| `apps/desktop/src/services/api/client.ts` | `apiClient` — tüm HTTP çağrıları |
| `apps/desktop/src/services/desktop/sidecar.ts` | `probeRuntimeHealth()` — `/healthz` → `SidecarHealth` |
| `apps/desktop/src/stores/ui-store.ts` | `onboardingComplete`, `isAuthenticated`, `authenticatedEmail` |
| `apps/desktop/src/screens/onboarding/OnboardingScreen.tsx` | İlk kurulum sihirbazı |
| `apps/desktop/src/screens/auth/LoginScreen.tsx` | Giriş ekranı |

---

## Tamamlanan İşler (13f937cb)

### Auth akışı (kritik düzeltme)
- `GET /healthz` loopback isteklerde `admin_token` döndürüyor
- `probeRuntimeHealth()` bu token'ı `SidecarHealth.adminToken` olarak alıyor
- `AppProviders.tsx:117` → `apiClient.setAdminToken(health.adminToken || "")`
- Sonuç: Tauri olmayan browser/dev modunda da auth çalışıyor

### OnboardingScreen — gerçek ilk kurulum sihirbazı
```
apps/desktop/src/screens/onboarding/OnboardingScreen.tsx
```
- 3 adım: hoş geldin → hesap formu (isim/e-posta/parola) → tamam
- `POST /api/v1/auth/bootstrap-owner` → session token → `signIn()` + `completeOnboarding()`
- Bootstrap sonrası `mark_setup_complete()` çağrılıyor (sonraki `/healthz` setup_complete:true döndürüyor)

### LoginScreen — backend bağlantısı
- Parola alanı eklendi
- `POST /api/v1/auth/login` çağrısı
- 409 + `bootstrap_required` → `/onboarding`'e yönlendirme

### Startup validation
- `main.py:_log_startup_config_warnings()` — LLM/billing/admin-token eksikliği startup logunda

### Billing hata mesajları
- `SettingsScreen.tsx:translateBillingError()` — iyzico teknik kodları → Türkçe mesaj

---

## Kalan İşler — Öncelik Sırasıyla

### P0 — Yayın öncesi mutlaka yapılmalı

#### 1. `getCurrentLocalUser()` boş email bug'u
**Dosya**: `apps/desktop/src/services/api/elyan-service.ts`
**Satır**: ~1889

**Sorun**: `/api/v1/auth/me` admin token ile çağrıldığında (henüz kullanıcı yokken)
`session.email = ""` döner. `getCurrentLocalUser()` bunu `{email: ""}` olarak parse eder,
`!currentUser` kontrolü pas geçer ve `signIn("")` çağrılır → `isAuthenticated: true` empty email ile.

**Düzeltme**: `getCurrentLocalUser()` içinde email boşsa `null` döndür:
```typescript
// apps/desktop/src/services/api/elyan-service.ts ~ satır 1893
const email = String(raw.user.email || "").trim().toLowerCase();
if (!email) return null;    // ← bu satırı ekle
return { email, displayName: String(raw.user.display_name || "").trim() };
```

---

#### 2. Artık olmayan `OnboardingScreen 2.tsx` dosyasını sil
**Dosya**: `apps/desktop/src/screens/onboarding/OnboardingScreen 2.tsx`

Bu dosya hiçbir yerde import edilmiyor, eski bir çalışma kopyası.
Sadece sil, başka bir değişiklik yapma.

---

#### 3. Frontend Vite build'i doğrula
```bash
cd apps/desktop
PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/vite build 2>&1
```
Build hatasız geçmeli. Hata varsa düzelt ve commit et.

---

#### 4. `.env.example`'a eksik değerleri ekle
**Dosya**: `.env.example`

Şu an eksik olan satırlar:
```bash
# Gateway admin token (opsiyonel — yoksa /healthz'de otomatik üretilir)
ELYAN_ADMIN_TOKEN=

# Backend port (varsayılan: 18789)
ELYAN_PORT=18789
```

---

### P1 — Kullanıcı deneyimi için önemli

#### 5. Session token localStorage'a yedekle
**Dosya**: `apps/desktop/src/services/api/client.ts`

**Sorun**: `apiClient.sessionToken` sadece memory'de. Sayfa yenilenince temizlenir.
`elyan_user_session` cookie `httponly:true` olduğu için JS okuyamaz.
Cookie browser'dan gönderilir ama Tauri webview'de cross-port cookie sorunları olabilir.

**Düzeltme**: `setSessionToken()` çağrılınca `localStorage.setItem("elyan_session_token", ...)` yaz,
constructor'da `localStorage.getItem("elyan_session_token")` ile restore et:
```typescript
// ApiClient constructor'una ekle:
constructor(baseUrl = DEFAULT_BASE_URL) {
  this.baseUrl = baseUrl;
  const saved = typeof localStorage !== "undefined"
    ? (localStorage.getItem("elyan_session_token") || "")
    : "";
  if (saved) this.sessionToken = saved;
}

// setSessionToken'ı güncelle:
setSessionToken(sessionToken: string) {
  this.sessionToken = sessionToken.trim();
  if (typeof localStorage !== "undefined") {
    if (this.sessionToken) {
      localStorage.setItem("elyan_session_token", this.sessionToken);
    } else {
      localStorage.removeItem("elyan_session_token");
    }
  }
}

// clearSessionToken'ı güncelle:
clearSessionToken() {
  this.sessionToken = "";
  if (typeof localStorage !== "undefined") {
    localStorage.removeItem("elyan_session_token");
  }
}
```

---

#### 6. Auth endpoint'lerine basit rate limit ekle
**Dosya**: `core/gateway/server.py`

`POST /api/v1/auth/login` ve `POST /api/v1/auth/bootstrap-owner` endpoint'lerine
aynı IP'den 10 dakikada 10 başarısız denemede 429 dön.

Bunu yapmak için server.py başına basit in-memory dict ekle:
```python
import time as _time
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}   # ip → [timestamp, ...]
_RATE_LIMIT_WINDOW = 600   # 10 dakika
_RATE_LIMIT_MAX = 10

def _check_login_rate_limit(ip: str) -> bool:
    """True if allowed, False if rate limited."""
    now = _time.time()
    attempts = _LOGIN_ATTEMPTS.get(ip, [])
    attempts = [t for t in attempts if now - t < _RATE_LIMIT_WINDOW]
    _LOGIN_ATTEMPTS[ip] = attempts
    if len(attempts) >= _RATE_LIMIT_MAX:
        return False
    attempts.append(now)
    _LOGIN_ATTEMPTS[ip] = attempts
    return True
```

`handle_v1_auth_login`'de başarısız denemelerde bu fonksiyonu çağır.

---

#### 7. LLM provider kurulum adımı — OnboardingScreen'e model setup ekle
**Dosya**: `apps/desktop/src/screens/onboarding/OnboardingScreen.tsx`

Şu an onboarding sadece hesap oluşturuyor ama LLM provider yapılandırmıyor.
Hesap oluşturulduktan sonra mevcut 3 adıma 4. adım ekle:

```
Adım 4: "Model ayarla (opsiyonel)"
- GET /api/llm/setup/ollama → çalışıyorsa "Ollama hazır, model: X" göster
- Ollama yoksa "API key gir" formu göster (OPENAI / ANTHROPIC / GROQ)
- POST /api/llm/setup/save-key ile kaydet
- "Atla" butonu olsun — zorunlu değil
```

Mevcut `/api/llm/setup/*` endpoint'leri zaten var (server.py:1856-1862).
`getSystemReadiness()` ve `getProviderDescriptors()` fonksiyonları da zaten var.

---

### P2 — Kararlılık ve temizlik

#### 8. Proses ölünce portun temizlenmesi
**Dosya**: `main.py`

Şu an `SIGTERM` handler yok. Backend crash olunca port 18789 bir süre meşgul kalıyor.
```python
import signal
def _handle_sigterm(sig, frame):
    raise KeyboardInterrupt
signal.signal(signal.SIGTERM, _handle_sigterm)
```
`_run_gateway()` başına ekle.

---

#### 9. React error boundary
**Dosya**: `apps/desktop/src/app/App.tsx`

Beklenmedik React hataları beyaz ekran gösteriyor.
`errorElement: <RouteErrorScreen />` zaten routes.tsx'te var ama
genel uygulama seviyesinde de bir error boundary olmalı:

```tsx
// App.tsx'e ekle — RouterProvider'ı ErrorBoundary ile sar
class AppErrorBoundary extends React.Component<...> { ... }
```

---

## Kritik Kurallar (Kodları Bozma)

### Python

1. **SQLAlchemy 2.0** — Raw SQL her zaman `text()` ile ve `:named_param` sözdizimi:
   ```python
   from sqlalchemy import text
   conn.execute(text("SELECT * FROM t WHERE id = :id"), {"id": val})
   ```
   `?` placeholder KULLANMA — çalışmaz.

2. **DB tablolar** — `core/persistence/runtime_db.py`'de `LOCAL_METADATA` ile tanımlı.
   Yeni tablo ekleyeceksen `LOCAL_METADATA` altına `Table(...)` tanımla,
   `create_all()` otomatik yaratır. Alembic yok.

3. **Auth middleware** — `_require_user_session()` hem `X-Elyan-Session-Token` header
   hem `elyan_user_session` cookie hem de `X-Elyan-Admin-Token` kabul eder.
   Admin token için `_is_loopback_request(request)` zorunlu.

4. **Workspace intelligence loop** — `_finalize_turn()` sonunda `record_task_outcome()` çağrılıyor.
   Bu akışı bozma.

5. **`mark_setup_complete()`** — Bootstrap sonrası çağrılmalı.
   `from cli.onboard import mark_setup_complete` şeklinde import edilir.

### TypeScript / React

6. **`apiClient`** — `apps/desktop/src/services/api/client.ts`'den import edilir.
   `apiClient.setAdminToken()` AppProviders'da `/healthz` sonrası set edilir.
   `apiClient.setSessionToken()` login/bootstrap sonrası set edilir.

7. **`useUiStore`** — `onboardingComplete`, `isAuthenticated`, `authenticatedEmail` persist edilir (Zustand + localStorage).
   `signIn(email)` → `isAuthenticated: true` + `authenticatedEmail: email`
   `completeOnboarding()` → `onboardingComplete: true`

8. **Routing guard sırası** — `routes.tsx`:
   - `onboardingComplete: false` → `/onboarding`
   - `onboardingComplete: true` + `isAuthenticated: false` → `/login`
   - `onboardingComplete: true` + `isAuthenticated: true` → `/home`
   Bu sıralamayı değiştirme.

9. **React import** — JSX için React import gerekmez (yeni JSX transform).
   Tip için: `import { type ReactNode } from "react"` kullan, `React.ReactNode` değil.

10. **Tailwind CSS** — `var(--text-primary)`, `var(--bg-surface)`, `var(--border-subtle)` gibi CSS değişkenler kullanılıyor.
    Yeni renkler için bu değişkenleri kullan, hardcoded hex/rgb yazma.

---

## Test Protokolü

Her P0 değişikliği sonrasında:

```bash
# 1. Python syntax check
.venv/bin/python -c "import ast; ast.parse(open('core/gateway/server.py').read()); print('OK')"

# 2. TypeScript check
cd apps/desktop && PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/tsc --noEmit

# 3. Backend başlat
.venv/bin/python main.py start --port 18789 &
sleep 6

# 4. /healthz admin_token döndürüyor mu?
curl -s http://127.0.0.1:18789/healthz | python3 -m json.tool | grep admin_token

# 5. Auth akışı — login endpoint çalışıyor mu?
curl -s -X POST http://127.0.0.1:18789/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"x@x.com","password":"wrong"}' | python3 -m json.tool

# 6. Frontend build
cd apps/desktop && PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/vite build 2>&1 | tail -10
```

---

## Commit Stili

```bash
git add <sadece değiştirilen dosyalar>
git commit -m "$(cat <<'EOF'
Kısa açıklama (ne değişti, neden)

- Madde 1
- Madde 2

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

Her P0 maddesi ayrı commit. P1/P2 gruplandırılabilir.

---

## Mevcut Çevre Durumu

- Backend v20.1.0 çalışıyor (port 18789), commit `13f937cb`
- DB'de zaten bir kullanıcı var (bootstrap tamamlanmış)
- TypeScript build `tsc --noEmit` sıfır hata
- `venv` Python 3.11.15 at `.venv/`
