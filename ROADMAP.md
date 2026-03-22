# ROADMAP.md

## Elyan Product Roadmap

## Purpose

This roadmap defines how Elyan should evolve from an early operator prototype into a production-grade local-first digital operator platform.

Elyan is being built as operational infrastructure, not as a simple chatbot.  
The roadmap therefore prioritizes:

- stable execution
- safe computer control
- auditable memory
- session integrity
- modular extensibility
- local-first performance
- premium operator UX
- production readiness

This document is intended to guide:

- founders
- core engineers
- coding agents
- future contributors
- architecture and product decisions

---

## North Star

Elyan should become a reliable digital operator that can:

- understand user intent
- manage sessions and project context correctly
- perform real work on the local machine and remote systems
- safely control files, terminal, apps, browser, and workflows
- operate with approval-first autonomy
- keep memory auditable and useful
- remain modular as new capabilities are added
- provide a premium command-center experience

---

## Roadmap Design Principles

All roadmap decisions must align with these rules:

### 1. Core before cosmetics
Do not prioritize surface-level demos over runtime stability.

### 2. Safe execution before autonomy
Elyan must be able to execute safely before it executes aggressively.

### 3. Local-first before distributed complexity
Computer control should work reliably on the local machine before distributed node orchestration becomes a major focus.

### 4. Typed systems before improvisation
The protocol, actions, and runtime boundaries must be explicit before large-scale feature growth.

### 5. Observability before scale
If we cannot inspect and explain Elyan’s behavior, we are not ready to scale it.

### 6. Memory quality before memory volume
Useful memory matters more than storing everything.

### 7. Extensibility without core corruption
New capabilities must enter through proper modules, capabilities, registries, and plugins.

---

## Current Strategic Objective

The immediate objective is to turn Elyan into a stable local-first operator runtime capable of:

- session-safe task execution
- controlled filesystem operations
- controlled terminal execution
- persistent desktop-agent-based machine control
- auditable run logging
- useful project memory
- approval-based high-risk actions

This is the minimum viable operator core.

---

## Roadmap Structure

The roadmap is divided into stages:

- Stage 0: Foundation and constraints
- Stage 1: Core runtime
- Stage 2: Safe local computer control
- Stage 3: Memory and context intelligence
- Stage 4: Extensibility and capability growth
- Stage 5: Premium operator UX
- Stage 6: Production hardening
- Stage 7: Multi-node and organization mode

Each stage includes:

- objective
- scope
- key deliverables
- success criteria
- exit conditions

---

## Stage 0 — Foundation and Constraints

## Objective

Establish the architectural baseline, development rules, and repository structure so Elyan grows in a controlled direction.

## Scope

- define architecture direction
- define coding rules
- define module boundaries
- define protocol-first mindset
- define memory strategy
- define product priorities
- avoid premature feature chaos

## Deliverables

- `AGENTS.md`
- `SYSTEM_ARCHITECTURE.md`
- `ROADMAP.md`
- initial repository structure
- naming conventions
- initial risk model
- initial capability taxonomy
- decision that local computer control uses a Desktop Agent

## Success Criteria

- new contributors can understand the system quickly
- coding agents can act without guessing the product model
- major architectural decisions are documented
- future work follows clear layer boundaries

## Exit Condition

Elyan has enough written clarity that implementation can proceed without architectural ambiguity.

---

## Stage 1 — Core Runtime

## Objective

Build the operational backbone of Elyan.

This stage is about turning Elyan into a real runtime with explicit event flow, session handling, and run lifecycle management.

## Scope

- protocol layer
- gateway / orchestrator
- session engine
- run lifecycle
- queue handling
- structured logs
- basic channel integration
- minimal runtime executor

## Deliverables

### 1. Protocol package
Define typed schemas for:

- inbound messages
- session resolution
- run events
- planner outputs
- tool requests
- approval requests
- verification outputs
- memory write requests
- node registration
- streaming blocks

### 2. Gateway / Orchestrator
Implement:

- event intake
- schema validation
- actor resolution
- workspace resolution
- session routing
- run dispatch
- lifecycle event emission

### 3. Session Engine
Implement:

- session identity
- lane locking
- queue state
- queue policies
- interruption rules
- follow-up handling
- session summaries

### 4. Run lifecycle model
Support at least:

- queued
- started
- waiting_for_approval
- executing
- verifying
- completed
- failed
- cancelled

### 5. Structured logging
Add:

- run logs
- event logs
- error logs
- session logs

## Success Criteria

- Elyan can receive a user request and create a valid run
- session boundaries are explicit
- multiple messages do not corrupt the same session state
- lifecycle events are inspectable
- failures are visible, not silent

## Exit Condition

Elyan behaves as a real orchestrated runtime, not a loose message-response loop.

---

## Stage 2 — Safe Local Computer Control

## Objective

Give Elyan reliable control over the local machine through a persistent Desktop Agent, with safety, verification, and policy enforcement.

## Scope

- desktop agent
- filesystem capability
- terminal capability
- policy engine
- verification layer
- rollback basics
- allowed roots
- sensitive path protection

## Deliverables

### 1. Desktop Agent v1
Implement a long-lived local process that:

- stays connected to the Gateway
- registers capabilities
- executes local typed actions
- emits progress and health events
- supports reconnect and heartbeats

### 2. Filesystem capability
Implement typed actions such as:

- list
- stat
- read_text
- write_text
- patch_text
- create_file
- create_folder
- rename
- move
- copy
- trash
- restore
- search

### 3. Terminal capability
Implement typed actions such as:

- exec
- stream_output
- cancel
- cwd-bound command execution
- exit code capture
- stdout / stderr logging

### 4. Policy Engine v1
Implement rules for:

- allowed roots
- protected files
- destructive operation detection
- approval requirements
- dry-run requirements
- risk classification

### 5. Verification layer
Implement post-action verification for:

- file existence
- content change
- move success
- rename success
- terminal exit code
- expected output presence

### 6. Rollback basics
Support rollback metadata for:

- rename
- move
- trash
- patch_text using snapshots where applicable

## Success Criteria

- Elyan can safely create, edit, move, and trash files on the local machine
- Elyan can run terminal commands through a controlled path
- risky actions do not bypass policy
- side effects are verified after execution
- basic rollback exists for reversible operations

## Exit Condition

Elyan can perform useful real machine operations safely and predictably.

---

## Stage 3 — Memory and Context Intelligence

## Objective

Make Elyan context-aware across sessions and projects without turning memory into noise.

## Scope

- profile memory
- project memory
- episodic memory
- run summaries
- retrieval
- context compaction
- memory scoring

## Deliverables

### 1. Memory stores
Implement readable memory structures:

- `memory/profile.md`
- `memory/projects/elyan/MEMORY.md`
- `memory/projects/elyan/DECISIONS.md`
- `memory/projects/elyan/ROADMAP.md`
- `memory/daily/YYYY-MM-DD.md`
- `memory/runs/<session-id>/<run-id>.json`

### 2. Memory writing rules
Create a memory promotion pipeline:

- extract candidate facts
- score usefulness
- detect duplication
- filter sensitive data
- route to the correct memory store

### 3. Session summarization
Add automatic session summaries that capture:

- what was attempted
- what changed
- what remains
- what decisions were made

### 4. Context Engine v1
Assemble context from:

- system rules
- user intent
- session summary
- project memory
- recent transcript
- tool results
- workspace facts

### 5. Retrieval support
Implement retrieval for:

- project documents
- previous decisions
- recent run summaries
- relevant memory snippets

## Success Criteria

- Elyan remembers the state of active projects correctly
- context assembly is relevant rather than bloated
- memory remains readable and inspectable
- the system can continue work across sessions with low confusion

## Exit Condition

Elyan can continue meaningful work across time without repeatedly “forgetting” important project facts.

---

## Stage 4 — Extensibility and Capability Growth

## Objective

Turn Elyan into a modular platform where new capabilities can be added without corrupting the core.

## Scope

- capability registry
- plugin kit
- application control
- browser control
- screen and clipboard support
- node registry
- model routing improvements

## Deliverables

### 1. Capability registry
A standard registry for:

- capability definitions
- actions
- schemas
- risk classes
- verification handlers
- rollback handlers

### 2. Plugin kit
Support plugin modules that can add:

- capabilities
- integrations
- channel adapters
- node types
- provider connectors

### 3. Application control
Add controlled actions for:

- open app
- focus app
- close app
- detect frontmost app
- list running apps

### 4. Browser capability
Add controlled browser support for:

