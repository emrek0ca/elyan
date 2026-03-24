# TASKS.md

## Purpose

This document converts Elyan’s architecture and roadmap into concrete implementation tasks.

It is designed for:

- core developers
- coding agents
- contributors
- future maintainers

This file should be treated as an execution document, not just a planning note.

The goal is to make Elyan buildable in the correct order, with minimal ambiguity and minimal architectural drift.

---

## Global Task Rules

All tasks must follow these rules:

### 1. Respect architecture boundaries
Do not mix protocol, runtime, UI, policy, and memory concerns in the same implementation unless explicitly required.

### 2. Prefer small strong implementations
Do not build giant abstractions before the runtime need is clear.

### 3. Side effects must remain controlled
Filesystem, terminal, browser, application control, and external writes must always go through typed runtime layers.

### 4. No unsafe shortcuts
Do not bypass policy, verification, or logging just to make something “work quickly”.

### 5. Keep the system observable
Every major action should leave enough evidence for debugging and future trust.

### 6. Update docs when the architecture changes
If a task changes contracts, lifecycle, or capability behavior, update the relevant docs.

---

## Task Status Conventions

Use these status markers consistently:

- `[ ]` not started
- `[-]` in progress
- `[x]` completed
- `[!]` blocked
- `[?]` needs architecture decision

---

## Priority Model

Tasks are grouped into these priorities:

### P0 — Must exist for core correctness
Without these, Elyan is not a serious runtime.

### P1 — Must exist for safe local operation
Without these, Elyan cannot safely control the local machine.

### P2 — Must exist for continuity and usability
Without these, Elyan forgets context or becomes hard to use.

### P3 — Important for extensibility and growth
Without these, Elyan becomes harder to evolve cleanly.

### P4 — Important for premium experience and scale
Without these, Elyan may work but will not feel production-grade.

---

## Phase 1 — Core Runtime Tasks

## Goal

Build the first stable operational spine of Elyan.

---

### P0.1 Protocol Package

#### Objective
Create the shared protocol layer used across all major components.

#### Tasks

- [ ] Create `packages/protocol`
- [ ] Define base event envelope schema
- [ ] Define actor identity schema
- [ ] Define session identity schema
- [ ] Define workspace identity schema
- [ ] Define run identity schema
- [ ] Define inbound message schema
- [ ] Define streaming block schema
- [ ] Define approval request schema
- [ ] Define tool request schema
- [ ] Define tool result schema
- [ ] Define verification result schema
- [ ] Define memory write request schema
- [ ] Define node registration schema
- [ ] Define node health schema
- [ ] Export typed event unions
- [ ] Add runtime schema validation helpers
- [ ] Add protocol version constant
- [ ] Add protocol compatibility guidelines

#### Done when
- all core events are typed
- invalid payloads fail fast
- all runtime modules can share the same schemas

---

### P0.2 Shared Types Package

#### Objective
Centralize cross-cutting types that are not protocol events but are core runtime concepts.

#### Tasks

- [ ] Create `packages/shared-types`
- [ ] Define `RiskLevel`
- [ ] Define `ExecutionMode`
- [ ] Define `RunStatus`
- [ ] Define `QueuePolicy`
- [ ] Define `CapabilityName`
- [ ] Define `ActionName`
- [ ] Define `ApprovalScope`
- [ ] Define `VerificationStatus`
- [ ] Define `RollbackAvailability`
- [ ] Define `MemoryType`
- [ ] Define `NodeType`
- [ ] Define `HealthStatus`

#### Done when
- shared enums and interfaces are consistent across packages
- duplicated type definitions are removed

---

### P0.3 Gateway Skeleton

#### Objective
Create the central entrypoint that receives normalized events and routes them into Elyan’s runtime.

#### Tasks

- [ ] Create `apps/gateway`
- [ ] Set up TypeScript runtime
- [ ] Set up config loading
- [ ] Set up structured logger
- [ ] Add HTTP health endpoint
- [ ] Add WebSocket server
- [ ] Add event intake entrypoint
- [ ] Validate incoming protocol payloads
- [ ] Emit invalid payload errors cleanly
- [ ] Resolve actor metadata
- [ ] Resolve or create session
- [ ] Resolve workspace context
- [ ] Forward work to session engine
- [ ] Emit run lifecycle events
- [ ] Add basic channel response adapter
- [ ] Add internal event bus abstraction
- [ ] Add correlation IDs for logs
- [ ] Add graceful shutdown flow

