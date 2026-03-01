 / Elyan Bot — Implementation Plan

**Son güncelleme:** 2026-02-26
**Test durumu:** 458 passed, 0 failed (test_office_tools.py hariç)
**Python:** 3.12 | **Venv:** `.venv/`

---

## 1. Projenin Kısa Özeti

macOS'ta çalışan Türkçe/İngilizce kişisel AI asistan botu. Telegram üzerinden veya yerel CLI ile kullanılıyor. Kullanıcıdan gelen metin komutlarını intent parser ile yorumluyor, task engine ile planlıyor, 70+ araçla yürütüyor.

**Ana akış:**
```
User Input
  → PipelineRunner.run(ctx) [6 stage]
  → StageRoute: intent parse, capability routing
  → StageExecute:
      → Direct intent (basit)
      → CDGEngine (orta karmaşıklık, DAG)
      → AgentOrchestrator (yüksek karmaşıklık, multi-agent)
  → StageVerify + StageDeliver
```

---

## 2. Kritik Dosyalar — Hızlı Referans

| Dosya | Ne yapar | Kritik metodlar |
|-------|----------|-----------------|
| `core/agent.py` (4800+ satır) | Ana entry point | `process()`, `_run_direct_intent()`, `_llm_build_project()`, `_execute_tool()` |
| `core/pipeline.py` (954 satır) | 6 aşamalı pipeline | `PipelineRunner.run()`, `StageExecute.run()` |
| `core/pipeline_state.py` | Adımlar arası veri paylaşımı | `store()`, `resolve_placeholders()` |
| `core/multi_agent/orchestrator.py` | Multi-agent orkestrasyon | `manage_flow()` — Industrial Loop |
| `core/multi_agent/specialists.py` | 6 uzman tanımı | `SpecialistRegistry`, workflow chains |
| `core/multi_agent/swarm_consensus.py` | 4 paralel QA persona | `run_tribunal_debate()` |
| `core/cdg_engine.py` | DAG tabanlı görev yürütme | `create_plan()`, `execute()`, QA gates |
| `core/intelligent_planner.py` | LLM görev ayrıştırma | `create_plan()`, `decompose_task()` |
| `core/capability_router.py` | Domain/karmaşıklık analizi | `route()` → `CapabilityPlan` |
| `core/kernel.py` | Servis locator (DI) | `kernel.llm`, `kernel.tools` |

---

## 3. Tamamlanan Çalışmalar (Özet)

- Faz 1–8: Temel sistem, 70+ araç, fuzzy intent (v19.0), stabilite (v19.2)
- Delivery Engine: IDLE→INTAKE→PLAN→EXECUTE→VERIFY→DELIVER
- Multi-Agent: 6 specialist, 3 workflow, SwarmConsensus (4 paralel QA)
- CDG Engine: DAG + QA gates + auto-patch
- Sprint G–L: CI/CD, 10 kanal, CLI, Dashboard
- LLM-Driven Kodlama: `_llm_build_project()` (2-pass code generation)
- Audio Feedback: macOS `afplay` ile başarı/hata sesleri

---

## 4. Sub-Agent & Agent Teams — Yeni Implementasyon Planı

### Motivasyon

Mevcut `AgentOrchestrator` sıralı çalışıyor: lead → builder → ops → qa. Sub-agent'ler izole session'a sahip değil, paralel spawn edilemiyor, birbirleriyle konuşamıyor. Bu plan, Elyan'ın "spawn-and-wait" modelini ve "Agent Teams" koordinasyonunu mevcut mimariye entegre ediyor.

### Mevcut Güçlü Yanlar (Korunacak)
- 6 uzman tanımı + system prompt'ları (`specialists.py`)
- SwarmConsensus paralel QA (`asyncio.gather`)
- CDGEngine DAG + QA gates
- PipelineState placeholder mekanizması
- BudgetTracker token/USD limit kontrolü

### Eksikler (Çözülecek)
1. Sub-agent'ler izole session ile çalışmıyor
2. Non-blocking spawn-and-wait mekanizması yok
3. Sub-agent'ler arası iletişim yok
4. Paylaşımlı task board yok
5. PipelineState global singleton — eşzamanlılık riski
6. Sub-agent tool kapsamı sınırlanmıyor

---

### Faz 1: Sub-Agent Session Altyapısı
**Dosyalar:** `core/sub_agent/session.py`, `core/sub_agent/manager.py`
**Bağımlılık:** Yok (temel modül)