- open URL
- extract page
- structured interaction
- download
- simple form fill
- safe browsing flows

### 5. Clipboard and screen support
Add:

- clipboard read/write
- screenshot capture
- active window detection

### 6. Node registry
Prepare for multiple execution nodes by implementing:

- node registration
- capability advertisement
- health tracking
- selection metadata

### 7. Model routing improvements
Define model usage by role:

- planner
- executor
- validator
- summarizer

Optimize for cost, speed, and quality.

## Success Criteria

- new capabilities can be added without editing core runtime everywhere
- browser and application workflows work through the same policy-aware model
- plugins have typed contracts
- the system architecture remains modular as features grow

## Exit Condition

Elyan becomes a platform, not a one-off implementation.

---

## Stage 5 — Premium Operator UX

## Objective

Build the user-facing command center that makes Elyan feel like a serious digital operator platform.

## Scope

- admin / command center UI
- live run inspector
- approvals interface
- progress visibility
- memory timeline
- node health
- operational clarity

## Deliverables

### 1. Command Center
Display:

- active sessions
- active runs
- pending approvals
- tool executions
- result previews
- node health
- recent failures
- memory updates

### 2. Run inspector
Allow users to inspect:

- run lifecycle
- step history
- tool invocations
- policy decisions
- verification outcomes
- rollback availability

### 3. Approval UI
Create user controls for:

- approve
- deny
- approve once
- approve for session
- preview before apply

### 4. Memory timeline
Show:

- recent memory writes
- project decisions
- daily summaries
- session milestones

### 5. Cost and performance views
Show:

- token usage
- average latency
- task success rate
- retry frequency

## Success Criteria

- users can clearly understand what Elyan is doing
- risky actions can be reviewed before execution
- the system feels professional and inspectable
- debugging and trust improve significantly

## Exit Condition

Elyan is no longer just a backend runtime; it becomes an operator product.

---

## Stage 6 — Production Hardening

## Objective

Make Elyan reliable enough for sustained real-world daily usage.

## Scope

- error classification
- retries
- rate limits
- recovery flows
- stronger observability
- crash resilience
- state durability
- performance tuning

## Deliverables

### 1. Failure taxonomy
Classify at least:

- schema errors
- policy denials
- capability failures
- verification failures
- timeouts
- node unavailability
- memory write failures
- session recovery failures

### 2. Retry strategy
Add explicit policies for:

- retryable failures
- non-retryable failures
- backoff behavior
- user-visible recovery suggestions

### 3. Checkpoint and resume
Allow long-running tasks to:

- checkpoint progress
- resume safely
- recover after interruptions

### 4. Performance optimization
Improve:

- queue delay
- local action latency
- indexing speed
- context assembly speed
- logging efficiency

### 5. Hardening tests
Add tests for:

- session isolation
- filesystem safety
- policy enforcement
- rollback correctness
- verification accuracy
- reconnect behavior
- node health behavior

### 6. Operational dashboards
Track:

- success rate
- failure rate
- approval rate
- rollback frequency
- queue backlog
- median task latency
- token cost per successful task

## Success Criteria

- Elyan can be used repeatedly without state degradation
- failures are classified and recoverable where possible
- system health is measurable
- recovery behavior is not improvised

## Exit Condition

Elyan reaches production-grade stability for serious operator workflows.

---

## Stage 7 — Multi-Node and Organization Mode

## Objective

Expand Elyan from a single-user operator into a multi-node, multi-workspace, organization-capable platform.

## Scope

- multiple execution nodes
- remote orchestration
- workspace isolation
- organization roles
- shared memory policy
- team approvals
- scheduled jobs
- organization-grade auditability

## Deliverables

### 1. Multi-node routing
Route tasks based on:

- capability availability
- locality
- trust
- latency
- cost

### 2. Organization mode
Support:

- multiple users
- multiple workspaces
- roles and permissions
- shared project memory boundaries
- approval delegation

### 3. Scheduled and background tasks
Add safe support for:

- scheduled runs
- recurring maintenance
- monitored workflows
- resumable background jobs

### 4. Expanded audit trails
Track:

- who approved what
- which node executed what
- what changed
- what memory was shared
- which workspace was affected

## Success Criteria

- Elyan can operate beyond a single personal desktop setup
- workspace and permission boundaries remain strong
- the system can support more serious SaaS or organization workflows

## Exit Condition