#### Done when
- the gateway accepts a valid input event
- the gateway creates a session-aware run
- the gateway logs the lifecycle of the request

---

### P0.4 Session Engine v1

#### Objective
Protect Elyan from session corruption and uncontrolled concurrent task mutation.

#### Tasks

- [ ] Create `packages/session-engine`
- [ ] Define `SessionState` model
- [ ] Define `LaneState` model
- [ ] Define `QueuedEvent` model
- [ ] Define `RunState` model
- [ ] Implement `getOrCreateSession`
- [ ] Implement session metadata persistence contract
- [ ] Implement per-session lane lock
- [ ] Implement basic queue
- [ ] Implement `followup` queue policy
- [ ] Implement `interrupt` policy placeholder
- [ ] Implement `merge` policy placeholder
- [ ] Implement session checkpoint structure
- [ ] Add session summary field
- [ ] Add active run pointer
- [ ] Add run cancellation state
- [ ] Add queue inspection methods
- [ ] Add tests for concurrent event intake
- [ ] Add tests for lane locking behavior

#### Done when
- the same session does not run uncontrolled parallel mutations
- follow-up events can queue safely
- the active run and pending work are inspectable

---

### P0.5 Run Lifecycle Manager

#### Objective
Represent work as explicit runs with consistent states.

#### Tasks

- [ ] Create `packages/runtime`
- [ ] Define `RunStatus` transitions
- [ ] Implement `RunCreated`
- [ ] Implement `RunQueued`
- [ ] Implement `RunStarted`
- [ ] Implement `RunWaitingForApproval`
- [ ] Implement `RunExecuting`
- [ ] Implement `RunVerifying`
- [ ] Implement `RunCompleted`
- [ ] Implement `RunFailed`
- [ ] Implement `RunCancelled`
- [ ] Enforce valid status transitions
- [ ] Add lifecycle timestamps
- [ ] Add run duration calculation
- [ ] Add failure reason shape
- [ ] Add retry metadata placeholder
- [ ] Add run checkpoint placeholder
- [ ] Add unit tests for transition correctness

#### Done when
- every request becomes a trackable run
- the system can explain current run status at any time

---

### P0.6 Observability Base

#### Objective
Make the system inspectable from the beginning.

#### Tasks

- [ ] Create `packages/observability`
- [ ] Define log event shape
- [ ] Add structured logger factory
- [ ] Add request-scoped logging
- [ ] Add session-scoped logging
- [ ] Add run-scoped logging
- [ ] Add event log helpers
- [ ] Add error classification helper
- [ ] Add timing measurement helper
- [ ] Add basic metric counters
- [ ] Add metric names for:
  - [ ] run_started
  - [ ] run_completed
  - [ ] run_failed
  - [ ] approval_requested
  - [ ] tool_invoked
  - [ ] verification_failed
- [ ] Add local console logger for development
- [ ] Define future sink interface for files / DB / telemetry backend

#### Done when
- core runtime actions produce consistent logs
- failures are visible and classifiable

---

## Phase 2 — Safe Local Computer Control

## Goal

Enable Elyan to operate on the local machine safely through a persistent Desktop Agent.

---

### P1.1 Desktop Agent Skeleton

#### Objective
Build the local runtime that will execute machine actions.

#### Tasks

- [ ] Create `apps/desktop-agent`
- [ ] Set up local config loading
- [ ] Set up structured logger
- [ ] Add persistent WebSocket client to Gateway
- [ ] Add reconnect strategy
- [ ] Add heartbeat / health ping
- [ ] Add node registration payload
- [ ] Add capability advertisement payload
- [ ] Add action receive handler
- [ ] Add action acknowledgement events
- [ ] Add action progress event support
- [ ] Add action completion event support
- [ ] Add action failure event support
- [ ] Add local graceful shutdown flow
- [ ] Add local panic recovery logging

#### Done when
- the Desktop Agent can connect to the gateway
- the gateway knows which capabilities the local node provides

---

### P1.2 Filesystem Capability v1

#### Objective
Implement the first serious computer-control capability.

#### Tasks

