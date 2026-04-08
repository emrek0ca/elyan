# AGENTS.md — System Architecture, Design Philosophy, and Architectural Decisions

---

## Philosophy & Core Design Principles

### Three-Layer Learning Hierarchy

Modern AI evolution follows a three-book framework:

1. **Deep Learning Layer** (Goodfellow et al.)
   - Mathematical brain: neural networks, transformers, vision models
   - Pattern recognition and knowledge representation

2. **Reinforcement Learning Layer** (Sutton & Barto)
   - Strategic decision-making from experience
   - Reward signals, temporal-difference learning, goal pursuit

3. **Agency Layer** (Michael Lanham, AI Agents in Action)
   - Autonomous operation with external tools
   - Perception → Planning → Action → Learning cycle
   - Multi-agent coordination, tool integration (MCP)

**Elyan implements all three layers**:
- LLM provides perception & memory (Deep Learning)
- CEO Planner + execution modes provide strategy (Reinforcement Learning)
- Agent loop + Computer Use provides autonomy (Agency)

### Seven Core Design Principles

1. **Correctness > Speed**
   - Mathematical rigor over "fast enough"
   - Every decision reversible or has safety exit
   - Tests drive implementation

2. **Safety > Feature Velocity**
   - Approval gates before risky actions
   - Risk-level mapping for all action types
   - Audit trails and evidence recording mandatory
   - Local-first execution (no required cloud)

3. **Observability > Hidden Behavior**
   - Structured logging in every component
   - Metrics stored locally
   - Session persistence for debugging
   - Evidence directories for forensics

4. **Modularity > Convenience Hacks**
   - Each layer independent and testable
   - Clear interfaces between systems
   - Singleton patterns for dependency injection
   - No spaghetti async

5. **Explicit Policy > Implicit Trust**
   - Configuration-driven behavior
   - Intent parsing rules transparent
   - Approval levels explicit
   - Rate limits and quotas enforced

6. **Local-First for Machine Control**
   - All vision processing local (Qwen2.5-VL via Ollama)
   - Action execution never phones home
   - Evidence stays on user's machine
   - Zero-cloud Computer Use mode

7. **Fail-Safe Design**
   - Deny-by-default for risky actions
   - Approval gates non-optional
   - Secrets protected
   - Full rollback capability

### Architectural Decision Records (ADRs)

**ADR-001:** Elyan is an **Operator Runtime**, not a Chatbot
- Separates Intent → Task Engine → Delivery → Agent
- Session state is critical
- Approval workflow is non-optional

**ADR-002:** Three-Tier Intent Routing (Tier 1: Rules, Tier 2: Fuzzy, Tier 3: LLM)
- 90%+ routed in <50ms
- Deterministic for routine tasks
- LLM only for novel requests

**ADR-003:** Singleton Pattern for Core Systems
- Single source of truth
- Clean dependency injection
- Easy to mock in tests

**ADR-004:** Evidence Mandatory for Operator Actions
- Pre/post screenshots
- Action trace (JSONL)
- Full forensics capability

**ADR-005:** Approval Levels (AUTO, CONFIRM, SCREEN, TWO_FA)
- Risk-aware approval mapping
- Secure by default

**ADR-006:** Delivery Engine for Complex Projects
- Multi-step projects use INTAKE→PLAN→EXECUTE→VERIFY→DELIVER
- Checkpoints prevent cascading failures
- Better error recovery

**ADR-007:** Local-Only Vision for Computer Use
- Qwen2.5-VL via Ollama
- Privacy-first
- Cost-free at scale

### Strategic Boundaries & Layer Ownership

| Layer | Components | Stability | Owner |
|-------|-----------|-----------|-------|
| **Session & Policy** | SessionMgr, EncryptedVault, SessionSecurity, ApprovalAuditLog, PolicyEngine, MemoryEngine | ⭐⭐⭐⭐⭐ | Core Team |
| **Intent & Routing** | IntentParser, Quick Detector, LLM Orchestrator | ⭐⭐⭐⭐ | Intent Team |
| **Execution & Agents** | TaskEngine, Tool Exec, Approval Workflow, RunStore | ⭐⭐⭐ | Executive Team |
| **Advanced Features** | DeliveryEngine, ComputerUse, CognitiveLayers, CacheManager, AsyncExecutor | ⭐⭐ | Innovation Team |

