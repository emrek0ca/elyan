# TOOLS.md — Elyan Capability & Tool Registry

**Purpose**: Complete reference of all tools, capabilities, and integrations available in Elyan.
**Updated**: 2026-03-23
**Status**: Living document — updated as new tools are added.

---

## Tool Categories

### Category 1: Core Intelligence
| Tool | Status | Module | Description |
|------|--------|--------|-------------|
| Intent Parser (3-Tier) | ACTIVE | `core/intent_parser/` | Rule-based + Semantic + LLM fallback intent detection |
| Task Engine | ACTIVE | `core/task_engine/` | Unified task decomposition + execution + delivery |
| Delivery Engine | ACTIVE | `core/delivery/` | Complex project delivery pipeline (brief→spec→plan→execute→verify→deliver) |
| Performance Cache | ACTIVE | `core/performance_cache.py` | Multi-layer caching (intent/decomposition/metrics/security) |
| LLM Client | ACTIVE | `core/llm_client.py` | Multi-provider orchestration (Groq→Gemini→Ollama→GPT) |
| Cognitive Integrator | ACTIVE | `core/cognitive_layer_integrator.py` | 5-layer cognitive pipeline orchestrator |

### Category 2: Cognitive Architecture (Phase 4)
| Tool | Status | Module | Description |
|------|--------|--------|-------------|
| CEO Planner | ACTIVE | `core/ceo_planner.py` | Pre-execution simulation, causality trees, conflict detection |
| Deadlock Detector | ACTIVE | `core/agent_deadlock_detector.py` | Stuck detection (3+ failures), recovery suggestions |
| Execution Modes | ACTIVE | `core/execution_modes.py` | FOCUSED (exploitation) / DIFFUSE (exploration) dual-mode |
| Cognitive State Machine | ACTIVE | `core/cognitive_state_machine.py` | Mode FSM, Pomodoro timer, success/failure tracking |
| Time-Boxed Scheduler | ACTIVE | `core/time_boxed_scheduler.py` | Task budgets, timeout enforcement, resource quotas |
| Sleep Consolidator | ACTIVE | `core/sleep_consolidator.py` | Offline learning, pattern chunking, Q-table optimization |
| Adaptive Tuning | ACTIVE | `core/adaptive_tuning.py` | Auto-optimization: budget, mode, deadlock prediction |

### Category 3: User Interface
| Tool | Status | Module | Description |
|------|--------|--------|-------------|
| CLI (22 Commands) | ACTIVE | `cli/commands/` | Full CLI: chat, status, cognitive, dashboard-api, gateway, channels... |
| Dashboard (Web) | ACTIVE | `ui/` | 6-card dashboard with WebSocket updates |
| Dashboard API | ACTIVE | `api/dashboard_api.py` | REST API + WebSocket for real-time metrics |
| HTTP Server | ACTIVE | `api/http_server.py` | Flask-based REST server with 10+ endpoints |
| Cognitive Widgets | ACTIVE | `ui/widgets/` | CognitiveState, ErrorPrediction, DeadlockPrevention, SleepConsolidation |

### Category 4: Desktop Control
| Tool | Status | Module | Description |
|------|--------|--------|-------------|
| Screenshot | ACTIVE | `tools/screenshot.py` | Screen capture + OCR |
| Volume Control | ACTIVE | `tools/set_volume.py` | macOS volume control |
| App Control | ACTIVE | `tools/open_app.py` | Open/close/focus applications |
| File Operations | ACTIVE | `tools/` | Create, read, write, move, rename, delete, search files |
| Terminal Exec | ACTIVE | `tools/terminal.py` | Controlled command execution |
| Clipboard | ACTIVE | `tools/clipboard.py` | Read/write clipboard |
| Notifications | ACTIVE | `tools/notifications.py` | macOS native notifications |
| Browser | ACTIVE | `tools/browser.py` | URL open, page extraction |

### Category 5: Communication Channels
| Channel | Status | Module | Description |
|---------|--------|--------|-------------|
| Telegram | ACTIVE | `handlers/telegram_handler.py` | Full bot with inline keyboard, voice, media |
| Discord | ACTIVE | `core/gateway/adapters/discord_adapter.py` | Guild + DM support |
| Slack | ACTIVE | `core/gateway/adapters/slack_adapter.py` | App + Bot integration |
| WhatsApp | ACTIVE | `core/gateway/adapters/whatsapp_adapter.py` | Business API webhook |
| Webchat | ACTIVE | `core/gateway/adapters/webchat_adapter.py` | Embedded web widget |
| Signal | ACTIVE | `core/gateway/adapters/signal_adapter.py` | signald unix socket |
| Matrix | ACTIVE | `core/gateway/adapters/matrix_adapter.py` | matrix-nio async |
| Teams | ACTIVE | `core/gateway/adapters/teams_adapter.py` | Azure Bot Framework |
| Google Chat | ACTIVE | `core/gateway/adapters/google_chat_adapter.py` | Webhook + Pub/Sub |
| iMessage | ACTIVE | `core/gateway/adapters/imessage_adapter.py` | BlueBubbles REST + WS |