- [ ] Create `packages/capability-filesystem`
- [ ] Define filesystem action schemas
- [ ] Implement `filesystem.list`
- [ ] Implement `filesystem.stat`
- [ ] Implement `filesystem.read_text`
- [ ] Implement `filesystem.create_file`
- [ ] Implement `filesystem.create_folder`
- [ ] Implement `filesystem.write_text`
- [ ] Implement `filesystem.patch_text`
- [ ] Implement `filesystem.rename`
- [ ] Implement `filesystem.move`
- [ ] Implement `filesystem.copy`
- [ ] Implement `filesystem.trash`
- [ ] Implement `filesystem.restore` placeholder
- [ ] Implement `filesystem.search` placeholder
- [ ] Normalize file metadata result shape
- [ ] Add dry-run support for rename / move / patch / trash
- [ ] Add atomic write behavior where applicable
- [ ] Add snapshot support for patch rollback
- [ ] Add tests for each action
- [ ] Add tests for invalid path input

#### Done when
- Elyan can safely perform basic file operations through typed actions
- actions are predictable and testable

---

### P1.3 Terminal Capability v1

#### Objective
Enable Elyan to run terminal commands through a controlled execution path.

#### Tasks

- [ ] Create `packages/capability-terminal`
- [ ] Define terminal action schemas
- [ ] Implement `terminal.exec`
- [ ] Implement `terminal.cancel`
- [ ] Implement stdout capture
- [ ] Implement stderr capture
- [ ] Implement exit code capture
- [ ] Implement cwd validation
- [ ] Implement execution timeout support
- [ ] Add streaming output support
- [ ] Add environment filtering
- [ ] Add command classification helper
- [ ] Add tests for success case
- [ ] Add tests for failing command
- [ ] Add tests for timeout case
- [ ] Add tests for invalid working directory

#### Done when
- terminal execution is controlled, inspectable, and cancellable
- results include enough detail for verification

---

### P1.4 Policy Engine v1

#### Objective
Insert a hard safety barrier between plan generation and machine execution.

#### Tasks

- [ ] Create `packages/policy-engine`
- [ ] Define policy input shape
- [ ] Define policy decision shape
- [ ] Define `allow`
- [ ] Define `allow_with_logging`
- [ ] Define `require_preview`
- [ ] Define `require_approval`
- [ ] Define `deny`
- [ ] Implement allowed roots check
- [ ] Implement sensitive path pattern protection
- [ ] Implement destructive action detection
- [ ] Implement bulk operation threshold check
- [ ] Implement terminal risk classification
- [ ] Implement protected file heuristics
- [ ] Implement policy reason reporting
- [ ] Add tests for each major rule path

#### Done when
- risky actions cannot silently pass into execution
- policy decisions are explainable

---

### P1.5 Verification Layer v1

#### Objective
Confirm that machine actions actually succeeded.

#### Tasks

- [ ] Create verification module in `packages/runtime` or dedicated package
- [ ] Define verification request shape
- [ ] Define verification result shape
- [ ] Implement file existence verification
- [ ] Implement file content verification
- [ ] Implement move verification
- [ ] Implement rename verification
- [ ] Implement trash verification
- [ ] Implement terminal exit code verification
- [ ] Implement expected artifact existence verification
- [ ] Implement partial failure reporting
- [ ] Add tests for positive and negative cases

#### Done when
- Elyan no longer assumes side effects succeeded without checking

---

### P1.6 Rollback Base

#### Objective
Make reversible actions safer to perform.

#### Tasks

- [ ] Define rollback metadata shape
- [ ] Add rollback record creation for rename
- [ ] Add rollback record creation for move
- [ ] Add rollback record creation for patch_text
- [ ] Add rollback record creation for trash where possible
- [ ] Add snapshot storage location
- [ ] Implement `canRollback` helper
- [ ] Implement rollback placeholder executor
- [ ] Add tests for metadata correctness

#### Done when
- reversible actions preserve enough information to attempt recovery

---

## Phase 3 — Memory and Context Tasks

## Goal

Make Elyan capable of continuing work across time and projects.

---

### P2.1 Memory Package v1

#### Objective
Create Elyan’s readable, auditable memory system.

#### Tasks

- [ ] Create `packages/memory`
- [ ] Define `MemoryType`
- [ ] Define memory record schema
- [ ] Define memory write request schema
- [ ] Create memory file helpers
- [ ] Implement profile memory writer
- [ ] Implement project memory writer
- [ ] Implement daily summary writer
- [ ] Implement run log writer
- [ ] Create directory bootstrap helpers
- [ ] Implement safe file append/update helpers
- [ ] Add tests for memory file generation
- [ ] Add tests for duplicate prevention basics

