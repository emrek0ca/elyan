
## Purpose

This document records the major architectural, product, runtime, safety, and implementation decisions for Elyan.

It exists to answer questions like:

- why was this architecture chosen?
- why does this layer exist?
- why was one tradeoff accepted over another?
- which decisions are stable?
- which decisions are provisional?
- what must future contributors preserve?

This file should be treated as a living decision log.

It is not a brainstorming file.  
It is not a scratchpad.  
It is a durable record of decisions that shape the system.

---

## How to Use This File

A new entry should be added when one of the following happens:

- a core architectural decision is made
- a boundary between layers changes
- a safety policy changes materially
- a capability model changes
- a persistence model changes
- a transport or protocol decision changes
- an important tradeoff is accepted
- a previous decision is replaced or deprecated

Do not create entries for minor implementation details unless they have system-wide implications.

---

## Status Values

Each decision must have one of these statuses:

- `proposed`
- `accepted`
- `in_progress`
- `deprecated`
- `replaced`
- `rejected`

---

## Decision Template

Use this template for future entries:

```md
## ADR-XXX — Title

**Status:** proposed | accepted | in_progress | deprecated | replaced | rejected  
**Date:** YYYY-MM-DD  
**Owners:** name / team / role  
**Related Docs:** AGENTS.md, SYSTEM_ARCHITECTURE.md, ROADMAP.md, TASKS.md  
**Replaces:** ADR-XXX (optional)  
**Replaced By:** ADR-XXX (optional)

### Context
What problem or pressure caused this decision?

### Decision
What was decided?

### Rationale
Why is this the correct decision right now?

### Alternatives Considered
What other options were considered and why were they not chosen?

### Consequences
What becomes easier, harder, or required because of this decision?

### Follow-up Work
What tasks, modules, docs, or migrations must happen because of this decision?
Decision-Making Principles

All decisions recorded here should align with these priorities:

correctness over demo appeal
safety over speed of reckless execution
observability over hidden behavior
modularity over convenience hacks
local-first execution for machine control
explicit policy over implicit trust
readable memory over opaque memory-only systems
runtime stability over premature feature expansion
Active Decisions
ADR-001 — Elyan is an operator runtime, not a chatbot

Status: accepted
Date: 2026-03-22
Owners: Elyan core
Related Docs: AGENTS.md, SYSTEM_ARCHITECTURE.md, ROADMAP.md

Context

There is a major architectural difference between a conversational assistant and a digital operator. A chatbot mostly produces text. A digital operator must manage state, sessions, tools, memory, and real actions.

Without a clear decision here, the system risks becoming a prompt-heavy assistant with weak operational behavior.

Decision

Elyan is defined as a local-first, multi-session, multi-channel digital operator runtime.

It is not a single chatbot loop.
It is not a UI-first AI demo.
It is not a raw tool-calling wrapper around a model.

Rationale

This decision keeps the product aligned with real operational value:

real task execution
machine control
session continuity
auditable memory
approval-based autonomy
extensible capability architecture
Alternatives Considered
Build Elyan as a simple chatbot with tool support
Build Elyan as a single desktop assistant process
Build Elyan as a UI shell around model prompts

These were rejected because they do not scale cleanly into a reliable operator platform.

Consequences

This decision requires:

explicit run lifecycle
session engine
policy engine
capability runtime
memory model
observability layer
desktop agent for local actions
Follow-up Work
preserve operator terminology across docs
avoid chatbot-centric shortcuts in runtime design
keep execution and safety central to the product
ADR-002 — Local machine control must happen through a persistent Desktop Agent

Status: accepted
Date: 2026-03-22
Owners: Elyan core
Related Docs: SYSTEM_ARCHITECTURE.md, ROADMAP.md, TASKS.md

Context

Elyan needs to manipulate files, run terminal commands, inspect local state, and eventually control apps and browser flows. These actions require low latency, local permissions, and durable local execution.

Using a remote-only runtime for local computer control would create poor latency, weak permission boundaries, brittle execution, and unnecessary trust problems.

Decision

All local machine actions must go through a long-lived Desktop Agent running on the user’s machine.

The model must not directly execute local operating system actions.
The Gateway must not directly impersonate the local operating system.
The Desktop Agent is the execution authority for local capabilities.

Rationale

This architecture supports:

lower latency
stronger permission control
local policy enforcement
safer filesystem and terminal behavior
better observability of local actions
future offline or degraded network capability
Alternatives Considered
Direct OS access from the main app
Remote-only execution from the gateway
Model-driven direct shell execution

These were rejected due to safety, reliability, and architecture concerns.

Consequences

This decision requires:

persistent gateway-to-agent communication
node registration
action acknowledgements
heartbeat/health model
local logging
local policy support
Follow-up Work
implement Desktop Agent v1
define capability advertisement contract
define reconnect and health behavior
ADR-003 — Per-session lane locking is mandatory

Status: accepted
Date: 2026-03-22
Owners: Elyan runtime
Related Docs: AGENTS.md, SYSTEM_ARCHITECTURE.md, TASKS.md

Context

A multi-session operator must prevent state corruption caused by uncontrolled concurrent work. If multiple runs mutate the same session state at once, file operations, memory updates, approvals, and run summaries can become inconsistent.

Decision

Each session must have an explicit lane with controlled run execution.

By default:

one side-effectful run may actively mutate a session at a time
new events enter a queue
queue policies determine follow-up behavior
Rationale

This protects:

state integrity
file operation order
memory coherence
approval handling
replayability
debugging clarity
Alternatives Considered
fully parallel execution within the same session
“best effort” merging without lane state
stateless task handling

These were rejected because they increase corruption risk and make runtime behavior harder to trust.

Consequences

This decision requires:

session state model
lane locks
queue policies
active run pointers
checkpoint handling
explicit interrupt rules
Follow-up Work
implement Session Engine v1
implement followup queue policy first
add tests for concurrent event intake
ADR-004 — All important system boundaries must be typed and schema-validated

Status: accepted
Date: 2026-03-22
Owners: Elyan protocol/runtime
Related Docs: AGENTS.md, SYSTEM_ARCHITECTURE.md, TASKS.md

Context

Unvalidated payloads lead to hidden bugs, unsafe assumptions, weak plugin contracts, and hard-to-debug failures.

Decision

Elyan will use typed contracts and runtime schema validation for:

inbound events
session resolution data
run lifecycle events
capability actions
tool results
approval requests
verification outputs
memory write requests
node registration

TypeScript is the default language for core runtime code.
Zod or an equivalent validation layer is the preferred baseline.

Rationale

Typed boundaries improve:

correctness
interoperability
plugin safety
log reliability
testability
future migrations
Alternatives Considered
loosely typed JSON-only payloads
compile-time types without runtime validation
implicit payload conventions

These were rejected because Elyan is a runtime system with multiple moving parts and safety-sensitive actions.

Consequences

This decision requires:

a dedicated protocol package
shared type definitions
versioned event shapes
fast failure on invalid payloads
Follow-up Work
implement packages/protocol
implement packages/shared-types
enforce validation at all major entrypoints
ADR-005 — Side effects must be isolated behind capability runtimes

Status: accepted
Date: 2026-03-22
Owners: Elyan core/runtime
Related Docs: AGENTS.md, SYSTEM_ARCHITECTURE.md

Context

Filesystem writes, terminal execution, application control, and external mutations are not ordinary function calls. They are side effects and must be treated as high-impact runtime actions.

Decision

All side-effectful operations must happen through explicit capability runtimes and typed actions.

Examples:

filesystem.write_text
filesystem.rename
terminal.exec
applications.open
browser.download

The model never receives raw unrestricted OS power.

Rationale

This makes it possible to add:

policy checks
verification
logging
rollback metadata
action-level testing
safer plugin growth
Alternatives Considered
helper functions scattered across the app
direct shell execution from planner output
direct filesystem access from unrelated modules

These were rejected because they destroy auditability and weaken safety.

Consequences

This decision requires:

capability registry
action manifests
verification hooks
rollback hooks
risk metadata
Follow-up Work
implement filesystem capability first
implement terminal capability second
define capability registry
ADR-006 — Policy must sit between planning and execution

Status: accepted
Date: 2026-03-22
Owners: Elyan safety/runtime
Related Docs: SYSTEM_ARCHITECTURE.md, TASKS.md

Context

A model can suggest an action, but that does not mean the system should perform it automatically. Some actions require preview, approval, or denial.

Decision

The Policy Engine is a mandatory layer between planner output and execution.

Policy decisions must be able to:

allow
allow with logging
require preview
require approval
deny
Rationale

This protects the system from unsafe autonomy and allows Elyan to act in a controlled, explainable manner.

Alternatives Considered
allow planner to call capabilities directly
use only prompt instructions as safety
ask approval for everything

These were rejected because they are either unsafe or too restrictive.

Consequences

This decision requires:

risk classification
allowed roots
sensitive path protection
approval workflow
policy reason reporting
Follow-up Work
implement Policy Engine v1
connect policy decisions to run lifecycle
expose approvals in UI
ADR-007 — Filesystem operations must default to safe behavior

Status: accepted
Date: 2026-03-22
Owners: Elyan local-runtime
Related Docs: AGENTS.md, SYSTEM_ARCHITECTURE.md, TASKS.md

Context

File operations are among the most useful and most dangerous actions Elyan can perform. Uncontrolled writes, deletes, and moves can destroy work quickly.

Decision

Filesystem behavior must follow these defaults:

writes should prefer atomic patterns where applicable
destructive operations should prefer trash over permanent delete
bulk changes should support dry-run
sensitive paths are protected
verification is required after important mutations
reversible actions should preserve rollback metadata
Rationale

This reduces the probability and impact of operational mistakes.

Alternatives Considered
direct overwrite everywhere
hard delete by default
no preview for bulk changes
best-effort file operations without verification

These were rejected because they are not acceptable for a trusted digital operator.

Consequences

This decision requires:

atomic write helpers
trash/restore behavior
dry-run support
rollback metadata
verification checks
Follow-up Work
implement filesystem capability v1
add patch snapshots
add bulk threshold rules in policy engine
ADR-008 — Terminal execution is allowed, but only through a controlled adapter

Status: accepted
Date: 2026-03-22
Owners: Elyan runtime/local-exec
Related Docs: SYSTEM_ARCHITECTURE.md, TASKS.md

Context

Terminal access is essential for development workflows, system inspection, build steps, and automation. It is also dangerous.

Decision

Elyan will support terminal execution, but only through a controlled terminal capability that enforces:

working directory checks
environment filtering
timeout support
stdout/stderr capture
exit code capture
risk classification
approval for dangerous commands when required
Rationale

Terminal power is necessary, but it must be observable and bounded.

Alternatives Considered
no terminal support
unrestricted shell execution
direct command strings executed from model output

These were rejected because they are either too weak or too unsafe.

Consequences

This decision requires:

terminal capability package
command classification
cancellation support
verification rules
policy integration
Follow-up Work
implement terminal capability v1
define high-risk command classes
test failure, timeout, and cancellation paths
ADR-009 — Memory must be hybrid and auditable

Status: accepted
Date: 2026-03-22
Owners: Elyan memory/core
Related Docs: AGENTS.md, SYSTEM_ARCHITECTURE.md, ROADMAP.md

Context

A powerful operator needs memory, but opaque memory-only systems are hard to trust, hard to edit, and hard to inspect.

Decision

Elyan will use a hybrid memory approach:

readable file-based memory as source of truth
optional indexing and retrieval on top
distinct memory types for profile, project, episodic, and run logs
Rationale

This supports both human inspectability and machine usefulness.

Alternatives Considered
vector-only memory
database-only hidden memory
no explicit long-lived memory design

These were rejected because they either reduce auditability or reduce continuity.

Consequences

This decision requires:

memory directory structure
promotion rules
deduplication logic
memory write events
retrieval layer
Follow-up Work
implement packages/memory
implement memory promotion pipeline
implement retrieval over readable stores
ADR-010 — Memory should be selective, not exhaustive

Status: accepted
Date: 2026-03-22
Owners: Elyan memory/runtime
Related Docs: ROADMAP.md, TASKS.md

Context

Storing everything creates memory pollution, duplication, and low-signal retrieval.

Decision

Only useful, durable, scoped facts should be promoted into long-lived memory.

Memory candidates must be evaluated for:

usefulness
persistence value
sensitivity
duplication
correct target memory type
Rationale

High-quality memory is more valuable than high-volume memory.

Alternatives Considered
store all conversations
store all tool outputs
store all run summaries permanently

These were rejected because they degrade retrieval quality and system clarity.

Consequences

This decision requires:

candidate extraction
scoring
sensitivity filtering
memory routing
discard logging
Follow-up Work
implement memory promotion pipeline
add duplicate detection
add summary-driven retention
ADR-011 — The first core capability set is filesystem plus terminal

Status: accepted
Date: 2026-03-22
Owners: Elyan core/product
Related Docs: ROADMAP.md, TASKS.md

Context

Elyan can eventually support many capabilities: apps, browser, clipboard, screenshots, scheduling, and more. But shipping too many at once would weaken the core.

Decision

The first must-have capability set is:

filesystem
terminal

Applications, browser, screen, and clipboard come later.

Rationale

This gives Elyan immediate real-world usefulness while keeping the surface area manageable.

Alternatives Considered
begin with browser automation first
begin with full UI automation first
begin with many small scattered integrations

These were rejected because filesystem and terminal provide stronger operator value with cleaner architecture.

Consequences

This decision narrows the early roadmap and keeps the first versions focused.

Follow-up Work
build filesystem capability first
build terminal capability second
postpone fragile UI automation work until core execution is strong
ADR-012 — Browser and app control are secondary to core local execution

Status: accepted
Date: 2026-03-22
Owners: Elyan product/runtime
Related Docs: ROADMAP.md, TASKS.md

Context

Browser automation and UI automation are attractive, but often fragile. They can consume large engineering effort before the core runtime is stable.

Decision

Application control and browser control will be added after:

gateway exists
session engine exists
policy engine exists
filesystem capability exists
terminal capability exists
basic memory exists
Rationale

This protects the roadmap from chasing flashy but fragile automation too early.

Alternatives Considered
prioritize browser automation from day one
prioritize full mouse/keyboard automation early

These were rejected because they are brittle and can distract from the operator core.

Consequences

This keeps the first build path disciplined.

Follow-up Work
add app/browser capability in later stages
keep the capability registry ready for later expansion
ADR-013 — Observability is a first-class system requirement

Status: accepted
Date: 2026-03-22
Owners: Elyan core/runtime
Related Docs: AGENTS.md, SYSTEM_ARCHITECTURE.md

Context

An operator that performs actions without clear logs, metrics, and timelines cannot be trusted or debugged effectively.

Decision

Observability is not optional.
The system must provide:

event logs
run logs
errors
policy decisions
verification results
approval history
node health
performance metrics
cost visibility later
Rationale

Operational trust depends on explainability and inspection.

Alternatives Considered
add observability later
rely on raw console output
rely only on UI summaries

These were rejected because runtime systems need visible evidence from the beginning.

Consequences

This decision requires a dedicated observability package and event-driven logging discipline.

Follow-up Work
implement structured logs first
add metrics next
expose key logs in Command Center later
ADR-014 — The Command Center is a control surface, not a decorative dashboard

Status: accepted
Date: 2026-03-22
Owners: Elyan product/UI
Related Docs: ROADMAP.md, SYSTEM_ARCHITECTURE.md

Context

A serious operator platform needs a UI where users can inspect runs, approve risky steps, see failures, and understand active work.

Decision

The Command Center must visualize real runtime state, including:

sessions
runs
approvals
step progress
tool and capability actions
node health
errors
memory events
Rationale

The UI must increase trust and control, not merely make the product look modern.

Alternatives Considered
minimal chat-only UX
glossy dashboard with little runtime detail
debug-only developer tools

These were rejected because Elyan needs a true operator interface.

Consequences

This decision requires runtime state to be queryable and visually inspectable.

Follow-up Work
implement Command Center skeleton
implement run inspector
implement approval UI
ADR-015 — Extensibility must happen through registries and plugins, not core hacks

Status: accepted
Date: 2026-03-22
Owners: Elyan architecture/core
Related Docs: AGENTS.md, SYSTEM_ARCHITECTURE.md, ROADMAP.md

Context

As Elyan grows, new capabilities, integrations, and channels will be added. Without a controlled extensibility model, the codebase will become brittle.

Decision

Elyan will support extensibility through:

capability registry
plugin kit
typed manifests
node registration
explicit contribution points
Rationale

This allows the system to grow while preserving core stability.

Alternatives Considered
direct edits to the core for each new feature
informal module conventions
integration-specific special cases

These were rejected because they cause coupling and slow future development.

Consequences

This decision requires more discipline early, but it prevents architectural collapse later.

Follow-up Work
implement capability registry
implement plugin kit
keep core runtime small and stable
ADR-016 — TypeScript is the default implementation language for Elyan core

Status: accepted
Date: 2026-03-22
Owners: Elyan core
Related Docs: TASKS.md

Context

The system needs a practical default language for protocol definitions, gateway, session engine, runtime, and most packages.

Decision

TypeScript is the default implementation language for Elyan core services and packages.

Optional performance-critical or native-integration pieces may later use Rust or other languages through well-defined boundaries.

Rationale

TypeScript provides:

fast iteration
strong typing
strong ecosystem support
schema-tool friendliness
good fit for Node.js runtime services
good fit for shared contracts
Alternatives Considered
Python for the entire core
Rust for the entire system from the start
mixed-language core without clear rules

These were rejected because they either reduce consistency or slow early product velocity.

Consequences

This decision standardizes the early codebase.

Follow-up Work
keep core packages in TypeScript
consider Rust only for targeted hotspots later
ADR-017 — The initial transport between Gateway and Desktop Agent is WebSocket

Status: accepted
Date: 2026-03-22
Owners: Elyan infrastructure/runtime
Related Docs: SYSTEM_ARCHITECTURE.md, TASKS.md

Context

The Gateway and Desktop Agent need a transport for persistent coordination, health events, action requests, progress updates, and completions.

Decision

The initial gateway-to-agent transport will be persistent WebSocket.

Rationale

WebSocket provides a strong first baseline for:

bidirectional communication
action streaming
low-latency event updates
heartbeat support
simple implementation path
Alternatives Considered
polling HTTP
gRPC from day one
local-only IPC assumptions

These were rejected for the initial build due to complexity or lack of fit.

Consequences

This decision shapes the first node protocol and agent lifecycle.

Follow-up Work
implement persistent connection logic
add reconnect strategy
add heartbeat behavior
allow future transport abstraction later
ADR-018 — Risky actions require approval-first autonomy, not full autonomous execution

Status: accepted
Date: 2026-03-22
Owners: Elyan safety/product
Related Docs: AGENTS.md, ROADMAP.md

Context

Elyan should feel powerful, but blind autonomy on sensitive operations would quickly destroy trust.

Decision

Elyan will adopt approval-first autonomy for risky actions.

This means:

low-risk read-only actions may run automatically
safe writes may run automatically within policy
sensitive or destructive actions require preview and/or approval
Rationale

This creates a strong balance between usefulness and trust.

Alternatives Considered
fully autonomous operator behavior
approval for every action
no autonomous execution at all

These were rejected because they are either unsafe or too restrictive.

Consequences

This decision requires approval UX, run waiting states, and policy clarity.

Follow-up Work
implement approval request flow
expose approval actions in Command Center
define approval scopes later
ADR-019 — Readable project memory files are first-class artifacts

Status: accepted
Date: 2026-03-22
Owners: Elyan memory/product
Related Docs: AGENTS.md, ROADMAP.md

Context

Project continuity is one of Elyan’s core value propositions. Architecture decisions, roadmap changes, and active system state should remain visible.

Decision

Readable project memory files such as:

MEMORY.md
DECISIONS.md
ROADMAP.md
TASKS.md

are first-class architectural artifacts, not temporary notes.

Rationale

These files help both humans and agents understand the project quickly and continue work consistently.

Alternatives Considered
hide all project continuity in internal DB rows
rely only on chat history
rely only on code comments

These were rejected because they are less durable and less inspectable.

Consequences

This decision strengthens documentation-driven continuity.

Follow-up Work
keep these files maintained
update them alongside core architectural changes
ADR-020 — Open architecture questions remain explicit until decided

Status: accepted
Date: 2026-03-22
Owners: Elyan core
Related Docs: ROADMAP.md, TASKS.md

Context

Some choices should not be forced too early, such as database selection details, semantic retrieval baseline, long-term transport abstractions, and organization mode details.

Decision

Unresolved architecture questions must remain explicit and tracked rather than being decided implicitly in code.

Rationale

Undocumented implicit decisions are hard to reverse and often create accidental architecture.

Alternatives Considered
let early implementation decide silently
postpone documentation until later

These were rejected because hidden decisions create long-term confusion.

Consequences

This requires explicit question tracking and follow-up decisions when the time is right.

Follow-up Work
create new ADR entries when open questions become active decisions
reference replacements when an earlier provisional choice changes
Open Decisions

The following are not yet fully decided and should eventually become formal ADRs when activated:

runtime state storage baseline: Postgres-first vs hybrid storage
first macOS native integration mechanism for app control
first browser automation backend
approval scope persistence model
default retrieval scoring baseline before semantic indexing
long-term transport abstraction beyond WebSocket
credential and secret management model for external integrations
artifact storage strategy for large run outputs or snapshots
Deprecated or Replaced Decisions

This section should remain empty until real replacements occur.

When a decision changes:

mark old entry as replaced
point to the new ADR
explain the migration reason
note any required cleanup work
Contributor Rules for Decisions

Before adding a new architectural decision, ask:

does this affect more than one module?
does this change safety, execution, persistence, or extensibility?
will future contributors need to know why this choice was made?
is this hard to reverse later?
does this create new constraints elsewhere?

If the answer is yes, record it here.

Final Directive

Elyan should not evolve through undocumented drift.

Every important architectural choice should become durable, explicit, and reviewable.

This file is the system’s decision memory.