---

## Elyan Overview

Elyan is not a simple chatbot.  
Elyan is a local-first, multi-session, multi-channel, tool-using digital operator.

Its job is not only to answer messages, but to:

- understand user intent
- resolve the correct session and workspace
- assemble context safely
- choose the right execution path
- use tools and capabilities
- operate on local and remote systems
- update memory
- stream progress
- recover from errors
- remain stable as new features are added

Elyan must behave like an operator runtime, not a prompt toy.

---

## Product Vision

Elyan should become a reliable digital operator that can:

- manage files and folders
- edit, create, move, rename, and trash files safely
- execute terminal tasks with verification
- coordinate desktop, browser, and remote nodes
- work across sessions without context corruption
- remember projects, user preferences, and recent work
- support approval-first autonomy
- remain modular, observable, and extensible

The core value of Elyan is: **stable execution with real operational capability**.

---

## North Star

When building Elyan, always optimize for:

1. correctness
2. safety
3. observability
4. extensibility
5. low-friction execution
6. clean architecture
7. local-first performance
8. premium user experience

Never optimize for “demo magic” at the cost of stability.

---

## Non-Goals

Do not turn Elyan into:

- a giant prompt file
- a monolithic chatbot app
- a random collection of scripts
- a fragile UI-automation bot
- an agent that directly executes raw model output without policy checks
- a system that mutates files without previews, logs, or rollback

---

## Core Principles

### 1. LLM decides, runtime executes
The model may propose a plan, but the runtime is responsible for what actually happens.

### 2. Core is stable, features are modular
Do not inject new features directly into the core runtime.  
New capabilities must be added through clear modules, registries, or plugins.

### 3. Every session has a lane
A session must not have uncontrolled parallel execution.  
Use per-session serialization or explicit queue policies.

### 4. All side effects must be explicit
Filesystem writes, terminal commands, browser actions, app control, and network changes are side effects.  
They must go through typed actions, policy checks, logging, and verification.

### 5. Preview before destructive change
Any risky or destructive operation must support dry-run, preview, or approval before execution.

### 6. Memory must be auditable
Memory should be readable, structured, and recoverable.  
Do not hide core memory entirely inside opaque vector-only layers.

### 7. Local-first for computer control
Desktop control, filesystem operations, terminal execution, and UI-level capabilities should run on the local machine through a persistent desktop agent.

### 8. Everything important must be observable
If Elyan performs an action, we must be able to answer:
- what happened
- why it happened
- which session triggered it
- which tool executed it
- whether it succeeded
- whether it can be rolled back

---

## High-Level Architecture

Elyan should be developed as a layered system.

### Layer 1: Gateway / Orchestrator
Responsible for:
- receiving events from all channels
- validating incoming payloads
- resolving actor, workspace, and session
- queueing work
- starting runs
- tracking lifecycle events

### Layer 2: Protocol Layer
Responsible for:
- typed schemas
- event definitions
- action payload contracts
- tool result validation
- compatibility across components

Use typed contracts everywhere.  
Preferred stack: TypeScript + Zod or equivalent schema validation.

### Layer 3: Session Engine
Responsible for:
- session resolution
- lane locking
- queue policies
- run state
- interruption rules
- follow-up handling

### Layer 4: Context Engine
Responsible for:
- system rules
- workspace state
- recent transcript
- pinned memory
- project memory
- retrieval results
- tool state
- compaction and token budgeting

### Layer 5: Runtime / Planner / Executor
Responsible for:
- planning
- step execution
- tool routing
- approval checkpoints
- retries
- failure recovery
- structured output production

### Layer 6: Capability Runtime
Responsible for:
- filesystem operations
- terminal commands
- application control
- browser control
- clipboard access
- screenshots
- node-specific actions

### Mobile Dispatch Boundary

Mobile dispatch and pairing must not create a second runtime.

- `elyan/*` is the canonical runtime owner for:
  - mobile dispatch
  - pairing lifecycle
  - computer use orchestration
  - evidence/session bridge
- `core/*` remains the canonical owner for:
  - privacy and consent truth
  - SQLite/runtime DB management
  - tiered learning
  - project runway
  - gateway and control-plane bridging
- `core/*` may normalize and route mobile events into `elyan/*`, but must not:
  - create a second planner
  - create a second approval path
  - create hidden session identifiers outside the existing run/session model