#### Done when
- memory is stored in readable files with consistent structure

---

### P2.2 Memory Promotion Pipeline

#### Objective
Prevent memory from becoming low-value noise.

#### Tasks

- [ ] Implement candidate extraction from run output
- [ ] Implement usefulness scoring
- [ ] Implement duplication detection
- [ ] Implement sensitivity filter
- [ ] Implement memory routing by type
- [ ] Implement rejection logging for discarded candidates
- [ ] Add tests for promotion logic
- [ ] Add tests for sensitivity downgrade cases

#### Done when
- useful facts are promoted
- junk is filtered out

---

### P2.3 Session Summaries

#### Objective
Allow Elyan to continue a session without replaying everything.

#### Tasks

- [ ] Define session summary shape
- [ ] Implement summary generation hook at run completion
- [ ] Capture:
  - [ ] intent
  - [ ] actions taken
  - [ ] files changed
  - [ ] pending work
  - [ ] key decisions
- [ ] Store summary in session state
- [ ] Update context engine to consume session summary
- [ ] Add tests for summary generation

#### Done when
- sessions can be resumed with concise operational awareness

---

### P2.4 Context Engine v1

#### Objective
Assemble the right context for each run without flooding the model.

#### Tasks

- [ ] Create `packages/context-engine`
- [ ] Define context assembly input
- [ ] Define context block types
- [ ] Implement system rules injection
- [ ] Implement user intent block
- [ ] Implement session summary block
- [ ] Implement recent transcript block
- [ ] Implement project memory block
- [ ] Implement workspace facts block
- [ ] Implement retrieved records block
- [ ] Implement recent tool result block
- [ ] Implement block prioritization
- [ ] Implement token budget trimming
- [ ] Add tests for block ordering
- [ ] Add tests for context compaction

#### Done when
- context is relevant, bounded, and reproducible

---

### P2.5 Retrieval v1

#### Objective
Enable Elyan to pull useful prior information into current work.

#### Tasks

- [ ] Define retrieval interface
- [ ] Implement retrieval over project memory
- [ ] Implement retrieval over daily summaries
- [ ] Implement retrieval over recent run logs
- [ ] Implement keyword-based matching baseline
- [ ] Add scoring placeholder for semantic retrieval
- [ ] Add tests for retrieval correctness

#### Done when
- Elyan can find prior relevant project facts without brute-forcing full history

---

## Phase 4 — Extensibility and Capability Growth Tasks

## Goal

Turn Elyan into a modular platform instead of a tightly coupled system.

---

### P3.1 Capability Registry

#### Objective
Standardize how capabilities are declared and discovered.

#### Tasks

- [ ] Create registry package or module
- [ ] Define capability manifest shape
- [ ] Define action manifest shape
- [ ] Register filesystem capability
- [ ] Register terminal capability
- [ ] Add risk metadata registration
- [ ] Add verification handler registration
- [ ] Add rollback handler registration
- [ ] Add capability lookup API
- [ ] Add tests for registry correctness

#### Done when
- capabilities can be discovered and used in a standard way

---

### P3.2 Plugin Kit v1

#### Objective
Allow new features to enter Elyan without hacking the core.

#### Tasks

- [ ] Create `packages/plugin-kit`
- [ ] Define plugin manifest
- [ ] Define plugin lifecycle hooks
- [ ] Define plugin config schema
- [ ] Define plugin health check interface
- [ ] Support capability contribution
- [ ] Support integration contribution
- [ ] Support channel adapter contribution
- [ ] Add plugin loader skeleton
- [ ] Add tests for plugin contract validation

#### Done when
- future extensions can be added through a controlled contract

---

### P3.3 Applications Capability v1

#### Objective
Control local apps in a typed and policy-aware way.

#### Tasks

- [ ] Create `packages/capability-applications`
- [ ] Define `applications.open`
- [ ] Define `applications.close`
- [ ] Define `applications.focus`
- [ ] Define `applications.list_running`
- [ ] Define `applications.get_frontmost`
- [ ] Implement macOS adapter baseline
- [ ] Add tests for schema validation
- [ ] Add integration tests where feasible

#### Done when
- Elyan can perform basic application control through a typed capability

---

### P3.4 Browser Capability v1

#### Objective
Add controlled browser operations for research and simple workflows.

#### Tasks

