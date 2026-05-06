# ROADMAP.md — Elyan Stratejik Yol Haritası

**Son Güncelleme**: 2026-04-18
**Strateji**: A ile Kazan → B ile Güçlen → C ile Dünyaya Aç
**Aktif Faz**: Faza A (Türkiye KOBİ) + Faza B altyapı hazırlığı

---

## STRATEJİK YÖNELİM

### Vizyon: Kişisel Operatör Platform

Elyan, tek bir kişisel AI operatör platformu içinden şunları yapabilecek:
- **Otonom kodlama**: Codebase analizi, feature planlama, implementasyon, audit
- **Sesli kontrol**: J.A.R.V.I.S. gibi sesli komutlarla browser, sistem, iş akışı kontrolü
- **Çoklu kanal**: Telegram, Discord, Web Chat, Voice, CLI — tek pipeline
- **Akıllı model seçimi**: Claude, Gemini, GPT — göreve göre otomatik routing
- **Sandbox execution**: Docker izole ortamda güvenli otonom çalışma
- **Google Cloud entegrasyon**: BigQuery, Calendar, Docs — MCP standardıyla
- **Website analizi**: Scraping, SEO audit, responsive rebuild
- **Doküman üretimi**: PowerPoint, Excel, Word otomatik oluşturma
- **Türkiye operasyonları**: e-Fatura, Logo/Netsis, SGK, KEP — yerel derinlik

### Neden Üç Faz?

Piyasadaki büyük oyuncular (Anthropic Claude Code, OpenAI Codex, Google Jules) ya sadece kodlama ya sadece sohbet yapıyor. Hiçbiri:
- Sesle kontrol edilemiyor
- Türkiye'ye özgü iş süreçlerini bilmiyor
- Proaktif davranmıyor (hep reactif)
- Tek bir platformda her şeyi birleştirmiyor

Elyan üç aşamada farklılaşır:

**Faza A — Türkiye KOBİ Operatörü (0-6 Ay)**
- Yabancı şirketlerin asla değmeyeceği derinlik: e-Fatura, Logo/Netsis, SGK, KEP
- Iyzico zaten entegre → ilk gelir buradan
- KVKK uyumlu by design — veri yerinden çıkmıyor
- Gerçek müşteri + gerçek kullanım verisi = sonraki fazların yakıtı

**Faza B — Enterprise Coding Agent + Voice + Multi-Channel (6-12 Ay)**
- Otonom yazılım geliştirme: Code Scout → Planner → Writer → Auditor pipeline'ı
- Kişisel sesli asistan: "Hey Elyan" ile browser kontrolü, görev yönetimi
- Çoklu giriş noktası: Web Chat UI + Discord + gelişmiş Telegram
- Plugin mimarisi: her yetenek bağımsız skill plugin
- Docker sandbox: güvenli otonom execution

**Faza C — Ambient/Proaktif Global Ajan + Cloud (12-24 Ay)**
- Reaktif → Proaktif dönüşüm: dünyada kimse ciddiye almıyor
- Google Cloud entegrasyon: BigQuery, Calendar, Docs, Sheets
- MCP standardı: external agent/tool interop
- Pattern engine: A+B fazından toplanan veriyle eğitilmiş
- Global çıkış: Türkiye'de kanıtlanmış ürün

---

## FAZA A — TÜRKİYE KOBİ OPERATÖRÜ (0-6 Ay)

### A-1: Türkiye Connector Paketi (Ay 1-3)
**Hedef**: Türk iş dünyasının günlük acılarını çözen connector'lar

| Connector | Açıklama | Öncelik |
|-----------|----------|---------|
| e-Fatura | GİB entegrasyonu, fatura oluştur/gönder/arşivle | P0 |
| e-Arşiv | e-Arşiv fatura portalı | P0 |
| Iyzico (mevcut) | Ödeme al, abonelik yönet | ✓ |
| Logo | Logo GO/Tiger muhasebe entegrasyonu | P1 |
| Netsis | Netsis Wings/Standard entegrasyon | P1 |
| Luca | Luca muhasebe connector | P1 |
| e-Devlet | Belge sorgulama, vergi borcu, sicil | P2 |
| SGK | Bildirim takibi, borç sorgulama | P2 |
| KEP | Kayıtlı Elektronik Posta yönetimi | P2 |