#### 1.1 SubAgentSession — İzole Oturum
```python
@dataclass
class SubAgentSession:
    session_id: str           # agent:<parentId>:subagent:<uuid>
    parent_session_id: str
    specialist_key: str       # "researcher", "builder", "qa" vb.
    task: SubAgentTask        # ne yapacağı
    state: SessionState       # PENDING → RUNNING → COMPLETED → FAILED
    result: Optional[SubAgentResult]
    pipeline_state: PipelineState  # İZOLE — global değil, session'a özel
    allowed_tools: frozenset[str]  # sınırlı tool seti
    created_at: float
    completed_at: Optional[float]
    can_spawn: bool = False   # sub-agent, sub-agent spawn edemez
```

#### 1.2 SubAgentManager — Spawn & Collect
```python
class SubAgentManager:
    async def spawn(self, specialist_key, task, tools=None) -> str:
        """Non-blocking: session oluştur, asyncio.create_task, runId dön."""

    async def spawn_and_wait(self, specialist_key, task, timeout=300) -> SubAgentResult:
        """Blocking: spawn + sonucu bekle."""

    async def spawn_parallel(self, tasks: list[tuple[str, SubAgentTask]]) -> list[SubAgentResult]:
        """Birden fazla sub-agent paralel, asyncio.gather ile bekle."""

    async def get_result(self, run_id: str, timeout=60) -> SubAgentResult:
        """Belirli sub-agent sonucunu al (asyncio.Event tabanlı)."""
```

**Tasarım Kararları:**
- Her sub-agent **kendi PipelineState** instance'ına sahip
- **Derin spawn engeli**: `can_spawn=False` → maliyet patlaması önlenir
- Tool kapsamı specialist bazında: researcher → `{web_search, read_file, summarize}`, builder → `{write_file, run_command, create_directory}` vb.

---

### Faz 2: Sub-Agent Yürütme Motoru
**Dosyalar:** `core/sub_agent/executor.py`
**Bağımlılık:** Faz 1

#### 2.1 SubAgentExecutor — Observe-Act-Verify Döngüsü
```python
class SubAgentExecutor:
    async def run(self, session: SubAgentSession) -> SubAgentResult:
        """
        1. Specialist system prompt yükle
        2. LLM'e task + context gönder
        3. Tool çağrılarını çalıştır (allowed_tools kontrolü)
        4. Observe → Act → Verify döngüsü (max 5 iterasyon)
        5. Sonucu normalize et (Status/Result/Notes)
        """
        for iteration in range(self.max_iterations):
            llm_response = await self._call_llm(session)
            if llm_response.has_tool_calls:
                for call in llm_response.tool_calls:
                    if call.tool not in session.allowed_tools:
                        continue  # izinsiz tool, atla
                    result = await kernel.tools.execute(call.tool, call.params)
                    session.pipeline_state.store(call.tool, result)
            elif llm_response.is_final:
                return self._normalize_result(llm_response, session)
```

#### 2.2 SubAgentResult — Normalize Çıktı
```python
@dataclass
class SubAgentResult:
    status: str          # "success" | "partial" | "failed"
    result: Any          # üretilen çıktı
    notes: list[str]     # açıklama notları
    artifacts: list[str] # dosya yolları
    execution_time_ms: int
    token_usage: dict    # {"prompt": N, "completion": M, "cost_usd": X}
```

---

### Faz 3: Validator Gate Sistemi
**Dosyalar:** `core/sub_agent/validator.py`
**Bağımlılık:** Faz 2

"Boş dosya oluşturma" gibi hataları yakalayan otomatik gate:

```python
class SubAgentValidator:
    GATES = {
        "file_exists":     lambda path: Path(path).exists(),
        "file_not_empty":  lambda path: Path(path).stat().st_size > 0,
        "valid_json":      lambda path: json.loads(Path(path).read_text()),
        "valid_html":      lambda path: "<html" in Path(path).read_text().lower(),
        "has_content":     lambda text: len(text.strip()) > 50,
        "no_placeholder":  lambda text: "TODO" not in text and "{{" not in text,
        "valid_python":    lambda path: compile(Path(path).read_text(), path, "exec"),
    }

    async def validate(self, result: SubAgentResult, gates: list[str]) -> ValidationResult:
        """Başarısız gate varsa: retry flag + hata detayı dön."""

    async def validate_and_retry(self, executor, session, gates, max_retries=2):
        """Validate → fail → hata context'e ekle → tekrar çalıştır."""
```

**Specialist → Gate Eşleştirmesi:**
| Specialist | Otomatik Gate'ler |
|-----------|-------------------|
| builder | file_exists, file_not_empty, valid_python/valid_html |
| researcher | has_content, no_placeholder |
| qa | file_exists, has_content |
| ops | file_exists |