- [ ] Create `packages/capability-browser`
- [ ] Define `browser.open_url`
- [ ] Define `browser.extract_page`
- [ ] Define `browser.download`
- [ ] Define `browser.fill_form` placeholder
- [ ] Define safe interaction rules
- [ ] Implement adapter abstraction
- [ ] Add tests for schemas and baseline flows

#### Done when
- browser operations fit into the same runtime and policy model as other capabilities

---

### P3.5 Clipboard and Screen Capability

#### Objective
Give Elyan more useful desktop operator power.

#### Tasks

- [ ] Create `packages/capability-screen`
- [ ] Add screenshot action
- [ ] Add active window detection
- [ ] Create clipboard module or capability
- [ ] Add clipboard read
- [ ] Add clipboard write
- [ ] Add tests for capability schemas

#### Done when
- Elyan can access basic visual and clipboard context safely

---

### P3.6 Node Registry v1

#### Objective
Prepare Elyan for multi-node routing.

#### Tasks

- [ ] Define node state model
- [ ] Define capability advertisement model
- [ ] Implement node registration store
- [ ] Implement node health updates
- [ ] Implement node availability status
- [ ] Implement basic node lookup by capability
- [ ] Add tests for registry behavior

#### Done when
- Elyan can track which nodes exist and what they can do

---

## Phase 5 — Premium Operator UX Tasks

## Goal

Expose Elyan’s operational behavior through a serious command center.

---

### P4.1 Command Center Skeleton

#### Objective
Build the baseline admin/operator UI.

#### Tasks

- [ ] Create `apps/admin-web`
- [ ] Set up application shell
- [ ] Add authentication placeholder
- [ ] Add sessions list view
- [ ] Add runs list view
- [ ] Add run status cards
- [ ] Add recent failures panel
- [ ] Add active nodes panel
- [ ] Add pending approvals panel
- [ ] Add live refresh or subscription layer

#### Done when
- the operator can see what Elyan is currently doing

---

### P4.2 Run Inspector

#### Objective
Make each run inspectable in detail.

#### Tasks

- [ ] Add run details page
- [ ] Show run lifecycle timeline
- [ ] Show tool/capability steps
- [ ] Show policy decisions
- [ ] Show verification results
- [ ] Show files affected
- [ ] Show rollback metadata if present
- [ ] Show errors and retry attempts
- [ ] Add structured JSON debug view where helpful

#### Done when
- a run can be debugged visually without reading raw logs only

---

### P4.3 Approval UI

#### Objective
Create a first-class interface for human-in-the-loop control.

#### Tasks

- [ ] Show pending approval requests
- [ ] Show risk level
- [ ] Show preview or dry-run result
- [ ] Add approve action
- [ ] Add deny action
- [ ] Add approve once
- [ ] Add approve for session placeholder
- [ ] Add approval audit trail view

#### Done when
- risky actions can be controlled from the UI cleanly

---

### P4.4 Memory Timeline

#### Objective
Expose what Elyan remembers and why.

#### Tasks

- [ ] Add memory events view
- [ ] Add project memory panel
- [ ] Add daily summary panel
- [ ] Add recent decisions panel
- [ ] Add run-to-memory linkage
- [ ] Add filtering by memory type

#### Done when
- memory is no longer hidden and mysterious

---

### P4.5 Metrics and Cost Views

#### Objective
Make performance and cost visible.

#### Tasks

- [ ] Add task success metric card
- [ ] Add failure metric card
- [ ] Add median latency card
- [ ] Add approval rate card
- [ ] Add retry rate card
- [ ] Add token usage view
- [ ] Add cost per successful task view
- [ ] Add queue backlog view

#### Done when
- operator quality can be evaluated from the UI

---

### P4.6 Computer Use Tool

#### Objective
Build a robust, approval-gated system for UI automation via screenshots and typed actions.

#### Status
✓ COMPLETE (104 tests, 100% passing)

#### Subtasks
- [x] Vision Module (320 lines, 18 tests) — Screenshot capture, OCR, layout tree
- [x] Executor Module (380 lines, 24 tests) — 10 action types, real-time verification
- [x] Planner Module (350 lines, 20 tests) — LLM-driven action sequencing
- [x] Evidence Recorder (260 lines, 16 tests) — Screenshots, action trace (JSONL), metadata
- [x] Approval Engine (400 lines, 20 tests) — 4-level approval gating (AUTO/CONFIRM/SCREEN/TWO_FA)
- [x] REST API (200 lines, 6 tests) — Unified interface, task management