Elyan evolves from a personal operator into a scalable digital operations platform.

---

## Cross-Stage Technical Priorities

The following concerns must remain active across all stages.

## A. Session Integrity

Always protect:

- lane safety
- queue discipline
- ordering where needed
- checkpointing
- state isolation

## B. Safety

Always protect:

- destructive operations
- sensitive files
- credentials
- uncontrolled shell execution
- policy bypass

## C. Observability

Always improve:

- logs
- metrics
- run inspection
- approval history
- verification visibility

## D. Memory Quality

Always optimize for:

- relevance
- readability
- deduplication
- project continuity
- low pollution

## E. Extensibility

Always prefer:

- typed modules
- registries
- plugins
- clear capability boundaries
- minimal core coupling

---

## Roadmap Milestones

## Milestone M1 — Operator Core
Elyan can receive requests, create runs, protect sessions, and log execution state.

## Milestone M2 — Local Machine Control
Elyan can safely manipulate files and run terminal commands through the Desktop Agent.

## Milestone M3 — Project Continuity
Elyan can remember project state and continue work across sessions without major confusion.

## Milestone M4 — Capability Platform
Elyan can grow through plugins, registries, and new capability modules without core rewrites.

## Milestone M5 — Premium Control Surface
Elyan offers a serious command center with approvals, live progress, and operational visibility.

## Milestone M6 — Production Readiness
Elyan is resilient, measurable, recoverable, and viable for daily use.

## Milestone M7 — Platform Expansion
Elyan supports multi-node routing, organization mode, and larger-scale workflows.

---

## Suggested Release Framing

A practical versioning path could be:

### Elyan v0.1
Architecture baseline and core runtime skeleton

### Elyan v0.2
Desktop Agent + filesystem + terminal safe execution

### Elyan v0.3
Memory, context, and project continuity

### Elyan v0.4
Plugins, browser/app support, extensibility layer

### Elyan v0.5
Command center and approvals UX

### Elyan v0.6
Hardening, recovery, performance stabilization

### Elyan v1.0
Reliable local-first digital operator with production-grade operator workflows

### Elyan v2.0
Multi-node orchestration, organization mode, advanced autonomy, and broader platformization

---

## Key Risks

The roadmap must actively avoid these failure modes:

### 1. Chatbot drift
Risk: Elyan becomes mostly a text assistant instead of an operator runtime.

Mitigation:
- keep capabilities and execution central
- prioritize operational infrastructure

### 2. Unsafe autonomy
Risk: Elyan performs harmful actions without sufficient checks.

Mitigation:
- strict policy engine
- approval gates
- verification
- rollback

### 3. Memory pollution
Risk: Elyan stores too much low-quality information and becomes less useful.

Mitigation:
- memory scoring
- scoped memory types
- deduplication
- summary-driven persistence

### 4. Session corruption
Risk: concurrent or merged work corrupts task state.

Mitigation:
- lane model
- queue policies
- checkpointing
- explicit run lifecycle

### 5. Core entanglement
Risk: new features are bolted directly into the core and make the system fragile.

Mitigation:
- plugins
- registries
- typed boundaries
- capability contracts

### 6. UX opacity
Risk: users cannot understand what Elyan is doing.

Mitigation:
- run inspector
- progress visibility
- approval UI
- observability-first design

---

## Definition of Roadmap Success

The roadmap is succeeding if Elyan becomes progressively better at:

- performing real tasks safely
- keeping session and project state intact
- operating on the local machine with confidence
- exposing its behavior clearly
- growing without architectural collapse
- supporting professional workflows
- becoming trustworthy enough for daily use

---

## Immediate Focus

If work must begin immediately, focus on this exact sequence:

1. protocol package
2. gateway
3. session engine
4. run lifecycle
5. structured logs
6. desktop agent
7. filesystem capability
8. terminal capability
9. policy engine
10. verification layer
11. memory system
12. command center baseline

This is the shortest credible path toward a serious Elyan core.

---

## Final Directive

Do not build Elyan as a flashy AI demo.

Build Elyan as a dependable operator system with:

- explicit contracts
- explicit safety
- explicit execution
- explicit memory
- explicit visibility
- explicit extensibility

Every roadmap decision should move Elyan closer to being:

- stable
- safe
- fast
- inspectable
- modular
- trustworthy
- production-capable