**Teknik gereksinim**:
- Her connector `integrations/turkey/` altında kendi paketi
- `ConnectorBase` abstract class'tan türetilmeli
- Her connector: bağlantı testi, health check, retry logic
- Tüm çağrılar audit log'a düşmeli
- KVKK: kişisel veri işlenmeden önce consent kaydı

### A-2: Türkçe Dil ve Kültür Katmanı (Ay 1-2)
- Tüm UI metinleri Türkçe-first (mevcut bazıları İngilizce)
- Tarih formatı: DD.MM.YYYY (GİB standardı)
- Para birimi: TRY öncelikli
- İş yazışması şablonları: Türk iş kültürüne uygun
- Hata mesajları Türkçe (mevcut `translateBillingError` genişletilmeli)

### A-3: KOBİ Operatör Senaryoları (Ay 2-4)
Tek komutla çalışan, gerçek KOBİ acılarını çözen akışlar:

```
"Bu ayın KDV özetini çıkar"
→ Muhasebe yazılımından veri çek
→ GİB formatına dönüştür
→ Taslak hazırla, göster, onayla, gönder

"Tedarikçi faturalarını işle"
→ e-posta eklerini tara
→ e-Fatura/PDF oku, muhasebe yazılımına kaydet
→ ödeme planını takvime ekle

"Aylık raporu hazırla"
→ Muhasebe verisi + banka ekstreleri + müşteri listesi
→ Şablona dök, PDF oluştur, yetkililere gönder
```

### A-4: Decision Fabric — Karar Hafızası (Ay 3-5)
Elyan'ın en kritik farklılaştırıcılarından biri: sadece **ne** yaptığını değil **neden** yaptığını hatırlamak.

```python
{
  "karar": "Tedarikçi X sözleşme yenilenmedi",
  "bağlam": "Q3 fiyat artışı + 3 kargo gecikmesi",
  "onaylayan": "kullanıcı",
  "tarih": "2026-03-14",
  "workspace_id": "...",
  "referans_event_ids": [...]
}
```

Arayüz: "Neden bu tedarikçiyle çalışmıyoruz?" → Elyan cevaplar.

### A-5: Türkiye İlk Müşteri Edinimi (Ay 2-6)
- 10 pilot KOBİ (muhasebe yoğun sektörler: inşaat, tekstil, ithalat-ihracat)
- Onboarding: 15 dakikada çalışan sistem
- Ölçüm: günlük aktif kullanım, zaman tasarrufu, hata azalması
- Feedback döngüsü: 2 haftada bir kullanıcı görüşmesi

---

## FAZA B — ENTERPRISE CODING AGENT + VOICE + MULTI-CHANNEL (6-12 Ay)

### B-1: Sub-Agent Orkestrasyon Sistemi (Ay 5-7)
Enterprise-grade otonom kodlama yeteneği.

```
Kullanıcı İsteği → DevAgent Orchestrator
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
     Code Scout    Feature       Code Writer
   (analiz et)    Planner        (implement et)
                 (planla)              │
                                      ▼
                                Code Auditor
                               (review et)
```

**Sub-Agent'lar:**

| Agent | Sorumluluk | Dosya |
|-------|-----------|-------|
| Orchestrator | Task decomposition, sub-agent dispatch | `core/agents/orchestrator.py` |
| Code Scout | Codebase analizi, dosya keşfi, bağımlılık haritası | `core/agents/code_scout.py` |
| Feature Planner | Implementation plan, ADR yazma | `core/agents/feature_planner.py` |
| Code Writer | Kod + test yazma, refactoring | `core/agents/code_writer.py` |
| Code Auditor | Review, güvenlik, performans analizi | `core/agents/code_auditor.py` |

**İletişim**: AgentMessageBus singleton üzerinden, doğrudan bellek paylaşımı yok.