#### Done when
- Computer Use Tool fully integrated with ApprovalEngine
- All 104 tests passing
- Evidence audit trail complete

---

### P4.7 ControlPlane Integration

#### Objective
Wire Computer Use Tool into main agent execution loop with scheduling and approval workflow.

#### Status
IN PROGRESS (Day 5)

#### Subtasks
- [ ] Router Integration (50 lines) — Detect/route computer_use actions
- [ ] Task Scheduling (80 lines) — Queue management, parallel vision analysis
- [ ] Approval Workflow (250 lines) — Request flow, user learning
- [ ] Session State (30 lines) — Preserve automation state across followups
- [ ] Integration Tests (200 lines) — Full workflow validation

#### Dependencies
- P4.6 (Computer Use Tool)

#### Estimated Effort
3-4 sessions

---

### P4.8 Dashboard Widgets

#### Objective
Expose Computer Use through admin dashboard with real-time visualization.

#### Status
PENDING

#### Subtasks
- [ ] Action Timeline Widget (200 lines) — Sequence visualization
- [ ] Evidence Viewer (300 lines) — Before/after screenshots + playback
- [ ] Approval Queue Panel (150 lines) — Pending approvals, 2FA UI
- [ ] Metrics Card (100 lines) — Success rate, latency, accuracy
- [ ] Integration Tests (200 lines)

#### Dependencies
- P4.6 (Computer Use Tool)
- P4.7 (ControlPlane Integration)

#### Estimated Effort
2-3 sessions

---

## Phase 6 — Hardening and Reliability Tasks

## Goal

Make Elyan stable enough for repeated real-world use.

---

### P4.6 Failure Taxonomy

#### Objective
Classify failures instead of handling them ad hoc.

#### Tasks

- [ ] Define error classes for:
  - [ ] schema failure
  - [ ] session failure
  - [ ] planner failure
  - [ ] policy denial
  - [ ] capability failure
  - [ ] verification failure
  - [ ] timeout
  - [ ] node unavailable
  - [ ] memory write failure
- [ ] Add structured error payloads
- [ ] Add error-to-user-message mapping
- [ ] Add error-to-retry-policy mapping

#### Done when
- failures are systematic and explainable

---

### P4.7 Retry and Recovery

#### Objective
Recover from appropriate failures without creating chaos.

#### Tasks

- [ ] Define retryable vs non-retryable errors
- [ ] Implement retry metadata
- [ ] Implement bounded retry count
- [ ] Implement backoff placeholder
- [ ] Add retry visibility in run inspector
- [ ] Add recovery suggestion hooks
- [ ] Add tests for retry boundaries

#### Done when
- recovery behavior is intentional, not accidental

---

### P4.8 Checkpoint and Resume

#### Objective
Allow longer tasks to survive interruptions.

#### Tasks

- [ ] Define checkpoint shape
- [ ] Save checkpoint after major run steps
- [ ] Restore run from checkpoint
- [ ] Prevent invalid resume attempts
- [ ] Add checkpoint visibility in run inspector
- [ ] Add tests for checkpoint restore

#### Done when
- long-running flows can resume safely after interruption

---

### P4.9 Local File Indexing

#### Objective
Make Elyan fast at finding relevant files on the local machine.

#### Tasks

- [ ] Add SQLite to Desktop Agent
- [ ] Define file index schema
- [ ] Index:
  - [ ] path
  - [ ] filename
  - [ ] extension
  - [ ] size
  - [ ] modified_at
  - [ ] workspace tag
- [ ] Add file watcher updates
- [ ] Add initial crawl strategy
- [ ] Add search API for agent use
- [ ] Add tests for index updates

#### Done when
- Elyan does not need to brute-force the filesystem for every search

---

### P4.10 Hardening Tests

#### Objective
Protect the architecture from regressions.

#### Tasks

- [ ] Add session isolation tests
- [ ] Add filesystem safety tests
- [ ] Add policy enforcement tests
- [ ] Add verification correctness tests
- [ ] Add rollback metadata tests
- [ ] Add reconnect tests for Desktop Agent
- [ ] Add run lifecycle regression tests
- [ ] Add memory promotion tests

#### Done when
- the most dangerous regressions are covered

---

## Suggested Immediate Sprint Backlog

## Sprint 1 — Core Skeleton

