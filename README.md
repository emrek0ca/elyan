# Elyan — Sessiz Ortak. Sormadan Fark Eder, İzin Almadan Dokunmaz.

Elyan bir chatbot değil. Masaüstünde yaşayan, neyin ortasında olduğunu bilen, onayın olmadan kritik şeylere dokunmayan ve zamanla seni tanıyan bir **iş yürütme ajanı**dır.

`elyan.dev` hosted control-plane ve public site yüzeyidir. Local runtime ana üründür; hosted katman sadece hesap, billing, entitlement, usage ve notifications için vardır. Hosted web workspace bu repo içinde `apps/web` altındadır.

Canlı VPS yüzeyi ayrı bir source of truth olarak çalışır: deploy root `/srv/elyan`, current symlink `/srv/elyan/current`, systemd service `elyan`, bind `127.0.0.1:3010` ve public domain `api.elyan.dev`. Yeni deploy sistemi icat edilmez; mevcut symlink + systemd + nginx düzeni korunur.

## Strateji: A ile Kazan, B ile Büyü

### Faza A — Türkiye KOBİ Operatörü (0-12 ay)
Türk KOBİ'lerinin günlük iş süreçlerini otomatikleştiren, hiçbir yabancı şirketin değmeyeceği derinlikte yerel entegrasyonlar sunan operatör runtime.

**Ne yapıyor:**
- e-Fatura / e-Arşiv / e-İrsaliye akışları
- Logo, Netsis, Luca muhasebe yazılımı entegrasyonu
- KDV beyannamesi taslağı, SGK bildirim takibi
- KEP yönetimi, e-Devlet işlemleri
- Iyzico ile Elyan Credits bazlı ödeme altyapısı
- KVKK uyumlu — veri hiç yerinden çıkmıyor

### Faza B — Ambient/Proaktif Ajan (12-24 ay)
Reaktif değil, proaktif. Sen sormadan, Elyan fark eder.

**Ne yapar:**
- "Yarın 9'da sunum var — ilgili dosyaları hazırladım, onaylarsanız kaydedeyim."
- "Bu tedarikçiyle son iletişimden 3 hafta geçti — takip mesajı hazır."
- "Her Pazartesi aynı raporu 45 dk harcayarak yapıyorsun — otomasyona alalım mı?"

Bu katman A fazından toplanan gerçek kullanım verisiyle eğitilir ve global çıkışın temelidir.

---

## Tech Stack

| Katman | Teknoloji |
|--------|-----------|
| Backend | Python 3.11+, aiohttp async, port 18789 |
| Database | Local runtime: SQLite WAL + SQLAlchemy 2.0 (`~/.elyan/runtime.db`) |
| Hosted Control Plane | PostgreSQL 16 on VPS (`/srv/elyan/.env`) |
| Frontend | React 18 + TypeScript + Vite + Tauri (macOS desktop) |
| Payment | Iyzico → Elyan Credits |
| Auth | Session token + CSRF enforcement |
| venv | `.venv/bin/python` (Python 3.11.x) |

## Install

### Homebrew

GitHub'daki güncel sürümü doğrudan kur:

```bash
brew install --formula https://raw.githubusercontent.com/emrek0ca/elyan/main/Formula/elyan.rb
```

### npm

Node tabanlı bootstrap wrapper ile güncel sürümü GitHub'dan kur:

```bash
npm install -g github:emrek0ca/elyan
```

Bu komut `elyan` binary'sini açar, ilk çalıştırmada gerekli Python virtualenv'ini `~/.elyan/npm-runtime/venv` altında kurar.

### İlk Çalıştırma

```bash
elyan launch
elyan desktop
```

Opsiyonel local model lane:

```bash
brew install ollama
ollama serve
ollama pull llama3.2:3b
```

---

## Mevcut Durum (Nisan 2026)

### Tamamlanan
- Workspace-first billing foundation (Elyan Credits, plan kataloğu)
- Iyzico payment provider abstraction
- Workspace RBAC + membership + seat enforcement
- Explicit owner bootstrap (login-time auto bootstrap kaldırıldı)
- CSRF enforcement gateway seviyesinde
- Mobile intake: WhatsApp / Telegram / iMessage inbound capture
- Desktop operator shell: onboarding, home, billing, settings ekranları
- Learning fabric: workspace intelligence loop, personal context engine

### P0 — Yayın Öncesi Kritik
1. `getCurrentLocalUser()` boş email bug'u düzeltildi
2. Eski `OnboardingScreen 2.tsx` kopyası temizlendi
3. Frontend Vite build doğrulandı
4. `.env.example` gerekli gateway anahtarlarını içeriyor

---

## Key Docs

| Döküman | İçerik |
|---------|--------|
| [ROADMAP.md](./ROADMAP.md) | Stratejik faz planı (A→B) + teknik fazlar |
| [AGENTS.md](./AGENTS.md) | Mimari kurallar + Codex direktifleri |
| [PROGRESS.md](./PROGRESS.md) | Aktif görevler, P0/P1/P2 öncelik listesi |
| [SKILLS.md](./SKILLS.md) | Session tracking + implementasyon playbook |
| [docs/ELYAN_V2_ARCHITECTURE.md](./docs/ELYAN_V2_ARCHITECTURE.md) | 7 katmanlı mimari detayı |