**Orkestrasyon Akışı**: INTAKE → SCOUT → PLAN → EXECUTE → AUDIT → VERIFY → DELIVER

### B-2: Skill Plugin Mimarisi (Ay 5-6)

Her yetenek bağımsız bir plugin olarak tanımlanır:

| Plugin | Açıklama | Sandbox |
|--------|----------|---------|
| Web Browser | Playwright headless browsing, search, scrape | ✓ |
| Semantic Search | Vector-based codebase/document search | ✗ |
| Terminal Session | Shell command execution ve interaction | ✓ |
| Office Generator | PPTX, XLSX, DOCX oluşturma (python-pptx, openpyxl) | ✗ |
| File Editor | Dosya okuma/yazma/düzenleme | ✓ |
| Python Notebook | Jupyter notebook cell execution | ✓ |
| Site Analyzer | Website scrape, SEO audit, rebuild plan | ✓ |

**Plugin Interface:**
```python
class SkillPlugin(ABC):
    def get_manifest(self) -> PluginManifest: ...
    async def execute(self, context: dict) -> dict: ...
    def health_check(self) -> bool: ...
```

### B-3: Docker Sandbox Execution (Ay 6-7)

Otonom tool execution güvenli izolasyon altında çalışır:

```python
class SandboxRuntime:
    """Isolated Docker-based execution environment."""
    async def execute(self, command: str, timeout: int = 60) -> ExecutionResult: ...
    async def write_file(self, path: str, content: str) -> None: ...
    async def run_notebook(self, cells: list[str]) -> list[dict]: ...
```

**Güvenlik kuralları:**
- `--network=none` varsayılan (web_browser skill için whitelist)
- Host dosya sistemi mount YASAK (read-only project mount only)
- CPU: 2 core, Memory: 2GB limit
- Timeout: 60s default, 300s max
- Human-in-the-loop: agent takıldığında kullanıcıdan yardım isteyebilir

### B-4: Voice Assistant — JARVIS Modu (Ay 7-9, opt-in)

```
Mikrofon → Wake Word ("Hey Elyan") → STT (Whisper) → Intent → Execute → TTS → Hoparlör
```

Bu hat varsayılan boot akışında açık değildir. Yalnızca `ELYAN_ENABLE_WAKE_WORD=1` ile etkinleştirilir.

| Bileşen | Teknoloji | Dosya |
|---------|-----------|-------|
| Wake Word | Porcupine / OpenWakeWord | `core/voice/wake_word.py` |
| STT | faster-whisper (local) | `core/voice/local_stt.py` |
| TTS | Piper (local) | `core/voice/local_tts.py` |
| Browser Control | Playwright | `core/voice/browser_controller.py` |
| Pipeline | Intent routing + execution | `core/voice/pipeline.py` |

**Sesli komut örnekleri:**
```
"Hey Elyan, Google'da Python async ara"
"Hey Elyan, YouTube'u aç"
"Hey Elyan, bu projeye login sayfası ekle"
"Hey Elyan, bu ayın e-faturalarını kontrol et"
"Hey Elyan, sunumu hazırla"
```

**Güvenlik:**
- Wake word olmadan STT aktifleşmez
- Destructive komutlar sesli onay ister
- Voice session timeout: 30s sessizlik → deaktive
- Tüm komutlar audit log'a düşer
- Local-first: ses verisi buluta gönderilmez

### B-5: Multi-Channel Gateway (Ay 7-8)

```
CLI ──────┐
Telegram ─┤
Discord ──┤──► Gateway Router ──► Agent Core ──► Response
Web Chat ─┤
Voice ────┘
```