- Pairing codes must never be persisted in plaintext.
- Mobile dispatch evidence must remain local-first, approval-gated, and auditable.

### Layer 7: Memory and Persistence
Responsible for:
- profile memory
- project memory
- episodic memory
- run logs
- daily summaries
- audit records

### Layer 8: UI / Command Center
Responsible for:
- active runs
- pending approvals
- live progress
- tool history
- memory timeline
- node health
- cost and usage visibility

---

## Execution Model

Elyan must follow this mental model for every user request:

1. receive input
2. validate input
3. normalize input
4. resolve session
5. resolve workspace
6. assemble context
7. decide execution mode
8. run plan
9. call tools if needed
10. verify results
11. update memory
12. log everything important
13. respond with status and outcome

Never skip validation, policy, verification, or logging for side-effectful work.

---

## Session Model

A session represents a stable operational context.

A session may correspond to:
- a conversation
- a project
- a workspace
- a task thread
- a user + channel pair

Each session must have:

- `session_id`
- `actor_id`
- `workspace_id`
- `lane_state`
- `active_run_id`
- `queued_events`
- `last_context_summary`
- `session_metadata`

### Rules

- Only one side-effectful run should actively mutate a session state at a time unless there is explicit safe concurrency.
- New events must enter a queue.
- Session queues must support policy-based handling.

### Queue Policies

Support these queue policies:

- `followup`: run after current task
- `interrupt`: only for high-priority work
- `merge`: merge into active plan if compatible
- `backlog`: store for later processing
- `summarize`: compress multiple pending items into one summary item

---

## Context Assembly Rules

When building context for a run, include only what is useful and current.

Context priority order:

1. system and safety rules
2. current user intent
3. session summary
4. relevant project memory
5. recent transcript
6. active workspace state
7. retrieved documents
8. tool state and previous outputs
9. optional older memory

### Requirements

- Always prefer current and task-relevant context.
- Compact aggressively when needed.
- Never bloat context with unrelated history.
- Preserve operational facts over decorative chat history.

---

## Memory Model

Elyan should use a hybrid memory model.

### Memory Types

#### 1. Profile Memory
Long-lived user preferences and stable behavior rules.

Examples:
- preferred coding style
- preferred architecture patterns
- product priorities
- recurring workflows

#### 2. Project Memory
Persistent project-specific facts.

Examples:
- Elyan architecture decisions
- roadmap decisions
- repo structure
- active milestones
- capability plans

#### 3. Episodic Memory
Session and recent work summaries.

Examples:
- what was implemented today
- which bug was investigated
- which files were changed
- next pending tasks

#### 4. Run Logs
Execution-level audit history.

Examples:
- which tool was called
- what it attempted
- what it changed
- what failed
- rollback details

### Storage Rules

Memory must be:
- structured
- readable
- easy to audit
- not solely dependent on vector storage
- easy to update safely

### Suggested Layout