---

## Mimari Özet

```
SEN
 │
 ▼
ELYAN (macOS masaüstü, local-first)
 │
 ├── OS Bağlamı: Açık uygulama, pano, takvim, dosyalar
 ├── Workspace Hafızası: Karar izi, görev geçmişi, öğrenme
 ├── Tool Runtime: Terminal, tarayıcı, dosya sistemi, API'ler
 ├── Türkiye Connectors: e-Fatura, Logo/Netsis, SGK, KEP
 ├── Onay Kapısı: Tehlikeli şeylere sormadan dokunmaz
 └── Ambient Engine: Pattern izle → Proaktif öner (Faza B)
```

---

## Ticari Akış

```
Kullanıcı / Workspace
  → Billing API
  → IyzicoProvider
  → Webhook → Billing Events
  → Entitlement Engine + Credit Ledger
  → Runtime Policy Gate
  → LLM / Connector / Workflow Execution
```

---

## Geliştirme Kuralları (Özet)

> Detay: AGENTS.md

1. SQLAlchemy 2.0 — raw SQL her zaman `text()` + `:named_param`
2. Routing guard sırası değiştirme: onboarding → login → home
3. `_finalize_turn()` → `record_task_outcome()` akışını bozma
4. Yeni feature → önce test yaz, sonra implement et
5. Var olmayan fonksiyon çağırma, stub bırakma
6. Çalışan kodu "refactor" bahanesiyle kırma

---

## Private Alpha Bootstrap

Bu sürüm için hedef akış tek ve nettir:

1. Ortamı hazırla
```bash
cp .env.example .env
```

2. En az bir model hazır et
```bash
brew install ollama
ollama serve
ollama pull llama3.2:3b
```

3. Gateway'i başlat
```bash
elyan launch
elyan health
```

4. Desktop'ı aç ve owner bootstrap tamamla
- bootstrap tamamlanınca `setup_complete: true` görünmeli
- onboarding sırası: provider/model -> channel -> routine -> summary

5. En az bir kanal bağla
- private alpha için minimum hedef kanal: `Telegram`
- gerekli env:
```bash
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

6. Öğrenilen draft'ları gözden geçir ve promote et
```bash
elyan memory drafts --type skills
elyan memory drafts --type routines
elyan skills promote-draft <draft_id> --skill-name <skill_name>
elyan routines promote-draft <draft_id>
```

7. İlk günlük özeti canlı çalıştır
```bash
elyan routines add --text "Her sabah bana Telegram'dan günlük özet gönder"
elyan routines run <routine_id>
```

Private alpha hazır sayılması için minimum kabul kriteri:
- `/healthz` sağlıklı dönüyor
- desktop home ekranında provider/model hazır görünüyor
- en az bir kanal bağlı
- en az bir routine mevcut
- `personal-daily-summary` en az bir kez çalışmış
- restart sonrası routine'ler kaybolmuyor


# Elyan v1.3

Elyan is a local-first personal agent runtime with a separate hosted control plane on elyan.dev.

The real v1 product surface is intentionally small:

- local chat runtime
- local health and readiness
- capability discovery
- dashboard
- CLI
- optional search
- optional MCP
- optional channels
- optional hosted control-plane integration

Everything else is secondary.

## Canonical Local Path

1. Install dependencies:

```bash
npm install
```

2. Prepare local storage and safe environment defaults:

```bash
npm install -g .
elyan setup
```

If the CLI is not linked globally yet:

```bash
node bin/elyan.cjs setup
```

`elyan setup` runs the safe bootstrap path, checks local model/search reachability, and prints the next local-first step without requiring hosted account linking.

3. Start Ollama and pull the recommended local model if setup reports that Ollama is not reachable:

```bash
elyan models setup
```

Cloud keys are optional and should only be set when you intentionally want cloud inference:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GROQ_API_KEY`

4. Run Elyan:

```bash
npm run dev
```

Production-like:

```bash
npm run build
npm run start
```

5. Check health and open the command center:

- `http://localhost:3000/api/healthz`
- `http://localhost:3000/manage`

Wake-word and realtime actuator are opt-in. Enable them only when you explicitly want background audio or screen automation:

```bash
ELYAN_ENABLE_WAKE_WORD=1
ELYAN_ENABLE_REALTIME_ACTUATOR=1
```

## What Is Required

You need one usable model source:

- local Ollama at `OLLAMA_URL`, or
- one cloud provider key

Local-first mode uses local Ollama and local storage. Without a model source, Elyan is not ready.

## CLI

```bash
elyan setup
elyan doctor
elyan doctor --fix
elyan health
elyan status
elyan status --json
elyan capabilities
elyan settings view
elyan open
```

Local operator permissions:

```bash
elyan desktop status
elyan desktop grant .
elyan desktop enable
```

Service mode:

```bash
elyan service install
elyan service start
elyan service status
```

Channel diagnostics:

```bash
elyan channels list
elyan channels doctor
elyan channels setup telegram
elyan channels test telegram
```

MCP diagnostics:

```bash
elyan mcp list
elyan mcp doctor
elyan mcp enable <server>
elyan mcp disable <server>
elyan mcp disable-tool <server> <tool>
```

v1.3 operator runs:

```bash
elyan run --mode research "compare local-first agent runtimes with sources"
elyan run --mode code "inspect this repo and plan a safe patch"
elyan run --mode cowork "plan the next product milestone"
elyan runs list
elyan runs show <runId>
elyan approvals list
elyan approvals approve <approvalId>
elyan approvals reject <approvalId>
```

Operator runs are local-first planning records. Each run records an adaptive reasoning profile (`shallow`, `standard`, or `deep`) so Elyan can stay fast for simple work and slow down for research, code, cowork, and verification-heavy tasks. Runs also track quality gates for the selected mode: research needs sources or an honest unavailable state, code needs repository inspection plus approval-safe verification, and cowork needs inspectable role artifacts. Risky file, terminal, browser, MCP, or automation actions must still pass typed action, policy, approval, audit, and verification before execution.

Hybrid quantum-inspired optimization:

```bash
elyan optimize demo assignment
elyan optimize demo resource-allocation --json
```

The v1.3 optimization capability is TEKNOFEST-oriented decision support, not a separate quantum chatbot. It models assignment and resource-allocation problems, builds a QUBO representation, compares greedy, simulated annealing, and small brute-force QUBO fallback solvers, then returns an auditable JSON plus Markdown decision report. No real quantum hardware is claimed or required.

## Optional Surfaces

### Search

SearXNG is optional. If it is reachable, Elyan uses live retrieval and citations. If it is missing, Elyan stays usable in local-only mode.

### MCP

MCP is optional. Only configure it if you actively use MCP servers.

### Channels

Telegram, WhatsApp Cloud, WhatsApp Baileys, and iMessage/BlueBubbles are optional.

- Telegram uses the official Bot API and supports polling or webhook mode.
- WhatsApp Cloud is the official Meta surface and can incur template-message costs.
- WhatsApp Baileys is local best-effort and unofficial; it is not a guaranteed business channel.
- iMessage requires a local BlueBubbles server on a Mac with iMessage available.

### Hosted Control Plane

The shared VPS control plane is optional and only for shared business/device state:

- accounts
- sessions
- plans
- subscriptions
- entitlements
- hosted usage accounting
- device linking and token rotation
- notifications and ledger entries

Private local runtime state stays local by default.

## Local Operator Safety

The local operator is permissioned computer control, not unrestricted system takeover.

- It is disabled until enabled in runtime settings or through `elyan desktop enable`.
- It can only operate inside configured `allowedRoots`.
- Sensitive paths such as `.env`, SSH keys, cloud credentials, wallets, shell profiles, and system directories are protected by default.
- Write, destructive, and system-critical actions require explicit approval policy levels.
- Evidence is written under `ELYAN_STORAGE_DIR/evidence`.

## Environment

Base local runtime:

- `ELYAN_STORAGE_DIR=storage`
- `ELYAN_RUNTIME_SETTINGS_PATH=storage/runtime/settings.json`
- `OLLAMA_URL=http://127.0.0.1:11434`
- `SEARXNG_URL=http://localhost:8080`

Optional cloud providers:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GROQ_API_KEY`

Optional hosted control plane:

- `DATABASE_URL`
- `NEXTAUTH_URL`
- `NEXTAUTH_SECRET`
- `IYZICO_API_KEY`
- `IYZICO_SECRET_KEY`
- `IYZICO_MERCHANT_ID`

Optional MCP:

- `ELYAN_MCP_SERVERS`
- `ELYAN_DISABLED_MCP_SERVERS`
- `ELYAN_DISABLED_MCP_TOOLS`

## Commands

```bash
npm run lint
npm run test
npm run build
npm run release:check
```

## Security

- Public-facing hosted and control-plane routes use hardened HTTP headers and no-store defaults on private surfaces.
- Do not commit secrets, tokens, or private credentials to the repository.
- Do not grant broad local operator roots unless you are comfortable with that machine scope.
- Report vulnerabilities privately through GitHub Security Advisories or `SECURITY` before public disclosure.

## Product Boundary

Elyan v1.3 is not:

- a Docker-first product
- a fake hosted everything-app
- an unrestricted computer-control bot
- a replacement for explicit channel credentials and platform rules

Elyan v1.3 is a directly runnable local-first runtime with guided setup, safer release/install surfaces, and a clearer operator workflow. The hosted surface is separate and only adds shared account and billing features when configured.

## License

Elyan is licensed under `AGPL-3.0-or-later`.

If you modify and deploy it as a network service, you must make the corresponding source available under the same terms.
