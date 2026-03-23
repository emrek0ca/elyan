# Elyan — Local-First Digital Operator Platform

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-223%20passing-brightgreen)](./tests)
[![Version](https://img.shields.io/badge/version-0.1.0-blue)](./RELEASES.md)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)](https://www.python.org/)

Elyan is a **production-grade local-first digital operator platform** that understands natural language, manages sessions, executes tasks safely, and operates across multiple channels.

Unlike simple chatbots, Elyan is an **operator runtime** that:
- 🎯 Understands user intent with multi-tier routing (fast patterns → semantic → LLM)
- 🔒 Executes tasks safely with approval gates and policy enforcement
- 💾 Maintains persistent session context across messages and channels
- 📊 Provides observable, auditable execution with full logging
- 🧠 Learns from outcomes and optimizes automatically (adaptive tuning)
- 🌐 Operates across Telegram, CLI, and other channels
- ⚡ Runs locally with free LLM providers (Groq, Google Gemini, Ollama)
- 🔄 Recovers from errors with deadlock detection and fallback strategies

---

## Quick Start

### Prerequisites
- Python 3.11+
- pip/poetry for dependency management

### Installation

```bash
# Clone repository
git clone https://github.com/emrek0ca/elyan.git
cd elyan

# Install dependencies
pip install -e .

# Configure environment (optional)
cp .env.example .env
# Edit .env with your LLM provider keys
```

### Run Elyan

```bash
# Interactive chat (operator mode - default)
python -m cli.main chat

# Or start a Telegram bot
python -m handlers.telegram_handler

# View all available commands
python -m cli.main --help
```

### Enable Phase 6 (Experimental Features)

```bash
# Advanced mode - enables research, code analysis, workflows, etc.
export ELYAN_OPERATOR_MODE=advanced
python -m cli.main chat
```

---

## Features

### Core Operator (v0.1.0 — Production Ready)

| Feature | Status | Details |
|---------|--------|---------|
| **Intent Routing** | ✅ | 3-tier system: patterns → semantic → LLM |
| **Session Management** | ✅ | Lane-locked sessions, context isolation |
| **Task Execution** | ✅ | Decomposition, verification, error recovery |
| **Safety & Policy** | ✅ | Approval gates, risk detection, audit logging |
| **Cognitive Layer** | ✅ | CEO Planner, Adaptive Tuning, Deadlock Detection |
| **Memory System** | ✅ | Profile, project, episodic, run summaries |
| **Multi-Channel** | ✅ | Telegram, CLI (Discord/Slack coming) |

### Phase 6: Competitive Edge (Experimental — ADVANCED mode)

| Pillar | Status | Tests | Description |
|--------|--------|-------|-------------|
| **Research Engine** | ⚠️ Experimental | 17 | Multi-source web search + citations |
| **Visual Intelligence** | ⚠️ Experimental | 15 | Screen OCR + UI automation |
| **Code Intelligence** | ⚠️ Experimental | 17 | AST analysis + security scanning |
| **Workflow Orchestration** | ⚠️ Experimental | 16 | Multi-step automation with branching |
| **Premium UX** | ⚠️ Experimental | 21 | Conversational flow + streaming + suggestions |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Channels                         │
│  (Telegram, CLI, Discord, Slack, Signal, etc.)      │
└──────────────┬──────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────┐
│                   Gateway / Adapter                 │
│  (Message normalization, session resolution)        │
└──────────────┬──────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────┐
│              Intent Router (3-tier)                 │
│  1. Quick Patterns (< 5ms)                          │
│  2. Semantic Analysis (< 100ms)                     │
│  3. LLM Routing (when needed)                       │
└──────────────┬──────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────┐
│               Task Engine                           │
│  • Plan decomposition                               │
│  • Dependency resolution                            │
│  • Verification & validation                        │
│  • Error recovery                                   │
└──────────────┬──────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────┐
│         Execution Layer (Policy-Driven)             │
│  • Approval gates                                   │
│  • Filesystem operations (safe)                     │
│  • Terminal execution (sandboxed)                   │
│  • Remote operations                                │
└──────────────┬──────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────┐
│            Supporting Systems                       │
│  • Memory (persistent learning)                     │
│  • Cognitive layer (planning, optimization)         │
│  • Audit logging (full observability)               │
│  • Policy enforcement                               │
│  • Capability gating (feature isolation)            │
└─────────────────────────────────────────────────────┘
```

---

## Operating Modes

### OPERATOR Mode (Default, v0.1.0)

**Production-ready minimal operator.** All Phase 6 features disabled.

```bash
python -m cli.main chat
# or
export ELYAN_OPERATOR_MODE=operator
```

**What works:**
- ✅ Intent understanding
- ✅ Session management
- ✅ Task execution
- ✅ File operations (with approval)
- ✅ Terminal commands (with policy)
- ✅ Memory & learning
- ✅ Error recovery

**What doesn't:**
- ❌ Research engine
- ❌ Visual analysis
- ❌ Code intelligence
- ❌ Workflows
- ❌ Premium UX features

### ADVANCED Mode (Experimental)

Enables Phase 6 competitive features for testing and development.

```bash
export ELYAN_OPERATOR_MODE=advanced
python -m cli.main chat

# Now available:
elyan research "quantum computing"
elyan code analyze app.py
elyan screen analyze
elyan workflow run spec.json
```

---

## Configuration

### Environment Variables

```bash
# Operating mode
ELYAN_OPERATOR_MODE=operator          # default (production)
ELYAN_OPERATOR_MODE=advanced          # experimental (testing)

# LLM Provider (auto-routes: Groq → Gemini → Ollama)
GROQ_API_KEY=your-key                 # Fastest free option
GOOGLE_API_KEY=your-key               # Google Gemini
OLLAMA_BASE_URL=http://localhost:11434 # Local LLM

# Telegram Bot
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_ADMIN_IDS=123456,789012      # Admin user IDs

# Logging
LOG_LEVEL=INFO                        # DEBUG, INFO, WARNING, ERROR
```

### See Also
- [`OPERATING_MODES.md`](./OPERATING_MODES.md) — Detailed mode guide
- [`config/settings.py`](./config/settings.py) — Full configuration options

---

## Development

### Project Structure

```
elyan/
├── cli/                          # CLI commands
│   ├── main.py                   # Entry point
│   └── commands/                 # Command modules
├── core/                         # Core runtime
│   ├── agent.py                  # Main orchestrator
│   ├── task_engine.py            # Task decomposition & execution
│   ├── intent_parser.py          # Intent routing
│   ├── session_engine/           # Session management
│   ├── memory/                   # Memory system
│   ├── capability_gating.py      # Feature isolation (v0.1.0)
│   ├── cognitive/                # Phase 4-5: Cognitive layer
│   ├── phase6/                   # Phase 6: Experimental features
│   │   ├── research/             # Research engine
│   │   ├── vision/               # Visual intelligence
│   │   ├── code_intel/           # Code intelligence
│   │   ├── workflow/             # Workflow orchestration
│   │   └── ux_engine/            # Premium UX
│   └── gateway/                  # Multi-channel gateway
├── handlers/                     # Channel handlers
│   ├── telegram_handler.py       # Telegram integration
│   └── ...
├── tools/                        # Tool integrations
│   ├── code_execution_tools.py
│   ├── vision_tools.py
│   └── ...
├── tests/                        # Test suite (223+ tests)
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── test_*.py
└── README.md                     # This file
```

### Running Tests

```bash
# All tests
pytest tests/ -v

# Specific module
pytest tests/test_capability_gating.py -v

# With coverage
pytest tests/ --cov=core --cov-report=html

# Fast run (no slow tests)
pytest tests/ -m "not slow" -v
```

### Adding Features

1. **Check feature scope** — Is this operator mode or Phase 6?
2. **Write tests first** — Test-driven development
3. **Implement feature** — Follow existing patterns
4. **Update docs** — README, OPERATING_MODES.md, etc.
5. **Submit PR** — See `CONTRIBUTING.md`

---

## Releases

### v0.1.0 (Current)
- ✅ Minimal viable operator (OPERATOR mode)
- ✅ Phase 6 features (experimental via ADVANCED mode)
- ✅ Capability gating system
- ✅ Telegram integration
- ✅ 223 tests passing
- 📅 March 23, 2026

### v0.2.0 (Planned)
- Additional channel integrations
- Phase 6 features promoted to stable
- Multi-user organization mode
- 📅 Q2 2026

### Roadmap
See [`ROADMAP.md`](./ROADMAP.md) for full strategic vision and stages.

---

## Contributing

We welcome contributions! Please see [`CONTRIBUTING.md`](./CONTRIBUTING.md) for:
- Code style guidelines
- Testing requirements
- Pull request process
- Code of conduct

---

## License

This project is licensed under the MIT License — see [`LICENSE`](./LICENSE) file for details.

### MIT License Summary
- ✅ Use for any purpose (commercial, personal, educational)
- ✅ Modify and distribute
- ✅ Private use
- ⚠️ Include license and copyright notice
- ❌ No warranty provided
- ❌ No liability accepted

---

## Support

### Documentation
- [Operating Modes Guide](./OPERATING_MODES.md)
- [Architecture Document](./SYSTEM_ARCHITECTURE.md)
- [Agents & Design](./AGENTS.md)

### Issues & Bugs
Report issues at: https://github.com/emrek0ca/elyan/issues

### Discussions
Community discussions: https://github.com/emrek0ca/elyan/discussions

---

## Status

| Component | Status | Version |
|-----------|--------|---------|
| Core Operator | ✅ Production Ready | v0.1.0 |
| Phase 6 Features | ⚠️ Experimental | v0.1.0 |
| Telegram Integration | ✅ Working | v0.1.0 |
| CLI | ✅ Full Featured | v0.1.0 |
| Test Coverage | ✅ 223 tests | v0.1.0 |
| Documentation | ✅ Complete | v0.1.0 |

---

## Acknowledgments

Elyan is built on principles of:
- **Stable execution** — Correctness and safety first
- **Observable operations** — Full auditability
- **Modular architecture** — Clear boundaries, easy to extend
- **Local-first design** — Privacy and independence
- **Learning systems** — Automatic improvement over time

---

## Quick Links

- **Repository:** https://github.com/emrek0ca/elyan
- **Issues:** https://github.com/emrek0ca/elyan/issues
- **Releases:** https://github.com/emrek0ca/elyan/releases
- **License:** MIT

---

**Built with focus on reliability, safety, and real operational capability.**