```text
memory/
  profile.md
  projects/
    elyan/
      MEMORY.md
      DECISIONS.md
      ROADMAP.md
  daily/
    YYYY-MM-DD.md
  runs/
    <session-id>/
      <run-id>.json
Capability Model

Do not think in terms of random tools only.
Think in terms of capabilities.

A capability is an operational domain.
An action is a specific operation inside that domain.

Core Capabilities
filesystem
terminal
applications
browser
clipboard
screen
notifications
search/index
network
scheduler
Example Actions
filesystem.list
filesystem.read_text
filesystem.write_text
filesystem.patch_text
filesystem.move
filesystem.rename
filesystem.trash
filesystem.restore
terminal.exec
terminal.stream
terminal.cancel
applications.open
applications.close
applications.focus
browser.open_url
browser.extract_page
browser.fill_form
browser.download

Each action must define:

input schema
risk level
approval rules
execution adapter
result schema
verification method
rollback strategy if applicable
Computer Control Architecture

Elyan must use a desktop agent for local machine operations.

Rule

The LLM must not directly control the operating system.

Correct model

User request
-> Orchestrator
-> Policy engine
-> Desktop agent
-> Capability adapter
-> Verification
-> Logging
-> Response

Desktop Agent Responsibilities
persistent connection to gateway
execute local filesystem actions
execute terminal commands
access local applications
access clipboard
capture screenshots
maintain fast local file index
enforce allowed roots and sensitive path restrictions
provide low-latency local execution
Desktop Agent Requirements
always-on process or daemon
typed protocol
reconnect logic
action acknowledgements
progress events
local audit logging
local capability registry
health heartbeat
## Computer Use Tool Architecture

### Overview

The Computer Use Tool enables Elyan to interact with graphical applications and UI elements through a vision-guided action loop:

**Vision → Planning → Execution → Verification**

This architecture mirrors desktop automation but adds LLM-driven reasoning instead of brittle pixel-matching or recording playback.

### Core Flow

1. **VisionAnalyzer** (Qwen2.5-VL, 320 lines): Screenshot → parsed layout tree + element detection
2. **ActionPlanner** (LLM integration, 350 lines): Task intent + visual context → action sequence
3. **ActionExecutor** (pynput/pyautogui, 380 lines): Type-safe action execution with verification
4. **EvidenceRecorder** (260 lines): Screenshots, action trace (JSONL), metadata
5. **ApprovalEngine** (400 lines): Risk-based gating with 4 levels

### 10 Action Types

| Action | Risk | Example |
|--------|------|---------|
| left_click, right_click | LOW | Click button, context menu |
| type | MEDIUM | Input text field |
| hotkey | MEDIUM | Ctrl+S (save) |
| drag | MEDIUM | Move window |
| scroll, select_all | LOW | Scroll page, select text |
| copy, paste | MEDIUM | Clipboard ops |
| wait | LOW | Wait for load |
| screenshot | LOW | Capture screen |

### Approval Levels

| Level | Requirement | Actions |
|-------|------------|---------|
| AUTO | None | screenshot, scroll, select_all |
| CONFIRM | Vision accuracy check | type, click, hotkey |
| SCREEN | User preview + approve | drag, system changes |
| TWO_FA | 2-person approval | Destructive operations |

### Integration Points

- **ApprovalEngine Singleton**: Shared approval workflow
- **RealTimeActuator** (future): Multi-desktop support
- **Evidence Storage**: `~/.elyan/computer_use/evidence/`

---

## Filesystem Safety Rules

Elyan must treat filesystem changes as high-importance operations.

Required behavior
Allowed Roots

Only operate inside allowed roots unless explicitly elevated.

Atomic Writes

Never risk partial file corruption.
Use temp-write + verify + rename patterns where appropriate.

Safe Delete

Default delete should mean:

move to trash
log operation
support restore if possible
Dry Run

Bulk rename, delete, move, and patch operations should support dry-run.

Verification

After a write or move:

verify path exists
verify content if relevant
verify target is correct
verify count of affected files
Rollback

For any reversible operation, preserve rollback metadata.

Sensitive Path Protection

Protect paths such as:

.env
private keys
SSH folders
cloud credentials
wallet files
shell profile files
system configuration files
Terminal Execution Rules

Terminal execution is powerful and dangerous.

Requirements
execute through a controlled adapter
validate allowed working directory
sanitize environment exposure
capture stdout, stderr, exit code
support cancellation
classify risk before execution
require approval for destructive commands
Never
run raw arbitrary shell from model output without filtering
expose secrets in logs
assume success without checking exit code and output
Approval and Safety Model

Elyan must support approval-first autonomy.

Risk Levels
read_only
write_safe
write_sensitive
destructive
system_critical
Approval Guidance
Auto-allow examples
read file
list directory
inspect process
search workspace
open a known document
Usually require approval
overwrite important files
bulk rename
bulk delete
terminal commands with system impact
package uninstall
secret-related file access
system config changes
Always high scrutiny
anything touching keys, credentials, wallet files, SSH, environment files, or deployment secrets
Plugin Model

Elyan must be extensible.

A plugin may add:

a new capability
a new tool adapter
a new channel integration
a new model provider
a new node type
a new UI module
Plugin Rules

Plugins must not bypass:

protocol typing
policy checks
logging
verification
lifecycle integration
Plugin Contract

Each plugin should declare:

plugin name
version
capabilities
actions
required permissions
runtime dependencies
health checks
configuration schema
Model Usage Rules

Use models intentionally.

Suggested role separation
planner model: small and fast when possible
executor model: stronger when precision is needed
validator model: deterministic checks when possible
summarizer model: cheap and compact
Rules
do not use the strongest model for everything
keep token cost under control
use retrieval and runtime state before asking the model to infer
prefer deterministic code paths over model creativity for operational actions
Observability Requirements

Every meaningful run should be inspectable.

Minimum observability
event logs
run lifecycle logs
tool call logs
errors
retries
approval waits
rollback records
memory write events
performance metrics
Important metrics

Track at least:

task success rate
tool success rate
average latency
queue delay
approval rate
rollback frequency
retry frequency
token cost per successful task
memory pollution rate
session recovery rate
Code Standards
General
prefer TypeScript for core system code
keep modules small and composable
favor pure functions where possible
separate orchestration from side effects
validate all external input
avoid hidden shared mutable state
Required practices
strong typing
schema validation
structured logs
explicit errors
predictable naming
minimal coupling
Avoid
giant files
magical helper layers with unclear ownership
silent failures
direct filesystem mutation from random app code
business logic inside UI components
undocumented side effects
Repo Structure Guidance

Suggested monorepo structure:

apps/
  gateway/
  desktop-agent/
  admin-web/
  mobile-client/
  cli/

packages/
  protocol/
  session-engine/
  context-engine/
  runtime/
  planner/
  policy-engine/
  memory/
  observability/
  capability-filesystem/
  capability-terminal/
  capability-applications/
  capability-browser/
  capability-screen/
  capability-search/
  plugin-kit/
  shared-types/

plugins/
  telegram/
  whatsapp/
  gmail/
  calendar/
  browser-playwright/
  desktop-macos/

memory/
  profile.md
  projects/
  daily/
  runs/
File Editing Rules for Agents

When changing code:

understand the relevant layer first
avoid cross-layer hacks
keep core contracts stable
preserve backward compatibility where reasonable
update schemas when interfaces change
update docs when architecture changes
preserve auditability
never weaken safety without explicit reason

If a change touches:

protocol
session logic
policy engine
filesystem execution
terminal execution
memory writing

then treat it as a sensitive architectural change.

Development Workflow

When implementing a feature, follow this order:

define the capability or behavior clearly
define the schema and contracts
define safety and approval rules
implement the runtime behavior
add verification
add observability
update memory/docs if architecture changed
expose in UI only after the runtime is stable
Preferred sequence

Do not build UI-first for runtime-heavy features.
Build core runtime first, then UI.

Definition of Done

A feature is not done because it “works once”.

A feature is done only if:

behavior is typed
failure cases are handled
logs exist
output can be verified
destructive behavior is protected
session interaction is considered
docs are updated if architecture changed
the feature fits the existing system instead of bypassing it
Quality Gates

Before merging or accepting a change, check:

Does this break session isolation?
Does this bypass policy?
Does this add side effects without logs?
Does this mutate files unsafely?
Does this make memory less auditable?
Does this increase coupling unnecessarily?
Can the action be verified?
Can failure be recovered?

If the answer is problematic, redesign before merging.

First-Class Priorities

When in doubt, prioritize work in this order:

Priority 1: Stable Core
protocol contracts
gateway lifecycle
session engine
queue model
run lifecycle
observability
Priority 2: Safe Computer Control
filesystem capability
terminal capability
local desktop agent
allowed roots
safe delete
rollback
verification
Priority 3: Context and Memory
project memory
session summaries
retrieval
memory write scoring
context compaction
Priority 4: Extensibility
plugin system
node system
capability registry
model routing
Priority 5: UX
command center
approvals UI
live progress
memory timeline
premium operator workflow
Immediate Build Priorities

If starting from scratch or continuing incomplete work, build in this order:

Phase 1
protocol package
event schemas
gateway
session engine
run state model
structured logging
Phase 2
desktop agent
filesystem capability
terminal capability
policy engine
verification and rollback base
Phase 3
memory system
retrieval
session summaries
project memory
Phase 4
plugin kit
browser/app capabilities
node registry
remote orchestration
Phase 5
admin UI
approvals
live run inspection
command center
Required Event Types

The system should be designed around explicit events such as:

MessageReceived
SessionResolved
WorkspaceResolved
RunQueued
RunStarted
PlanCreated
ToolRequested
ToolApproved
ToolRejected
ToolStarted
ToolSucceeded
ToolFailed
VerificationPassed
VerificationFailed
MemoryWriteRequested
MemoryWritten
RunCompleted
RunFailed
RunCancelled

Do not hide important lifecycle transitions.

Planning Guidance for Agents

When asked to implement something, first decide which category it belongs to:

protocol
session
context
runtime
capability
policy
memory
plugin
UI
observability

Then work within that boundary.

If a request seems simple but affects core runtime, treat it as an architecture change, not a small patch.

Behavior Expectations for All Coding Agents

When working on Elyan, you must:

understand the full architecture before making core changes
preserve stability over speed
build minimal but strong implementations
avoid unnecessary abstraction until the layer is clear
keep code clean, typed, and modular
prefer robust infrastructure over flashy shortcuts
write changes that future agents can understand quickly

You must not:

inject random dependencies without strong justification
create silent destructive behavior
mix UI logic with execution logic
bypass logging or policy layers
write code that “only works on the happy path”
weaken system safety to make demos easier

---

## Agent Runtime Evolution — ADR-008 (2026-04-06)

Elyan is evolving from a single-agent operator into a **multi-agent runtime** where
specialized agents collaborate on complex tasks.

### Core Architecture Additions

**ADR-008:** Inter-Agent Message Bus
- All agent-to-agent communication flows through `AgentMessageBus` singleton
- Topics: `direct` (1-1), `broadcast` (all), `topic` (pattern-based)
- Persistent message log in SQLite for crash recovery
- See: `docs/AGENT_RUNTIME_ROADMAP.md` for full plan

**ADR-009:** Agent Task Lifecycle
- Every delegated task has an `AgentTask` contract with:
  - parent-child relationship (delegation chain)
  - deadline, constraints, tool scope
  - status tracking: pending → running → completed → failed
- `AgentTaskTracker` manages the task tree and timeout escalation

**ADR-010:** Parallel Agent Execution
- CDG engine detects independent sub-tasks
- Independent tasks dispatched to parallel agents via `AgentPool`
- Resource conflict detection prevents data races
- Max concurrency configurable (default: 4)

**ADR-011:** Autonomous Model Selection
- `ModelSelectionPolicy` decides local vs cloud per-call:
  - Sensitive data → mandatory local (Ollama)
  - Simple task → local preferred (cost/latency)
  - Complex reasoning → cloud preferred (capability)
- Agent doesn't choose model; policy decides

**ADR-012:** Agent Learning Loop
- Every completed task generates `OutcomeFeedback`
- Orchestrator uses historical performance for specialist assignment
- Model selection incorporates past success rates
- SQLite-persisted, trend-analyzed

**ADR-013:** ElyanCore Mimari — Orchestrator Wrapper
- ElyanCore mevcut AgentOrchestrator üzerine oturur, onu değiştirmez
- Multi-channel (Telegram/WA/iMessage) → ChannelGateway → ElyanCore → Orchestrator
- ElyanCore: intent sınıflandırma + task decomposition + response synthesis
- Gerekçe: 1731 test geçen orchestrator kodunu bozmamak

**ADR-014:** Bilgisayar Kontrol Katmanı — Hibrit Yaklaşım
- AppleScript: yüksek seviye uygulama kontrolü (Mail, Calendar, Finder)
- Accessibility API (pyobjc): hassas UIElement bazlı kontrol
- PyAutoGUI: koordinat bazlı fallback + fare/klavye
- VisionAgent (Qwen2.5-VL yerel): ekran anlama, element bulma
- Güvenlik: tüm aksiyonlar audit log + snapshot + onay kapısı

**ADR-015:** Ses Mimarisi — Tam Yerel Pipeline
- Wake word: OpenWakeWord (CPU, "hey_elyan" custom model)
- STT: Whisper Large V3 (Ollama) — Türkçe optimize, streaming
- TTS: Kokoro (ONNX, yerel) — Elyan tarzı ses profili
- Gerekçe: ses mahremiyeti; kullanıcı konuşurken buluta veri gitmez

### Multi-Agent Team Roles

| Role | Emoji | Responsibility | Primary Model |
|------|-------|---------------|---------------|
| Lead | :dart: | Task decomposition, coordination | Claude |
| Researcher | :microscope: | Web search, fact extraction | GPT-4o / Gemini |
| Builder | :building_construction: | Code, files, creation | Claude |
| Ops | :gear: | System, filesystem, terminal | Ollama (local) |
| QA | :white_check_mark: | Verification, testing | Claude |

### Execution Flow (Multi-Agent)

```
User Request
  → Intent Parser (Tier 1/2/3)
  → Orchestrator (CEO)
    → AgentMessageBus.publish(task.assign)
    → Specialist A receives via subscribe
    → Specialist A works (uses tools, LLM calls)
    → Specialist A may delegate sub-task to Specialist B
      → B receives via message bus
      → B completes, publishes result
      → A receives B's result, continues
    → A publishes task.result
  → Orchestrator merges results
  → Pipeline verify + deliver
  → UI receives via WebSocket