**Web Chat UI** (`ui/web-chat/`):
- **Stack**: Lit Web Components + Tailwind CSS
- **Özellikler**: Real-time streaming, code highlighting, dark/light mode, responsive, embeddable iframe
- **Bağlantı**: WebSocket (token ilk mesajda, URL'de değil)

### B-6: Multi-Model Orkestrasyon (Ay 6-7)

Farklı görev türleri için en uygun model otomatik seçilir:

| Görev Türü | Birincil Model | Fallback |
|-----------|---------------|----------|
| Kodlama | Claude Sonnet 4 | Gemini 2.5 Pro |
| Araştırma | Gemini 2.5 Pro | GPT-4o |
| Yaratıcı | Claude Sonnet 4 | GPT-4o |
| Hızlı aksiyon | Gemini 2.5 Flash | GPT-4o Mini |
| Analiz | Gemini 2.5 Pro | Claude Sonnet 4 |
| Local/Privacy | Ollama (Llama/Qwen) | — |

**ProviderPool**: Failure tracking, exponential backoff, health monitoring.

### B-7: Website Analiz & Rebuild Yeteneği (Ay 8-10)

```
1. URL al → Playwright ile scrape
2. İçerik çıkar: metin, görseller, yapı
3. SEO audit: meta tags, headings, alt texts
4. Performans: Lighthouse skorları
5. Redesign planı oluştur (modern stack öner)
6. Mobile-first responsive build
7. Sonucu sun, feedback al
```

**Stack önerisi**: Astro + Tailwind CSS (statik site) veya Next.js (dinamik).

### B-8: Office Doküman Üretimi (Ay 8-9)

```python
class OfficeGeneratorPlugin(SkillPlugin):
    async def create_presentation(self, slides: list[dict]) -> bytes: ...  # python-pptx
    async def create_spreadsheet(self, sheets: list[dict]) -> bytes: ...  # openpyxl
    async def create_document(self, content: dict) -> bytes: ...           # python-docx
```

Kullanım: "Bu Q3 verileriyle sunum hazırla" → PPTX dosyası üretir.

---

## FAZA C — AMBİENT/PROAKTİF GLOBAL AJAN + CLOUD (12-24 Ay)

### C-1: Pattern Engine (Ay 10-13)
A+B fazından toplanan gerçek kullanım verisi pattern engine'i besler.

```python
class PatternEngine:
    def detect_recurring(self, window_days=30) -> list[Pattern]: ...
    def suggest_automation(self, pattern: Pattern) -> AutomationProposal: ...
    def score_confidence(self, pattern: Pattern) -> float: ...
```

**Kritik kural**: Düşük güvenli öneri asla gösterilmez. Kullanıcı rahatsız edilmemeli.

### C-2: Proaktif Bildirim Sistemi (Ay 12-14)
```
"Yarın 09:00'da Müşteri X sunumu — geçen ay şunları konuşmuştunuz.
 Slaytları o bağlamla güncelledim. Onaylarsanız kaydedeyim."

"Bu tedarikçiyle son iletişimden 3 hafta geçti.
 Takip mesajı hazırladım. Göndermemi ister misiniz?"
```

Bildirim kuralları:
- Gün içinde maksimum 3 proaktif bildirim
- Reddedilen öneri tipi 30 gün sessiz kalır
- Kullanıcı "şimdi değil" diyebilir

### C-3: Google Cloud & MCP Entegrasyon (Ay 12-16)

**Model Context Protocol (MCP) Server:**
```python
class ElyanMCPServer:
    def list_tools(self) -> list[Tool]: ...
    def call_tool(self, name: str, arguments: dict) -> ToolResult: ...
    def list_resources(self) -> list[Resource]: ...
    def read_resource(self, uri: str) -> ResourceContent: ...
```

**Google Cloud Connector'ları:**

| Connector | Açıklama | Dosya |
|-----------|----------|-------|
| BigQuery | SQL sorguları, veri analizi | `integrations/google_cloud/bigquery.py` |
| Spanner | CRUD işlemleri | `integrations/google_cloud/spanner.py` |
| GCS | Dosya okuma/yazma | `integrations/google_cloud/gcs.py` |
| Workspace | Calendar, Docs, Sheets | `integrations/google_cloud/workspace.py` |

**Deployment**: Cloud Run üzerinde MCP server, local Elyan → Cloud Run bridge.

### C-4: Ambient Context Engine (Ay 13-16)
PersonalContextEngine genişletilir:
- Takvim: "1 saat sonra toplantı var, bağlamı hazırlayayım mı?"
- Uygulama değişimi: "Faturalamaya geçtin — devam eden görev var"
- Mesai sonu: "Bugün 3 yarım kalan görev — yarın için sıralayayım mı?"

### C-5: Global Çıkış Hazırlığı (Ay 18-24)
- İngilizce UI (çeviri katmanı, Türkçe core bozulmadan)
- Connector API: üçüncü parti connector marketplace
- Multi-tenant SaaS hazırlığı (hosted version)
- Pricing: global plan + Türkiye özel plan

---

## TEKNİK FAZLAR (Devam Eden)

### Tamamlanan ✓
- Phase 1: Canonical commercial domain (billing types, plan kataloğu)
- Phase 2: Iyzico provider abstraction
- Phase 3: Workspace RBAC + membership + owner bootstrap
- Phase 7 (kısmi): Gateway CSRF enforcement

### Aktif

#### Phase 0 — P0 Taskları (Tamamlandı / Doğrulandı)
1. `getCurrentLocalUser()` boş email guard mevcut
2. `OnboardingScreen 2.tsx` repo yüzeyinden kaldırıldı
3. Vite build doğrulandı
4. `.env.example` güncellemesi mevcut (`ELYAN_ADMIN_TOKEN`, `ELYAN_PORT`)

#### Phase 4 — Admin Control Plane
- Workspace overview
- Subscription management
- Credit ledger UI
- Token pack purchase flow
- Member/role management
- Approval queue
- Connector health dashboard

#### Phase 5 — Learning Fabric
- User memory (mevcut foundation üzerine)
- Workspace intelligence (mevcut temel çalışıyor)
- Global aggregate intelligence
- Privacy classify + consent gate
- Offline eval + shadow/canary promotion

#### Phase 6 — Runtime Credit Enforcement
- LLM/tool usage → commercial ledger bağlantısı
- Calibrated usage estimator
- Soft degrade ordering (included → purchased → degraded)

### Güvenlik Fazı (Paralel)

#### SEC-1: Kritik Güvenlik Düzeltmeleri
1. WebSocket token URL'den çıkar → WS message payload'a taşı
2. `hmac.compare_digest` ile webhook imzası
3. Query string admin auth kaldır (`query.get("token")`)
4. Dosya yükleme MIME whitelist + boyut sınırı
5. Prompt injection firewall → case-insensitive + semantic

#### SEC-2: Auth Güçlendirme
6. Rate limiter'ı auth endpoint'lerine bağla (altyapı mevcut)
7. Session token localStorage → HttpOnly cookie
8. Sign-out: localStorage + WebSocket + in-flight temizlik
9. Path traversal: symlink-safe `resolve()`

#### SEC-3: Sandbox & Altyapı
10. Docker sandbox escape prevention
11. `requirements.txt` exact pin (`==`)
12. SQLite transaction isolation seviyesi
13. Audit log şifrelemesi
14. Voice recording local-only enforcement

---

## YENİ TEKNİK FAZLAR (Faza B/C)

### Phase 8 — Sub-Agent Framework
- DevAgent Orchestrator core
- Code Scout + semantic indexing
- Feature Planner + plan template
- Code Writer + diff-based editing
- Code Auditor + security scanning
- AgentMessageBus genişletme
- Sub-agent task lifecycle management

### Phase 9 — Plugin Architecture
- SkillPlugin base class + manifest schema
- Web Browser plugin (Playwright)
- Semantic Search plugin (vector embeddings)
- Terminal Session plugin
- Office Generator plugin (python-pptx, openpyxl, python-docx)
- File Editor plugin
- Python Notebook plugin (Jupyter kernel)
- Site Analyzer plugin (scrape + SEO + rebuild)
- Plugin hot-load + health check

### Phase 10 — Voice Assistant
- Wake word detection (Porcupine/OpenWakeWord, opt-in)
- Voice pipeline integration
- Browser controller (Playwright)
- Voice-to-intent routing
- TTS response streaming
- Voice session management
- Audio device selection

### Phase 11 — Multi-Channel Gateway Extension
- Web Chat adapter (WebSocket)
- Web Chat UI (Lit + Tailwind)
- Discord rich interactions (slash commands, embeds)
- Channel-agnostic message format
- Per-channel feature flags

### Phase 12 — Docker Sandbox
- Container lifecycle management
- Network isolation policies
- Resource limits (CPU/memory/disk)
- Secure file sharing (host ↔ container)
- Execution timeout enforcement
- Container image management

### Phase 13 — Multi-Model Router
- Task-type classification
- Provider health monitoring
- Cost-aware routing
- Latency budget enforcement
- Model capability indexing
- A/B testing framework

### Phase 14 — Google Cloud & MCP
- MCP server implementation
- BigQuery connector
- Spanner connector
- GCS connector
- Google Workspace connector (Calendar, Docs, Sheets)
- OAuth2 + service account auth
- Cloud Run deployment config

---

## Mühendislik Disiplini

### Preservation-First (Değiştirme Değil, Genişlet)
- Çalışan davranışı önce koru
- Replacement yerine wrapper, adapter, verifier
- Non-trivial değişiklikler feature flag ile
- Planner/router/verifier değişiklikleri shadow mode olmadan aktifleştirme
- Yeni katmanlar kendi modüllerinde yaşar, mevcut pipeline'a hook ile bağlanır

### Test Protokolü
Her değişiklik sonrası:
```bash
# 1. Python syntax
.venv/bin/python -c "import ast; ast.parse(open('core/gateway/server.py').read()); print('OK')"

# 2. TypeScript
cd apps/desktop && PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/tsc --noEmit

# 3. Backend + healthz
elyan launch &
sleep 6
curl -s http://127.0.0.1:18789/healthz | python3 -m json.tool | grep admin_token

# 4. Frontend build
cd apps/desktop && PATH="/opt/homebrew/bin:$PATH" node node_modules/.bin/vite build 2>&1 | tail -10

# 5. Docker sandbox test (Phase 12+)
docker run --rm elyan-sandbox echo "sandbox OK"
```

---

## Açık Riskler

| Risk | Seviye | Mitigation |
|------|--------|------------|
| `core/agent.py` 14.766 satır monolith | YÜKSEK | Dokunmadan çalıştır, sub-agent'lar yeni modüllerde |
| `core/gateway/server.py` 10K satır | YÜKSEK | Web Chat adapter ayrı dosyada |
| WebSocket token URL'de açıkta | KRİTİK | SEC-1'de düzeltiliyor |
| Webhook imzası timing attack | KRİTİK | SEC-1'de düzeltiliyor |
| Rate limiting tanımlandı ama bağlanmamış | ORTA | SEC-2'de tamamlanıyor |
| Stripe route'ları deprecated | ORTA | Iyzico migration devam ediyor |
| Learning fabric design seviyesinde | ORTA | Phase 5'te implemente ediliyor |
| Docker sandbox escape riski | YÜKSEK | SEC-3: network=none, resource limits |
| Voice pipeline privacy riski | YÜKSEK | Local-first enforcement, no cloud STT |
| Multi-model routing maliyet kontrolü | ORTA | Cost-aware routing politikası |
| Sub-agent infinite loop riski | YÜKSEK | Execution budget + timeout + depth limit |
| MCP security (external tool access) | YÜKSEK | Permission scoping + audit trail |

---

## Başarı Metrikleri

### Faza A Hedefleri
- 10 pilot KOBİ aktif kullanıcı
- e-Fatura connector production-ready
- Günlük aktif kullanım > 5 KOBİ
- NPS > 30

### Faza B Hedefleri
- DevAgent 50+ başarılı coding task
- Voice assistant crash rate < %1
- Web Chat UI production-ready
- 3+ model provider aktif routing
- Plugin marketplace 10+ skill

### Faza C Hedefleri
- MCP ile 5+ external tool bağlı
- Google Cloud 3+ connector production-ready
- Pattern engine 100+ pattern tespit
- Proaktif bildirim acceptance rate > %40
- İngilizce UI tam çeviri