### Category 6: LLM Providers
| Provider | Status | Model | Priority |
|----------|--------|-------|----------|
| Groq | ACTIVE | llama-3.3-70b-versatile | 1 (fastest, free) |
| Google Gemini | ACTIVE | gemini-2.0-flash | 2 (free) |
| Ollama | ACTIVE | Auto-detect best model | 3 (local) |
| GPT-4 | PLANNED | gpt-4o | 4 (premium) |
| Other Providers | PLANNED | Custom APIs | 5 (extensible) |

### Category 7: Security & Safety
| Tool | Status | Module | Description |
|------|--------|--------|-------------|
| Security Audit | ACTIVE | `security/audit.py` | Action audit logging |
| Policy Engine | ACTIVE | `security/policy.py` | Risk classification, approval gates |
| Path Protection | ACTIVE | `security/` | Sensitive path blocking (.env, keys, etc.) |
| Input Sanitization | ACTIVE | `core/intent_parser/` | Turkish normalization, injection prevention |

### Category 8: Monitoring & Analytics
| Tool | Status | Module | Description |
|------|--------|--------|-------------|
| Metrics Store | ACTIVE | `api/dashboard_api.py` | Time-series metrics with sliding window |
| Cache Stats | ACTIVE | `core/performance_cache.py` | Hit/miss/eviction tracking |
| Cognitive Trace | ACTIVE | `logs/cognitive_trace.log` | JSONL trace of all cognitive decisions |
| Budget Optimizer | ACTIVE | `core/adaptive_tuning.py` | Actual vs budgeted performance tracking |
| Deadlock Predictor | ACTIVE | `core/adaptive_tuning.py` | Historical pattern risk scoring |

---

## Tool Interaction Flow

```
User Input
  │
  ├─ Channel Adapter (Telegram/Discord/CLI/...)
  │     │
  │     ▼
  ├─ Gateway Router
  │     │
  │     ▼
  ├─ Intent Parser (3-Tier)
  │     │
  │     ▼
  ├─ CEO Planner (simulate before execute)
  │     │
  │     ▼
  ├─ Adaptive Tuning (budget + mode recommendation)
  │     │
  │     ▼
  ├─ Task Engine (decompose + execute)
  │     │
  │     ▼
  ├─ Tool Execution (72 tools)
  │     │
  │     ▼
  ├─ Verification + Logging
  │     │
  │     ▼
  └─ Response (Text / Attachment / Dashboard Update)
```

---

## Phase 6+ Tool Pipeline (Planned)

### Agentic Research Engine
- Deep web research with citation tracking
- Multi-source synthesis (academic, news, code)
- Fact verification pipeline
- Real-time knowledge graph

### Visual Intelligence
- Screen understanding (OCR + layout analysis)
- Visual task automation
- Multi-monitor awareness
- UI element detection and interaction

### Code Intelligence
- Full-project code analysis
- Automated refactoring
- Test generation from code
- Security vulnerability scanning
- Dependency analysis

### Workflow Automation
- Multi-step workflow builder
- Conditional execution paths
- Schedule-based triggers
- Cross-app integration chains

### Voice & Multimodal
- Real-time voice commands
- Audio transcription
- Image analysis
- Document understanding (PDF, Excel, etc.)

---

## Tool Development Guidelines

### Adding a New Tool
1. Define action schema (input/output types)
2. Classify risk level (read_only, write_safe, write_sensitive, destructive)
3. Implement execution adapter
4. Add verification method
5. Add rollback strategy (if applicable)
6. Register in capability registry
7. Add unit + integration tests
8. Update this file

### Tool Quality Requirements
- Type annotations on all functions
- Docstrings for every public method
- Error handling (never silent failures)
- Logging (all tool invocations logged)
- Timeout support
- Cancellation support where applicable

---

**Total Active Tools**: 72+ tool actions across 8 categories
**Total Active Channels**: 10 communication channels
**Total Active LLM Providers**: 3 (Groq, Gemini, Ollama)
**Total Active Tests**: 122+ cognitive tests, 458+ system tests
