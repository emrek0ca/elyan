# Elyan — Sessiz Ortak. Sormadan Fark Eder, İzin Almadan Dokunmaz.

Elyan bir chatbot değil. Masaüstünde yaşayan, neyin ortasında olduğunu bilen, onayın olmadan kritik şeylere dokunmayan ve zamanla seni tanıyan bir **iş yürütme ajanı**dır.

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
| Database | SQLite WAL + SQLAlchemy 2.0 (`~/.elyan/runtime.db`) |
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
elyan start --port 18789
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
.venv/bin/python main.py start --port 18789
curl -s http://127.0.0.1:18789/healthz
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