---

### Faz 4: Orchestrator Entegrasyonu
**Dosyalar:** `core/multi_agent/orchestrator.py` (güncelleme)
**Bağımlılık:** Faz 1, 2, 3

#### manage_flow() → Sub-Agent Destekli
Mevcut sıralı çağrılar → bağımlılık DAG'ına göre paralel spawn:

```python
# ÖNCEKI (sıralı):
# Phase 0: lead düşünür → Phase 1: lead planlar → Phase 2: builder yürütür → Phase 3: qa doğrular

# YENİ (paralel mümkün):
async def manage_flow(self, plan, original_input):
    manager = SubAgentManager()

    # Phase 0: Lead analiz + görev kırılımı
    lead_result = await manager.spawn_and_wait("lead", LeadTask(original_input))

    # Phase 1: Bağımsız görevleri paralel spawn
    parallel_tasks = lead_result.independent_tasks
    parallel_results = await manager.spawn_parallel([
        ("researcher", task) for task in parallel_tasks if task.domain == "research"
    ] + [
        ("builder", task) for task in parallel_tasks if task.domain == "build"
    ])

    # Phase 2: Bağımlı görevler sıralı
    for task in lead_result.dependent_tasks:
        context = merge_results(parallel_results)
        await manager.spawn_and_wait(task.specialist, task, context=context)

    # Phase 3: QA (mevcut SwarmConsensus korunur)
    qa_result = await SwarmConsensus.run_tribunal_debate(...)
```

#### Workflow Chains → DAG Dönüşümü
```python
CODING_DAG = {
    "lead":         {"depends_on": []},
    "researcher":   {"depends_on": ["lead"]},     # lead ile paralel değil, plan lazım
    "builder":      {"depends_on": ["lead"]},      # researcher ile PARALEL olabilir
    "ops":          {"depends_on": ["builder"]},   # builder bitince test
    "qa":           {"depends_on": ["ops"]},       # ops bitince doğrula
    "communicator": {"depends_on": ["qa"]},        # qa bitince raporla
}
```

---

### Faz 5: Agent Teams — Koordineli Çalışma
**Dosyalar:** `core/sub_agent/team.py`, `core/sub_agent/shared_state.py`
**Bağımlılık:** Faz 1, 2, 3, 4

#### 5.1 SharedTaskBoard — Paylaşımlı Görev Tahtası
```python
class SharedTaskBoard:
    """asyncio.Lock korumalı görev tahtası."""

    async def post_task(self, task: TeamTask) -> str:
        """Görev ekle, task_id dön."""

    async def claim_task(self, agent_id: str, task_id: str) -> bool:
        """Görevi sahiplen (çift claim engelli)."""

    async def complete_task(self, task_id: str, result: Any):
        """Tamamla, bağımlı görevleri unblock et."""

    async def get_available(self, agent_id: str) -> list[TeamTask]:
        """Agent'ın sahiplenebileceği, bağımlılıkları çözülmüş görevler."""
```

#### 5.2 TeamMessageBus — Agent'lar Arası İletişim
```python
class TeamMessageBus:
    """asyncio.Queue tabanlı mesaj kuyruğu."""

    async def send(self, from_agent: str, to_agent: str, message: TeamMessage):
    async def broadcast(self, from_agent: str, message: TeamMessage):
    async def receive(self, agent_id: str, timeout=30) -> Optional[TeamMessage]:
```

#### 5.3 AgentTeam — Koordineli Ekip
```python
class AgentTeam:
    async def execute_project(self, brief: str) -> TeamResult:
        """
        1. Lead: brief analiz → görevleri board'a yaz
        2. Specialist worker'lar: görev claim et → çalıştır → tamamla
        3. Validator: her çıktıyı gate'den geçir
        4. Lead: sonuçları birleştir, final çıktı üret
        """
```

**Pratik Senaryo — "E-ticaret sitesi yap":**
```
1. Lead: 5 görev oluşturur (HTML layout, CSS styling, ürün kataloğu, sepet, API)
2. Researcher: Referans site'leri araştırır (paralel)
3. Builder-1: HTML + CSS yazar (paralel)
4. Builder-2: JavaScript + API yazar (researcher sonucuna bağımlı)
5. QA: Her dosyayı validate eder (file_not_empty, valid_html)
6. Lead: Birleştirir, README yazar, paketler
```

---

### Faz 6: Pipeline Entegrasyonu
**Dosyalar:** `core/pipeline.py` (güncelleme)
**Bağımlılık:** Faz 4, 5

