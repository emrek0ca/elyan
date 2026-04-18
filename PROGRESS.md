# Elyan — Aktif Çalışma Brifing

> Bu dosyayı her çalışmaya başlamadan önce oku.
> Nereden kaldığını anla, öncelik sırasına göre devam et.

**Son Güncelleme**: 2026-04-13
**Aktif Branch**: `main` (ya da `codex/cowork-desktop-platform`)
**Strateji**: Faza A (Türkiye KOBİ) → Faza B (Ambient Global)

---

## Proje Özeti

**Elyan**, macOS masaüstü için local-first AI operatör runtime'ı.

- **Backend**: Python 3.11+, aiohttp async, SQLite WAL, port 18789
- **Frontend**: React 18 + TypeScript + Vite + Tauri
- **DB**: `~/.elyan/runtime.db` — `LOCAL_METADATA.create_all()` otomatik
- **venv**: `.venv/bin/python`

---

## Nasıl Çalıştırılır

```bash
# Backend
.venv/bin/python main.py start --port 18789

# Frontend (geliştirme)
cd apps/desktop
PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/vite dev

# TypeScript kontrol
cd apps/desktop
PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/tsc --noEmit
```

---

## Mimari — Kilit Dosyalar

| Dosya | Rol |
|-------|-----|
| `main.py` | Backend entry point, `_run_gateway()` |
| `core/gateway/server.py` | HTTP endpoint'leri, auth middleware (10K satır — dikkatli) |
| `core/agent.py` | Ana ajan, `_finalize_turn()` learning loop (14K satır — dikkatli) |
| `core/pipeline.py` | StageContext, LLM prompt assembly |
| `core/workspace/intelligence.py` | Workspace learning engine |
| `core/personal_context_engine.py` | OS context (AppleScript, 30s polling) |
| `core/persistence/runtime_db.py` | SQLite DB, tüm tablolar burada |
| `core/billing/iyzico_provider.py` | Iyzico payment provider |
| `apps/desktop/src/app/providers/AppProviders.tsx` | Frontend auth hydration |
| `apps/desktop/src/app/routes.tsx` | Routing guard'ları |
| `apps/desktop/src/services/api/client.ts` | apiClient — tüm HTTP çağrıları |

---

## P0 — Yayın Öncesi Kritik (Doğrulandı)

### 1. `getCurrentLocalUser()` Boş Email Bug'u ✓

**Dosya**: `apps/desktop/src/services/api/elyan-service.ts` ~satır 1889

**Sorun**: `/api/v1/auth/me` admin token ile çağrıldığında (henüz kullanıcı yokken)
`session.email = ""` dönüyor. `getCurrentLocalUser()` bunu `{email: ""}` olarak parse ediyor,
`signIn("")` çağrılıyor → `isAuthenticated: true` ama email boş.

**Düzeltme** (tek satır ekle):
```typescript
const email = String(raw.user.email || "").trim().toLowerCase();
if (!email) return null;    // ← BU SATIRI EKLE
return { email, displayName: String(raw.user.display_name || "").trim() };
```

**Durum**: Guard mevcut. Boş email geldiğinde `null` dönüyor.

---

### 2. Eski Dosyayı Sil ✓

**Dosya**: `apps/desktop/src/screens/onboarding/OnboardingScreen 2.tsx`

**Durum**: Dosya repo yüzeyinde yok.

---

### 3. Vite Build Doğrulama ✓

```bash
cd apps/desktop
PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/vite build 2>&1
```

**Durum**: `PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/vite build` başarılı.

---

### 4. `.env.example` Güncellemesi ✓

**Dosya**: `.env.example`

**Durum**: Gerekli env anahtarları mevcut:
```bash
# Gateway admin token (opsiyonel — yoksa /healthz'de otomatik üretilir)
ELYAN_ADMIN_TOKEN=

# Backend port (varsayılan: 18789)
ELYAN_PORT=18789
```

---

## P1 — Kullanıcı Deneyimi (Aktif Yüzey)

### 5. Session Token localStorage Yedekleme

