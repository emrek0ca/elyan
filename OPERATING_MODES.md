# Elyan Operating Modes

Elyan supports two operating modes to balance stability (v0.1.0) with feature richness (Advanced).

## Default: OPERATOR Mode (v0.1.0)

**Status:** ✅ **PRODUCTION READY**

The default mode provides a stable, minimal operator that:

- ✅ Handles user intent through Telegram
- ✅ Manages sessions safely
- ✅ Executes tasks with approval gates
- ✅ Operates on files and terminal safely
- ✅ Maintains memory across sessions
- ✅ Provides observable, auditable runs
- ✅ Recovers from errors gracefully

### Features in OPERATOR Mode

| Capability | Status |
|-----------|--------|
| Intent Understanding | ✅ |
| Session Management | ✅ |
| Approval Gates | ✅ |
| Filesystem Operations | ✅ |
| Terminal Execution | ✅ |
| Memory System | ✅ |
| Error Recovery | ✅ |
| Cognitive Layer (Phase 4-5) | ✅ |
| Telegram Channel | ✅ |
| **Research Engine** | ❌ |
| **Visual Intelligence** | ❌ |
| **Code Intelligence** | ❌ |
| **Workflow Orchestration** | ❌ |
| **Premium UX** | ❌ |

### Running in OPERATOR Mode (Default)

```bash
# No action needed - operator mode is the default
python -m cli.main chat

# Or explicitly set:
export ELYAN_OPERATOR_MODE=operator
python -m cli.main chat
```

---

## Optional: ADVANCED Mode (Phase 6 Experimental)

**Status:** ⚠️ **EXPERIMENTAL, NOT PRODUCTION**

Advanced mode includes all Phase 6 competitive features:

- ✅ Research Engine (multi-source web search + citations)
- ✅ Visual Intelligence (screen OCR + UI automation)
- ✅ Code Intelligence (AST analysis + security scanning)
- ✅ Workflow Orchestration (multi-step automation)
- ✅ Premium UX (conversational flow + streaming + suggestions)

### Features Added in ADVANCED Mode

| Capability | Status | Tests |
|-----------|--------|-------|
| Research Engine | ✅ | 17 |
| Visual Intelligence | ✅ | 15 |
| Code Intelligence | ✅ | 17 |
| Workflow Orchestration | ✅ | 16 |
| Premium UX | ✅ | 21 |

### Running in ADVANCED Mode

```bash
# Set environment variable and run
export ELYAN_OPERATOR_MODE=advanced
python -m cli.main chat

# Or with CLI:
ELYAN_OPERATOR_MODE=advanced elyan research "quantum computing"
ELYAN_OPERATOR_MODE=advanced elyan code analyze --language python
ELYAN_OPERATOR_MODE=advanced elyan workflow list
```

---

## Feature Isolation

The system uses **capability gating** to prevent Phase 6 features from being invoked in OPERATOR mode:

1. **Task Engine** — Skips advanced research/workflow tasks when in operator mode
2. **Intent Router** — Does not trigger Phase 6 features by default
3. **CLI Commands** — Phase 6 CLI commands work but are not exposed in default help

---

## Environment Variables

### `ELYAN_OPERATOR_MODE`

Controls which operating mode to use:

```bash
# v0.1.0 MVP (stable, minimal) — DEFAULT
ELYAN_OPERATOR_MODE=operator

# Full system with Phase 6 experimental features
ELYAN_OPERATOR_MODE=advanced
```

---

## Migration Path

**v0.1.0** ships with capability gating enabled:

```
OPERATOR mode (default) → stable baseline for production
ADVANCED mode (optional) → experimental for power users/testing
```

As Phase 6 features mature and gain production-grade testing:

```
Phase 6.1 (Research) → candidate for v0.2.0
Phase 6.2 (Vision) → candidate for v0.2.0
...and so on
```

---

## Summary

| Dimension | OPERATOR | ADVANCED |
|-----------|----------|----------|
| **Release Status** | ✅ Production Ready | ⚠️ Experimental |
| **Default** | Yes | No |
| **Feature Set** | Core operator only | Core + Phase 6 |
| **Test Coverage** | Full (80+ tests) | Full (86+ Phase 6 tests) |
| **Safe for Production** | Yes | No |
| **Recommended Use** | Real users, Telegram | Development, testing |

---

## Switching Modes

The mode can be switched at runtime via environment variable:

```bash
# Start in operator mode (default)
python -m cli.main chat

# Switch to advanced to test Phase 6
export ELYAN_OPERATOR_MODE=advanced
python -m cli.main chat

# Back to operator
unset ELYAN_OPERATOR_MODE
python -m cli.main chat
```

**Note:** Phase 6 features are only available when Mode = ADVANCED.