#### StageExecute Karar Ağacı Güncellemesi
```python
# Mevcut:
# if multi_agent_recommended + complexity >= 0.9 → AgentOrchestrator

# Yeni:
if team_mode and complexity >= 0.95:
    result = await AgentTeam(team_config).execute_project(original_input)
elif multi_agent_recommended:
    result = await orchestrator.manage_flow(plan, original_input)  # sub-agent destekli
elif needs_parallel_research:
    results = await sub_agent_manager.spawn_parallel(research_tasks)
    result = merge_and_respond(results)
else:
    # mevcut CDG / direct yol
```

---

## 5. Dosya Yapısı (Yeni Modüller)

```
core/sub_agent/
├── __init__.py          # Public API: SubAgentManager, AgentTeam, SubAgentResult
├── session.py           # SubAgentSession, SessionState, SubAgentTask
├── manager.py           # SubAgentManager (spawn, collect, parallel)
├── executor.py          # SubAgentExecutor (Observe-Act-Verify loop)
├── team.py              # AgentTeam, TeamConfig
├── shared_state.py      # SharedTaskBoard, TeamMessageBus, TeamMessage
└── validator.py         # SubAgentValidator (gate checks)
```

## 6. Uygulama Önceliği ve Takvim

| Sıra | Faz | Değer | Karmaşıklık | Tahmini Dosya |
|------|-----|-------|-------------|---------------|
| 1 | Faz 1 — Session Altyapısı | Temel | Düşük | session.py, manager.py |
| 2 | Faz 2 — Yürütme Motoru | Yüksek | Orta | executor.py |
| 3 | Faz 3 — Validator Gate | Yüksek | Düşük | validator.py |
| 4 | Faz 4 — Orchestrator Entegrasyonu | Yüksek | Orta | orchestrator.py (update) |
| 5 | Faz 6 — Pipeline Entegrasyonu | Orta | Düşük | pipeline.py (update) |
| 6 | Faz 5 — Agent Teams | Çok Yüksek | Yüksek | team.py, shared_state.py |

## 7. Bağımlılık Grafiği

```
Faz 1 (Session) ──→ Faz 2 (Executor) ──→ Faz 3 (Validator)
                                     │
                                     ├──→ Faz 4 (Orchestrator) ──→ Faz 6 (Pipeline)
                                     │                                    │
                                     └────────────────────────────────────→ Faz 5 (Teams)
```

## 8. Maliyet & Performans

- Sub-agent başına ek LLM çağrısı: 1-3 (plan + execute + verify)
- Paralel 3 sub-agent: ~2-4x hızlanma (I/O-bound)
- Token bütçe: mevcut `BudgetTracker` sub-agent seviyesine genişletilecek
- Timeout: sub-agent başına 5dk, toplam team 15dk
- Derin spawn engeli: sub-agent → sub-agent zinciri kapalı

## 9. Test Stratejisi

```bash
# Her faz sonrası
python -m pytest tests/unit/test_sub_agent*.py -v

# Entegrasyon testi
python -m pytest tests/test_sub_agent_integration.py -v

# Mevcut regresyon
python -m pytest tests/ --ignore=tests/unit/test_office_tools.py -q
```

Her faz için:
1. **Unit test**: Mock LLM + mock tools ile akış testi
2. **Integration test**: Orchestrator + sub-agent uçtan uca
3. **Hata senaryoları**: timeout, tool hatası, validation failure, budget aşımı

---

## 10. Eski Plan Maddeleri (Referans)

### Öncelik: YÜKSEK
- A. `_infer_stack` oyun → "pygame" dönmeli (şu an "python")
- B. `_llm_build_project` Pass 2 token limiti dinamik olmalı
- C. `_parse_create_coding_project` eksik tetikleyiciler

### Öncelik: ORTA
- D. Delivery Engine + `_llm_build_project` entegrasyonu
- E. Dosya sayısı config'den okunmalı
- F. Brief temizleme (IDE referansları)

### Öncelik: DÜŞÜK
- G. `test_office_tools.py` fix
- H. Progress bildirimi (dosya üretimi sırasında)
- I. Brief otomatik genişletme (Pass 0)

---

## 11. Mimari Notlar

- `core/agent.py`'de `import re as _re` — yeni kodlarda `_re` kullan
- `max_tokens` TypeError fallback gerekli (bazı provider'lar desteklemiyor)
- Path güvenliği: her dosya yazımında `resolve()` + `startswith()` kontrolü
- LLM öncelik: Groq → Gemini → Ollama (ücretsiz)
- `_ensure_llm()` → LLM lazım olan her yerde çağır