- [ ] Create monorepo structure
- [ ] Create `packages/protocol`
- [ ] Create `packages/shared-types`
- [ ] Create `apps/gateway`
- [ ] Create `packages/session-engine`
- [ ] Create `packages/runtime`
- [ ] Create `packages/observability`
- [ ] Implement base schemas
- [ ] Implement gateway event intake
- [ ] Implement session creation
- [ ] Implement run lifecycle skeleton
- [ ] Implement structured logging baseline

### Sprint 1 success condition
A valid user input becomes a logged, session-aware run.

---

## Sprint 2 — Desktop Agent and Filesystem

- [ ] Create `apps/desktop-agent`
- [ ] Implement gateway connection
- [ ] Implement node registration
- [ ] Implement heartbeat
- [ ] Create `packages/capability-filesystem`
- [ ] Implement basic filesystem actions
- [ ] Add dry-run basics
- [ ] Add allowed roots config
- [ ] Add policy engine baseline
- [ ] Add verification for filesystem writes

### Sprint 2 success condition
Elyan can safely perform basic local file operations through the Desktop Agent.

---

## Sprint 3 — Terminal and Safety

- [ ] Create `packages/capability-terminal`
- [ ] Implement exec + capture + timeout
- [ ] Expand policy classification
- [ ] Add approval pathway
- [ ] Add run waiting-for-approval state
- [ ] Add rollback metadata baseline
- [ ] Add tests for terminal and policy paths

### Sprint 3 success condition
Elyan can run local terminal actions through a controlled, inspectable path.

---

## Sprint 4 — Memory and Context

- [ ] Create `packages/memory`
- [ ] Implement memory directory bootstrap
- [ ] Implement run log writer
- [ ] Implement project memory writer
- [ ] Implement session summaries
- [ ] Create `packages/context-engine`
- [ ] Implement first context assembly pipeline
- [ ] Add retrieval over memory files

### Sprint 4 success condition
Elyan can continue project work across sessions with useful memory support.

---

## Sprint 5 — Command Center Baseline

- [ ] Create `apps/admin-web`
- [ ] Add sessions view
- [ ] Add runs view
- [ ] Add run details page
- [ ] Add pending approvals panel
- [ ] Add nodes health panel
- [ ] Add basic metrics cards

### Sprint 5 success condition
The operator can see what Elyan is doing in near real time.

---

## Open Architecture Decisions

These items may require explicit decisions before deeper implementation.

- [?] Which database should store runtime state first: Postgres or SQLite-first hybrid?
- [?] Which transport should be primary for gateway-to-agent communication beyond WebSocket fallback?
- [?] Which macOS integration layer should be used first for application control?
- [?] How should approval scopes be persisted across sessions?
- [?] What is the first supported browser integration path?
- [?] Which model providers are first-class in v1?
- [?] Which retrieval method should remain default before semantic indexing is introduced?

---

## Anti-Tasks

The following should not be prioritized before the core is stable:

- [ ] flashy UI-only demos without runtime depth
- [ ] uncontrolled full-device automation
- [ ] broad plugin explosion before capability registry exists
- [ ] complex multi-agent improvisation before session integrity is stable
- [ ] heavy semantic memory systems before readable memory works
- [ ] large-scale organization features before local-first operator workflows are stable

These are intentionally lower priority because they can create architectural debt early.

---

## Definition of Done for Any Task

A task is only done if:

- the implementation fits the documented architecture
- side effects are controlled
- inputs are typed
- errors are handled clearly
- logs exist
- tests exist where risk justifies them
- docs are updated if the architecture changed
- the implementation does not weaken safety or session integrity

---

## Contributor Execution Checklist

Before starting a task:

- [ ] Identify which layer the task belongs to
- [ ] Read relevant architecture docs
- [ ] Confirm whether the task touches side effects
- [ ] Confirm whether policy changes are needed
- [ ] Confirm whether verification is needed
- [ ] Confirm whether new events or schemas are needed

Before marking a task done:

- [ ] Inputs validated
- [ ] Outputs typed
- [ ] Logs added
- [ ] Failure path considered
- [ ] Tests added or updated
- [ ] Docs updated if necessary
- [ ] No unsafe shortcut introduced

---

## Final Directive

Do not treat this file as a loose wishlist.

This file is the execution contract for building Elyan in the correct order.

Always prioritize:

1. stable runtime
2. safe local execution
3. auditable memory
4. modular extensibility
5. premium operator visibility

If in doubt, choose the task that improves correctness, safety, or observability first.