```

### UI Integration

- **Agent Workspace Screen** — real-time view of agent collaboration
- **Agent streaming** via SSE endpoint `/api/v1/agents/live`
- **Task tree** visualization in Command Center
- WebSocket events: `agent.started`, `agent.progress`, `agent.completed`

### Implementation Roadmap

Full phased plan with timelines, dependencies, and success metrics:
→ `docs/AGENT_RUNTIME_ROADMAP.md` — Agent altyapısı (tamamlandı ✓)
→ `docs/ELYAN_CORE_ROADMAP.md` — Elyan vizyonu (kanal + bilgisayar kontrolü + ses)

---

## Known Issues & Technical Debt (Updated: 2026-04-06)

> Bu bölüm gerçek codebase analizi sonucunda yazılmıştır. Codex veya diğer agent'lar çalışmaya başlamadan önce bu listeyi okuyun.
> Son güncelleme: 2026-04-06 — kapanan maddeler [KAPANDI] olarak isaretlendi.

### CRITICAL — Production'ı Bloke Eden Sorunlar

**[C-1] Çift `run_store.py` — Farklı API'lar**
- `/core/run_store.py` → async tabanlı, dataclass, JSON persistence
- `/core/evidence/run_store.py` → senkron, farklı constructor, telemetry entegrasyonu
- `agent.py` evidence versiyonunu import ediyor, `dashboard_api.py` async versiyonunu bekliyor
- **Fix**: `/core/run_store.py` canonical olarak kalmalı, `/core/evidence/run_store.py` kaldırılmalı, tüm import'lar güncellenmeli
- **Neden fark eder**: `test_attachment_wallpaper_flow` bu yüzden fail ediyor (`data["steps"]` boş dönüyor)

**[C-2] Var Olmayan Fonksiyon/Widget Çağrıları**
`dashboard_api.py` şunları çağırıyor ama hiçbiri tanımlı değil:
- `get_cognitive_integrator()` — fonksiyon yok
- `DeadlockPreventionWidget` — class yok
- `SleepConsolidationWidget` — class yok
- Silent `except` ile yutuluyorlar → metrics sistemi sessizce kırık

**[C-3] `run_visualizer.js` Hardcoded Localhost** [KAPANDI]
- Relative path'e taşındı, artık hardcoded localhost yok

**[C-4] Threading vs Async Lock Karışıklığı**
- `core/performance/cache_manager.py`: `asyncio.Lock()` ✓
- `core/performance_cache.py`: `threading.RLock()` ✗ → async context'te deadlock riski

### HIGH — Release Öncesi Düzeltilmeli

**[H-1] `core/agent.py` Monolith**
- 14.766 satır, tek dosya, 254 fonksiyon
- Refactor hedefi: `AgentRouter`, `AgentExecutor`, `AgentValidator` olarak bölünmeli
- Şu an touch edilmesi çok riskli

**[H-2] Stub Modüller (NotImplementedError fırlatıyor)**
- `core/health_checks.py` — altyapı, hiçbir şey implement edilmemiş
- `core/realtime_actuator/` — tamamen stub, agent path'ine bağlı değil
- `core/alerting.py` — core metodlar boş

**[H-3] Üç Ayrı Real-Time Sistem — Entegre Değil**
- `MetricsStore` (threading.Lock tabanlı)
- Socket.IO (`http_server.py` içinde)
- `EventBroadcaster` (ayrı singleton)
→ Birleştirilmeli, hiçbiri dashboard'a tam entegre değil

**[H-4] Approval Requests Kalıcı Değil** [KAPANDI]
- `approval_engine.py` artık `_persist_pending()` ile JSON dosyasına yazıyor
- `_restore_pending()` ile startup'ta geri yüklüyor
- SQLite repository da mevcut (`_repository.upsert_pending`)

**[H-5] Web UI'da Güvenlik Eksiklikleri** [KISMI KAPANDI]
- Desktop app (Tauri): CSP header `tauri.conf.json` içinde mevcut ve sıkı
- CSRF: `elyan_csrf_token` cookie + `X-Elyan-CSRF` header mekanizması mevcut
- Kalan risk: legacy `dashboard.html` web UI hâlâ CSP/CSRF yok (React/Tauri canonical)

**[H-6] Run Store Payload'ları Şifresiz** [KAPANDI]
- `run_store.py` artık `_serialize_run_record()` ile hassas alanları encrypt ediyor
- `EncryptedVault` entegrasyonu mevcut, `_protect_value` / `_restore_value` çalışıyor
- Hassas alanlar: steps, tool_calls, error, artifacts, review_report, metadata

### MEDIUM — Teknik Borç

**[M-1] Tutarsız Response Formatları**
- `dashboard_api.py`: `{"success": bool, "data": ...}`
- `http_server.py`: `(dict, int)` tuple
- `EventBroadcaster`: dataclass
→ Birleşik ResponseContract şart

**[M-2] Config Layer Yok**
- Port (`18789`), path (`~/.elyan/runs`), timeout (`600.0`) her yere hardcoded
- `.env` veya `config.py` singleton ile merkezi yönetim gerekli

**[M-3] Integration Test Eksiklikleri**
- HTTP Flask route'ları test edilmiyor
- WebSocket delivery test edilmiyor
- Dashboard JS endpoint'leri test edilmiyor
- Metrics collector background thread test edilmiyor

**[M-4] `asyncio.run()` Flask Handler'da**
- `http_server.py` Flask route'larından async fonksiyonları `asyncio.run()` ile çağırıyor
- Flask thread pool'u bloke ediyor
- Fix: async Flask (quart) veya background task queue

### LOW — Temizlik

**[L-1] Dead Code**
- `core/health_checks.py` — implement edilmemiş, import edilmiyor → sil veya implement et
- `core/realtime_actuator/` — hiçbir yere bağlı değil → sil veya implement et

**[L-2] Lazy Import Anti-Pattern**
- Her yerde `try: import X; except: pass` → hataları gizliyor, fail fast gerekli

**[L-3] Unused Imports**
- `dashboard_api.py`'de `Event`, `timedelta` import edilmiş ama kullanılmıyor

**[L-4] Debug Kodu Production'da**
- `agent.py` satır 252-253: developer note yanlışlıkla f-string olarak kalmış

**[L-5] Metrics Collector Blocking Sleep**
- `dashboard_api.py`'de `time.sleep(5)` daemon thread içinde — `asyncio.sleep()` olmalı

### Test Durumu (2026-04-06)
- **Toplam**: 2791 test (collection error'lu 10 dosya hariç)
- **Geçen**: 2718 test
- **Başarısız**: 57 test (tümü pre-existing)
- **Error**: 9 test (computer_use modülü import hataları)
- **Atlanan**: 7 test
- **Yeni eklenen testler**: 13 workspace isolation testi (tümü geçiyor)
- **Hedefli test suite**: 96/96 geçiyor (gateway + workspace + billing + execution guard)
- **Desktop build**: Temiz (151 modül, 8.92s)

**Başarısız test dağılımı:**
- `test_agent_routing` (16) — agent.py monolith mock uyumsuzlukları
- `test_computer_use_*` (9+9err) — computer use modülü stabil değil
- `test_dashboard_html/assets` (5) — path uyumsuzlukları (kısmen düzeltildi)
- `test_llm_router` (4) — LLM mock timeout davranışı
- `test_operator_control_plane` (3) — operator planlama mock
- Diğer (10) — dağınık pre-existing sorunlar

---

Final Directive

Elyan is a serious operator system.
Build it like infrastructure, not like a toy.

Every change should move Elyan closer to:

reliable execution
safe autonomy
modular extensibility
local-first power
premium operator UX
auditable memory
production-grade control over real tasks

If you are uncertain, choose the path that is:

simpler
safer
more observable
easier to extend later
less likely to corrupt state