**Dosya**: `apps/desktop/src/services/api/client.ts`

**Durum**: Uygulandı. `ApiClient` localStorage üzerinden session token restore/persist ediyor.

```typescript
// Constructor'a ekle:
constructor(baseUrl = DEFAULT_BASE_URL) {
  this.baseUrl = baseUrl;
  const saved = typeof localStorage !== "undefined"
    ? (localStorage.getItem("elyan_session_token") || "")
    : "";
  if (saved) this.sessionToken = saved;
}

// setSessionToken güncelle:
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
```

---

### 6. Auth Rate Limit Aktifleştirme

**Dosya**: `core/gateway/server.py`

**Durum**: Uygulandı. Login ve owner bootstrap endpoint'leri IP bazlı auth failure rate limit kullanıyor.

```python
import time as _time
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_RATE_LIMIT_WINDOW = 600   # 10 dakika
_RATE_LIMIT_MAX = 10

def _check_login_rate_limit(ip: str) -> bool:
    """True = izin ver, False = rate limited."""
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

`handle_v1_auth_login` başına ekle, başarısız denemelerde çağır.

---

### 7. OnboardingScreen'e LLM Kurulum Adımı

**Dosya**: `apps/desktop/src/screens/onboarding/OnboardingScreen.tsx`

**Durum**: Uygulandı.

Mevcut onboarding akışında ayrı bir `model` adımı var:
- Ollama hazırsa local model durumu gösteriliyor
- Ollama görünmüyorsa `openai` / `anthropic` / `groq` için API key formu açılıyor
- `saveProviderKey()` ile `/api/llm/setup/save-key` çağrılıyor
- "Atla" ve "Tekrar kontrol et" aksiyonları mevcut

İlgili yüzeyler:
- `apps/desktop/src/screens/onboarding/OnboardingScreen.tsx`
- `apps/desktop/src/services/api/elyan-service.ts`
- `core/gateway/server.py` (`/api/llm/setup/*`)

Not: UX daha ileri taşınacaksa bir sonraki adım, onboarding içinden önerilen Ollama modelini pull etme akışını da doğrudan sunmak olabilir.

---

## Hazırlık Notları

- Voice startup yolunda `LocalSTT.transcribe was never awaited` uyarısı giderildi.
- Hedefli doğrulama: `tests/unit/test_local_stt.py`, `tests/voice/test_voice_modules.py`
- Runtime şu an kalkıyor; ancak tam local LLM deneyimi için `ollama pull llama3.2:3b` hâlâ gerekli.

---

## P2 — Güvenlik (Sprint 1)

### 8. WebSocket Token URL'den Kaldır

**Dosya**: `apps/desktop/src/services/websocket/runtime-socket.ts:123`

```typescript
// YASAK — browser history'ye düşer:
socketUrl.searchParams.set("token", token.trim());

// DOĞRU: bağlantı kurulduktan sonra ilk message'da gönder
socket.onopen = () => {
  socket.send(JSON.stringify({ type: "auth", token: token.trim() }));
};
```

### 9. Webhook Signature — hmac.compare_digest

**Dosya**: `core/billing/iyzico_provider.py:455`

```python
import hmac
# Mevcut:
if computed_signature == received_signature:  # TIMING ATTACK

# Düzeltme:
if hmac.compare_digest(computed_signature, received_signature):
    ...
```

### 10. Query String Admin Auth Kaldır

**Dosya**: `core/gateway/server.py:1704`

```python
# Kaldır:
or query.get("token", "")
or query.get("admin_token", "")
```

Token sadece header üzerinden gelmeli.

---

## P3 — Türkiye Connector Altyapısı (Faza A)

### 11. Connector Altyapısı Kur

**Dizin**: `integrations/turkey/`

```
integrations/turkey/
├── __init__.py
├── base.py          # ConnectorBase abstract class
├── e_fatura.py      # GİB e-Fatura connector
├── e_arsiv.py       # e-Arşiv connector
├── logo.py          # Logo muhasebe connector
├── netsis.py        # Netsis connector
├── sgk.py           # SGK connector
└── tests/
    ├── test_e_fatura.py
    └── test_logo.py
```

Her connector şu interface'i implement eder:
```python
class ConnectorBase(ABC):
    @abstractmethod
    def health_check(self) -> bool: ...

    @abstractmethod
    def test_credentials(self) -> bool: ...

    @abstractmethod
    def get_name(self) -> str: ...
```

### 12. Decision Fabric — Karar Hafızası

**Dosya**: `core/decision_fabric.py` (yeni)

Her kritik kararla birlikte bağlamı kaydet:
```python
@dataclass
class Decision:
    id: str
    summary: str          # "Tedarikçi X sözleşme yenilenmedi"
    context: str          # "Q3 fiyat artışı + 3 kargo gecikmesi"
    actor_id: str
    workspace_id: str
    timestamp: str
    related_event_ids: list[str]

class DecisionFabric:
    def record(self, decision: Decision) -> str: ...
    def search(self, query: str, workspace_id: str) -> list[Decision]: ...
```

---

## P4 — Ambient Engine Temeli (Faza B Hazırlığı)

> Bu katmanı şimdi tasarla ama aktive etme. Feature flag ile kapalı gelecek.

### 13. Pattern Engine İskeleti

**Dosya**: `core/ambient/pattern_engine.py` (yeni, feature flag ile kapalı)

```python
@dataclass
class Pattern:
    id: str
    description: str      # "Her Pazartesi 09:00'da rapor hazırlama"
    frequency: int        # Kaç kez gözlemlendi
    confidence: float     # 0.0 - 1.0
    trigger_conditions: dict

class PatternEngine:
    """
    Kullanıcı davranışını izler, tekrarlayan işleri tespit eder.

    ŞIMDI: veri topla, öğren
    FAZA B: proaktif öner
    """

    def record_activity(self, event: dict) -> None: ...

    def detect_patterns(self, window_days: int = 30) -> list[Pattern]: ...

    def suggest_automation(self, pattern: Pattern) -> dict | None:
        """Güven skoru 0.8'den düşükse None döndür."""
        ...
```

---

## Kritik Kurallar (Özet)

### Python
1. SQLAlchemy 2.0 — `text()` + `:named_param` zorunlu, `?` yasak
2. DB tabloları — `core/persistence/runtime_db.py`'de `LOCAL_METADATA` altına
3. Auth — `_require_user_session()` üç yolu var, loopback kontrolü zorunlu
4. Learning loop — `_finalize_turn()` → `record_task_outcome()` bozma
5. Bootstrap — `mark_setup_complete()` sonrasında çağrılmalı

### TypeScript / React
6. `apiClient` — `client.ts`'den import, admin token `/healthz` sonrası set
7. `useUiStore` — `onboardingComplete`, `isAuthenticated`, `authenticatedEmail` persist
8. Routing guard sırası — kesinlikle değiştirme
9. React import — JSX için gerekmiyor, tip için `import { type ReactNode } from "react"`
10. Tailwind — CSS değişkenler kullan: `var(--text-primary)`, `var(--bg-surface)`

---

## Test Protokolü

Her P0 değişikliği sonrasında:

```bash
# 1. Python syntax
.venv/bin/python -c "import ast; ast.parse(open('core/gateway/server.py').read()); print('OK')"

# 2. TypeScript
cd apps/desktop && PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/tsc --noEmit

# 3. Backend + healthz
.venv/bin/python main.py start --port 18789 &
sleep 6
curl -s http://127.0.0.1:18789/healthz | python3 -m json.tool | grep admin_token

# 4. Auth endpoint
curl -s -X POST http://127.0.0.1:18789/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"x@x.com","password":"wrong"}' | python3 -m json.tool

# 5. Frontend build
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

## Mevcut Çevre

- Backend v20.1.0, commit `13f937cb`
- DB'de zaten kullanıcı var (bootstrap tamamlanmış)
- TypeScript `tsc --noEmit` sıfır hata
- venv Python 3.11.x `.venv/`
